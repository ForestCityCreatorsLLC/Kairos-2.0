"""Phase 5 Second-Pass Forensic Hardening & Fortification Suite (`v2.0-checkpoint-2`):
1. Intra-Vault entity ID traversal blocked across `session_id`, `event_id`, and `task_id` (`HTTP 400`)
2. Multi-turn session privacy taint propagation, Fast Skills `#private` isolation, and `gsuite_link_doc` URL/iframe + disk-backed privacy guard
3. Outbound SSRF & redirect-hop guard blocking loopback, private LAN, link-local metadata, and `file://` in Browser Clipper & CrewAI
4. CORS origin regex lockdown on Core (`:8420`) & Voice Sidecar (`:8421`) + `HTTP 413` 15 MB audio payload cap
5. SQLite `ShadowIndex` FTS5 punctuation safety, frontmatter numeric coercers, `rebuild_all` fault isolation, and Windows file-handle closure
6. `DualAIRouter` locked `64 KB` tail audit reader, `AI_Audit_Log_Archive.jsonl` rotation, and `_safe_env_int` inline-comment resilience
7. Paperclip voice/chat task mutation `HTTP 409` lock guard, `POST /api/paperclip/locks/{id}/release` force-unlock, and CrewAI offline `degraded_offline` status protection
8. Soft-archived Tasks (`05_Archives/Tasks/[Project]/`) and Sessions (`05_Archives/Sessions/`) browse & 1-click restore E2E (`18` MCP tools preserved)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

import services.kairos_core.api as api_mod
import services.kairos_core.config as config_mod
import services.kairos_core.net_guard as net_guard_mod
import services.kairos_voice.voice_service as voice_mod
from services.kairos_core.mcp_server import create_mcp_bundle
from services.kairos_core.net_guard import (
    SSRFBlockedError,
    safe_fetch_public_text,
    validate_entity_id,
    validate_public_http_url,
)
from services.kairos_core.router import DualAIRouter
from services.kairos_core.schemas import AuditLogRecord
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine, parse_markdown_note


def test_intra_vault_entity_id_traversal_blocked_on_sessions_calendar_and_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Unit checks on `validate_entity_id`
    assert validate_entity_id("SES-20261025-120000.md", "session_id") == "SES-20261025-120000"
    assert validate_entity_id("EVT-20261025-001", "event_id") == "EVT-20261025-001"
    for bad in (
        "",
        "..",
        "../03_Personal/Finance/Taxes",
        "..\\03_Personal\\Finance\\Taxes",
        "SES-1/../../secret",
        "A" * 129,
    ):
        with pytest.raises(ValueError, match="Invalid"):
            validate_entity_id(bad, "session_id")

    # 2. Service + FastAPI endpoint checks ensuring private/sibling Vault files can NEVER be deleted or overwritten
    isolated_bundle = create_mcp_bundle(str(tmp_path / "EntityGuard_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    vault: VaultEngine = isolated_bundle["vault"]
    client = TestClient(api_mod.app)

    vault.write_note(
        "03_Personal/Finance/Protected_Ledger.md",
        {"title": "Protected Ledger", "tags": ["private"]},
        "Confidential tax reserve.",
    )
    protected_file = vault.resolve_safe_path("03_Personal/Finance/Protected_Ledger.md")
    assert protected_file.is_file()

    with pytest.raises(ValueError, match="Invalid session_id"):
        isolated_bundle["assistant"].delete_session(
            "../../03_Personal/Finance/Protected_Ledger", permanent=True
        )
    with pytest.raises(ValueError, match="Invalid event_id"):
        isolated_bundle["connectors"].delete_calendar_event("../Finance/Protected_Ledger")
    with pytest.raises(ValueError, match="Invalid task_id"):
        vault.find_task_file("../../03_Personal/Finance/Protected_Ledger")

    # FastAPI maps Windows backslash / malformed ID traversal attempts cleanly to HTTP 400
    r_ses = client.delete(
        "/api/assistant/sessions/..%5C..%5C03_Personal%5CFinance%5CProtected_Ledger?permanent=true"
    )
    assert r_ses.status_code == 400

    r_cal = client.delete("/api/calendar/events/..%5CFinance%5CProtected_Ledger")
    assert r_cal.status_code == 400

    assert protected_file.is_file()


def test_multi_turn_session_privacy_taint_fast_skills_and_disk_backed_gsuite_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "PrivacyTaint_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    vault: VaultEngine = isolated_bundle["vault"]
    router: DualAIRouter = isolated_bundle["router"]
    client = TestClient(api_mod.app)

    vault.write_note(
        "03_Personal/Finance/Payroll_2026.md",
        {"title": "Payroll 2026", "tags": ["finance", "private"]},
        "Executive compensation figures: $240,000 reserve.",
    )
    vault.write_note(
        "01_Business/Public_Memo.md",
        {"title": "Public Memo", "tags": ["ops"]},
        "General weekly status notes.",
    )
    vault.write_note(
        "01_Business/YAML_Tagged_Private_Spec.md",
        {"title": "Confidential M&A Spec", "tags": ["strategy", "private"]},
        "Confidential acquisition targets with no inline hashtag.",
    )

    monkeypatch.setattr(
        router,
        "_call_lmstudio_gemma4",
        lambda prompt, sys_p="": {"ok": True, "text": "Local Gemma 4 response."},
    )

    def _forbid_cloud(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise AssertionError("Privacy violation: Gemini cloud must NEVER be called!")

    monkeypatch.setattr(router, "_call_gemini_cloud", _forbid_cloud)

    # Turn 1: Private note active -> session becomes tainted with `🔒 Local`
    t1 = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Summarize the reserve numbers in this payroll note",
            "mode": "gemini",
            "active_note_path": "03_Personal/Finance/Payroll_2026.md",
        },
    )
    assert t1.status_code == 200
    t1_json = t1.json()
    assert t1_json["privacy_locked"] is True
    sid = t1_json["session"]["session_id"]

    # Turn 2: Operator switches to a PUBLIC note in the SAME session and requests `mode="gemini"`
    # Because Turn 1 tainted the session history, Turn 2 MUST remain hard-locked to Local Gemma 4!
    t2 = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Compare what we just discussed with our weekly memo",
            "session_id": sid,
            "mode": "gemini",
            "active_note_path": "01_Business/Public_Memo.md",
        },
    )
    assert t2.status_code == 200
    t2_json = t2.json()
    assert t2_json["privacy_locked"] is True
    assert t2_json["route_reason"] == "privacy_hard_lock_local"

    # Fast Skill #1: Inbox capture with `#private` preserves `is_private`
    r_inbox = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Capture to inbox: #private Q4 personal tax distribution",
            "mode": "auto",
        },
    ).json()
    assert r_inbox["privacy_locked"] is True
    inbox_notes = vault.list_markdown_files("00_Inbox")
    assert any(
        vault.read_note(vault.to_rel_path(p))["is_private"] is True for p in inbox_notes
    )

    # Fast Skill #1b: Hermes retain with `#private` routes strictly to `03_Personal/Finance/Hermes_Private_Memory.md`
    r_hermes = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Hermes, remember #private cold-storage hardware key rotation schedule",
            "mode": "auto",
        },
    ).json()
    assert r_hermes["privacy_locked"] is True
    priv_mem = vault.read_note("03_Personal/Finance/Hermes_Private_Memory.md")["body"]
    shared_mem = vault.read_note("04_Resources/Hermes/MEMORY.md")["body"]
    assert "cold-storage hardware key" in priv_mem
    assert "cold-storage hardware key" not in shared_mem

    # Fast Skill #2: KAIROS operator memory with `#private` isolates strictly to `03_Personal/Finance/KAIROS_Operator_Private_Memory.md`
    r_mem = client.post(
        "/api/assistant/chat",
        json={
            "prompt": "Remember that my #private ledger backup runs every Sunday night",
            "mode": "auto",
        },
    ).json()
    assert r_mem["privacy_locked"] is True
    assert vault.read_note("03_Personal/Finance/KAIROS_Operator_Private_Memory.md")["is_private"] is True

    # `gsuite_link_doc`: rejects XSS / non-Google hosts, sanitizes valid iframe, and enforces disk-backed YAML privacy
    r_bad_xss = client.post(
        "/api/connectors/gsuite-link",
        json={
            "note_path": "01_Business/Public_Memo.md",
            "google_doc_url": 'https://docs.google.com/document/d/123/edit?x="><script>alert(1)</script>',
        },
    )
    assert r_bad_xss.status_code == 400

    r_bad_host = client.post(
        "/api/connectors/gsuite-link",
        json={
            "note_path": "01_Business/Public_Memo.md",
            "google_doc_url": "https://evil.example/document/d/123/edit",
        },
    )
    assert r_bad_host.status_code == 400

    r_good_priv = client.post(
        "/api/connectors/gsuite-link",
        json={
            "note_path": "01_Business/YAML_Tagged_Private_Spec.md",
            "google_doc_url": "https://docs.google.com/document/d/1AbCdEfG/edit?usp=sharing&pli=1",
            "pull_summary": True,
        },
    )
    assert r_good_priv.status_code == 200
    body_out = r_good_priv.json()["body"]
    assert 'sandbox="allow-scripts allow-same-origin allow-popups"' in body_out
    assert 'referrerpolicy="no-referrer"' in body_out
    assert "&amp;pli=1" in body_out


def test_ssrf_loopback_private_ip_and_redirect_blocked_in_clipper_and_crewai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "SSRF_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    blocked_urls = [
        "http://127.0.0.1:8420/api/health",
        "http://localhost:1234/v1/models",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.25/admin",
        "http://10.0.0.5:8080/internal",
        "http://[::1]:8420/api/health",
        "file:///C:/Windows/win.ini",
    ]
    for bad_url in blocked_urls:
        with pytest.raises(SSRFBlockedError):
            validate_public_http_url(bad_url)

    # Redirect-hop SSRF bypass (`93.184.216.34` -> `http://127.0.0.1:8420/api/health`) MUST be blocked
    class _FakeRedirectResponse:
        status_code = 302
        headers = {"Location": "http://127.0.0.1:8420/api/health"}
        encoding = "utf-8"

        def __enter__(self) -> "_FakeRedirectResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def iter_content(self, chunk_size: int = 16384):
            return iter(())

    monkeypatch.setattr(net_guard_mod.requests, "get", lambda *_a, **_kw: _FakeRedirectResponse())
    with pytest.raises(SSRFBlockedError, match="non-public"):
        safe_fetch_public_text("http://93.184.216.34/public-landing")

    # FastAPI Browser Clipper & CrewAI Dispatcher return HTTP 400 on SSRF URLs
    r_clip_loopback = client.post(
        "/api/browser/clip",
        json={"url": "http://127.0.0.1:8420/api/health"},
    )
    assert r_clip_loopback.status_code == 400
    assert "non-public" in r_clip_loopback.json()["detail"].lower()

    r_clip_file = client.post(
        "/api/browser/clip",
        json={"url": "file:///C:/Windows/win.ini"},
    )
    assert r_clip_file.status_code == 400

    task = client.post(
        "/api/tasks",
        json={
            "title": "SSRF Check Task",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
        },
    ).json()
    tid = task["frontmatter"]["id"]

    r_crew_ssrf = client.post(
        "/api/paperclip/dispatch-crew",
        json={
            "task_id": tid,
            "crew_name": "CrewAI-Research",
            "reference_url": "http://169.254.169.254/latest/meta-data/",
        },
    )
    assert r_crew_ssrf.status_code == 400


def test_cors_origin_lockdown_and_voice_audio_payload_413_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "CORS_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    core_client = TestClient(api_mod.app)
    voice_client = TestClient(voice_mod.app)

    # Trusted local origins are permitted on both `:8420` and `:8421`
    for cl, path in ((core_client, "/api/health"), (voice_client, "/api/voice/state")):
        r_ok = cl.get(path, headers={"Origin": "http://127.0.0.1:5173"})
        assert r_ok.status_code == 200
        assert r_ok.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

        # Untrusted web origin & sandboxed webview `Origin: null` MUST NOT receive CORS allow header
        for untrusted in ("https://evil.example", "null"):
            r_deny = cl.get(path, headers={"Origin": untrusted})
            assert "access-control-allow-origin" not in r_deny.headers

    # Oversized `audio_base64` payload (> 15 MB) is immediately rejected with HTTP 413
    oversized_b64 = "A" * (((voice_mod.MAX_AUDIO_PAYLOAD_BYTES * 4) // 3) + 2048)
    r_413 = voice_client.post(
        "/api/voice/audio-command",
        json={"audio_base64": oversized_b64, "mime_type": "audio/webm"},
    )
    assert r_413.status_code == 413
    assert "15 MB" in r_413.json()["detail"]


def test_shadow_index_fts5_punctuation_safety_coercers_and_handle_closing(tmp_path: Path) -> None:
    v_dir = tmp_path / "Shadow_Resilience_Vault"
    vault = VaultEngine(v_dir)
    idx = ShadowIndex(vault)

    # Write a task note with string priority & non-numeric float fields (e.g. hand-edited in Obsidian)
    hand_edited = vault.resolve_safe_path(
        "02_Projects/KAIROS_2_0/Software_Development/Sprint_01/Tasks/TSK-20990101-001.md"
    )
    hand_edited.parent.mkdir(parents=True, exist_ok=True)
    hand_edited.write_text(
        "---\n"
        "id: TSK-20990101-001\n"
        "title: Hand Edited C++ Widget\n"
        "type: task\n"
        "status: In Progress\n"
        "priority: High\n"
        "project: '[[KAIROS_2_0]]'\n"
        "department: Software_Development\n"
        "list: Sprint_01\n"
        "time_estimate_hrs: TBD\n"
        "time_logged_hrs: ~2h\n"
        "---\n"
        "# Hand Edited C++ Widget\n\nTesting FTS5 punctuation & numeric coercion.\n",
        encoding="utf-8",
    )

    count = idx.rebuild_all()
    assert count >= 1

    tasks = idx.list_tasks(project="KAIROS_2_0")
    matched = [t for t in tasks if t["id"] == "TSK-20990101-001"]
    assert len(matched) == 1
    assert matched[0]["priority"] == 2
    assert matched[0]["time_estimate_hrs"] == 0.0
    assert matched[0]["time_logged_hrs"] == 0.0

    # Adversarial FTS5 queries MUST never raise `sqlite3.OperationalError`
    for tricky_q in ('"""', "??? *** ()", "AND OR NOT", 'C++ "Widget" (TSK-20990101-001):!'):
        results = idx.search_vault(tricky_q)
        assert isinstance(results, list)

    found = idx.search_vault('C++ "Widget" (TSK-20990101-001):!')
    assert any(r["rel_path"].endswith("TSK-20990101-001.md") for r in found)

    # Windows SQLite file handles MUST be closed after every session so directory deletion succeeds cleanly
    shutil.rmtree(v_dir)
    assert not v_dir.exists()


