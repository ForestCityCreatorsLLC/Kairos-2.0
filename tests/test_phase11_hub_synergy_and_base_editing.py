"""Phase 11 — Section Hub Spoken Navigation, Deictic Browser-to-Hub Capture, GitHub Org AI Sync & Live `.base` Inline Editing Suite."""

from __future__ import annotations

import time
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


class _MockGitHubResp:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


def test_spoken_section_hub_and_fcc_subrepo_navigation(tmp_path: Path) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase11_Nav_Vault"))
    vault = bundle["vault"]
    index = bundle["index"]
    nav = bundle["navigator"]

    vault.create_project_structure(project="KAIROS_2_0")
    scaf = vault.scaffold_vault_section("", blueprint_key="music_production", seed_starters=True)
    index.rebuild_all()

    # 1. Spoken Section Hub MOC, Live `.base` Catalog, Ecosystem `.canvas`, and Vault Master Catalog
    cmds_hub, _ = nav.resolve_utterance("Open Music Studio")
    assert cmds_hub == [
        {"type": "navigate_tab", "tab": "second-brain"},
        {"type": "open_note", "rel_path": scaf["hub_index_rel"]},
    ]

    cmds_base, _ = nav.resolve_utterance("Pull up my Music Studio catalog")
    assert cmds_base == [
        {"type": "navigate_tab", "tab": "second-brain"},
        {"type": "open_note", "rel_path": scaf["base_rel"]},
    ]

    cmds_canvas, _ = nav.resolve_utterance("Show me the Music Studio canvas")
    assert cmds_canvas == [
        {"type": "navigate_tab", "tab": "second-brain"},
        {"type": "open_note", "rel_path": scaf["canvas_rel"]},
    ]

    cmds_master, _ = nav.resolve_utterance("Open Vault Master Catalog")
    assert cmds_master == [
        {"type": "navigate_tab", "tab": "second-brain"},
        {"type": "open_note", "rel_path": "_System/Dashboards/Vault_Master_Catalog.base"},
    ]

    # 2. Spoken ForestCityCreatorsLLC/<repo> sub-repository navigation without colliding with Projects or plain GitHub
    cmds_sub_direct, _ = nav.resolve_utterance("Open ForestCityCreatorsLLC/Kairos")
    assert cmds_sub_direct == [
        {"type": "navigate_tab", "tab": "browser"},
        {
            "type": "browser_navigate",
            "url": "https://github.com/ForestCityCreatorsLLC/Kairos",
            "title": "ForestCityCreatorsLLC/Kairos",
        },
    ]

    cmds_sub_spoken, _ = nav.resolve_utterance("Pull up FCC repo FCC-Brand-Portal")
    assert cmds_sub_spoken[1]["url"] == "https://github.com/ForestCityCreatorsLLC/FCC-Brand-Portal"

    cmds_plain_gh, _ = nav.resolve_utterance("Pull up GitHub")
    assert cmds_plain_gh[1]["url"] == "https://github.com"

    cmds_proj, _ = nav.resolve_utterance("Open KAIROS")
    assert cmds_proj[0] == {"type": "navigate_tab", "tab": "projects"}


def test_fast_skill_github_org_catalog_sync_and_kairos_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v_dir = tmp_path / "Phase11_GitHubSkill_Vault"
    cfg = KairosSettings(vault_path=v_dir, gemini_api_key="")
    cfg.github_token = "ghp_phase11MockTokenSecret777"
    cfg.github_username = "fcc-dev"
    cfg.github_password = "Phase11#VaultPasswordSecret!"
    bundle = create_mcp_bundle(str(v_dir), cfg=cfg)

    def _fake_get(url: str, *args: Any, **kwargs: Any) -> _MockGitHubResp:
        if "/orgs/ForestCityCreatorsLLC/repos" in url:
            return _MockGitHubResp(
                200,
                [
                    {
                        "name": "Kairos",
                        "full_name": "ForestCityCreatorsLLC/Kairos",
                        "html_url": "https://github.com/ForestCityCreatorsLLC/Kairos",
                        "description": "KAIROS 2.0 Canopy Vault Executive OS",
                        "private": True,
                        "language": "Python",
                        "default_branch": "main",
                        "pushed_at": "2026-10-26T15:00:00Z",
                    },
                    {
                        "name": "Canopy-Audio-DSP",
                        "full_name": "ForestCityCreatorsLLC/Canopy-Audio-DSP",
                        "html_url": "https://github.com/ForestCityCreatorsLLC/Canopy-Audio-DSP",
                        "description": "Audio DSP & Plug-in Utilities",
                        "private": True,
                        "language": "C++",
                        "default_branch": "main",
                        "pushed_at": "2026-10-25T20:00:00Z",
                    },
                ],
            )
        return _MockGitHubResp(404, {})

    monkeypatch.setattr(connectors_mod.requests, "get", _fake_get)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    r_chat = client.post(
        "/api/assistant/chat",
        json={"prompt": "Sync Forest City Creators repositories to Vault", "mode": "auto"},
    )
    assert r_chat.status_code == 200
    payload = r_chat.json()
    assert payload["route_reason"] == "fast_github_org_sync"
    assert payload["repo_count"] == 2
    assert payload["private_count"] == 2
    assert payload["catalog_rel_path"] == "04_Resources/Code_and_Research/ForestCityCreatorsLLC_Repositories.md"
    assert {"type": "open_note", "rel_path": payload["catalog_rel_path"]} in payload["ui_commands"]

    # Verify zero secret leakage in API output or indexed Vault Markdown
    cat_note = bundle["vault"].read_note(payload["catalog_rel_path"])
    combined_dump = f"{payload} {cat_note}"
    assert "ghp_phase11MockTokenSecret777" not in combined_dump
    assert "Phase11#VaultPasswordSecret!" not in combined_dump

    # Also verify direct `PlatformActionExecutor` `<kairos_op>` support
    op_res = bundle["assistant"].platform_executor.execute(
        "github_sync_org_catalog",
        {"org": "ForestCityCreatorsLLC", "open_in_ui": False},
    )
    assert op_res["ok"] is True
    assert op_res["data"]["repo_count"] == 2


