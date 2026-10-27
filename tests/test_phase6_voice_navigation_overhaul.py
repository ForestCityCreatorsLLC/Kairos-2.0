"""Phase 6 — Natural Voice-to-Navigate, Context-Aware YouTube Highlights, & Hybrid Navigation Suite.

Verifies:
1. Natural conversational prefixes/gerunds/STT variants ("Can you pull up highlights of the game?",
   "Would you mind pulling up...", "I'd like to watch...", "pull op...").
2. Multi-turn session context resolution ("What's the score of the Browns game?" -> "Can you pull up highlights of the game?")
   + cold-start live ESPN scoreboard matchup inference.
3. Chained YouTube navigation collapsing ("Go to YouTube and pull up Cleveland Browns highlights" -> single search URL),
   well-known spoken websites without `.com` ("Open YouTube", "Go to ESPN", "Pull up GitHub"), and Google/GitHub/Reddit searches.
4. Hybrid Question + Navigation utterances ("What's the score of the Browns game and can you pull up the highlights?").
5. Zero-Leak Privacy Shield on external search URLs & `<ui_nav>` SSRF/scheme sanitization.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
import services.kairos_core.assistant as assistant_mod
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.navigator import extract_llm_ui_commands


class _FakeScoreboardResp:
    ok = True

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def test_conversational_wrappers_and_youtube_highlights_resolution(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Voice_Highlights_Vault"))
    nav = bundle["navigator"]

    # 1. Exact user scenario (cold start, no prior turns) -> YouTube highlights search in Browser
    cmds1, notes1 = nav.resolve_utterance("Can you pull up highlights of the game?")
    assert cmds1[0] == {"type": "navigate_tab", "tab": "browser"}
    assert cmds1[1]["type"] == "browser_navigate"
    assert cmds1[1]["url"] == "https://www.youtube.com/results?search_query=game+highlights"
    assert "YouTube" in notes1[0]

    # 2. Polite modal + trailing filler + Cleveland nickname expansion ("Browns" -> "Cleveland Browns")
    cmds2, _ = nav.resolve_utterance("Hey Kairos, could you please pull up Browns highlights for me?")
    assert cmds2[0] == {"type": "navigate_tab", "tab": "browser"}
    assert cmds2[1]["url"] == "https://www.youtube.com/results?search_query=Cleveland+Browns+highlights"

    # 3. Gerund phrasing ("Would you mind pulling up...") + specific matchup
    cmds3, _ = nav.resolve_utterance("Would you mind pulling up Lakers vs Celtics highlights?")
    assert cmds3[1]["url"] == "https://www.youtube.com/results?search_query=Lakers+vs+Celtics+highlights"

    # 4. STT typo tolerance ("pull op") + "last night's game" time qualifier
    cmds4, _ = nav.resolve_utterance("can you pull op highlights from last night's game")
    assert cmds4[0] == {"type": "navigate_tab", "tab": "browser"}
    assert cmds4[1]["url"] == "https://www.youtube.com/results?search_query=game+highlights+last+night"


def test_multi_turn_session_context_and_cold_live_scoreboard_highlight_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "MultiTurn_Highlights_Vault"))
    router = isolated_bundle["router"]

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Final: Cleveland Browns 24, Baltimore Ravens 17!",
            "tokens_used": 22,
            "latency_ms": 4,
        },
    )

    def _fake_espn_get(url: str, *args: Any, **kwargs: Any) -> _FakeScoreboardResp:
        if "football/nfl/scoreboard" in url:
            return _FakeScoreboardResp(
                {
                    "events": [
                        {
                            "name": "Baltimore Ravens at Cleveland Browns",
                            "competitions": [
                                {
                                    "status": {"type": {"shortDetail": "Final"}},
                                    "competitors": [
                                        {
                                            "team": {"displayName": "Cleveland Browns", "shortDisplayName": "Browns"},
                                            "score": "24",
                                        },
                                        {
                                            "team": {"displayName": "Baltimore Ravens", "shortDisplayName": "Ravens"},
                                            "score": "17",
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            )
        return _FakeScoreboardResp({"events": []})

    monkeypatch.setattr(assistant_mod.requests, "get", _fake_espn_get)
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # Turn 1: Ask about the Browns score
    r_turn1 = client.post(
        "/api/assistant/chat",
        json={"prompt": "What's the score of the Browns game?", "mode": "gemma-4"},
    )
    assert r_turn1.status_code == 200
    sid = r_turn1.json()["session"]["session_id"]

    # Turn 2: Say "Can you pull up highlights of the game?" -> resolves Browns vs Ravens from Turn 1!
    r_turn2 = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Can you pull up highlights of the game?",
            "session_id": sid,
            "mode": "auto",
        },
    )
    assert r_turn2.status_code == 200
    d2 = r_turn2.json()
    assert d2["route_reason"] == "platform_voice_navigation"
    assert d2["ui_commands"][0] == {"type": "navigate_tab", "tab": "browser"}
    nav_url = d2["ui_commands"][1]["url"]
    assert "youtube.com/results?search_query=" in nav_url
    assert "Cleveland+Browns" in nav_url
    assert "Baltimore+Ravens" in nav_url
    assert "YouTube" in d2["spoken_reply"]

    # Cold session (brand-new session, 0 prior turns) ALSO infers active Cleveland matchup from live scoreboard
    fresh_sid = client.post("/api/assistant/sessions", json={"persona": "companion"}).json()["session_id"]
    r_cold = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Can you pull up highlights of the game?",
            "session_id": fresh_sid,
            "mode": "auto",
        },
    )
    assert r_cold.status_code == 200
    cold_url = r_cold.json()["ui_commands"][1]["url"]
    assert "Cleveland+Browns" in cold_url


def test_chained_youtube_known_websites_and_site_searches(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Web_Nav_Vault"))
    nav = bundle["navigator"]

    # 1. Chained "Go to YouTube and pull up ..." collapses into ONE single YouTube search navigation
    cmds_chain, notes_chain = nav.resolve_utterance(
        "Go to YouTube and pull up Cleveland Browns highlights"
    )
    assert cmds_chain == [
        {"type": "navigate_tab", "tab": "browser"},
        {
            "type": "browser_navigate",
            "url": "https://www.youtube.com/results?search_query=Cleveland+Browns+highlights",
            "title": "▶ YouTube: Cleveland Browns highlights",
            "new_tab": True,
        },
    ]
    assert len(notes_chain) == 1

    # 2. Chained "Open YouTube and play lofi hip hop"
    cmds_play, _ = nav.resolve_utterance("Open YouTube and play lofi hip hop")
    assert len(cmds_play) == 2
    assert cmds_play[1]["url"] == "https://www.youtube.com/results?search_query=lofi+hip+hop"

    # 3. Tutorial / video intent without explicitly saying "YouTube"
    cmds_tut, _ = nav.resolve_utterance("I want to watch a video tutorial on React Three Fiber")
    assert cmds_tut[0] == {"type": "navigate_tab", "tab": "browser"}
    assert cmds_tut[1]["url"] == "https://www.youtube.com/results?search_query=React+Three+Fiber+tutorial"

    # 4. Spoken well-known websites without `.com`
    for phrase, expected_url in (
        ("Open YouTube", "https://www.youtube.com"),
        ("Go to ESPN", "https://www.espn.com"),
        ("Pull up GitHub", "https://github.com"),
        ("Let's check out Reddit", "https://www.reddit.com"),
    ):
        c_site, _ = nav.resolve_utterance(phrase)
        assert c_site[0] == {"type": "navigate_tab", "tab": "browser"}
        assert c_site[1]["url"] == expected_url

    # 5. Natural Google & GitHub site searches
    c_goog, _ = nav.resolve_utterance("Google Printful heavyweight hoodie sizing")
    assert c_goog[1]["url"] == "https://www.google.com/search?q=Printful+heavyweight+hoodie+sizing"

    c_gh, _ = nav.resolve_utterance("Search GitHub for kepano obsidian skills")
    assert c_gh[1]["url"] == "https://github.com/search?q=kepano+obsidian+skills"


def test_hybrid_question_plus_trailing_voice_navigation_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Hybrid_Question_Nav_Vault"))
    router = isolated_bundle["router"]

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda sys_p, usr_p: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "The Cleveland Cavaliers beat the Boston Celtics 114-108!",
            "tokens_used": 26,
            "latency_ms": 5,
        },
    )
    monkeypatch.setattr(
        assistant_mod.requests,
        "get",
        lambda *_a, **_kw: _FakeScoreboardResp({"events": []}),
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # Single-breath question + navigation ("What's the score of the Cavs game and can you pull up the highlights?")
    r_hyb = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "What's the score of the Cavs game and can you pull up the highlights?",
            "mode": "gemma-4",
        },
    )
    assert r_hyb.status_code == 200
    data = r_hyb.json()
    assert "Cleveland Cavaliers beat the Boston Celtics" in data["reply"]
    assert data["ui_commands"][0] == {"type": "navigate_tab", "tab": "browser"}
    assert (
        data["ui_commands"][1]["url"]
        == "https://www.youtube.com/results?search_query=Cleveland+Cavaliers+game+highlights"
    )


def test_privacy_shield_and_llm_ui_nav_url_sanitization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "Priv_Nav_Vault"))
    monkeypatch.setattr(
        assistant_mod.requests,
        "get",
        lambda *_a, **_kw: _FakeScoreboardResp({"events": []}),
    )
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    # 1. Create a `#private`-tainted session mentioning a team name in confidential context
    r_priv_cap = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Capture in Inbox: Confidential Cleveland Browns suite contract figures #private",
            "mode": "auto",
        },
    )
    assert r_priv_cap.status_code == 200
    priv_sid = r_priv_cap.json()["session"]["session_id"]

    # 2. Follow-up voice navigation in that `#private` session MUST NOT leak session text into YouTube URL
    r_nav = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Can you pull up highlights of the game?",
            "session_id": priv_sid,
            "mode": "auto",
        },
    )
    assert r_nav.status_code == 200
    nav_json = r_nav.json()
    assert nav_json["privacy_locked"] is True
    assert nav_json["ui_commands"][1]["url"] == "https://www.youtube.com/results?search_query=game+highlights"
    assert "Browns" not in nav_json["ui_commands"][1]["url"]

    # 3. `extract_llm_ui_commands` strips unsafe schemes/loopback URLs while auto-prepending `navigate_tab: browser` for valid YouTube URLs
    raw_llm = (
        "Pulling that up now! "
        '<ui_nav>{"type":"browser_navigate","url":"javascript:alert(1)"}</ui_nav>'
        '<ui_nav>{"type":"browser_navigate","url":"http://127.0.0.1:8420/api/health"}</ui_nav>'
        '<ui_nav>{"type":"browser_navigate","url":"https://www.youtube.com/results?search_query=Browns+highlights","title":"Browns"}</ui_nav>'
    )
    cleaned_txt, safe_cmds = extract_llm_ui_commands(raw_llm)
    assert cleaned_txt == "Pulling that up now!"
    assert safe_cmds == [
        {"type": "navigate_tab", "tab": "browser"},
        {
            "type": "browser_navigate",
            "url": "https://www.youtube.com/results?search_query=Browns+highlights",
            "title": "Browns",
        },
    ]