def test_audit_log_tail_reader_rotation_and_env_port_comment_resilience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. `_safe_env_int` strips inline `#` comments and falls back cleanly on malformed values
    monkeypatch.setenv("TEST_KAIROS_PORT_COMMENT", "8420 # local core port")
    monkeypatch.setenv("TEST_KAIROS_PORT_BAD", "invalid_port")
    assert config_mod._safe_env_int("TEST_KAIROS_PORT_COMMENT", 9999) == 8420
    assert config_mod._safe_env_int("TEST_KAIROS_PORT_BAD", 8421) == 8421

    # 2. `DualAIRouter` rotates `AI_Audit_Log.jsonl` to `AI_Audit_Log_Archive.jsonl` and tail-reads latest rows
    audit_file = tmp_path / "Logs" / "AI_Audit_Log.jsonl"
    vault = VaultEngine(tmp_path / "Audit_Vault")
    router = DualAIRouter(audit_path=audit_file, vault=vault)
    monkeypatch.setattr(router, "MAX_AUDIT_LOG_BYTES", 2_048)

    for i in range(45):
        router.log_audit(
            AuditLogRecord(
                agent="Gemma-4-Local",
                route_reason="local_default",
                tool=f"step_{i:03d}",
                target="01_Business/Note.md",
                latency_ms=i,
            )
        )

    archive_file = tmp_path / "Logs" / "AI_Audit_Log_Archive.jsonl"
    assert archive_file.is_file()
    assert archive_file.stat().st_size > 0

    recent = router.read_recent_audit_logs(limit=5)
    assert len(recent) == 5
    # `read_recent_audit_logs` returns newest-first
    assert recent[0]["tool"] == "step_044"
    assert recent[-1]["tool"] == "step_040"


