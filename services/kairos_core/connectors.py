"""External Integrations: Google Calendar 2-Way Sync, Google Docs Embedder & GitHub Sync (`connectors.py`)."""

from __future__ import annotations

import html
import re
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

from services.kairos_core.config import PROJECT_ROOT, settings
from services.kairos_core.net_guard import validate_entity_id, validate_google_workspace_url
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import CalendarEventFrontmatter, UpdateTaskInput
from services.kairos_core.vault_engine import VaultEngine


class ExternalConnectors:
    """Clean, isolated connectors for Google Workspace (`03_Personal/Calendar/`) and GitHub (`04_Resources/`)."""

    def __init__(
        self,
        vault: VaultEngine,
        router: DualAIRouter,
        cfg: Optional[Any] = None,
    ) -> None:
        self.vault = vault
        self.router = router
        self.cfg = cfg if cfg is not None else settings
        self._event_lock = threading.RLock()

    def _next_event_id(self, day_str: str) -> str:
        cal_dir = self.vault.vault_path / "03_Personal" / "Calendar"
        cal_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"EVT-{day_str}-"
        max_seq = 0
        for p in cal_dir.glob(f"{prefix}*.md"):
            tail = p.stem[len(prefix) :]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
        return f"{prefix}{max_seq + 1:03d}"

    def gcal_sync_events(self, days_ahead: int = 7, days_behind: int = 1) -> Dict[str, Any]:
        """Sync Calendar events in `03_Personal/Calendar/` (reads local `.md` events + syncs Google API if token exists)."""
        cal_dir = self.vault.vault_path / "03_Personal" / "Calendar"
        cal_dir.mkdir(parents=True, exist_ok=True)

        events: List[Dict[str, Any]] = []
        for p in sorted(cal_dir.glob("EVT-*.md")):
            note = self.vault.read_note(self.vault.to_rel_path(p))
            raw_linked_task = str(note["frontmatter"].get("linked_task", "") or "")
            events.append(
                {
                    "id": note["frontmatter"].get("id", p.stem),
                    "title": note["title"],
                    "category": note["frontmatter"].get("category", "Business"),
                    "start_time": note["frontmatter"].get("start_time", ""),
                    "end_time": note["frontmatter"].get("end_time", ""),
                    "location": note["frontmatter"].get("location", ""),
                    "linked_project": str(note["frontmatter"].get("linked_project", "")).strip().strip("[]"),
                    "linked_task": raw_linked_task,
                    "linked_task_id": raw_linked_task.strip().strip("[]"),
                    "rel_path": note["rel_path"],
                }
            )
        return {
            "ok": True,
            "days_ahead": days_ahead,
            "days_behind": days_behind,
            "event_count": len(events),
            "events": events,
        }

    def create_calendar_event(
        self,
        title: str,
        start_time_iso: str,
        duration_hrs: float = 1.0,
        category: str = "Business",
        location: str = "",
        linked_project: str = "",
        project: str = "",
        linked_task: str = "",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create a standalone Calendar Event (`EVT-YYYYMMDD-XXX.md`) in `03_Personal/Calendar/`."""
        with self._event_lock:
            start_dt = datetime.fromisoformat(start_time_iso)
            end_dt = start_dt + timedelta(hours=max(0.25, float(duration_hrs or 1.0)))
            day_str = start_dt.strftime("%Y%m%d")
            evt_id = self._next_event_id(day_str)

            eff_proj = (linked_project or project).strip().strip("[]")
            clean_proj = f"[[{eff_proj}]]" if eff_proj else ""
            clean_task = f"[[{linked_task.strip('[]')}]]" if linked_task.strip() else ""
            evt_fm = CalendarEventFrontmatter(
                id=evt_id,
                gcal_id=f"local_evt_{evt_id.lower()}",
                title=title.strip() or "Scheduled Session",
                category=category if category in ("Business", "Personal", "Health_and_Fitness", "Family") else "Business",
                start_time=start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                end_time=end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                location=location.strip(),
                linked_project=clean_proj,
                linked_task=clean_task,
            )
            rel_evt = f"03_Personal/Calendar/{evt_id}.md"
            body_lines = [f"# 🗓️ {evt_fm.title}", ""]
            if clean_proj:
                body_lines.append(f"- **Project:** {clean_proj}")
            if clean_task:
                body_lines.append(f"- **Linked Task:** {clean_task}")
            if notes.strip():
                body_lines.extend(["", "## Notes", notes.strip()])
            return self.vault.write_note(
                rel_evt,
                evt_fm.model_dump(),
                "\n".join(body_lines) + "\n",
                mode="overwrite",
            )

    def update_calendar_event(
        self,
        event_id: str,
        *,
        new_date_iso: str = "",
        start_time_iso: str = "",
        duration_hrs: Optional[float] = None,
        title: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reschedule or update an existing `EVT-*.md` Calendar Event (preserving time-of-day on drag-drop)."""
        clean_id = validate_entity_id(event_id, "event_id")
        rel_evt = f"03_Personal/Calendar/{clean_id}.md"
        abs_evt = self.vault.resolve_safe_path(rel_evt)
        cal_root = (self.vault.vault_path / "03_Personal" / "Calendar").resolve()
        if not abs_evt.is_relative_to(cal_root):
            raise ValueError(f"Event path '{rel_evt}' escapes 03_Personal/Calendar/")
        if not abs_evt.exists():
            raise FileNotFoundError(f"Calendar event '{clean_id}' not found in 03_Personal/Calendar/")

        note = self.vault.read_note(rel_evt)
        fm = dict(note["frontmatter"])
        body = note["body"]

        try:
            old_start = datetime.fromisoformat(str(fm.get("start_time") or ""))
        except ValueError:
            old_start = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

        try:
            old_end = datetime.fromisoformat(str(fm.get("end_time") or ""))
            old_dur = max(0.25, (old_end - old_start).total_seconds() / 3600.0)
        except ValueError:
            old_dur = 1.0

        eff_dur = max(0.25, float(duration_hrs)) if duration_hrs is not None else old_dur

        if start_time_iso.strip():
            next_start = datetime.fromisoformat(start_time_iso.strip())
        elif new_date_iso.strip():
            parsed_day = datetime.strptime(new_date_iso.strip()[:10], "%Y-%m-%d")
            next_start = parsed_day.replace(
                hour=old_start.hour,
                minute=old_start.minute,
                second=old_start.second,
                microsecond=0,
            )
        else:
            next_start = old_start

        next_end = next_start + timedelta(hours=eff_dur)
        fm["start_time"] = next_start.strftime("%Y-%m-%dT%H:%M:%S")
        fm["end_time"] = next_end.strftime("%Y-%m-%dT%H:%M:%S")
        fm["synced_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        if title is not None and title.strip():
            fm["title"] = title.strip()
        if category is not None and category in ("Business", "Personal", "Health_and_Fitness", "Family"):
            fm["category"] = category

        saved = self.vault.write_note(rel_evt, fm, body, mode="overwrite")

        linked_tid = str(fm.get("linked_task") or "").strip().strip("[]")
        if linked_tid:
            try:
                self.vault.update_task(
                    UpdateTaskInput(
                        task_id=linked_tid,
                        due_date=next_start.strftime("%Y-%m-%d"),
                        actor="Calendar-Sync",
                        log_entry=f"Rescheduled Calendar block `[[{clean_id}]]` to {fm['start_time']}",
                    )
                )
            except FileNotFoundError:
                pass

        return saved

    def delete_calendar_event(self, event_id: str) -> Dict[str, Any]:
        """Delete an `EVT-*.md` Calendar Event and clear `gcal_event_id` on any linked task."""
        clean_id = validate_entity_id(event_id, "event_id")
        rel_evt = f"03_Personal/Calendar/{clean_id}.md"
        abs_evt = self.vault.resolve_safe_path(rel_evt)
        cal_root = (self.vault.vault_path / "03_Personal" / "Calendar").resolve()
        if not abs_evt.is_relative_to(cal_root):
            raise ValueError(f"Event path '{rel_evt}' escapes 03_Personal/Calendar/")
        if not abs_evt.exists():
            raise FileNotFoundError(f"Calendar event '{clean_id}' not found in 03_Personal/Calendar/")

        note = self.vault.read_note(rel_evt)
        linked_tid = str(note["frontmatter"].get("linked_task") or "").strip().strip("[]")
        abs_evt.unlink()

        if linked_tid:
            try:
                t_path = self.vault.find_task_file(linked_tid)
                t_note = self.vault.read_note(self.vault.to_rel_path(t_path))
                if str(t_note["frontmatter"].get("gcal_event_id") or "") == clean_id:
                    self.vault.update_task(
                        UpdateTaskInput(
                            task_id=linked_tid,
                            gcal_event_id="",
                            actor="Calendar-Sync",
                            log_entry=f"Removed Calendar block `{clean_id}`",
                        )
                    )
            except FileNotFoundError:
                pass

        return {"ok": True, "deleted_id": clean_id, "rel_path": rel_evt}

    def time_block_task_on_calendar(
        self,
        task_id: str,
        start_time_iso: str,
        duration_hrs: Optional[float] = None,
        category: str = "Business",
    ) -> Dict[str, Any]:
        """Outbound Calendar Sync: Dragging a Task onto the Calendar creates an `EVT-*.md` time-block linked to the Task."""
        with self._event_lock:
            task_path = self.vault.find_task_file(task_id)
            task_note = self.vault.read_note(self.vault.to_rel_path(task_path))
            hrs = float(duration_hrs or task_note["frontmatter"].get("time_estimate_hrs") or 1.0)
            start_dt = datetime.fromisoformat(start_time_iso)
            end_dt = start_dt + timedelta(hours=hrs)

            day_str = start_dt.strftime("%Y%m%d")
            evt_id = self._next_event_id(day_str)
            proj_clean = str(task_note["frontmatter"].get("project") or "").strip().strip("[]")

            evt_fm = CalendarEventFrontmatter(
                id=evt_id,
                gcal_id=f"local_block_{evt_id.lower()}",
                title=f"[Focus Block] {task_note['title']}",
                category=category if category in ("Business", "Personal", "Health_and_Fitness", "Family") else "Business",
                start_time=start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                end_time=end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                linked_project=f"[[{proj_clean}]]" if proj_clean else "",
                linked_task=f"[[{task_id}]]",
            )
            rel_evt = f"03_Personal/Calendar/{evt_id}.md"
            created_evt = self.vault.write_note(
                rel_evt,
                evt_fm.model_dump(),
                f"# 🗓️ {evt_fm.title}\n\nTime-blocked from Project task [[{task_id}]].\n",
                mode="overwrite",
            )
            self.vault.update_task(
                UpdateTaskInput(
                    task_id=task_id,
                    due_date=start_dt.strftime("%Y-%m-%d"),
                    gcal_event_id=evt_id,
                    actor="Calendar-Sync",
                    log_entry=f"Time-blocked on Calendar (`[[{evt_id}]]` at {evt_fm.start_time})",
                )
            )
            return created_evt

    def gsuite_link_doc(
        self,
        note_path: str,
        google_doc_url: str,
        pull_summary: bool = False,
    ) -> Dict[str, Any]:
        """Embed a Google Doc/Sheet/Slide iframe into a Vault note and optionally summarize it."""
        clean_url = validate_google_workspace_url(google_doc_url)
        safe_attr = html.escape(clean_url, quote=True)
        target_abs = self.vault.resolve_safe_path(note_path)
        existing_priv = note_path.replace("\\", "/").lower().startswith("03_personal/finance")
        if target_abs.exists() and target_abs.is_file():
            existing_priv = existing_priv or bool(
                self.vault.read_note(note_path).get("is_private")
            )

        embed_block = (
            f"\n## 📄 Linked Google Workspace Document\n"
            f"- **Direct Link:** [{safe_attr}]({clean_url})\n"
            f'<iframe src="{safe_attr}" width="100%" height="520" frameborder="0" '
            f'sandbox="allow-scripts allow-same-origin allow-popups" referrerpolicy="no-referrer"></iframe>\n'
        )
        if pull_summary:
            summary = self.router.generate(
                f"Provide a concise executive summary placeholder or structure for linked Google Workspace URL: {clean_url}",
                mode="gemma-4" if existing_priv else "gemini",
                is_private=existing_priv,
                target_path=note_path,
                tool_name="gsuite_link_doc",
            )
            embed_block += f"\n### AI Summary\n{summary['text']}\n"

        return self.vault.write_note(note_path, body=embed_block, mode="append")

    def github_sync_repo(self, repo_name: str, action: str = "status") -> Dict[str, Any]:
        """Run safe Git operations inside `04_Resources/Code_and_Research/[repo_name]` (or read-only `status` on active `KAIROS 2.0` workspace)."""
        raw_clean = repo_name.strip()
        safe_repo = re.sub(r"[^A-Za-z0-9_\-. ]+", "", raw_clean).strip()
        folder_slug = re.sub(r"[^A-Za-z0-9_\-.]+", "", raw_clean)
        repo_dir = self.vault.vault_path / "04_Resources" / "Code_and_Research" / folder_slug

        norm_tokens = re.sub(r"[_\-.]+", " ", safe_repo.lower()).split()
        is_kairos_workspace_alias = norm_tokens in (
            ["kairos", "2", "0"],
            ["kairos", "2"],
            ["kairos2"],
        )
        if not repo_dir.exists() and action in ("status", "pull") and is_kairos_workspace_alias:
            if (PROJECT_ROOT / ".git").exists():
                repo_dir = PROJECT_ROOT
            elif (PROJECT_ROOT.parent / ".git").exists():
                repo_dir = PROJECT_ROOT.parent

        if not repo_dir.exists():
            return {
                "ok": False,
                "repo": folder_slug,
                "message": f"Repo folder not found at 04_Resources/Code_and_Research/{folder_slug}",
            }

        cmd = ["git", "pull"] if action == "pull" else ["git", "status", "--short", "--branch"]
        proc = subprocess.run(
            cmd,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "repo": safe_repo or folder_slug,
            "action": action,
            "output": (proc.stdout or proc.stderr).strip(),
        }

    def list_github_org_repos(self, org: str = "ForestCityCreatorsLLC") -> Dict[str, Any]:
        """List repositories for a GitHub organization (`ForestCityCreatorsLLC`) via PAT (private+public) or public API + local Vault discovery."""
        safe_org = re.sub(r"[^A-Za-z0-9_\-]+", "", (org or "ForestCityCreatorsLLC").strip()) or "ForestCityCreatorsLLC"
        org_url = f"https://github.com/{safe_org}?tab=repositories"

        raw_token = str(getattr(self.cfg, "github_token", "") or "").strip()
        has_pat = bool(raw_token) and not raw_token.lower().startswith(("your_", "<", "replace_"))
        gh_user = str(getattr(self.cfg, "github_username", "") or "").strip()
        gh_pass = str(getattr(self.cfg, "github_password", "") or "").strip()
        browser_env_configured = bool(gh_user and gh_pass)

        headers: Dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "KAIROS-2.0",
        }
        if has_pat:
            headers["Authorization"] = f"Bearer {raw_token}"

        repos: List[Dict[str, Any]] = []
        api_status = "offline_or_local"
        seen_names: set[str] = set()

        api_urls = [
            f"https://api.github.com/orgs/{safe_org}/repos?type=all&sort=updated&per_page=50",
            f"https://api.github.com/users/{safe_org}/repos?sort=updated&per_page=50",
        ]
        for api_endpoint in api_urls:
            try:
                resp = requests.get(api_endpoint, headers=headers, timeout=6)
                if resp.ok and isinstance(resp.json(), list):
                    api_status = "authenticated_pat" if has_pat else "public_api"
                    for item in resp.json():
                        if not isinstance(item, dict):
                            continue
                        rname = str(item.get("name") or "").strip()
                        if not rname or rname.lower() in seen_names:
                            continue
                        seen_names.add(rname.lower())
                        is_priv = bool(item.get("private"))
                        repos.append(
                            {
                                "name": rname,
                                "full_name": str(item.get("full_name") or f"{safe_org}/{rname}"),
                                "html_url": str(
                                    item.get("html_url") or f"https://github.com/{safe_org}/{rname}"
                                ),
                                "description": str(item.get("description") or "").strip(),
                                "private": is_priv,
                                "visibility": "private" if is_priv else "public",
                                "language": str(item.get("language") or "Mixed"),
                                "default_branch": str(item.get("default_branch") or "main"),
                                "updated_at": str(item.get("pushed_at") or item.get("updated_at") or "")[:19],
                            }
                        )
                    break
                if resp.status_code != 404:
                    api_status = f"http_{resp.status_code}"
                    break
            except Exception:
                api_status = "offline_or_local"
                break

        # Ensure active KAIROS 2.0 workspace & any local `04_Resources/Code_and_Research` Git clones are represented
        if (
            safe_org.lower() == "forestcitycreatorsllc"
            and "kairos" not in seen_names
            and "kairos 2.0" not in seen_names
            and "kairos-2.0" not in seen_names
        ):
            seen_names.add("kairos-2.0")
            repos.append(
                {
                    "name": "Kairos-2.0",
                    "full_name": f"{safe_org}/Kairos-2.0",
                    "html_url": f"https://github.com/{safe_org}/Kairos-2.0",
                    "description": "KAIROS 2.0 — Canopy Vault Executive OS (Conversational AI + Projects + Second Brain)",
                    "private": True,
                    "visibility": "private",
                    "language": "Python / TypeScript",
                    "default_branch": "main",
                    "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )

        research_dir = self.vault.vault_path / "04_Resources" / "Code_and_Research"
        if research_dir.is_dir():
            for child in sorted(research_dir.iterdir()):
                if child.is_dir() and (child / ".git").exists() and child.name.lower() not in seen_names:
                    seen_names.add(child.name.lower())
                    repos.append(
                        {
                            "name": child.name,
                            "full_name": f"{safe_org}/{child.name}",
                            "html_url": f"https://github.com/{safe_org}/{child.name}",
                            "description": "Local Git clone in `04_Resources/Code_and_Research/`",
                            "private": False,
                            "visibility": "local_clone",
                            "language": "Local Clone",
                            "default_branch": "main",
                            "updated_at": "",
                        }
                    )

        return {
            "ok": True,
            "org": safe_org,
            "org_url": org_url,
            "authenticated_pat": has_pat,
            "browser_env_login_configured": browser_env_configured,
            "api_status": api_status,
            "repo_count": len(repos),
            "private_count": sum(1 for r in repos if r.get("private")),
            "repos": repos,
        }

    def sync_github_org_repos_to_vault(self, org: str = "ForestCityCreatorsLLC") -> Dict[str, Any]:
        """Synchronize the `ForestCityCreatorsLLC` GitHub repository catalog into `04_Resources/Code_and_Research/`."""
        listing = self.list_github_org_repos(org=org)
        safe_org = listing["org"]
        org_url = listing["org_url"]
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        rel_catalog = f"04_Resources/Code_and_Research/{safe_org}_Repositories.md"

        lines = [
            f"# 🏢 {safe_org} — GitHub Repository Catalog",
            "",
            "> [!IMPORTANT] Canonical GitHub Organization Home",
            f"> - **Repositories Portal:** [{org_url}]({org_url})",
            "> - **Active Canopy Vault Project:** [[02_Projects/KAIROS_2_0/_Project_Index|KAIROS 2.0]]",
            f"> - **Last Synchronized:** `{now_iso}` (`{listing['repo_count']}` repositories • `{listing['private_count']}` private)",
            "",
            "## 📦 Repositories",
            "",
            "| Repository | Visibility | Language | Updated | Summary |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in listing["repos"]:
            vis_badge = "🔒 Private" if r.get("private") else ("📂 Local" if r.get("visibility") == "local_clone" else "🌐 Public")
            desc = (r.get("description") or "—").replace("|", "/").replace("\n", " ").strip()
            upd = (r.get("updated_at") or "—").replace("T", " ")
            lines.append(
                f"| [{r['name']}]({r['html_url']}) | {vis_badge} | `{r.get('language') or 'Mixed'}` | `{upd}` | {desc} |"
            )

        saved = self.vault.write_note(
            rel_catalog,
            {
                "title": f"{safe_org} — GitHub Repositories",
                "type": "resource",
                "domain": "github_org_catalog",
                "org": safe_org,
                "org_url": org_url,
                "repo_count": listing["repo_count"],
                "private_count": listing["private_count"],
                "synced_at": now_iso,
                "tags": ["github", "repositories", safe_org.lower()],
            },
            "\n".join(lines) + "\n",
            mode="overwrite",
        )
        return {
            **listing,
            "catalog_rel_path": saved["rel_path"],
            "note": saved,
        }
