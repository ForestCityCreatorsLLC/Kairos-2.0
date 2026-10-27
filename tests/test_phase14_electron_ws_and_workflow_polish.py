"""Phase 14 — Electron WebView Fullscreen & Lifecycle Guards, Auto-Reconnecting Voice WS, Cross-Tab Session Sync & Archive Path Guard."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
import services.kairos_voice.voice_service as voice_mod
from services.kairos_core.mcp_server import create_mcp_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"
ELECTRON_ROOT = REPO_ROOT / "apps" / "desktop" / "electron"


def test_phase14_electron_webview_fullscreen_and_is_destroyed_safety() -> None:
    main_src = (ELECTRON_ROOT / "main.cjs").read_text(encoding="utf-8")

    # 1. HTTPS fullscreen allowed for YouTube video playback inside `persist:kairos-browser`, all hardware permissions still denied
    assert "isSafeWebviewFullscreen" in main_src
    assert "permission !== 'fullscreen'" in main_src
    assert "protocol === 'https:'" in main_src
    assert "permission === 'media' || permission === 'clipboard-read'" in main_src

    # 2. `isDestroyed()` guards protect async `did-finish-load` and `setWindowOpenHandler` when tabs close mid-load
    assert "!contents.isDestroyed()" in main_src
    assert main_src.count("if (contents.isDestroyed()) return;") >= 2
    assert "!webContents.isDestroyed()" in main_src


def test_phase14_voice_ws_reconnect_escape_dismiss_and_context_hud() -> None:
    topbar_src = (UI_SRC_ROOT / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    hud_src = (UI_SRC_ROOT / "components" / "VoiceNavigatorHUD.tsx").read_text(encoding="utf-8")

    # 1. Voice Sidecar WebSocket (:8421) auto-reconnects and preserves active client LISTENING/SPEAKING state
    assert "const connectVoiceWs = () => {" in topbar_src
    assert "ws.onclose = () => {" in topbar_src
    assert "window.setTimeout(connectVoiceWs, 2500)" in topbar_src
    assert "window.clearTimeout(reconnectTimer)" in topbar_src
    assert "listeningWantedRef.current && parsed.status === 'IDLE'" in topbar_src

    # 2. Escape dismisses open TopBar popovers when not actively speaking
    assert "replyCard || showVoiceHud || showPaperclipPopover" in topbar_src
    assert "activeTaskId={activeTaskId}" in topbar_src

    # 3. VoiceNavigatorHUD has zero hardcoded archived demo task IDs (`TSK-20261024-009`) and adapts to `activeTaskId`
    assert "TSK-20261024-009" not in hud_src
    assert "function buildVoiceGroups(activeTaskId: string)" in hud_src
    assert "Create task base for KAIROS 2.0" in hud_src


def test_phase14_paperclip_skill_session_sync_inbox_locks_and_settings_refresh() -> None:
    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    paperclip_src = (UI_SRC_ROOT / "features" / "paperclip" / "PaperclipWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    drawer_src = (UI_SRC_ROOT / "components" / "KairosChatDrawer.tsx").read_text(encoding="utf-8")
    asst_src = (UI_SRC_ROOT / "features" / "assistant" / "AssistantWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    inbox_src = (UI_SRC_ROOT / "features" / "inbox" / "InboxWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    settings_src = (UI_SRC_ROOT / "features" / "settings" / "SettingsWorkspace.tsx").read_text(
        encoding="utf-8"
    )

    # 1. Paperclip "Apply with KAIROS" routes into active session, executes UI commands, and speaks reply
    assert "session_id: activeSessionId" in paperclip_src
    assert "onSelectSessionId?.(res.session.session_id)" in paperclip_src
    assert "[...(res.ui_commands || []), { type: 'set_chat_drawer', open: true }]" in paperclip_src
    assert "onSpeakReply?.(res.spoken_reply || res.reply, res.privacy_locked)" in paperclip_src

    # 2. Session persona & CODE_RED tone sync back across ChatDrawer, AssistantWorkspace, TopBar, and App
    assert "onChangeToneMode(res.session.tone_mode)" in drawer_src
    assert "onChangeToneMode(res.session.tone_mode)" in asst_src
    assert "onChangeToneMode={setToneMode}" in app_src

    # 3. Inbox double-click promotion race locks (`capturing` + `busyItemPath`)
    assert "busyItemPath" in inbox_src
    assert "if (busyItemPath) return;" in inbox_src
    assert "setCapturing(true)" in inbox_src

    # 4. Settings live diagnostics refresh on `refreshTick`
    assert "refreshTick={refreshTick}" in app_src
    assert "}, [refreshTick]);" in settings_src


def test_phase14_archive_project_traversal_guard_and_ws_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase14_ArchiveGuard_Vault"))
    vault = bundle["vault"]

    # Seed a sensitive note in `03_Personal/Finance/` and verify `POST /api/projects/archive` blocks `../` traversal with HTTP 400
    vault.write_note(
        "03_Personal/Finance/Protected_Tax_Vault.md",
        {"title": "Protected Tax Vault", "tags": ["private"]},
        "Confidential financial records.",
    )
    finance_file = vault.resolve_safe_path("03_Personal/Finance/Protected_Tax_Vault.md")
    assert finance_file.is_file()

    monkeypatch.setattr(api_mod, "_bundle", bundle)
    core_client = TestClient(api_mod.app)

    for bad_proj in ("", "..", "../03_Personal/Finance", "..\\03_Personal\\Finance", "KAIROS_2_0/../../03_Personal"):
        r_bad = core_client.post("/api/projects/archive", json={"project": bad_proj})
        assert r_bad.status_code == 400
    assert finance_file.is_file()

    # Valid project archive still succeeds cleanly
    vault.create_project_structure("Temp_Completed_Proj")
    r_ok = core_client.post("/api/projects/archive", json={"project": "Temp_Completed_Proj"})
    assert r_ok.status_code == 200
    assert "05_Archives/Temp_Completed_Proj" in r_ok.json()["archived_rel"]

    # WebSocket connect/disconnect leaves zero leaked sockets in Core `_ws_clients` and Voice `voice_ws_clients`
    before_core_ws = len(api_mod._ws_clients)
    with core_client.websocket_connect("/ws/events"):
        assert len(api_mod._ws_clients) == before_core_ws + 1
    assert len(api_mod._ws_clients) == before_core_ws

    voice_client = TestClient(voice_mod.app)
    before_voice_ws = len(voice_mod.voice_ws_clients)
    with voice_client.websocket_connect("/ws/voice") as ws_v:
        snap = ws_v.receive_json()
        assert "status" in snap
        assert len(voice_mod.voice_ws_clients) == before_voice_ws + 1
    assert len(voice_mod.voice_ws_clients) == before_voice_ws