def test_fast_skill_deictic_browser_page_to_section_hub_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase11_DeicticHub_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    r_save = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Save this page as a plugin in Music Studio",
            "mode": "auto",
            "active_browser_url": "https://xferrecords.com/products/serum-2",
            "active_browser_title": "Serum 2 — Xfer Records",
        },
    )
    assert r_save.status_code == 200
    data = r_save.json()
    assert data["route_reason"] == "fast_browser_section_entry"
    rel_path = data["entry_rel_path"]
    assert rel_path == "04_Resources/Music_Studio/Plugins/Serum_2.md"

    saved_note = bundle["vault"].read_note(rel_path)
    assert saved_note["frontmatter"]["vendor"] == "Xfer Records"
    assert saved_note["frontmatter"]["support_url"] == "https://xferrecords.com/products/serum-2"

    # Immediately visible inside the live Obsidian `.base` query engine
    r_base = client.get(
        "/api/vault/base-query",
        params={"rel_path": "04_Resources/Music_Studio/Music_Studio_Catalog.base"},
    )
    assert r_base.status_code == 200
    rows = r_base.json()["rows"]
    serum_row = next((r for r in rows if r["rel_path"] == rel_path), None)
    assert serum_row is not None
    assert serum_row["cells"]["vendor"] == "Xfer Records"


def test_inline_base_cell_frontmatter_patch_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = create_mcp_bundle(str(tmp_path / "Phase11_BaseInline_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    scaf = client.post(
        "/api/vault/sections",
        json={"blueprint_key": "music_production", "seed_starters": True},
    )
    assert scaf.status_code == 200
    sec_rel = scaf.json()["section_rel"]
    base_rel = scaf.json()["base_rel"]

    created = client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": sec_rel,
            "collection": "Plugins",
            "title": "Valhalla VintageVerb",
            "properties": {"vendor": "Valhalla DSP", "version": "4.0.0", "status": "Installed"},
        },
    )
    assert created.status_code == 200
    entry_rel = created.json()["rel_path"]

    t0 = time.perf_counter()
    patched = client.patch(
        "/api/vault/note/frontmatter",
        json={
            "rel_path": entry_rel,
            "updates": {"version": "4.0.5", "status": "Active"},
        },
    )
    assert patched.status_code == 200

    queried = client.get("/api/vault/base-query", params={"rel_path": base_rel})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert queried.status_code == 200
    assert elapsed_ms < 250.0

    vv_row = next((r for r in queried.json()["rows"] if r["rel_path"] == entry_rel), None)
    assert vv_row is not None
    assert vv_row["cells"]["version"] == "4.0.5"
    assert vv_row["cells"]["status"] == "Active"


def test_phase11_ui_wiring_contracts() -> None:
    sidebar_src = (UI_SRC_ROOT / "components" / "LeftSidebar.tsx").read_text(encoding="utf-8")
    assert "vaultSections" in sidebar_src
    assert "onOpenSectionNote" in sidebar_src
    assert "Section Hubs" in sidebar_src
    assert "PanelRight" in sidebar_src

    app_src = (UI_SRC_ROOT / "App.tsx").read_text(encoding="utf-8")
    assert "vaultSections={vaultSections}" in app_src
    assert "onOpenSectionNote={handleOpenNoteInSecondBrain}" in app_src

    browser_src = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "showFccReposDrawer" in browser_src
    assert "handleToggleFccReposDrawer" in browser_src
    assert "showHubEntryComposer" in browser_src
    assert "handleSaveHubEntry" in browser_src

    sb_src = (UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx").read_text(
        encoding="utf-8"
    )
    assert "baseSortCol" in sb_src
    assert "editingBaseCell" in sb_src
    assert "handleSaveBaseCellEdit" in sb_src
    assert "handleCopyBaseExport" in sb_src
    assert "Copy MD" in sb_src
    assert "Copy CSV" in sb_src
