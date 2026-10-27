"""Automatic Codebase-to-Canopy-Vault Change Synchronizer (`vault_sync_hook.py`).

Whenever files in the KAIROS 2.0 repository are added, modified, or deleted (or when invoked
via CLI / API / server startup), this module:
1. Diffs SHA-256 hashes of `services/`, `apps/desktop/src/`, `apps/desktop/electron/`, `tests/`, and root configs
   against `_System/Cache/codebase_sync_state.json` inside `Canopy Vault`.
2. Appends a structured Markdown changelog entry to `01_Business/OS_Updates/KAIROS_2_0_Change_Ledger.md`.
3. Recalculates `progress_pct` across all Project folders (`02_Projects/**/_Project_Index.md`).
4. Refreshes the SQLite WAL + FTS5 Shadow Index (`_System/Cache/vault_index.sqlite`) and logs to `AI_Audit_Log.jsonl`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.kairos_core.config import PROJECT_ROOT
from services.kairos_core.router import DualAIRouter
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine

TRACKED_SUBDIRS = (
    "services",
    "apps/desktop/src",
    "apps/desktop/electron",
    "tests",
)
TRACKED_ROOT_FILES = (
    "pyproject.toml",
    "README.md",
    ".env.example",
    "setup_kairos_2.bat",
    "run_tests.bat",
    "start_kairos_2.bat",
    "stop_kairos_2.bat",
    "verify_apis.bat",
    "sync_vault_changes.bat",
    "apps/desktop/package.json",
    "apps/desktop/vite.config.ts",
)
IGNORED_PARTS = {"__pycache__", "node_modules", "dist", ".venv", ".pytest_cache", ".git"}
TRACKED_SUFFIXES = {".py", ".ts", ".tsx", ".cjs", ".json", ".toml", ".bat", ".md", ".css", ".html"}

LEDGER_REL_PATH = "01_Business/OS_Updates/KAIROS_2_0_Change_Ledger.md"


def compute_codebase_manifest(codebase_root: Optional[Path] = None) -> Dict[str, str]:
    """Compute SHA-256 fingerprint map of all tracked KAIROS 2.0 source files."""
    root = (codebase_root or PROJECT_ROOT).resolve()
    manifest: Dict[str, str] = {}
    if not root.exists():
        return manifest

    for rel_file in TRACKED_ROOT_FILES:
        fp = root / rel_file
        if fp.is_file():
            manifest[rel_file.replace("\\", "/")] = hashlib.sha256(fp.read_bytes()).hexdigest()

    for sub in TRACKED_SUBDIRS:
        sub_dir = root / sub
        if not sub_dir.is_dir():
            continue
        for fp in sorted(sub_dir.rglob("*")):
            if not fp.is_file():
                continue
            if any(part in IGNORED_PARTS for part in fp.parts):
                continue
            if fp.suffix.lower() not in TRACKED_SUFFIXES:
                continue
            rel = str(fp.resolve().relative_to(root)).replace("\\", "/")
            manifest[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()

    return manifest


def sync_codebase_changes_to_vault(
    vault: VaultEngine,
    index: ShadowIndex,
    router: Optional[DualAIRouter] = None,
    *,
    codebase_root: Optional[Path] = None,
    summary_note: str = "",
    actor: str = "KAIROS-AutoSync",
) -> Dict[str, Any]:
    """Diff codebase files and synchronize changes + project rollups into Canopy Vault."""
    root = (codebase_root or PROJECT_ROOT).resolve()
    state_file = vault.vault_path / "_System" / "Cache" / "codebase_sync_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    current_manifest = compute_codebase_manifest(root)
    first_baseline = not state_file.exists()
    prev_manifest: Dict[str, str] = {}
    if not first_baseline:
        try:
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prev_manifest = {str(k): str(v) for k, v in loaded.get("files", {}).items()}
        except Exception:
            prev_manifest = {}

    added = sorted(k for k in current_manifest if k not in prev_manifest)
    modified = sorted(
        k for k in current_manifest if k in prev_manifest and current_manifest[k] != prev_manifest[k]
    )
    deleted = sorted(k for k in prev_manifest if k not in current_manifest)

    ledger_target = vault.resolve_safe_path(LEDGER_REL_PATH)
    ledger_exists = ledger_target.exists()

    # Recalculate all active project `_Project_Index.md` progress percentages
    projects_root = vault.vault_path / "02_Projects"
    # Non-destructively archive legacy seeded Multi-Department Structure Demo (`02_Projects/KAIROS`)
    # into `05_Archives/KAIROS` when `02_Projects/KAIROS_2_0` is the active Canopy Vault project.
    legacy_demo_idx = projects_root / "KAIROS" / "_Project_Index.md"
    if (projects_root / "KAIROS_2_0").is_dir() and legacy_demo_idx.is_file():
        try:
            demo_raw = legacy_demo_idx.read_text(encoding="utf-8", errors="replace")
            if "Multi-Department Structure Demo" in demo_raw:
                vault.archive_completed_project("KAIROS")
        except Exception:
            pass

    recalculated_projects: List[str] = []
    if projects_root.exists():
        for proj_idx in projects_root.rglob("_Project_Index.md"):
            vault.recalculate_project_progress(proj_idx.parent)
            recalculated_projects.append(vault.to_rel_path(proj_idx))

    now_iso = datetime.now().isoformat(timespec="seconds")
    now_human = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Save updated manifest state
    state_file.write_text(
        json.dumps({"updated_at": now_iso, "files": current_manifest}, indent=2),
        encoding="utf-8",
    )

    changed_total = len(added) + len(modified) + len(deleted)

    # If baseline state file didn't exist yet and ledger already exists with no manual summary,
    # record baseline cleanly without duplicating existing manual ledger notes.
    should_write_ledger = (not ledger_exists) or bool(summary_note.strip()) or (
        not first_baseline and changed_total > 0
    )

    if should_write_ledger:
        file_bullets: List[str] = []
        for f in added[:20]:
            file_bullets.append(f"  - `[ADDED]` `{f}`")
        for f in modified[:20]:
            file_bullets.append(f"  - `[MODIFIED]` `{f}`")
        for f in deleted[:10]:
            file_bullets.append(f"  - `[DELETED]` `{f}`")
        if changed_total > len(file_bullets):
            file_bullets.append(f"  - *...and {changed_total - len(file_bullets)} additional file(s)*")

        summary_line = summary_note.strip() or (
            "Initial codebase baseline synchronized to Canopy Vault."
            if first_baseline
            else f"Detected {len(added)} added, {len(modified)} modified, and {len(deleted)} removed file(s)."
        )
        entry_md = (
            f"## Auto-Synced Codebase Update — `{now_human}`\n"
            f"- **Actor:** `{actor}`\n"
            f"- **Project Link:** [[PRJ-2026-01]]\n"
            f"- **Summary:** {summary_line}\n"
        )
        if file_bullets:
            entry_md += f"- **Changed Files (`{changed_total}`):**\n" + "\n".join(file_bullets) + "\n"

        if not ledger_exists:
            header_body = (
                "# 📜 KAIROS 2.0 — Live OS & Codebase Change Ledger\n\n"
                "> [!IMPORTANT] Automatic Vault Synchronization Active\n"
                "> Every codebase, UI, backend, or test update automatically logs here.\n\n---\n\n"
                + entry_md
            )
            vault.write_note(
                LEDGER_REL_PATH,
                {
                    "id": "OSU-2026-KAIROS2",
                    "title": "KAIROS 2.0 — Live OS & Codebase Change Ledger",
                    "type": "os_update_ledger",
                    "project": "[[PRJ-2026-01]]",
                    "updated_at": now_iso,
                    "tags": ["os-updates", "changelog", "kairos-2", "vault-sync"],
                },
                header_body,
                mode="overwrite",
            )
        else:
            vault.write_note(
                LEDGER_REL_PATH,
                {"updated_at": now_iso},
                f"---\n\n{entry_md}",
                mode="append",
            )

        if router is not None:
            router.log_audit(
                agent=actor,
                route_reason="auto_codebase_vault_sync",
                tool="sync_codebase_changes_to_vault",
                target=LEDGER_REL_PATH,
            )

    index.rebuild_all()
    return {
        "ok": True,
        "ledger_updated": should_write_ledger,
        "ledger_rel_path": LEDGER_REL_PATH,
        "first_baseline": first_baseline,
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "recalculated_projects": recalculated_projects,
        "tracked_file_count": len(current_manifest),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize KAIROS 2.0 codebase changes to Canopy Vault")
    parser.add_argument("--summary", default="", help="Optional human-readable change summary to append")
    parser.add_argument("--actor", default="KAIROS-AutoSync", help="Actor label recorded in the Vault ledger")
    args = parser.parse_args()

    from services.kairos_core.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle()
    res = sync_codebase_changes_to_vault(
        bundle["vault"],
        bundle["index"],
        bundle["router"],
        summary_note=args.summary,
        actor=args.actor,
    )
    status = "Updated Vault Change Ledger" if res["ledger_updated"] else "Vault already in sync with codebase"
    print(
        f"[VaultSync] {status} ({res['tracked_file_count']} files tracked; "
        f"+{len(res['added'])} ~{len(res['modified'])} -{len(res['deleted'])})"
    )


if __name__ == "__main__":
    main()
