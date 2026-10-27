"""Network & Entity-ID Security Perimeter Guards (`services/kairos_core/net_guard.py`).

Enforces `v2.0-checkpoint-2` defense-in-depth across KAIROS 2.0:
1. Strict Vault Entity ID validation (`validate_entity_id`) blocking intra-Vault `../` traversal on
   `session_id`, `event_id`, `task_id`, and `skill_id`.
2. Outbound SSRF & OOM response-size protection (`validate_public_http_url`, `safe_fetch_public_text`)
   blocking loopback (`127.0.0.0/8`, `::1`), RFC1918 private LAN, link-local metadata (`169.254.0.0/16`),
   and redirect-hop bypasses in Browser Clipper & CrewAI Co-Browsing.
3. Google Workspace embed URL validation (`validate_google_workspace_url`) preventing stored
   HTML/iframe attribute injection in `gsuite_link_doc`.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import requests

ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

ALLOWED_GSUITE_HOSTS = frozenset({"docs.google.com", "drive.google.com"})


class SSRFBlockedError(ValueError):
    """Raised when an outbound URL targets a non-public, loopback, link-local, or invalid host."""


def validate_entity_id(raw_id: str, label: str = "entity_id") -> str:
    """Validate Vault entity identifiers (`TSK-*`, `SES-*`, `EVT-*`, `SKL-*`) against path traversal."""
    clean = (raw_id or "").strip()
    if clean.lower().endswith(".md"):
        clean = clean[:-3].strip()
    if not clean or len(clean) > 128 or not ENTITY_ID_RE.fullmatch(clean):
        raise ValueError(f"Invalid {label}: '{raw_id}'")
    return clean


def _is_disallowed_ip(ip_str: str) -> bool:
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def validate_public_http_url(url: str) -> str:
    """Verify `url` uses `http(s)://` and resolves exclusively to public routable IP addresses."""
    clean = (url or "").strip()
    if not clean or any(ord(ch) < 32 for ch in clean):
        raise SSRFBlockedError("URL cannot be empty or contain control characters")

    parsed = urlsplit(clean)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SSRFBlockedError(f"Blocked unsupported URL scheme '{scheme or 'none'}'")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SSRFBlockedError("URL is missing a valid hostname")

    if host in ("localhost", "localhost.localdomain") or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise SSRFBlockedError(f"Blocked local/internal hostname '{host}'")

    # Direct IP literal check (no DNS needed)
    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        if _is_disallowed_ip(str(ip_obj)):
            raise SSRFBlockedError(f"Blocked non-public IP literal '{ip_obj}'")
        return clean

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ConnectionError(f"Unable to resolve hostname '{host}': {exc}") from exc

    if not infos:
        raise SSRFBlockedError(f"Hostname '{host}' returned no DNS records")

    for _family, _socktype, _proto, _canon, sockaddr in infos:
        resolved_ip = str(sockaddr[0])
        if _is_disallowed_ip(resolved_ip):
            raise SSRFBlockedError(
                f"Blocked non-public resolved address '{resolved_ip}' for host '{host}'"
            )

    return clean


def safe_fetch_public_text(
    url: str,
    *,
    user_agent: str = "KAIROS-2.0-Clipper/1.0",
    timeout: float = 8.0,
    max_bytes: int = 2_000_000,
    max_redirects: int = 3,
) -> str:
    """Fetch text from a public HTTP(S) URL with per-hop SSRF validation and bounded streaming."""
    current_url = url.strip()
    for _hop in range(max_redirects + 1):
        validated_url = validate_public_http_url(current_url)
        with requests.get(
            validated_url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        ) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = (resp.headers.get("Location") or "").strip()
                if not loc:
                    break
                current_url = urljoin(validated_url, loc)
                continue

            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=16_384):
                if not chunk:
                    continue
                remaining = max_bytes - total
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
                if total >= max_bytes:
                    break

            raw_bytes = b"".join(chunks)
            encoding = resp.encoding or "utf-8"
            try:
                return raw_bytes.decode(encoding, errors="replace")
            except LookupError:
                return raw_bytes.decode("utf-8", errors="replace")

    raise SSRFBlockedError(f"Exceeded maximum redirects ({max_redirects}) for '{url}'")


def validate_google_workspace_url(url: str) -> str:
    """Validate that `url` is a clean `https://docs.google.com/...` or `https://drive.google.com/...` URL."""
    clean = (url or "").strip()
    if not clean or any(ch in clean for ch in ('"', "'", "<", ">", "\r", "\n", "\x00")):
        raise ValueError("Invalid Google Workspace URL")
    parsed = urlsplit(clean)
    if (parsed.scheme or "").lower() != "https":
        raise ValueError("Google Workspace embed URL must use https://")
    host = (parsed.hostname or "").strip().lower()
    if host not in ALLOWED_GSUITE_HOSTS:
        raise ValueError(
            f"Unsupported Google Workspace host '{host}' (expected docs.google.com or drive.google.com)"
        )
    return clean