def test_paperclip_voice_mutation_lock_guard_force_unlock_and_offline_degraded_crew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "VoiceLock_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    client = TestClient(api_mod.app)

    t1 = client.post(
        "/api/tasks",
        json={
            "title": "Locked Sprint Deliverable",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
        },
    ).json()
    tid = t1["frontmatter"]["id"]

    # Check out `tid` via Paperclip
    isolated_bundle["paperclip"].checkout_task(tid, agent_name="CrewAI-Dev", crew_type="crew")

    # Voice/Chat Fast Skill mutation while checked out MUST return HTTP 409
    r_blocked_cmd = client.post(
        "/api/kairos/command",
        json={"prompt": f"Mark task {tid} as Done", "mode": "auto"},
    )
    assert r_blocked_cmd.status_code == 409
    assert "Paperclip Lock Conflict" in r_blocked_cmd.json()["detail"]

    # Active lock snapshot includes `elapsed_sec`
    p_stat = client.get("/api/paperclip/status").json()["paperclip"]
    assert p_stat["active_count"] == 1
    assert "elapsed_sec" in p_stat["active_locks"][0]

    # Operator force-unlocks hung checkout via `POST /api/paperclip/locks/{tid}/release`
    r_unlock = client.post(
        f"/api/paperclip/locks/{tid}/release",
        json={"actor": "Jaime", "reason": "Test force-unlock"},
    )
    assert r_unlock.status_code == 200
    assert r_unlock.json()["released"] is True
    assert r_unlock.json()["previous_agent"] == "CrewAI-Dev"

    # Now Voice/Chat Fast Skill mutation succeeds cleanly
    r_ok_cmd = client.post(
        "/api/kairos/command",
        json={"prompt": f"Mark task {tid} as Done", "mode": "auto"},
    )
    assert r_ok_cmd.status_code == 200
    assert client.get(f"/api/tasks/{tid}").json()["frontmatter"]["status"] == "Done"

    # Offline degraded CrewAI run MUST keep task `In Progress` instead of falsely promoting to `Review`
    t2 = client.post(
        "/api/tasks",
        json={
            "title": "Offline Engine Resilience Check",
            "project": "KAIROS_2_0",
            "department": "Software_Development",
            "list": "Sprint_01",
        },
    ).json()
    tid2 = t2["frontmatter"]["id"]

    monkeypatch.setattr(
        isolated_bundle["router"],
        "generate",
        lambda *_a, **_kw: {
            "ok": False,
            "text": "[All AI engines offline]",
            "agent": "Router-Error",
            "route_reason": "offline",
            "privacy_locked": False,
        },
    )
    crew_res = isolated_bundle["crew"].execute_task_with_crew(tid2, "CrewAI-Dev")
    assert crew_res["degraded"] is True
    fm2, _ = parse_markdown_note(isolated_bundle["vault"].find_task_file(tid2).read_text(encoding="utf-8"))
    assert fm2["status"] == "In Progress"
    snap2 = isolated_bundle["paperclip"].get_snapshot()
    assert snap2["recent_runs"][0]["status"] == "degraded_offline"


