"""Phase 9 Verification Suite: State-of-the-Art Expandable Obsidian Vault Architecture.

Verifies:
1. Domain Section Hub Blueprints (`music_production`: Plugins, Add-ons & Presets, Samples & Packs, Support & Websites, Online Distribution for YouTube / Spotify / SoundCloud) + 4 additional domain blueprints + 100% custom Section Hubs.
2. Strict Official Obsidian Specifications:
   - Obsidian Bases (`.base` pure YAML with `filters`, `formulas`, `properties`, `views` Table/Cards, `summaries` — zero `---` frontmatter).
   - JSON Canvas Spec 1.0 (`.canvas` pure JSON with 16-char lowercase hex IDs, `group`/`file`/`text`/`link` nodes & valid edges).
   - Obsidian Flavored Markdown (`_Hub_Index.md` MOC, `_Collection_Index.md`, Callouts, Embeds, YAML `aliases` & properties).
3. Live `.base` Query Evaluator (`GET /api/vault/base-query`), Interactive Frontmatter Patching (`PATCH /api/vault/note/frontmatter`), Link-Safe Note Rename (`POST /api/vault/note/rename` rewriting `[[WikiLinks]]` + `.canvas` file nodes), Paperclip `HTTP 409` Lock Guards, and Vault Health Diagnostics (`GET /api/vault/health`).
4. Cross-Platform Synergy: Inbox -> Section Hub auto-metadata wiring, Browser Clipper -> Section Hub Support & Websites routing, KAIROS Fast Skills (`5g`, `5h`, `5i`) + `PlatformActionExecutor` ops, `#private` firewall isolation, and preserved 18 MCP / 4 Voice Tool invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
from services.kairos_core.config import KairosSettings
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.schemas import CreateTaskInput
from services.kairos_core.tool_registry import UnifiedVoiceToolRegistry
from services.kairos_core.vault_blueprint import validate_and_normalize_canvas
from services.kairos_core.vault_engine import parse_markdown_note

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_SRC_ROOT = REPO_ROOT / "apps" / "desktop" / "src"


def test_music_studio_section_hub_blueprint_bases_and_canvas_specs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify scaffolding the Music Studio Section Hub produces spec-valid MOC, Collections, `.base`, `.canvas` & Distribution guides."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_Music_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)
    vault = bundle["vault"]

    # Master `.base` catalog is seeded automatically during Vault initialization
    master_base_path = vault.vault_path / "_System" / "Dashboards" / "Vault_Master_Catalog.base"
    assert master_base_path.is_file()
    raw_master_base = master_base_path.read_text(encoding="utf-8")
    assert not raw_master_base.lstrip().startswith("---"), "Obsidian .base files must be pure YAML without frontmatter"
    parsed_master_base = yaml.safe_load(raw_master_base)
    assert isinstance(parsed_master_base, dict)
    assert "views" in parsed_master_base

    # Scaffold the Music Studio, Plugins & Distribution hub
    res = client.post(
        "/api/vault/sections",
        json={
            "section_name": "",
            "blueprint_key": "music_production",
            "seed_starters": True,
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["section_rel"] == "04_Resources/Music_Studio"
    assert payload["hub_index_rel"] == "04_Resources/Music_Studio/_Hub_Index.md"
    assert payload["base_rel"] == "04_Resources/Music_Studio/Music_Studio_Catalog.base"
    assert payload["canvas_rel"] == "04_Resources/Music_Studio/Music_Studio_Ecosystem.canvas"
    assert payload["template_rel"] == "_System/Templates/Music_Studio_Entry_Template.md"

    col_folders = {c["folder"] for c in payload["collections"]}
    assert col_folders == {
        "Plugins",
        "Addons_and_Presets",
        "Samples_and_Packs",
        "Support_and_Websites",
        "Distribution",
    }

    # Verify starter guides cover YouTube, Spotify, SoundCloud & Master Plug-in Managers
    seeded_joined = "\n".join(payload["seeded_entry_rels"])
    assert "YouTube" in seeded_joined
    assert "Spotify" in seeded_joined
    assert "SoundCloud" in seeded_joined
    assert "Plug-in" in seeded_joined or "Plugin" in seeded_joined

    # Verify `.base` YAML strictly conforms to Obsidian Bases syntax
    sec_base_raw = (vault.vault_path / payload["base_rel"]).read_text(encoding="utf-8")
    assert not sec_base_raw.lstrip().startswith("---")
    sec_base_doc = yaml.safe_load(sec_base_raw)
    assert isinstance(sec_base_doc["filters"], dict)
    assert "formulas" in sec_base_doc
    assert "properties" in sec_base_doc
    assert len(sec_base_doc["views"]) >= 6
    view_types = {v["type"] for v in sec_base_doc["views"]}
    assert {"table", "cards"}.issubset(view_types)

    # Verify `.canvas` JSON strictly conforms to JSON Canvas Spec 1.0
    sec_canvas_raw = (vault.vault_path / payload["canvas_rel"]).read_text(encoding="utf-8")
    assert not sec_canvas_raw.lstrip().startswith("---")
    canvas_check = validate_and_normalize_canvas(sec_canvas_raw)
    assert canvas_check["valid"] is True, f"Canvas spec errors: {canvas_check['errors']}"
    canvas_doc = json.loads(sec_canvas_raw)
    node_types = {n["type"] for n in canvas_doc["nodes"]}
    assert {"group", "file", "text", "link"}.issubset(node_types)
    link_urls = [n.get("url", "") for n in canvas_doc["nodes"] if n.get("type") == "link"]
    assert any("spotify.com" in u for u in link_urls)
    assert any("youtube.com" in u for u in link_urls)
    assert any("soundcloud.com" in u for u in link_urls)

    # Verify `GET /api/vault/structure` discovers the Section Hub, Collections, Folders & Blueprints
    struct_res = client.get("/api/vault/structure")
    assert struct_res.status_code == 200
    struct_data = struct_res.json()
    assert len(struct_data["blueprints"]) >= 5
    music_sec = next(
        (s for s in struct_data["sections"] if s["section_rel"] == "04_Resources/Music_Studio"),
        None,
    )
    assert music_sec is not None
    assert music_sec["entry_count"] >= 4
    assert "04_Resources/Music_Studio/Plugins" in struct_data["folders"]
    assert "04_Resources/Music_Studio/Distribution" in struct_data["folders"]


def test_structured_section_entries_and_live_obsidian_base_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify adding plug-ins, add-ons, and sample packs populates live `.base` Table & Cards views with formulas and summaries."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_Base_Eval_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    client.post(
        "/api/vault/sections",
        json={"section_name": "", "blueprint_key": "music_production", "seed_starters": True},
    )

    # 1. Add a VST3 Synth Plug-in
    r_plug = client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": "04_Resources/Music_Studio",
            "collection": "Plugins",
            "title": "Serum 2",
            "item_type": "plugin",
            "properties": {
                "vendor": "Xfer Records",
                "category": "Wavetable Synth",
                "format": "VST3 / CLAP",
                "version": "2.0.1",
                "license_model": "Owned",
                "support_url": "https://xferrecords.com/products/serum",
            },
            "checklist": ["Verify VST3 scan in DAW", "Sync preset user folder"],
            "aliases": ["Xfer Serum"],
        },
    )
    assert r_plug.status_code == 200
    plug_note = r_plug.json()
    assert plug_note["rel_path"] == "04_Resources/Music_Studio/Plugins/Serum_2.md"
    assert plug_note["frontmatter"]["vendor"] == "Xfer Records"
    assert plug_note["frontmatter"]["collection"] == "Plugins"
    assert "https://xferrecords.com/products/serum" in plug_note["body"]

    # 2. Add an Expansion Add-on & a Sample Pack
    r_addon = client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": "04_Resources/Music_Studio",
            "collection": "Addons_and_Presets",
            "title": "Neon Analog Bank",
            "properties": {
                "vendor": "Splice",
                "parent_plugin": "[[Serum_2]]",
                "support_url": "https://splice.com",
            },
        },
    )
    assert r_addon.status_code == 200

    r_pack = client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": "04_Resources/Music_Studio",
            "collection": "Samples_and_Packs",
            "title": " Velvet 808 Essentials ",
            "properties": {
                "vendor": "Native Instruments",
                "bpm_or_key": "140 BPM / F Minor",
                "license_type": "Royalty-Free",
            },
        },
    )
    assert r_pack.status_code == 200

    # Evaluate default `All Music Studio, Plugins & Distribution Items` Table view
    q_all = client.get(
        "/api/vault/base-query",
        params={"path": "04_Resources/Music_Studio/Music_Studio_Catalog.base"},
    )
    assert q_all.status_code == 200
    base_all = q_all.json()
    assert base_all["ok"] is True
    assert base_all["active_view"]["type"] == "table"
    assert base_all["total_rows"] >= 7  # 4 starters + 3 created items
    serum_row = next((r for r in base_all["rows"] if r["title"] == "Serum 2"), None)
    assert serum_row is not None
    assert serum_row["cells"]["formula.status_badge"] == "✅ Active"
    assert serum_row["cells"]["vendor"] == "Xfer Records"

    # Evaluate `Cards Gallery` view
    q_cards = client.get(
        "/api/vault/base-query",
        params={
            "path": "04_Resources/Music_Studio/Music_Studio_Catalog.base",
            "view": "Cards Gallery",
        },
    )
    assert q_cards.status_code == 200
    assert q_cards.json()["active_view"]["type"] == "cards"

    # Evaluate `🎛️ Plug-ins & Virtual Instruments` filtered view
    q_plugins = client.get(
        "/api/vault/base-query",
        params={
            "path": "04_Resources/Music_Studio/Music_Studio_Catalog.base",
            "view": "🎛️ Plug-ins & Virtual Instruments",
        },
    )
    assert q_plugins.status_code == 200
    plugin_titles = {r["title"] for r in q_plugins.json()["rows"]}
    assert "Serum 2" in plugin_titles
    assert "Spotify for Artists & Release Pipeline" not in plugin_titles

    # Evaluate `📡 Online Distribution & Streaming Setup` filtered view
    q_dist = client.get(
        "/api/vault/base-query",
        params={
            "path": "04_Resources/Music_Studio/Music_Studio_Catalog.base",
            "view": "📡 Online Distribution & Streaming Setup",
        },
    )
    assert q_dist.status_code == 200
    dist_titles = " | ".join(r["title"] for r in q_dist.json()["rows"])
    assert "YouTube" in dist_titles
    assert "Spotify" in dist_titles
    assert "SoundCloud" in dist_titles

    # Evaluate `_System/Dashboards/Vault_Master_Catalog.base` (Hubs view + All Active Notes view)
    q_master_hubs = client.get(
        "/api/vault/base-query",
        params={"path": "_System/Dashboards/Vault_Master_Catalog.base"},
    )
    assert q_master_hubs.status_code == 200
    assert q_master_hubs.json()["total_rows"] >= 1

    q_master_all = client.get(
        "/api/vault/base-query",
        params={"path": "_System/Dashboards/Vault_Master_Catalog.base", "view": "All Active Notes"},
    )
    assert q_master_all.status_code == 200
    assert q_master_all.json()["total_rows"] >= 7


def test_custom_domain_section_hub_and_idempotent_collection_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify arbitrary user-invented Section Hubs scaffold cleanly and expand idempotently without overwriting existing entries."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_Custom_Hub_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)

    # 1. Create a brand-new custom Photography Rig hub
    r_custom = client.post(
        "/api/vault/sections",
        json={
            "section_name": "Photography Rig",
            "blueprint_key": "custom",
            "parent_folder": "04_Resources",
            "icon": "📷",
            "description": "Camera bodies, lenses, lighting setups, and client delivery portals.",
            "collections": ["Bodies_and_Lenses", "Lighting_Gear"],
            "schema_fields": ["brand", "mount", "serial_ref", "support_url"],
            "seed_starters": False,
        },
    )
    assert r_custom.status_code == 200
    c_data = r_custom.json()
    assert c_data["section_rel"] == "04_Resources/Photography_Rig"
    assert {c["folder"] for c in c_data["collections"]} == {"Bodies_and_Lenses", "Lighting_Gear"}

    # Add a camera entry
    r_cam = client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": "04_Resources/Photography_Rig",
            "collection": "Bodies_and_Lenses",
            "title": "Sony A7R V",
            "properties": {"brand": "Sony", "mount": "E-Mount", "support_url": "https://electronics.sony.com"},
            "body": "# 📷 Sony A7R V\n\nCustom user calibration notes preserved across expansions.\n",
        },
    )
    assert r_cam.status_code == 200

    # 2. Expand the existing Section Hub with a new collection (`Client_Delivery`)
    r_expand = client.post(
        "/api/vault/sections",
        json={
            "section_name": "Photography Rig",
            "blueprint_key": "custom",
            "parent_folder": "04_Resources",
            "icon": "📷",
            "collections": ["Bodies_and_Lenses", "Lighting_Gear", "Client_Delivery"],
            "schema_fields": ["brand", "mount", "serial_ref", "support_url", "delivery_platform"],
            "seed_starters": False,
        },
    )
    assert r_expand.status_code == 200
    exp_cols = {c["folder"] for c in r_expand.json()["collections"]}
    assert exp_cols == {"Bodies_and_Lenses", "Lighting_Gear", "Client_Delivery"}

    # Verify existing `Sony_A7R_V.md` body was NOT overwritten
    preserved = client.get(
        "/api/vault/note",
        params={"path": "04_Resources/Photography_Rig/Bodies_and_Lenses/Sony_A7R_V.md"},
    )
    assert preserved.status_code == 200
    assert "Custom user calibration notes preserved across expansions." in preserved.json()["body"]


def test_frontmatter_patch_link_safe_rename_paperclip_409_and_vault_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify YAML property patching, link-safe note rename across Markdown + `.canvas`, Paperclip `409` guards, and Vault Health."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_Integrity_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)
    vault = bundle["vault"]
    index = bundle["index"]
    paperclip = bundle["paperclip"]

    client.post(
        "/api/vault/sections",
        json={"section_name": "", "blueprint_key": "music_production", "seed_starters": True},
    )
    client.post(
        "/api/vault/sections/entries",
        json={
            "section_or_folder": "04_Resources/Music_Studio",
            "collection": "Plugins",
            "title": "Pigments 5",
            "properties": {"vendor": "Arturia", "temp_flag": "remove-me"},
            "body": "# 🎛️ Pigments 5\n\nPolychrome synth engine notes.\n",
        },
    )
    pigments_rel = "04_Resources/Music_Studio/Plugins/Pigments_5.md"

    # 1. Patch frontmatter properties without touching Markdown body
    r_patch = client.patch(
        "/api/vault/note/frontmatter",
        json={
            "file_path": pigments_rel,
            "updates": {"version": "5.0.3", "format": "VST3", "rating": 5},
            "remove_keys": ["temp_flag"],
        },
    )
    assert r_patch.status_code == 200
    patched_fm = r_patch.json()["frontmatter"]
    assert patched_fm["version"] == "5.0.3"
    assert patched_fm["rating"] == 5
    assert "temp_flag" not in patched_fm
    assert "Polychrome synth engine notes." in r_patch.json()["body"]

    # 2. Add a Markdown note AND a `.canvas` file node referencing `Pigments_5.md`
    mix_chain_rel = "04_Resources/Music_Studio/Synth_Bus_Chain.md"
    client.post(
        "/api/vault/note",
        json={
            "file_path": mix_chain_rel,
            "frontmatter": {
                "title": "Synth Bus Chain",
                "type": "guide",
                "section_hub": "[[04_Resources/Music_Studio/_Hub_Index|Music Studio]]",
            },
            "body": (
                "# 🎚️ Synth Bus Chain\n\n"
                "- Primary Instrument: [[04_Resources/Music_Studio/Plugins/Pigments_5|Arturia Pigments]]\n"
                "- Short Stem Link: [[Pigments_5]]\n"
            ),
            "mode": "overwrite",
        },
    )

    canvas_rel = "04_Resources/Music_Studio/Music_Studio_Ecosystem.canvas"
    canvas_abs = vault.resolve_safe_path(canvas_rel)
    canvas_obj = json.loads(canvas_abs.read_text(encoding="utf-8"))
    canvas_obj["nodes"].append(
        {
            "id": "abcdef0123456789",
            "type": "file",
            "file": pigments_rel,
            "x": 920,
            "y": 120,
            "width": 320,
            "height": 180,
        }
    )
    canvas_bytes = (json.dumps(canvas_obj, indent=2) + "\n").encode("utf-8")
    vault.hash_guard.record_write(canvas_abs, canvas_bytes)
    canvas_abs.write_bytes(canvas_bytes)
    index.index_file(canvas_abs)

    # 3. Link-safe rename `Pigments_5.md` -> `Arturia_Pigments_6.md`
    new_pigments_rel = "04_Resources/Music_Studio/Plugins/Arturia_Pigments_6.md"
    r_ren = client.post(
        "/api/vault/note/rename",
        json={
            "src_rel_path": pigments_rel,
            "dest_rel_path": new_pigments_rel,
            "new_title": "Arturia Pigments 6",
            "update_links": True,
        },
    )
    assert r_ren.status_code == 200
    ren_payload = r_ren.json()
    assert ren_payload["new_rel_path"] == new_pigments_rel
    assert mix_chain_rel in ren_payload["updated_backlink_files"]
    assert canvas_rel in ren_payload["updated_backlink_files"]

    # Verify both Markdown `[[WikiLinks]]` and `.canvas` `"file"` node updated cleanly
    rewritten_md = client.get("/api/vault/note", params={"path": mix_chain_rel}).json()["body"]
    assert "[[04_Resources/Music_Studio/Plugins/Arturia_Pigments_6|Arturia Pigments]]" in rewritten_md
    assert "[[Arturia_Pigments_6]]" in rewritten_md

    rewritten_canvas = json.loads(canvas_abs.read_text(encoding="utf-8"))
    assert any(
        n.get("type") == "file" and n.get("file") == new_pigments_rel
        for n in rewritten_canvas["nodes"]
    )

    # Verify incoming backlinks include BOTH `Synth_Bus_Chain.md` AND `Music_Studio_Ecosystem.canvas`
    bl_res = client.get("/api/vault/backlinks", params={"path": new_pigments_rel})
    assert bl_res.status_code == 200
    bl_paths = {b["rel_path"] for b in bl_res.json()["backlinks"]}
    assert mix_chain_rel in bl_paths
    assert canvas_rel in bl_paths

    # 4. Verify Vault Health reports valid syntax & zero broken links
    health_res = client.get("/api/vault/health")
    assert health_res.status_code == 200
    health = health_res.json()
    assert health["syntax_issues"] == []
    assert health["broken_links"] == []
    assert health["health_score"] >= 90

    # 5. Verify Paperclip `HTTP 409` checkout lock guards on frontmatter patch & rename
    created_tsk = vault.create_task(
        CreateTaskInput(title="Locked Studio Audit Task", project="KAIROS_2_0")
    )
    tid = created_tsk["frontmatter"]["id"]
    tsk_rel = created_tsk["rel_path"]
    index.index_file(vault.resolve_safe_path(tsk_rel))
    paperclip.checkout_task(tid, agent="CrewAI-Dev")

    r_locked_patch = client.patch(
        "/api/vault/note/frontmatter",
        json={"file_path": tsk_rel, "updates": {"priority": 1}},
    )
    assert r_locked_patch.status_code == 409

    r_locked_rename = client.post(
        "/api/vault/note/rename",
        json={"src_rel_path": tsk_rel, "dest_rel_path": f"{tid}_Renamed.md"},
    )
    assert r_locked_rename.status_code == 409
    paperclip.force_release_lock(tid, actor="TestSuite", reason="Cleanup")


def test_inbox_to_section_hub_triage_and_conversational_fast_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify natural-language KAIROS commands, Browser Clipper routing, Inbox-to-Hub auto-wiring & `#private` isolation."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_AI_Synergy_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    monkeypatch.setattr(api_mod, "_bundle", bundle)
    client = TestClient(api_mod.app)
    vault = bundle["vault"]

    # 1. Natural-language request matching the user's exact Music Studio & Distribution prompt
    r_cmd_hub = client.post(
        "/api/kairos/command",
        json={
            "prompt": (
                "I want to make a music section in my vault that lists all my plug-ins and websites "
                "for support, add-ons, samples, and setup for online distribution on platforms like "
                "YouTube, Spotify, SoundCloud"
            ),
            "mode": "gemma-4",
        },
    )
    assert r_cmd_hub.status_code == 200
    hub_reply = r_cmd_hub.json()
    assert hub_reply["route_reason"] == "fast_vault_section_scaffold"
    assert hub_reply["section_rel"] == "04_Resources/Music_Studio"
    assert any(c.get("tab") == "second-brain" for c in hub_reply["ui_commands"])

    # 2. Natural-language plugin registration (`Fast Skill 5h`)
    r_cmd_entry = client.post(
        "/api/kairos/command",
        json={
            "prompt": (
                "Add plugin FabFilter Pro-Q 4 by FabFilter to Music Studio "
                "with support https://www.fabfilter.com/support"
            ),
            "mode": "gemma-4",
        },
    )
    assert r_cmd_entry.status_code == 200
    ent_reply = r_cmd_entry.json()
    assert ent_reply["route_reason"] == "fast_vault_section_entry"
    assert ent_reply["entry_rel_path"] == "04_Resources/Music_Studio/Plugins/FabFilter_Pro-Q_4.md"
    fab_fm, _ = parse_markdown_note(
        vault.resolve_safe_path(ent_reply["entry_rel_path"]).read_text(encoding="utf-8")
    )
    assert fab_fm["vendor"] == "FabFilter"
    assert fab_fm["support_url"] == "https://www.fabfilter.com/support"

    # 3. Conversational rename of the open note (`Fast Skill 5i`)
    r_cmd_ren = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Rename this note to FabFilter_Pro_Q4_EQ",
            "mode": "gemma-4",
            "active_note_path": "04_Resources/Music_Studio/Plugins/FabFilter_Pro-Q_4.md",
        },
    )
    assert r_cmd_ren.status_code == 200
    assert r_cmd_ren.json()["route_reason"] == "fast_vault_note_rename"
    assert (vault.vault_path / "04_Resources" / "Music_Studio" / "Plugins" / "FabFilter_Pro_Q4_EQ.md").is_file()

    # 4. Triage an `00_Inbox/` capture into `04_Resources/Music_Studio/Samples_and_Packs` -> auto-wires `section_hub` & `collection`
    cap = vault.write_note(
        "00_Inbox/Capture_Vocal_Chops.md",
        {"title": "Soul Vocal Chops Vol 1", "type": "inbox_capture", "tags": ["inbox", "capture"]},
        "# 📥 Soul Vocal Chops Vol 1\n\nRoyalty-free chop pack from Splice.\n",
    )
    r_move = client.post(
        "/api/inbox/move",
        json={
            "src_rel_path": cap["rel_path"],
            "dest_folder": "04_Resources/Music_Studio/Samples_and_Packs",
        },
    )
    assert r_move.status_code == 200
    moved_fm = r_move.json()["frontmatter"]
    assert "04_Resources/Music_Studio/_Hub_Index" in str(moved_fm.get("section_hub", ""))
    assert moved_fm["collection"] == "Samples_and_Packs"
    assert "inbox" not in [str(t).lower() for t in moved_fm.get("tags", [])]

    # 5. `#private` Section Hub entry stays strictly privacy-locked
    r_priv_entry = client.post(
        "/api/kairos/command",
        json={
            "prompt": "Add support site Royalty Tax Portal to Music Studio with support https://distrokid.com/tax #private",
            "mode": "auto",
        },
    )
    assert r_priv_entry.status_code == 200
    assert r_priv_entry.json()["privacy_locked"] is True
    priv_fm, _ = parse_markdown_note(
        vault.resolve_safe_path(r_priv_entry.json()["entry_rel_path"]).read_text(encoding="utf-8")
    )
    assert "private" in [str(t).lower() for t in priv_fm.get("tags", [])]


def test_phase9_ui_cross_tab_integration_and_mcp_invariants(tmp_path: Path) -> None:
    """Verify preserved 18 MCP / 4 Voice Tool invariants and dynamic Vault Section Hub wiring across Second Brain, Browser & Inbox."""
    cfg = KairosSettings(vault_path=tmp_path / "Phase9_Invariants_Vault", gemini_api_key="")
    bundle = create_mcp_bundle(vault_path=cfg.vault_path, cfg=cfg)
    assert len(bundle["mcp_tools"]) == 18

    voice_reg = UnifiedVoiceToolRegistry(bundle["vault"], bundle["index"])
    assert len(voice_reg.get_tool_declarations()) == 4

    exec_ops = bundle["assistant"].platform_executor.SUPPORTED_OPS
    assert {
        "vault_scaffold_section",
        "vault_create_entry",
        "vault_update_frontmatter",
        "vault_rename_note",
    }.issubset(exec_ops)

    sb_tsx = (UI_SRC_ROOT / "features" / "second-brain" / "SecondBrainWorkspace.tsx").read_text(encoding="utf-8")
    assert "scaffoldVaultSection" in sb_tsx
    assert "createVaultSectionEntry" in sb_tsx
    assert "queryVaultBase" in sb_tsx
    assert "updateNoteFrontmatter" in sb_tsx
    assert "renameVaultNote" in sb_tsx
    assert "getVaultHealth" in sb_tsx

    browser_tsx = (UI_SRC_ROOT / "features" / "browser" / "BrowserWorkspace.tsx").read_text(encoding="utf-8")
    assert "getVaultStructure" in browser_tsx
    assert "soundcloud.com" in browser_tsx
    assert "spotify.com" in browser_tsx

    inbox_tsx = (UI_SRC_ROOT / "features" / "inbox" / "InboxWorkspace.tsx").read_text(encoding="utf-8")
    assert "getVaultStructure" in inbox_tsx
    assert "filingDestinations" in inbox_tsx
