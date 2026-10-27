"""Phase 13 — WebView `dom-ready` Lifecycle Fix, Anti-Hallucination Voice VAD/STT Guard & Full Tab-by-Tab Audit."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
import pytest

from services.kairos_core.mcp_server import create_mcp_bundle
import services.kairos_voice.voice_service as voice_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


def test_phase13_stt_silence_and_hallucination_firewall_blocks_phantom_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Strict STT prompt must NOT contain platform buzzwords that cause LLM parroting on room silence
    for forbidden_buzzword in ("Kanban", "Paperclip", "Printful", "CrewAI", "Code Red", "Gemma 4"):
        assert forbidden_buzzword.lower() not in voice_mod.STT_STRICT_PROMPT.lower()
    assert "[SILENCE]" in voice_mod.STT_STRICT_PROMPT

    # 2. Sanitizer rejects silence markers, Whisper artifacts, prompt echoes, and single-char noise
    for phantom in (
        "[SILENCE]",
        "  [silence]  ",
        "[NO_SPEECH]",
        "[BLANK_AUDIO]",
        "(inaudible)",
        "Thank you for watching.",
        "Thanks for watching!",
        "Subtitles by Amara.org community",
        "you.",
        "You",
        "You are a strict speech-to-text audio transcriber.",
        "...",
        "a",
        "",
    ):
        assert voice_mod._sanitize_stt_transcript(phantom) == ""

    # Real utterances pass through with phonetic normalization intact
    assert (
        voice_mod._sanitize_stt_transcript("Hey Kros, bring up Browns highlights on YouTube")
        == "Hey KAIROS, bring up Browns highlights on YouTube"
    )

    # 3. When primary Gemini STT model outputs `[SILENCE]`, cascade stops immediately (1 call, zero Core dispatch)
    call_models: list[str] = []

    class _FakeModels:
        def generate_content(self, *, model: str, contents: object, config: object = None) -> object:
            call_models.append(model)
            return SimpleNamespace(text="[SILENCE]")

    class _FakeGenAIClient:
        def __init__(self, api_key: str) -> None:
            self.models = _FakeModels()

    import google.genai as genai_pkg

    monkeypatch.setattr(genai_pkg, "Client", _FakeGenAIClient)
    monkeypatch.setattr(voice_mod.settings, "gemini_api_key", "test-key")

    core_called = False

    def _forbid_core_post(*args: object, **kwargs: object) -> object:
        nonlocal core_called
        core_called = True
        raise AssertionError("Core :8420 should never be called when STT detects [SILENCE]!")

    monkeypatch.setattr(voice_mod.requests, "post", _forbid_core_post)

    stt_res = voice_mod.transcribe_audio_bytes(b"fake-silent-webm-bytes" * 40, "audio/webm", is_private=False)
    assert stt_res["ok"] is False
    assert stt_res.get("no_speech") is True
    assert stt_res["text"] == ""
    assert len(call_models) == 1

    from fastapi.testclient import TestClient

    v_client = TestClient(voice_mod.app)
    b64_audio = base64.b64encode(b"fake-silent-webm-bytes" * 40).decode("ascii")
    r_audio = v_client.post(
        "/api/voice/audio-command",
        json={"audio_base64": b64_audio, "mime_type": "audio/webm", "mode": "auto"},
    )
    assert r_audio.status_code == 200
    r_json = r_audio.json()
    assert r_json.get("no_speech") is True
    assert r_json.get("core_response") is None
    assert core_called is False

    # 4. Deterministic Voice Navigation resolves "bring up browns highlights on youtube" cleanly
    bundle = create_mcp_bundle(str(tmp_path / "Phase13_Nav_Vault"))
    cmds, _notes = bundle["navigator"].resolve_utterance("bring up browns highlights on youtube")
    assert any(c.get("type") == "navigate_tab" and c.get("tab") == "browser" for c in cmds)
    nav_urls = [str(c.get("url") or "") for c in cmds if c.get("type") == "browser_navigate"]
    assert nav_urls and "youtube.com/results?search_query=" in nav_urls[0]
    assert "browns" in nav_urls[0].lower()


def test_phase13_sports_word_boundary_guard_prevents_kanban_nba_false_positives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.kairos_core.assistant as asst_mod

    bundle = create_mcp_bundle(str(tmp_path / "Phase13_Sports_Vault"))
    assistant = bundle["assistant"]

    def _fail_if_espn_called(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"Unexpected ESPN HTTP call for non-sports prompt: {args}")

    monkeypatch.setattr(asst_mod.requests, "get", _fail_if_espn_called)

    # Substrings that previously collided: ka[nba]n, under[score], safe[guards], con[tribe], end[game]
    non_sports_prompt = (
        "Generate a mind map for the Second Brain project including Kanban, Gantt, Paperclip, "
        "safeguards, underscore formatting, contribute guidelines, and endgame architecture."
    )
    assert assistant._fetch_live_sports_scores(non_sports_prompt) is None

    # Legitimate sports prompts still trigger ESPN cleanly
    seen_urls: list[str] = []

    class _FakeResp:
        ok = True

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "events": [
                    {
                        "name": "Baltimore Ravens at Cleveland Browns",
                        "competitions": [
                            {
                                "status": {"type": {"shortDetail": "Final"}},
                                "competitors": [
                                    {"team": {"displayName": "Cleveland Browns", "shortDisplayName": "Browns"}, "score": "24"},
                                    {"team": {"displayName": "Baltimore Ravens", "shortDisplayName": "Ravens"}, "score": "17"},
                                ],
                            }
                        ],
                    }
                ]
            }

    def _mock_espn_get(url: str, timeout: float = 4.5) -> _FakeResp:
        seen_urls.append(url)
        return _FakeResp()

    monkeypatch.setattr(asst_mod.requests, "get", _mock_espn_get)
    scores = assistant._fetch_live_sports_scores("What is the Cleveland Browns score today?")
    assert scores is not None
    assert "Cleveland Browns" in scores
    assert any("football/nfl" in u for u in seen_urls)


def test_phase13_code_red_explicit_activation_vs_incidental_mention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase13_CodeRed_Vault"))
    assistant = bundle["assistant"]

    monkeypatch.setattr(
        assistant.router,
        "generate",
        lambda *args, **kwargs: {
            "ok": True,
            "agent": "Gemma-4",
            "text": "Here is the requested architecture overview.",
            "route_reason": "test_stub",
            "privacy_locked": False,
        },
    )

    # Mentioning "Code Red" in a feature list or question must NOT flip session tone into CODE_RED
    incidental = assistant.chat(
        prompt="Please add a section for AI features like Code Red, Printful, and Gemma 4.",
        mode="gemma-4",
        tone_mode="DEFAULT",
    )
    inc_turns = incidental["session"]["turns"]
    assert inc_turns[-1]["tone_mode"] == "DEFAULT"

    question_res = assistant.chat(
        prompt="What is Code Red mode in KAIROS?",
        mode="gemma-4",
        tone_mode="DEFAULT",
    )
    assert question_res["session"]["turns"][-1]["tone_mode"] == "DEFAULT"

    # Explicit activation command DOES engage CODE_RED
    activated = assistant.chat(
        prompt="Activate Code Red: summarize top blockers.",
        mode="gemma-4",
        tone_mode="DEFAULT",
    )
    assert activated["session"]["turns"][-1]["tone_mode"] == "CODE_RED"


def test_phase13_webview_dom_ready_voice_vad_and_tab_audit_ui_contracts() -> None:
    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "webviewDomReadyTabRef" in browser_src
    assert "'dom-ready'" in browser_src
    assert "safeLoadWebviewUrl" in browser_src
    assert "mountedWebviewSrc" in browser_src
    # Must NEVER call webviewRef.current.getURL() directly before dom-ready
    assert "webviewRef.current.getURL" not in browser_src
    assert "webviewRef.current?.getURL" not in browser_src

    speech_src = (UI_SRC_ROOT / "utils" / "speech.ts").read_text(encoding="utf-8")
    assert "subscribeKairosSpeech" in speech_src
    assert "isKairosSpeaking" in speech_src
    assert "setGlobalSpeakingState" in speech_src

    topbar_src = (UI_SRC_ROOT / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    assert "subscribeKairosSpeech" in topbar_src
    assert "scheduleHandsFreeRelisten" in topbar_src
    assert "hasMediaPlaybackNavigation" in topbar_src
    assert "sustainedSpeechConfirmed" in topbar_src
    assert "voicedFrames >= 10" in topbar_src

    palette_src = (UI_SRC_ROOT / "components" / "CommandPalette.tsx").read_text(encoding="utf-8")
    assert "'filter_second_brain'" in palette_src
    assert "set_second_brain_view" not in palette_src

    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    assert "if (backendConnected) return;" in app_src
    assert "scheduleWsRefresh" in app_src
    assert 'resetKey={`${activeBrowserTabId}-${browserSignal.seq}`}' in app_src

    drawer_src = (UI_SRC_ROOT / "components" / "KairosChatDrawer.tsx").read_text(encoding="utf-8")
    assert "fallbackSid" in drawer_src

    asst_src = (UI_SRC_ROOT / "features" / "assistant" / "AssistantWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "fallbackSid" in asst_src

    task_drawer_src = (UI_SRC_ROOT / "features" / "projects" / "TaskDrawer.tsx").read_text(
        encoding="utf-8"
    )
    assert "loadSeqRef" in task_drawer_src
    assert "editingBodyRef" in task_drawer_src

    sb_src = (UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "let cancelled = false;" in sb_src