def test_archived_tasks_and_sessions_browse_and_restore_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_bundle = create_mcp_bundle(str(tmp_path / "ArchiveRestore_Vault"))
    monkeypatch.setattr(api_mod, "_bundle", isolated_bundle)
    assert len(isolated_bundle["mcp_tools"]) == 18
    client = TestClient(api_mod.app)

    # 1. Task soft-archive -> list archived -> 1-click restore
    created_task = client.post(
        "/api/tasks",
        json={
            "title": "Campaign Hero Copy",
            "project": "KAIROS_2_0",
            "department": "Marketing_and_Branding",
            "list": "Campaigns",
        },
    ).json()
    tid = created_task["frontmatter"]["id"]

    r_arch = client.delete(f"/api/tasks/{tid}?permanent=false")
    assert r_arch.status_code == 200
    assert r_arch.json()["mode"] == "archived"

    arch_list = client.get("/api/projects/archived-tasks?project=KAIROS_2_0").json()["archived_tasks"]
    assert any(item["id"] == tid for item in arch_list)
    assert all(t["id"] != tid for t in client.get("/api/tasks").json()["tasks"])

    r_restored_task = client.post(f"/api/tasks/{tid}/restore")
    assert r_restored_task.status_code == 200
    assert (
        "02_Projects/KAIROS_2_0/Marketing_and_Branding/Campaigns/Tasks/"
        in r_restored_task.json()["rel_path"]
    )
    assert any(t["id"] == tid for t in client.get("/api/tasks").json()["tasks"])

    # 2. Assistant session soft-archive -> list archived -> 1-click restore
    created_ses = client.post(
        "/api/assistant/sessions",
        json={"title": "Sprint Retro Notes", "persona": "pm", "tone_mode": "DEFAULT"},
    ).json()
    sid = created_ses["session_id"]

    r_arch_ses = client.delete(f"/api/assistant/sessions/{sid}?permanent=false")
    assert r_arch_ses.status_code == 200
    assert r_arch_ses.json()["mode"] == "archived"

    arch_sessions = client.get("/api/assistant/archived-sessions").json()["sessions"]
    assert any(s["session_id"] == sid for s in arch_sessions)
    assert all(s["session_id"] != sid for s in client.get("/api/assistant/sessions").json()["sessions"])

    r_restored_ses = client.post(f"/api/assistant/sessions/{sid}/restore")
    assert r_restored_ses.status_code == 200
    assert r_restored_ses.json()["session_id"] == sid
    assert r_restored_ses.json()["rel_path"].startswith("01_Business/KAIROS_Sessions/")
    assert any(s["session_id"] == sid for s in client.get("/api/assistant/sessions").json()["sessions"])
