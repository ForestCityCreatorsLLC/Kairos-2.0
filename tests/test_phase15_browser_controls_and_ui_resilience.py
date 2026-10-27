"""Phase 15 — Hands-Free Browser Controls, Authenticated WebView DOM Clipping, Fetch Abort Timeouts & UI Race/Orbit Resilience."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.navigator import PlatformNavigator, extract_llm_ui_commands

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


def test_phase15_spoken_browser_controls_and_ui_nav_sanitization(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase15_Nav_Vault"))
    nav = PlatformNavigator(bundle["vault"], bundle["index"])

    cases = [
        ("Hey KAIROS, go back in the browser", "back"),
        ("Navigate forward", "forward"),
        ("Can you please refresh this page", "reload"),
        ("Open a new browser tab", "new_tab"),
        ("Create a new browser tab", "new_tab"),
        ("Close this browser tab", "close_tab"),
        ("Go home in the browser", "home"),
    ]
    for utterance, expected_action in cases:
        cmds, notes = nav.resolve_utterance(utterance)
        assert cmds == [
            {"type": "navigate_tab", "tab": "browser"},
            {"type": "browser_control", "action": expected_action},
        ], f"Unexpected commands for {utterance!r}: {cmds}"
        assert len(notes) >= 1

    # Valid `<ui_nav>` `browser_control` action is preserved & auto-prefixed with `navigate_tab`; invalid action is dropped
    cleaned_ok, cmds_ok = extract_llm_ui_commands(
        'Reloading now. <ui_nav>{"type":"browser_control","action":"reload"}</ui_nav>'
    )
    assert cleaned_ok == "Reloading now."
    assert cmds_ok == [
        {"type": "navigate_tab", "tab": "browser"},
        {"type": "browser_control", "action": "reload"},
    ]

    _, cmds_bad = extract_llm_ui_commands(
        'Blocked. <ui_nav>{"type":"browser_control","action":"exec_shell"}</ui_nav>'
    )
    assert cmds_bad == []

    # Non-browser `create` / `add` commands still pass through `MUTATION_OR_QUESTION_GUARD_RE` untouched
    assert nav.resolve_utterance("Create a new project called Apollo") == ([], [])
    assert nav.resolve_utterance("Add a task in KAIROS 2.0 for sprint testing") == ([], [])


def test_phase15_authenticated_webview_dom_clipping_and_did_fail_load_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase15_Clip_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)

    def _forbid_network_fetch(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("External fetch should be skipped when live <webview> HTML is supplied")

    monkeypatch.setattr(api_mod, "safe_fetch_public_text", _forbid_network_fetch)
    client = TestClient(api_mod.app)

    r_clip = client.post(
        "/api/browser/clip",
        json={
            "url": "https://github.com/ForestCityCreatorsLLC/Kairos",
            "title": "ForestCityCreatorsLLC/Kairos",
            "dest_folder": "04_Resources/Code_and_Research",
            "html_or_text": (
                "<html><body><main><h1>Private Repo Architecture</h1>"
                "<p>Authenticated Electron DOM capture verified.</p></main></body></html>"
            ),
        },
    )
    assert r_clip.status_code == 200
    saved = r_clip.json()
    assert "Authenticated Electron DOM capture verified." in saved["body"]

    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "extractLiveWebviewHtml" in browser_src
    assert "wv.addEventListener('did-fail-load', onDidFailLoad)" in browser_src
    assert "wv.removeEventListener('did-fail-load', onDidFailLoad)" in browser_src
    assert "code === -3 || code === 0" in browser_src
    assert "failEv.isMainFrame === false" in browser_src
    assert "if (clipping) return;" in browser_src
    assert "!vaultSections.some((s) => s.section_rel === '04_Resources/Music_Studio')" in browser_src


def test_phase15_client_abort_timeout_and_app_browser_control_wiring() -> None:
    client_src = (UI_SRC_ROOT / "api" / "client.ts").read_text(encoding="utf-8")
    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")

    # 1. `requestJson` enforces `AbortController` timeout with guaranteed `clearTimeout` cleanup
    assert "type: 'browser_control'" in client_src
    assert "new AbortController()" in client_src
    assert "Request timed out after" in client_src
    assert "globalThis.clearTimeout(timer)" in client_src

    # 2. `App.tsx` handles `browser_control` across `new_tab`, `close_tab`, `home`, `back`, `forward`, and `reload`
    assert "case 'browser_control':" in app_src
    assert "cmd.action === 'new_tab'" in app_src
    assert "cmd.action === 'close_tab'" in app_src
    assert "cmd.action === 'home'" in app_src
    assert "controlAction: cmd.action" in app_src


def test_phase15_command_palette_second_brain_orbit_and_startup_probe() -> None:
    palette_src = (UI_SRC_ROOT / "components" / "CommandPalette.tsx").read_text(encoding="utf-8")
    sb_src = (UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    start_bat = (REPO_ROOT / "start_kairos_2.bat").read_text(encoding="utf-8")

    # 1. CommandPalette cancels stale async searches and clamps `safeSelectedIdx`
    assert palette_src.count("let cancelled = false;") >= 2
    assert "const safeSelectedIdx =" in palette_src
    assert "Math.min(selectedIdx, keyboardItems.length - 1)" in palette_src
    assert "keyboardItems[safeSelectedIdx]" in palette_src

    # 2. SecondBrainWorkspace sequences `loadListAndGraph`, pauses 20Hz orbit during text editing, and guards drag-vs-click
    assert "listLoadSeqRef" in sb_src
    assert "if (seq !== listLoadSeqRef.current) return;" in sb_src
    assert "focusedTag === 'TEXTAREA' || focusedTag === 'INPUT' || focusedTag === 'SELECT'" in sb_src
    assert "draggingRef.current.moved" in sb_src

    # 3. `start_kairos_2.bat` uses 30s readiness deadline and reports accurate `[OK]` vs `[WARN]` status
    assert "AddSeconds(30)" in start_bat
    assert "[WARN] Startup probe timed out after 30s" in start_bat
