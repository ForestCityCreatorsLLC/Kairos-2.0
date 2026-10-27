"""Phase 10 — Adaptive Multi-Panel Layout Controls, ForestCityCreatorsLLC GitHub Org Sync & KAIROS 2.0 Continuity Suite."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
import services.kairos_core.connectors as connectors_mod
from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


class _FakeGitHubOrgResp:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


def test_voice_layout_controls_focus_mode_and_fcc_repos_navigation(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase10_Nav_Vault"))
    nav = bundle["navigator"]

    # 1. Left Sidebar retract / expand
    cmds_retract, _ = nav.resolve_utterance("Can you retract the sidebar?")
    assert cmds_retract == [{"type": "set_left_sidebar", "collapsed": True}]

    cmds_expand, _ = nav.resolve_utterance("Expand the left sidebar")
    assert cmds_expand == [{"type": "set_left_sidebar", "collapsed": False}]

    # 2. Focus Mode (collapses both Left Sidebar & Right Chat Drawer) and Exit Focus Mode
    cmds_focus, _ = nav.resolve_utterance("Enter focus mode")
    assert cmds_focus == [
        {"type": "set_left_sidebar", "collapsed": True},
        {"type": "set_chat_drawer", "open": False},
    ]

    cmds_restore, _ = nav.resolve_utterance("Exit focus mode")
    assert cmds_restore == [
        {"type": "set_left_sidebar", "collapsed": False},
        {"type": "set_chat_drawer", "open": True},
    ]

    # 3. Spoken ForestCityCreatorsLLC Repositories navigation vs plain GitHub root
    cmds_fcc, _ = nav.resolve_utterance("Can you pull up Forest City Creators repositories?")
    assert cmds_fcc == [
        {"type": "navigate_tab", "tab": "browser"},
        {
            "type": "browser_navigate",
            "url": "https://github.com/ForestCityCreatorsLLC?tab=repositories",
            "title": "Forest City Creators LLC — Repositories",
        },
    ]

    cmds_fcc_short, _ = nav.resolve_utterance("Open FCC repos")
    assert cmds_fcc_short[1]["url"] == "https://github.com/ForestCityCreatorsLLC?tab=repositories"

    cmds_gh_plain, _ = nav.resolve_utterance("Pull up GitHub")
    assert cmds_gh_plain[1]["url"] == "https://github.com"


def test_kairos_project_resolution_when_only_kairos_2_0_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase10_Kairos2Only_Vault"))
    vault = bundle["vault"]
    index = bundle["index"]

    # Remove seeded legacy `02_Projects/KAIROS` if present so ONLY `KAIROS_2_0` exists (live Canopy Vault layout)
    legacy_dir = vault.vault_path / "02_Projects" / "KAIROS"
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir)
    vault.create_project_structure(
        project="KAIROS_2_0",
        department="Marketing_and_Branding",
        list_name="Campaigns",
        scaffold_standard_departments=True,
    )
    index.rebuild_all()
    assert [p["name"] for p in index.get_projects_hierarchy()] == ["KAIROS_2_0"]

    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    # Spoken / quick-chip "Open KAIROS and switch to Gantt" resolves seamlessly to KAIROS_2_0
    r_nav = client.post(
        "/api/assistant/chat",
        json={"prompt": "Open KAIROS and switch to Gantt", "mode": "auto"},
    )
    assert r_nav.status_code == 200
    ui_cmds = r_nav.json()["ui_commands"]
    assert {"type": "select_project_scope", "project": "KAIROS_2_0", "department": "", "list": ""} in ui_cmds
    assert {"type": "set_projects_view", "view": "gantt"} in ui_cmds

    # Task creation saying "in KAIROS Marketing" routes cleanly into KAIROS_2_0/Marketing_and_Branding
    r_task = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Create high-priority task in KAIROS Marketing to draft launch reel and open it",
            "mode": "auto",
        },
    )
    assert r_task.status_code == 200
    t_rel = r_task.json().get("task_rel_path") or ""
    assert t_rel.startswith("02_Projects/KAIROS_2_0/Marketing_and_Branding/")


def test_github_org_catalog_sync_and_kairos_2_git_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v_dir = tmp_path / "Phase10_GitHubOrg_Vault"
    cfg = KairosSettings(vault_path=v_dir, gemini_api_key="")
    cfg.github_token = "ghp_mockSecretOrgPat999999"
    cfg.github_username = "fcc-operator"
    cfg.github_password = "SuperSecret#VaultPassword1!"
    bundle = create_mcp_bundle(str(v_dir), cfg=cfg)

    def _fake_github_get(url: str, *args: Any, **kwargs: Any) -> _FakeGitHubOrgResp:
        headers = kwargs.get("headers") or {}
        assert headers.get("Authorization") == "Bearer ghp_mockSecretOrgPat999999"
        if "/orgs/ForestCityCreatorsLLC/repos" in url:
            return _FakeGitHubOrgResp(
                200,
                [
                    {
                        "name": "Kairos",
                        "full_name": "ForestCityCreatorsLLC/Kairos",
                        "html_url": "https://github.com/ForestCityCreatorsLLC/Kairos",
                        "description": "KAIROS 2.0 Executive OS",
                        "private": True,
                        "language": "Python",
                        "default_branch": "main",
                        "pushed_at": "2026-10-26T14:30:00Z",
                    },
                    {
                        "name": "FCC-Brand-Portal",
                        "full_name": "ForestCityCreatorsLLC/FCC-Brand-Portal",
                        "html_url": "https://github.com/ForestCityCreatorsLLC/FCC-Brand-Portal",
                        "description": "Forest City Creators Web Showcase",
                        "private": False,
                        "language": "TypeScript",
                        "default_branch": "main",
                        "pushed_at": "2026-10-25T18:00:00Z",
                    },
                ],
            )
        return _FakeGitHubOrgResp(404, {})

    monkeypatch.setattr(connectors_mod.requests, "get", _fake_github_get)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    r_list = client.get("/api/connectors/github-org-repos?org=ForestCityCreatorsLLC")
    assert r_list.status_code == 200
    list_data = r_list.json()
    assert list_data["repo_count"] == 2
    assert list_data["private_count"] == 1
    assert list_data["authenticated_pat"] is True
    assert list_data["browser_env_login_configured"] is True
    raw_dump = str(list_data)
    assert "ghp_mockSecretOrgPat999999" not in raw_dump
    assert "SuperSecret#VaultPassword1!" not in raw_dump

    r_sync = client.post("/api/connectors/github-org-sync", json={"org": "ForestCityCreatorsLLC"})
    assert r_sync.status_code == 200
    sync_data = r_sync.json()
    assert sync_data["catalog_rel_path"] == "04_Resources/Code_and_Research/ForestCityCreatorsLLC_Repositories.md"
    cat_note = bundle["vault"].read_note(sync_data["catalog_rel_path"])
    assert "https://github.com/ForestCityCreatorsLLC?tab=repositories" in cat_note["body"]
    assert "🔒 Private" in cat_note["body"]
    assert "FCC-Brand-Portal" in cat_note["body"]

    # Read-only Git status on `KAIROS 2.0` resolves against the active workspace repository
    r_git = client.post(
        "/api/connectors/github-sync",
        json={"repo_name": "KAIROS 2.0", "action": "status"},
    )
    assert r_git.status_code == 200
    git_payload = r_git.json()
    assert "repo" in git_payload


def test_adaptive_resizable_drawer_and_github_ui_wiring() -> None:
    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    drawer_src = (UI_SRC_ROOT / "components" / "KairosChatDrawer.tsx").read_text(encoding="utf-8")
    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    settings_src = (UI_SRC_ROOT / "features" / "settings" / "SettingsWorkspace.tsx").read_text(
        encoding="utf-8"
    )

    assert "chatDrawerWidth" in app_src
    assert "handleStartResizeDrawer" in app_src
    assert "case 'set_left_sidebar':" in app_src
    assert "onResizeMouseDown" in drawer_src
    assert "syncGitHubOrgToVault" in browser_src
    assert "githubAuthInfo.loggedIn" in browser_src
    assert "handleSyncFccOrgCatalog" in settings_src
