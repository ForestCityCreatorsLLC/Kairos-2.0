"""KAIROS 2.0 Voice & Conversational Platform Navigation Engine (`navigator.py`).

Translates natural spoken utterances (and `<ui_nav>{...}</ui_nav>` LLM tags) into
structured `UIActionCommand` objects that drive every workspace, project, department,
sub-view, task drawer, note editor, 3D knowledge graph, YouTube media/highlights search,
and embedded multi-tab browser hands-free across the KAIROS 2.0 Desktop Shell.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

from services.kairos_core.net_guard import SSRFBlockedError, validate_public_http_url
from services.kairos_core.shadow_index import ShadowIndex
from services.kairos_core.vault_engine import VaultEngine

UI_NAV_TAG_RE = re.compile(r"<ui_nav>\s*(\{.*?\})\s*</ui_nav>", flags=re.DOTALL | re.IGNORECASE)
KAIROS_OP_TAG_RE = re.compile(r"<kairos_op>\s*(\{.*?\})\s*</kairos_op>", flags=re.DOTALL | re.IGNORECASE)

VALID_TABS = {
    "assistant",
    "inbox",
    "projects",
    "second-brain",
    "browser",
    "paperclip",
    "settings",
}

VALID_BROWSER_CONTROLS = {
    "back",
    "forward",
    "reload",
    "home",
    "new_tab",
    "close_tab",
}

DEPARTMENT_SYNONYMS: List[Tuple[Tuple[str, ...], str, str, str]] = [
    (
        ("fabrication swarm", "3d printing", "moonraker", "fabrication"),
        "Software_Development",
        "Fabrication_Swarm",
        "Software Development (Fabrication Swarm)",
    ),
    (
        ("software development", "software dev", "engineering", "software", "dev sprint", "sprint 01", "sprint 1"),
        "Software_Development",
        "Sprint_01",
        "Software Development",
    ),
    (
        ("marketing and branding", "marketing & branding", "marketing", "branding", "campaigns", "social"),
        "Marketing_and_Branding",
        "Campaigns",
        "Marketing & Branding",
    ),
    (
        ("documentation", "specs and guides", "specs & guides", "guides", "sops"),
        "Documentation",
        "Specs_and_Guides",
        "Documentation",
    ),
    (
        ("website", "web launch", "landing page", "web showcase"),
        "Website",
        "Web_Launch",
        "Website",
    ),
    (
        ("merch", "merchandise", "printful", "printful drops", "apparel", "hoodie"),
        "Merch",
        "Printful_Drops",
        "Merch",
    ),
]

PROJECTS_VIEW_SYNONYMS: List[Tuple[Tuple[str, ...], str, str]] = [
    (("rollup", "portfolio rollup", "rollup view", "metrics view", "progress dashboard"), "rollup", "Portfolio Rollup"),
    (("list view", "task table", "table view", "task list"), "list", "List View"),
    (("kanban", "board view", "kanban board", "cards view", "board"), "board", "Kanban Board"),
    (("calendar view", "project calendar", "schedule view", "time block view", "monthly calendar"), "calendar", "Calendar View"),
    (("gantt", "timeline", "gantt chart", "roadmap view", "roadmap", "dependencies view"), "gantt", "Gantt Timeline"),
    (
        (
            "project docs",
            "docs view",
            "documentation view",
            "project wiki",
            "wiki view",
            "wiki",
            "project notes",
            "whiteboard",
            "architecture canvas",
            "canvas view",
        ),
        "docs",
        "Documentation Wiki",
    ),
]

PERSONA_SYNONYMS: List[Tuple[Tuple[str, ...], str, str]] = [
    (("companion", "kairos companion", "default persona", "co-pilot"), "companion", "KAIROS Companion"),
    (("project director", "pm mode", "pm persona", "project manager"), "pm", "Project Director"),
    (("systems architect", "architect persona", "dev mode", "developer persona", "engineer mode"), "dev", "Systems Architect"),
    (("brand and merch", "brand & merch", "creative director", "creative persona", "marketing persona"), "creative", "Brand & Merch Director"),
    (("executive", "co-ceo", "owner mode", "strategist", "ceo mode"), "owner", "Executive Strategist"),
]

# Well-known web destinations that operators speak naturally without saying `.com`
KNOWN_WEB_DESTINATIONS: List[Tuple[Tuple[str, ...], str, str, str]] = [
    (("youtube music", "yt music"), "https://music.youtube.com", "YouTube Music", "youtube"),
    (("youtube", "you tube", "yt"), "https://www.youtube.com", "YouTube", "youtube"),
    (("espn",), "https://www.espn.com", "ESPN", "espn"),
    (("bleacher report",), "https://bleacherreport.com", "Bleacher Report", "web"),
    (("cbs sports",), "https://www.cbssports.com", "CBS Sports", "web"),
    (("yahoo sports",), "https://sports.yahoo.com", "Yahoo Sports", "web"),
    (("nfl", "nfl network"), "https://www.nfl.com", "NFL.com", "web"),
    (("nba",), "https://www.nba.com", "NBA.com", "web"),
    (("mlb",), "https://www.mlb.com", "MLB.com", "web"),
    (("nhl",), "https://www.nhl.com", "NHL.com", "web"),
    (
        (
            "forest city creators",
            "forest city creators repos",
            "forest city creators repositories",
            "forest city creators github",
            "fcc repos",
            "fcc repositories",
            "fcc github",
            "our github",
            "our repos",
            "our repositories",
            "private repos",
            "private repositories",
            "github repositories",
            "github repos",
            "browser home",
        ),
        "https://github.com/ForestCityCreatorsLLC?tab=repositories",
        "Forest City Creators LLC — Repositories",
        "github",
    ),
    (("github", "git hub"), "https://github.com", "GitHub", "github"),
    (("gitlab",), "https://gitlab.com", "GitLab", "web"),
    (("hugging face", "huggingface"), "https://huggingface.co", "Hugging Face", "web"),
    (("stack overflow", "stackoverflow"), "https://stackoverflow.com", "Stack Overflow", "web"),
    (("hacker news", "hn"), "https://news.ycombinator.com", "Hacker News", "web"),
    (("reddit",), "https://www.reddit.com", "Reddit", "reddit"),
    (("google drive",), "https://drive.google.com", "Google Drive", "web"),
    (("google docs",), "https://docs.google.com", "Google Docs", "web"),
    (("google calendar",), "https://calendar.google.com", "Google Calendar", "web"),
    (("gmail", "google mail"), "https://mail.google.com", "Gmail", "web"),
    (("google",), "https://www.google.com", "Google", "google"),
    (("duckduckgo", "duck duck go"), "https://duckduckgo.com", "DuckDuckGo", "duckduckgo"),
    (("wikipedia",), "https://en.wikipedia.org", "Wikipedia", "wikipedia"),
    (("amazon",), "https://www.amazon.com", "Amazon", "amazon"),
    (("twitch",), "https://www.twitch.tv", "Twitch", "web"),
    (("spotify",), "https://open.spotify.com", "Spotify", "web"),
    (("twitter", "x.com"), "https://x.com", "X", "web"),
    (("linkedin",), "https://www.linkedin.com", "LinkedIn", "web"),
    (("printful website", "printful dashboard", "printful store"), "https://www.printful.com/dashboard", "Printful", "web"),
]

# Sports team aliases for context-aware "highlights of the game" resolution (ordered specific-first)
SPORTS_TEAM_ALIASES: List[Tuple[Tuple[str, ...], str]] = [
    (("cleveland browns", "browns", "dawg pound", "dawgs"), "Cleveland Browns"),
    (("cleveland cavaliers", "cavaliers", "cavs"), "Cleveland Cavaliers"),
    (("cleveland guardians", "guardians", "guards", "tribe"), "Cleveland Guardians"),
    (("ohio state buckeyes", "ohio state", "buckeyes"), "Ohio State Buckeyes"),
    (("columbus blue jackets", "blue jackets"), "Columbus Blue Jackets"),
    (("baltimore ravens", "ravens"), "Baltimore Ravens"),
    (("pittsburgh steelers", "steelers"), "Pittsburgh Steelers"),
    (("cincinnati bengals", "bengals"), "Cincinnati Bengals"),
    (("kansas city chiefs", "chiefs"), "Kansas City Chiefs"),
    (("buffalo bills", "bills"), "Buffalo Bills"),
    (("philadelphia eagles", "eagles"), "Philadelphia Eagles"),
    (("dallas cowboys", "cowboys"), "Dallas Cowboys"),
    (("san francisco 49ers", "49ers", "niners"), "San Francisco 49ers"),
    (("detroit lions", "lions"), "Detroit Lions"),
    (("green bay packers", "packers"), "Green Bay Packers"),
    (("miami dolphins", "dolphins"), "Miami Dolphins"),
    (("houston texans", "texans"), "Houston Texans"),
    (("new york jets", "jets"), "New York Jets"),
    (("new york giants", "giants"), "New York Giants"),
    (("chicago bears", "bears"), "Chicago Bears"),
    (("minnesota vikings", "vikings"), "Minnesota Vikings"),
    (("boston celtics", "celtics"), "Boston Celtics"),
    (("los angeles lakers", "la lakers", "lakers"), "Los Angeles Lakers"),
    (("golden state warriors", "warriors"), "Golden State Warriors"),
    (("new york knicks", "knicks"), "New York Knicks"),
    (("milwaukee bucks", "bucks"), "Milwaukee Bucks"),
    (("denver nuggets", "nuggets"), "Denver Nuggets"),
    (("oklahoma city thunder", "okc thunder", "thunder"), "Oklahoma City Thunder"),
    (("dallas mavericks", "mavericks", "mavs"), "Dallas Mavericks"),
    (("miami heat", "heat"), "Miami Heat"),
    (("phoenix suns", "suns"), "Phoenix Suns"),
    (("indiana pacers", "pacers"), "Indiana Pacers"),
    (("orlando magic", "magic"), "Orlando Magic"),
    (("new york yankees", "yankees"), "New York Yankees"),
    (("los angeles dodgers", "la dodgers", "dodgers"), "Los Angeles Dodgers"),
    (("new york mets", "mets"), "New York Mets"),
    (("houston astros", "astros"), "Houston Astros"),
    (("atlanta braves", "braves"), "Atlanta Braves"),
    (("philadelphia phillies", "phillies"), "Philadelphia Phillies"),
    (("detroit tigers", "tigers"), "Detroit Tigers"),
]

GERUND_TO_IMPERATIVE: List[Tuple[str, str]] = [
    ("pulling up", "pull up"),
    ("bringing up", "bring up"),
    ("putting on", "put on"),
    ("cueing up", "cue up"),
    ("looking up", "look up"),
    ("checking out", "check out"),
    ("switching to", "switch to"),
    ("navigating to", "navigate to"),
    ("going to", "go to"),
    ("taking me to", "take me to"),
    ("searching", "search"),
    ("opening", "open"),
    ("showing", "show"),
    ("playing", "play"),
    ("watching", "watch"),
    ("finding", "find"),
]

MUTATION_OR_QUESTION_GUARD_RE = re.compile(
    r"^(?:(?:create|add)(?!\s+(?:a\s+)?new\s+(?:browser\s+|web\s+)?tab\b)|scaffold|make\s+(?:a|an|new|my)|build\s+(?:a|an|new|my)|set\s+up|"
    r"register|rename|save\s+(?:a|an|new)|"
    r"sync\s+(?:forest\s+city|fcc|our\s+github|github)|update\s+(?:our\s+)?(?:forest\s+city|fcc|github)\s+(?:catalog|repos)|"
    r"start\s+(?:a\s+|an\s+|new\s+)?project|initialize|schedule|reschedule|"
    r"dispatch\b|run\s+(?:crewai|hermes)|log\s+\d+(?:\.\d+)?|capture|quick\s+note|"
    r"remember|hermes[, ]+remember|retain\s+in\s+hermes|hermes[, ]+distill|distill\b|"
    r"move\s+(?:task\s+)?tsk-|move\s+(?:inbox|the\s+inbox|latest\s+inbox)|make\s+(?:task\s+)?tsk-|link\s+(?:task\s+)?tsk-|"
    r"set\s+(?:due\s+date|start\s+date|tsk-)|mark\s+(?:tsk-|this\s+task|current\s+task|the\s+open\s+task)|"
    r"archive\s+(?:task\s+|this\s+task|current\s+task|tsk-)|restore\s+(?:archived\s+)?(?:task\s+|tsk-)|"
    r"unlock\s+(?:task\s+|this\s+task|tsk-)|force[\s\-]+unlock\b|release\s+(?:the\s+)?(?:paperclip\s+)?lock\b|"
    r"check\s+off\b|toggle\s+checklist\b|complete\s+checklist\b|"
    r"promote\s+(?:the\s+)?(?:latest\s+|newest\s+|inbox\s+)|triage\s+(?:the\s+)?(?:latest\s+|inbox\s+)|"
    r"clip\s+(?:this|the|current|https?://)|save\s+(?:this|the|current)\s+(?:open\s+)?(?:page|web\s*page|article|site|website|tab|url)\b|"
    r"turn\s+(?:this|the)\s+(?:web\s*page|page|tab|article|site)\s+into\b|"
    r"append\s+to\b|write\s+(?:a\s+)?note\b|add\s+to\s+(?:today'?s?\s+)?daily\s+note\b|"
    r"give\s+me\s+(?:my\s+|a\s+)?(?:daily|morning|executive)\s+briefing|"
    r"(?:daily|morning|executive)\s+briefing|post\s+to\s+discord|send\s+to\s+discord|"
    r"what\b|what's\b|whats\b|who\b|who's\b|when\b|where\b|why\b|how\b)\b",
    flags=re.IGNORECASE,
)

VAGUE_GAME_REFERENCE_RE = re.compile(
    r"^(?:the\s+|that\s+|this\s+|their\s+)?"
    r"(?:"
    r"(?:last\s+night'?s?|yesterday'?s?|today'?s?|tonight'?s?|latest|recent)"
    r"(?:\s+(?:game|match|matchup|ballgame|ball\s+game|fight|bout))?"
    r"|(?:game|match|matchup|ballgame|ball\s+game|fight|bout)"
    r")"
    r"(?:\s*(?:highlights?|recap|condensed\s+game|game\s+tape|postgame|replay))?$",
    flags=re.IGNORECASE,
)


_KAIROS_PHONETIC_WORD_RE = re.compile(
    r"\b(?:kros|kyros|kiros|cairos|kayros|karos|k['\-]ros|kai[\s\-]+ross?)\b",
    flags=re.IGNORECASE,
)
_KAIROS_VOCATIVE_CAIRO_RE = re.compile(
    r"^(\s*(?:(?:hey|hi|hello|yo|ok|okay)\s+)?)cairo(?=$|[\s,:;!\-?.])",
    flags=re.IGNORECASE,
)


def normalize_kairos_phonetics(text: str) -> str:
    """Normalize common WebSpeech/Whisper STT phonetic misspellings ('Kros', 'Kyros', 'Hey Cairo') -> 'KAIROS'."""
    if not text:
        return ""
    out = _KAIROS_PHONETIC_WORD_RE.sub("KAIROS", text)
    if re.match(
        r"^\s*(?:(?:hey|hi|hello|yo|ok|okay)\s+cairo\b|cairo\s*[,:;!\-?])",
        out,
        flags=re.IGNORECASE,
    ):
        out = _KAIROS_VOCATIVE_CAIRO_RE.sub(r"\1KAIROS", out, count=1)
    return out


def _strip_conversational_wrappers(raw: str) -> str:
    """Strip spoken greetings, wake words, polite modal requests, and trailing conversational fillers."""
    text = normalize_kairos_phonetics(raw or "").strip().strip(" .!?;,")
    if not text:
        return ""

    # 1. Strip leading greeting + wake word ("Hey Kairos,", "Yo Kairos -", "Okay Kairos", bare "Hey Kairos")
    text = re.sub(
        r"^(?:(?:hey|hi|hello|ok|okay|yo|alright|listen)\s+)?(?:kairos(?:[\s,:;\-]+|$))?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # 2. Convert "would/do you mind <gerund> ..." -> "<imperative> ..."
    m_mind = re.match(r"^(?:would|do)\s+you\s+mind\s+(.+)$", text, flags=re.IGNORECASE)
    if m_mind:
        rest = m_mind.group(1).strip()
        rest_low = rest.lower()
        for gerund, imp in GERUND_TO_IMPERATIVE:
            if rest_low.startswith(gerund + " "):
                rest = imp + rest[len(gerund) :]
                break
        text = rest

    # 3. Strip conversational modal & desire prefixes (up to 3 nested layers: "can you please go ahead and ...")
    prefix_re = re.compile(
        r"^(?:"
        r"please\s+|kindly\s+|"
        r"(?:can|could|would|will)\s+you\s+(?:please\s+|kindly\s+|just\s+)?|"
        r"(?:can|could|may)\s+we\s+(?:please\s+)?|"
        r"i\s+(?:want|need)\s+(?:you\s+)?to\s+|"
        r"i'?d\s+(?:like|love)\s+(?:you\s+|for\s+you\s+)?to\s+|"
        r"let'?s\s+(?:go\s+ahead\s+and\s+|just\s+)?|"
        r"go\s+ahead\s+and\s+|"
        r"help\s+me\s+|"
        r"just\s+(?=(?:open|go\s+to|go\s+back|go\s+forward|go\s+home|reload|refresh|close|pull\s+up|bring\s+up|show|switch|take\s+me|watch|play|search|google|look\s+up|browse)\b)"
        r")",
        flags=re.IGNORECASE,
    )
    for _ in range(3):
        updated = prefix_re.sub("", text).strip()
        if updated == text:
            break
        text = updated

    # 4. Strip trailing conversational politeness ("for me please", "real quick", "right now", "thanks")
    text = re.sub(
        r"\s+(?:for\s+me(?:\s+please)?|please|real\s+quick|right\s+now|if\s+you\s+can|thanks|thank\s+you)$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" .!?;,")

    return text


def _build_youtube_search_url(query: str) -> Tuple[str, str]:
    clean_q = re.sub(r"\s+", " ", query).strip(" '?.!,")
    url = f"https://www.youtube.com/results?search_query={quote_plus(clean_q)}"
    short_title = clean_q if len(clean_q) <= 34 else (clean_q[:31].rstrip() + "...")
    return url, f"▶ YouTube: {short_title}"


def _build_site_search_url(site_key: str, query: str) -> Tuple[str, str]:
    clean_q = re.sub(r"\s+", " ", query).strip(" '?.!,")
    enc = quote_plus(clean_q)
    short_q = clean_q if len(clean_q) <= 28 else (clean_q[:25].rstrip() + "...")
    if site_key == "youtube":
        return _build_youtube_search_url(clean_q)
    if site_key == "google":
        return f"https://www.google.com/search?q={enc}", f"Google: {short_q}"
    if site_key == "github":
        return f"https://github.com/search?q={enc}", f"GitHub: {short_q}"
    if site_key == "reddit":
        return f"https://www.reddit.com/search/?q={enc}", f"Reddit: {short_q}"
    if site_key == "espn":
        return f"https://www.espn.com/search/_/q/{enc}", f"ESPN: {short_q}"
    if site_key == "wikipedia":
        return f"https://en.wikipedia.org/w/index.php?search={enc}", f"Wiki: {short_q}"
    if site_key == "amazon":
        return f"https://www.amazon.com/s?k={enc}", f"Amazon: {short_q}"
    return f"https://duckduckgo.com/?q={enc}", f"Search: {short_q}"


def _extract_sports_subject_from_text(text: str) -> Optional[str]:
    """Extract up to two matched teams (e.g. 'Cleveland Browns vs Baltimore Ravens') or a single team/league from text."""
    low = (text or "").lower()
    if not low or "#private" in low:
        return None

    found_teams: List[Tuple[int, str]] = []
    seen_canon: set[str] = set()
    for aliases, canon_name in SPORTS_TEAM_ALIASES:
        for alias in aliases:
            m = re.search(rf"\b{re.escape(alias)}\b", low)
            if m and canon_name not in seen_canon:
                found_teams.append((m.start(), canon_name))
                seen_canon.add(canon_name)
                break

    found_teams.sort(key=lambda item: item[0])
    if len(found_teams) >= 2:
        return f"{found_teams[0][1]} vs {found_teams[1][1]}"
    if len(found_teams) == 1:
        return found_teams[0][1]

    for league_kw, league_title in (
        ("ufc", "UFC"),
        ("champions league", "UEFA Champions League"),
        ("premier league", "Premier League"),
        ("formula 1", "Formula 1"),
        ("f1", "Formula 1"),
        ("world series", "MLB World Series"),
        ("super bowl", "NFL Super Bowl"),
        ("stanley cup", "NHL Stanley Cup"),
        ("college football", "College Football"),
        ("nfl", "NFL"),
        ("nba", "NBA"),
        ("mlb", "MLB"),
        ("nhl", "NHL"),
    ):
        if re.search(rf"\b{re.escape(league_kw)}\b", low):
            return league_title

    return None


def _is_safe_browser_nav_url(raw_url: str) -> bool:
    """Ensure `<ui_nav>` or spoken URLs only navigate to public http(s) destinations."""
    try:
        parsed = urlparse(raw_url.strip())
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith((".local", ".internal")):
            return False
        # Verify literal IPs are public (avoid DNS resolution latency on standard hostnames like youtube.com)
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", host) or ":" in host:
            validate_public_http_url(raw_url)
        return True
    except (SSRFBlockedError, ValueError):
        return False


def deduplicate_ui_commands(cmds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize and deduplicate consecutive or redundant `UIActionCommand` items."""
    if not cmds:
        return []

    normalized: List[Dict[str, Any]] = []
    has_tab_for: set[str] = set()

    for cmd in cmds:
        ctype = str(cmd.get("type") or "")
        if not ctype:
            continue
        if ctype == "navigate_tab":
            tab = str(cmd.get("tab") or "")
            if tab not in VALID_TABS:
                continue
            has_tab_for.add(tab)
            normalized.append({"type": "navigate_tab", "tab": tab})
            continue

        if ctype == "browser_navigate":
            url = str(cmd.get("url") or "").strip()
            if not _is_safe_browser_nav_url(url):
                continue
            if "browser" not in has_tab_for:
                normalized.append({"type": "navigate_tab", "tab": "browser"})
                has_tab_for.add("browser")
            clean_cmd: Dict[str, Any] = {"type": "browser_navigate", "url": url}
            if cmd.get("title"):
                clean_cmd["title"] = str(cmd["title"])
            if cmd.get("new_tab") is not None:
                clean_cmd["new_tab"] = bool(cmd["new_tab"])
            normalized.append(clean_cmd)
            continue

        if ctype == "browser_control":
            action = str(cmd.get("action") or "").strip().lower()
            if action not in VALID_BROWSER_CONTROLS:
                continue
            if "browser" not in has_tab_for:
                normalized.append({"type": "navigate_tab", "tab": "browser"})
                has_tab_for.add("browser")
            normalized.append({"type": "browser_control", "action": action})
            continue

        if ctype == "browser_clip":
            if "browser" not in has_tab_for:
                normalized.append({"type": "navigate_tab", "tab": "browser"})
                has_tab_for.add("browser")
            normalized.append(cmd)
            continue

        if ctype in ("select_project_scope", "set_projects_view", "open_task_drawer", "filter_projects_tasks"):
            if "projects" not in has_tab_for:
                normalized.append({"type": "navigate_tab", "tab": "projects"})
                has_tab_for.add("projects")
            normalized.append(cmd)
            continue

        if ctype in ("open_note", "set_second_brain_graph", "filter_second_brain"):
            if ctype == "set_second_brain_graph" and cmd.get("show") is False:
                normalized.append(cmd)
                continue
            if "second-brain" not in has_tab_for:
                normalized.append({"type": "navigate_tab", "tab": "second-brain"})
                has_tab_for.add("second-brain")
            normalized.append(cmd)
            continue

        normalized.append(cmd)

    # Collapse redundant root homepage `browser_navigate` followed by a search/path `browser_navigate` on the same site
    collapsed: List[Dict[str, Any]] = []
    for idx, cmd in enumerate(normalized):
        if cmd.get("type") == "browser_navigate":
            cur_parsed = urlparse(str(cmd.get("url") or ""))
            cur_is_root = cur_parsed.path in ("", "/") and not cur_parsed.query
            if cur_is_root:
                later_nav = next(
                    (
                        later
                        for later in normalized[idx + 1 :]
                        if later.get("type") == "browser_navigate"
                    ),
                    None,
                )
                if later_nav is not None:
                    continue
        collapsed.append(cmd)

    # Final pass: remove adjacent or identical duplicates
    deduped: List[Dict[str, Any]] = []
    last_tab: Optional[str] = None
    seen_json: set[str] = set()
    for cmd in collapsed:
        if cmd.get("type") == "navigate_tab":
            tab_val = str(cmd.get("tab") or "")
            if tab_val == last_tab:
                continue
            last_tab = tab_val
            deduped.append(cmd)
            continue
        sig = json.dumps(cmd, sort_keys=True)
        if sig in seen_json:
            continue
        seen_json.add(sig)
        deduped.append(cmd)

    return deduped


def clean_text_for_speech(markdown_text: str, max_chars: int = 460) -> str:
    """Convert Markdown + WikiLinks + file paths into crisp, natural spoken English."""
    if not markdown_text:
        return ""
    text = UI_NAV_TAG_RE.sub("", markdown_text)
    text = KAIROS_OP_TAG_RE.sub("", text)
    # Replace [[path/to/file|Alias]] -> Alias, and [[02_Projects/.../TSK-123]] -> TSK-123
    text = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", text)

    def _clean_wikilink(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        tail = inner.split("/")[-1]
        return tail.replace("_", " ")

    text = re.sub(r"\[\[([^\]]+)\]\]", _clean_wikilink, text)
    # Simplify long relative file paths like `02_Projects/KAIROS/Marketing_and_Branding/...`
    text = re.sub(r"`([A-Za-z0-9_\-/]+\.(?:md|canvas|base))`", lambda m: m.group(1).split("/")[-1].replace("_", " "), text)
    # Remove markdown formatting symbols & emojis that TTS reads awkwardly
    text = re.sub(r"[`*_#>~]+", " ", text)
    text = re.sub(r"[•✓⚠️🔒🚨🚀💻📣📄🌐👕📥📎🧭🤖🏈🧠👤🪽📖📅🗓️⚡📂➕⛓▶🎬🔎]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars].rsplit(".", 1)[0]
        text = (cut + ".") if len(cut) > 80 else (text[:max_chars].rstrip() + "...")
    return text


def extract_llm_ui_commands(raw_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract and sanitize `<ui_nav>{...}</ui_nav>` JSON action blocks emitted by Gemma 4 or Gemini."""
    cmds: List[Dict[str, Any]] = []
    for match in UI_NAV_TAG_RE.finditer(raw_text or ""):
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict) and parsed.get("type"):
                cmds.append(parsed)
        except Exception:
            pass
    cleaned = UI_NAV_TAG_RE.sub("", raw_text or "").strip()
    return cleaned, deduplicate_ui_commands(cmds)


class PlatformNavigator:
    """Deterministic + context-aware voice navigation resolver for KAIROS 2.0."""

    def __init__(self, vault: VaultEngine, index: ShadowIndex) -> None:
        self.vault = vault
        self.index = index

    def _match_project_name(self, text_low: str) -> Optional[str]:
        """Match spoken project names against live `02_Projects/` folders (longest match first)."""
        hierarchy = self.index.get_projects_hierarchy()
        project_names = [p["name"] for p in hierarchy]
        for std in ("KAIROS_2_0", "KAIROS"):
            if std not in project_names and (self.vault.vault_path / "02_Projects" / std).is_dir():
                project_names.append(std)

        candidates: List[Tuple[int, str]] = []
        for pname in project_names:
            variants = {
                pname.lower(),
                pname.lower().replace("_", " "),
                pname.lower().replace("_", "."),
            }
            if pname == "KAIROS_2_0":
                variants.update({"kairos 2.0", "kairos 2", "kairos two", "kairos v2"})
            elif pname == "KAIROS":
                variants.update({"kairos project", "original kairos", "kairos 1", "kairos v1", "project kairos"})

            for v in variants:
                if re.search(rf"\b{re.escape(v)}\b", text_low):
                    candidates.append((len(v), pname))

        if not candidates:
            # Check plain "kairos" ONLY when "kairos 2" wasn't said and user explicitly mentions project/board/tasks/department
            if re.search(r"\bkairos\b", text_low) and not re.search(r"\bkairos\s*(?:2|two|2\.0)\b", text_low):
                stripped_wake = re.sub(r"^(?:hey\s+|ok\s+|yo\s+)?kairos[\s,:;\-]+", "", text_low).strip()
                if re.search(r"\bkairos\b", stripped_wake):
                    if "KAIROS" in project_names:
                        return "KAIROS"
                    if "KAIROS_2_0" in project_names:
                        return "KAIROS_2_0"
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _match_department(self, text_low: str) -> Tuple[str, str, str]:
        for phrases, dept_id, list_id, label in DEPARTMENT_SYNONYMS:
            for ph in phrases:
                if ph in text_low:
                    return dept_id, list_id, label
        # Also match custom categories created inside `02_Projects/`
        for proj in self.index.get_projects_hierarchy():
            for dept in proj.get("departments") or []:
                dname = str(dept.get("name") or "")
                if not dname:
                    continue
                d_spoken = dname.lower().replace("_", " ")
                if re.search(rf"\b{re.escape(d_spoken)}\b", text_low):
                    lists = dept.get("lists") or []
                    first_list = (
                        str(lists[0].get("name") or "General")
                        if lists and isinstance(lists[0], dict)
                        else str(lists[0])
                        if lists
                        else "General"
                    )
                    return dname, first_list, dname.replace("_", " ")
        return "", "", ""

    def _match_projects_subview(self, text_low: str) -> Tuple[str, str]:
        for phrases, view_id, label in PROJECTS_VIEW_SYNONYMS:
            for ph in phrases:
                if re.search(rf"\b{re.escape(ph)}\b", text_low):
                    return view_id, label
        return "", ""

    def _infer_context_sports_subject(
        self,
        prior_turns: Optional[List[Dict[str, Any]]],
        *,
        is_private_context: bool = False,
        live_sports_hint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> Optional[str]:
        """Resolve contextual 'the game' / 'the highlights' against recent session turns or live Cleveland sports."""
        if not is_private_context and prior_turns:
            for turn in reversed(prior_turns):
                content = str(turn.get("content") or "")
                if turn.get("privacy_locked") or "#private" in content.lower():
                    continue
                subj = _extract_sports_subject_from_text(content)
                if subj:
                    return subj

        if not is_private_context and live_sports_hint_fn is not None:
            try:
                live_hint = live_sports_hint_fn()
                if live_hint:
                    return live_hint
            except Exception:
                pass

        return None

    def _infer_last_turn_topic(
        self,
        prior_turns: Optional[List[Dict[str, Any]]],
        *,
        is_private_context: bool = False,
    ) -> Optional[str]:
        """Extract a clean public topic when the user says 'pull that up on YouTube' or 'google that'."""
        if is_private_context or not prior_turns:
            return None
        for turn in reversed(prior_turns):
            if str(turn.get("role") or "") != "user":
                continue
            content = str(turn.get("content") or "").strip()
            if not content or turn.get("privacy_locked") or "#private" in content.lower():
                continue
            sports_subj = _extract_sports_subject_from_text(content)
            if sports_subj:
                return sports_subj
            cleaned = _strip_conversational_wrappers(content)
            cleaned = re.sub(
                r"^(?:what(?:'s|\s+is|\s+are)|who(?:'s|\s+is)|tell\s+me\s+about|explain)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip(" ?.!,'\"")
            if 2 <= len(cleaned) <= 72:
                return cleaned
        return None

    def _resolve_media_or_web_navigation(
        self,
        body: str,
        low: str,
        *,
        active_site_context: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
        is_private_context: bool = False,
        live_sports_hint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str], str]:
        """Resolve YouTube highlights/videos, well-known websites, natural web searches, and direct URLs.

        Returns `(ui_commands, action_notes, next_site_context)`.
        """
        # Security & Privacy Guard: Never transmit `#private` text in external URL queries
        if "#private" in low:
            return [], [], active_site_context

        # A. Explicit Highlight / Game Recap / Condensed Game Intent (automatically routes to YouTube!)
        m_highlights = re.match(
            r"^(?:(?:pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|cue\s+up|queue\s+up|open(?:\s+up)?|show(?:\s+me)?|watch|play|find|search(?:\s+youtube)?\s+for|look\s+up)\s+)?"
            r"(?:(?:the|some|latest|recent|full|extended)\s+)?"
            r"(?:"
            r"(?:video\s+)?highlights?\s+(?:of|from|for)\s+(.+?)"
            r"|(.+?)\s+(?:game\s+)?(?:highlights?|game\s+recap|condensed\s+game|postgame\s+highlights?)"
            r"|(?:highlights?|game\s+recap)"
            r")"
            r"(?:\s+(?:on|in)\s+(?:youtube|you\s+tube|the\s+browser|browser))?$",
            body,
            flags=re.IGNORECASE,
        )
        if m_highlights:
            raw_subject = (m_highlights.group(1) or m_highlights.group(2) or "").strip(" '\"")
            explicit_sports = _extract_sports_subject_from_text(raw_subject) if raw_subject else None

            if raw_subject and not VAGUE_GAME_REFERENCE_RE.match(raw_subject):
                # User named a specific team, player, matchup, or event (e.g. "Browns", "UFC 308", "Lakers vs Celtics")
                trimmed_subj = re.sub(r"^the\s+", "", raw_subject, flags=re.IGNORECASE).strip()
                subject_label = (
                    explicit_sports
                    if (
                        explicit_sports
                        and trimmed_subj.lower() in ("browns", "cavs", "guards", "tribe", "dawgs", "buckeyes")
                    )
                    else trimmed_subj
                )
                yt_query = (
                    subject_label
                    if "highlight" in subject_label.lower() or "recap" in subject_label.lower()
                    else f"{subject_label} highlights"
                )
            else:
                # Vague sports reference ("the game", "last night's game", or bare "pull up the highlights")
                ctx_subject = self._infer_context_sports_subject(
                    prior_turns,
                    is_private_context=is_private_context,
                    live_sports_hint_fn=live_sports_hint_fn,
                )
                time_qualifier = ""
                if "last night" in low:
                    time_qualifier = " last night"
                elif "yesterday" in low:
                    time_qualifier = " yesterday"
                elif "today" in low or "tonight" in low:
                    time_qualifier = " today"

                if ctx_subject:
                    yt_query = f"{ctx_subject} game highlights{time_qualifier}".strip()
                else:
                    yt_query = f"game highlights{time_qualifier}".strip()

            yt_url, yt_title = _build_youtube_search_url(yt_query)
            return (
                [
                    {"type": "navigate_tab", "tab": "browser"},
                    {"type": "browser_navigate", "url": yt_url, "title": yt_title, "new_tab": True},
                ],
                [f"Pulled up YouTube highlights for '{yt_query}'"],
                "youtube",
            )

        # B. Explicit YouTube Search / Watch / Play / Video Tutorial Intent
        yt_query_extracted: Optional[str] = None

        # Pattern B1: "search youtube for X" / "youtube search X" / "on youtube search for X"
        m_yt_search = re.match(
            r"^(?:search\s+(?:on\s+)?(?:youtube|you\s+tube)\s+(?:for\s+)?|(?:youtube|you\s+tube)\s+search\s+(?:for\s+)?|on\s+(?:youtube|you\s+tube)\s+(?:search\s+(?:for\s+)?|find\s+|pull\s+up\s+|play\s+|watch\s+))(.+)$",
            body,
            flags=re.IGNORECASE,
        )
        if m_yt_search:
            yt_query_extracted = m_yt_search.group(1).strip()

        # Pattern B2: "<verb> <query> on youtube" (e.g., "pull up Three.js shaders on YouTube", "watch Obsidian tips on YouTube", "play lofi beats on YouTube")
        if not yt_query_extracted:
            m_on_yt = re.match(
                r"^(?:pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|cue\s+up|queue\s+up|open(?:\s+up)?|show(?:\s+me)?|watch|play|listen\s+to|find|look\s+up|search(?:\s+for)?)\s+(.+?)\s+(?:on|in)\s+(?:youtube|you\s+tube|yt)$",
                body,
                flags=re.IGNORECASE,
            )
            if m_on_yt:
                yt_query_extracted = m_on_yt.group(1).strip()

        # Pattern B3: Video / Tutorial media verbs even without saying "on YouTube" ("watch a video on X", "pull up videos of X", "show me a video tutorial on X")
        if not yt_query_extracted:
            m_video_topic = re.match(
                r"^(?:pull\s+up|pull\s+op|pull-up|bring\s+up|cue\s+up|queue\s+up|open(?:\s+up)?|show(?:\s+me)?|watch|play|find)\s+(?:a\s+|some\s+|the\s+)?(?:youtube\s+)?(?:videos?|video\s+tutorials?|tutorials?)\s+(?:on|about|for|of)\s+(.+)$",
                body,
                flags=re.IGNORECASE,
            )
            if m_video_topic:
                yt_query_extracted = f"{m_video_topic.group(1).strip()} tutorial" if "tutorial" in low and "tutorial" not in m_video_topic.group(1).lower() else m_video_topic.group(1).strip()

        # Pattern B4: Chained follow-up clause when previous clause just opened YouTube ("go to YouTube and search for X" / "open YouTube and pull up X" / "go to YouTube and play X")
        if not yt_query_extracted and active_site_context == "youtube":
            m_yt_chained = re.match(
                r"^(?:search(?:\s+for)?|look\s+up|pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|cue\s+up|queue\s+up|play|watch|find|show(?:\s+me)?)\s+(.+)$",
                body,
                flags=re.IGNORECASE,
            )
            if m_yt_chained:
                yt_query_extracted = m_yt_chained.group(1).strip()

        if yt_query_extracted:
            if yt_query_extracted.lower() in ("that", "it", "this", "them"):
                inferred = self._infer_last_turn_topic(prior_turns, is_private_context=is_private_context)
                yt_query_extracted = inferred or "trending videos"
            elif VAGUE_GAME_REFERENCE_RE.match(yt_query_extracted):
                inferred_game = self._infer_context_sports_subject(
                    prior_turns,
                    is_private_context=is_private_context,
                    live_sports_hint_fn=live_sports_hint_fn,
                )
                yt_query_extracted = f"{inferred_game} highlights" if inferred_game else "game highlights"

            yt_url, yt_title = _build_youtube_search_url(yt_query_extracted)
            return (
                [
                    {"type": "navigate_tab", "tab": "browser"},
                    {"type": "browser_navigate", "url": yt_url, "title": yt_title, "new_tab": True},
                ],
                [f"Opened YouTube search for '{yt_query_extracted}'"],
                "youtube",
            )

        # C. Site-Specific Searches ("search GitHub for ...", "look up ... on Reddit", "search Google for ...", "google ...")
        m_site_search = re.match(
            r"^(?:search|check)\s+(google|duckduckgo|github|reddit|espn|wikipedia|amazon)\s+(?:for\s+)?(.+)$",
            body,
            flags=re.IGNORECASE,
        ) or re.match(
            r"^(?:look\s+up|search(?:\s+for)?|find|pull\s+up)\s+(.+?)\s+on\s+(google|duckduckgo|github|reddit|espn|wikipedia|amazon)$",
            body,
            flags=re.IGNORECASE,
        )
        if m_site_search:
            if m_site_search.re.pattern.startswith("^(?:search|check)"):
                s_key = m_site_search.group(1).lower()
                s_q = m_site_search.group(2).strip()
            else:
                s_q = m_site_search.group(1).strip()
                s_key = m_site_search.group(2).lower()
            if s_q.lower() in ("that", "it", "this"):
                s_q = self._infer_last_turn_topic(prior_turns, is_private_context=is_private_context) or s_q
            s_url, s_title = _build_site_search_url(s_key, s_q)
            return (
                [
                    {"type": "navigate_tab", "tab": "browser"},
                    {"type": "browser_navigate", "url": s_url, "title": s_title, "new_tab": True},
                ],
                [f"Searched {s_key.capitalize()} for '{s_q}' in Browser"],
                s_key,
            )

        # D. Natural Web / Google / Browser Search ("google X", "search the web for X", "search in the browser for X", "look up X online")
        m_bsearch = (
            re.match(
                r"^(?:search\s+(?:in\s+)?(?:the\s+)?(?:browser|web)\s+for|search\s+online\s+for|google\s+in\s+browser|google)\s+(.+)$",
                body,
                flags=re.IGNORECASE,
            )
            or re.match(
                r"^(?:look\s+up|search(?:\s+for)?|pull\s+up)\s+(.+?)\s+(?:online|on\s+the\s+web|in\s+(?:the\s+)?browser)$",
                body,
                flags=re.IGNORECASE,
            )
        )
        if m_bsearch:
            q_str = m_bsearch.group(1).strip(" '\"")
            if q_str.lower() in ("that", "it", "this"):
                q_str = self._infer_last_turn_topic(prior_turns, is_private_context=is_private_context) or q_str
            # Preserve DuckDuckGo default for "search in the browser for ...", use Google when explicitly "google ..."
            use_google = low.startswith("google ") and not low.startswith("google in browser")
            if use_google:
                search_url, title_lbl = _build_site_search_url("google", q_str)
            else:
                search_url = f"https://duckduckgo.com/?q={quote_plus(q_str)}"
                title_lbl = f"Search: {q_str[:24]}"
            return (
                [
                    {"type": "navigate_tab", "tab": "browser"},
                    {"type": "browser_navigate", "url": search_url, "title": title_lbl},
                ],
                [f"Opened Browser search for '{q_str}'"],
                "google" if use_google else "duckduckgo",
            )

        # Chained search when previous clause opened Browser or Google ("open browser and search for X")
        if active_site_context in ("browser", "google", "duckduckgo"):
            m_chained_web = re.match(
                r"^(?:search(?:\s+for)?|look\s+up|find)\s+(.+)$",
                body,
                flags=re.IGNORECASE,
            )
            if m_chained_web:
                q_str = m_chained_web.group(1).strip(" '\"")
                s_key = "google" if active_site_context == "google" else "duckduckgo"
                s_url, s_title = _build_site_search_url(s_key, q_str)
                return (
                    [
                        {"type": "navigate_tab", "tab": "browser"},
                        {"type": "browser_navigate", "url": s_url, "title": s_title},
                    ],
                    [f"Opened Browser search for '{q_str}'"],
                    s_key,
                )

        # E. Direct URL / Domain Navigation ("open espn.com", "go to github.com/kepano", "browse to https://...")
        m_url = re.match(
            r"^(?:browse\s+to|navigate\s+(?:browser\s+)?to|go\s+to\s+url|open\s+url|visit|check\s+out)\s+((?:https?://)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)+(?:/[^\s]*)?)$",
            low,
        ) or re.match(
            r"^(?:open(?:\s+website)?|go\s+to|pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|show(?:\s+me)?|check\s+out|head\s+to|launch|visit)\s+((?:https?://)?[a-z0-9\-]+\.(?:com|org|io|dev|net|ai|gov|edu|co|app|tv|gg|me|xyz|us)(?:/[^\s]*)?)(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        )
        if m_url:
            raw_url = m_url.group(1).strip()
            full_url = raw_url if raw_url.startswith(("http://", "https://")) else f"https://{raw_url}"
            if _is_safe_browser_nav_url(full_url):
                host_lbl = (urlparse(full_url).hostname or raw_url).replace("www.", "")
                site_ctx = "youtube" if "youtube.com" in host_lbl else "google" if "google.com" in host_lbl else "web"
                return (
                    [
                        {"type": "navigate_tab", "tab": "browser"},
                        {"type": "browser_navigate", "url": full_url, "title": host_lbl},
                    ],
                    [f"Navigated embedded Browser to `{full_url}`"],
                    site_ctx,
                )

        # F. Known Website Destinations without TLD ("open YouTube", "go to ESPN", "pull up GitHub", "check out Reddit")
        m_known_site = re.match(
            r"^(?:open(?:\s+up)?|go\s+to|pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|show(?:\s+me)?|check\s+out|head\s+to|navigate\s+to|take\s+me\s+to|launch|visit)\s+(?:the\s+)?(.+?)(?:\s+(?:website|site|in\s+(?:the\s+)?browser))?$",
            low,
        )
        if m_known_site:
            site_candidate = m_known_site.group(1).strip()
            for aliases, dest_url, dest_title, site_ctx in KNOWN_WEB_DESTINATIONS:
                if site_candidate in aliases:
                    return (
                        [
                            {"type": "navigate_tab", "tab": "browser"},
                            {"type": "browser_navigate", "url": dest_url, "title": dest_title},
                        ],
                        [f"Opened {dest_title} (`{dest_url}`) in Browser"],
                        site_ctx,
                    )

        # F2. ForestCityCreatorsLLC Sub-Repository Navigation ("open ForestCityCreatorsLLC/Kairos", "open FCC repo FCC-Brand-Portal")
        m_fcc_repo = re.match(
            r"^(?:open(?:\s+up)?|go\s+to|pull\s+up|pull\s+op|pull-up|bring\s+up|show(?:\s+me)?|check\s+out|visit|launch)\s+"
            r"(?:(?:the\s+)?(?:repo(?:sitory)?\s+)?)?"
            r"(?:forestcitycreatorsllc/([A-Za-z0-9_.\-]+)|(?:fcc|forest\s+city\s+creators(?:\s+llc)?)\s+repo(?:sitory)?\s+([A-Za-z0-9_.\-]+))"
            r"(?:\s+(?:repo(?:sitory)?|in\s+(?:the\s+)?browser|on\s+github))?$",
            body,
            flags=re.IGNORECASE,
        )
        if m_fcc_repo:
            repo_slug = (m_fcc_repo.group(1) or m_fcc_repo.group(2) or "").strip()
            if repo_slug:
                repo_url = f"https://github.com/ForestCityCreatorsLLC/{repo_slug}"
                repo_title = f"ForestCityCreatorsLLC/{repo_slug}"
                return (
                    [
                        {"type": "navigate_tab", "tab": "browser"},
                        {"type": "browser_navigate", "url": repo_url, "title": repo_title},
                    ],
                    [f"Opened GitHub repository `{repo_title}` in Browser"],
                    "github",
                )

        return [], [], active_site_context

    def resolve_clause(
        self,
        clause: str,
        *,
        current_project: str = "",
        current_department: str = "",
        active_site_context: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
        is_private_context: bool = False,
        live_sports_hint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str], str]:
        """Resolve a single spoken navigation/control clause into `(UIActionCommands, notes, next_site_context)`."""
        raw = clause.strip()
        if not raw:
            return [], [], active_site_context

        # Check raw & stripped against mutation/question guard so creation, scheduling, memory, briefing, and live Q&A are never hijacked
        body = _strip_conversational_wrappers(raw)
        low = body.lower()
        if not low:
            return [], [], active_site_context

        if MUTATION_OR_QUESTION_GUARD_RE.match(low):
            return [], [], active_site_context

        cmds: List[Dict[str, Any]] = []
        notes: List[str] = []

        # 1. Tone Mode (`CODE RED` / `Normal`)
        if re.search(r"\b(?:activate|enable|turn\s+on|enter|switch\s+to)\s+code\s+red\b", low) or low == "code red":
            cmds.append({"type": "set_tone_mode", "tone_mode": "CODE_RED"})
            notes.append("Activated tactical CODE RED mode")
            return cmds, notes, active_site_context
        if re.search(r"\b(?:deactivate|disable|turn\s+off|exit|stand\s+down(?:\s+from)?)\s+code\s+red\b", low) or re.search(
            r"\b(?:normal|default)\s+tone(?:\s+mode)?\b", low
        ):
            cmds.append({"type": "set_tone_mode", "tone_mode": "DEFAULT"})
            notes.append("Restored Normal executive tone mode")
            return cmds, notes, active_site_context

        # 2. Persona Switching
        if any(w in low for w in ("persona", "act as", "switch role", "director mode", "architect mode", "executive mode", "companion mode")):
            for phrases, pid, plabel in PERSONA_SYNONYMS:
                if any(ph in low for ph in phrases):
                    cmds.append({"type": "set_persona", "persona": pid})
                    notes.append(f"Switched KAIROS persona to {plabel}")
                    return cmds, notes, active_site_context

        # 3. Brain Routing Mode (`Auto` / `Gemma 4` / `Gemini` / `Hybrid`)
        m_brain = re.match(
            r"^(?:switch|set|change|use)\s+(?:the\s+)?(?:ai\s+|brain(?:\s+mode)?\s+)?(?:to\s+)?(local\s+gemma(?:\s*4)?|gemma(?:\s*4)?|cloud\s+gemini|gemini|hybrid(?:\s+mode)?|auto(?:\s+route|\s+mode)?)$",
            low,
        )
        if m_brain:
            b_raw = m_brain.group(1)
            b_mode = (
                "gemma-4"
                if "gemma" in b_raw
                else "gemini"
                if "gemini" in b_raw
                else "hybrid"
                if "hybrid" in b_raw
                else "auto"
            )
            cmds.append({"type": "set_brain_mode", "brain_mode": b_mode})
            notes.append(f"Switched AI Brain router to `{b_mode}`")
            return cmds, notes, active_site_context

        # 4. Docked Chat Drawer / Left Sidebar / Focus Mode / Quick Jump Palette / Voice Controls
        if re.search(
            r"\b(?:enter|activate|enable|turn\s+on)\s+focus\s+mode\b|\b(?:maximize|full[\s\-]+width)\s+workspace\b",
            low,
        ) or low == "focus mode":
            cmds.append({"type": "set_left_sidebar", "collapsed": True})
            cmds.append({"type": "set_chat_drawer", "open": False})
            notes.append("Entered Focus Mode (retracted Left Sidebar & collapsed Chat Drawer)")
            return cmds, notes, active_site_context
        if re.search(
            r"\b(?:exit|leave|disable|turn\s+off)\s+focus\s+mode\b|\brestore\s+(?:all\s+)?(?:panels|sidebars)\b",
            low,
        ):
            cmds.append({"type": "set_left_sidebar", "collapsed": False})
            cmds.append({"type": "set_chat_drawer", "open": True})
            notes.append("Exited Focus Mode (restored Left Sidebar & docked Chat Drawer)")
            return cmds, notes, active_site_context
        if re.search(
            r"\b(?:collapse|retract|shrink|minimize|hide)\s+(?:the\s+)?(?:left\s+sidebar|sidebar|left\s+menu|workspace\s+menu)\b|\bicon(?:\s*-\s*|\s+)only\s+(?:menu|sidebar)\b",
            low,
        ):
            cmds.append({"type": "set_left_sidebar", "collapsed": True})
            notes.append("Retracted Left Sidebar to icon rail")
            return cmds, notes, active_site_context
        if re.search(
            r"\b(?:expand|open|show|uncollapse|restore)\s+(?:the\s+)?(?:left\s+sidebar|sidebar|left\s+menu|workspace\s+menu)\b",
            low,
        ):
            cmds.append({"type": "set_left_sidebar", "collapsed": False})
            notes.append("Expanded Left Sidebar menu")
            return cmds, notes, active_site_context
        if re.search(r"\b(?:open|show|expand)\s+(?:the\s+)?(?:chat\s+drawer|chat\s+panel|side\s+chat)\b", low):
            cmds.append({"type": "set_chat_drawer", "open": True})
            notes.append("Opened docked KAIROS Chat panel")
            return cmds, notes, active_site_context
        if re.search(r"\b(?:close|hide|collapse)\s+(?:the\s+)?(?:chat\s+drawer|chat\s+panel|side\s+chat)\b", low):
            cmds.append({"type": "set_chat_drawer", "open": False})
            notes.append("Collapsed docked KAIROS Chat panel")
            return cmds, notes, active_site_context
        if re.search(r"\b(?:open|show|launch)\s+(?:quick\s+jump|command\s+palette|omni\s*search)\b", low):
            cmds.append({"type": "set_command_palette", "open": True})
            notes.append("Opened Quick Jump Omni-Search")
            return cmds, notes, active_site_context
        if re.search(r"\b(?:close|hide)\s+(?:quick\s+jump|command\s+palette|task\s+drawer)\b", low):
            if "task" in low:
                cmds.append({"type": "close_task_drawer"})
                notes.append("Closed Task Drawer")
            else:
                cmds.append({"type": "set_command_palette", "open": False})
                notes.append("Closed Quick Jump")
            return cmds, notes, active_site_context

        # 5. Daily Note
        if re.search(r"\b(?:open|show|go\s+to|pull\s+up|bring\s+up|create)\s+(?:today'?s?\s+|my\s+)?daily\s+note\b", low):
            today = datetime.now().strftime("%Y-%m-%d")
            rel = f"03_Personal/Calendar/{today}.md"
            target = self.vault.resolve_safe_path(rel)
            if not target.exists():
                self.vault.write_note(
                    rel,
                    {"title": f"Daily System Note — {today}", "type": "daily", "date": today, "tags": ["daily-note"]},
                    (
                        f"# 📅 Daily System Note — {today}\n\n"
                        "> [!IMPORTANT] Top 3 Executive Priorities\n"
                        "> - [ ] Review active Project tasks across `KAIROS` & `KAIROS_2_0`\n"
                        "> - [ ] Triage `00_Inbox/` captures\n"
                        "> - [ ] Check in with KAIROS Voice Co-Pilot\n"
                    ),
                )
                self.index.index_file(target)
            cmds.append({"type": "navigate_tab", "tab": "second-brain"})
            cmds.append({"type": "open_note", "rel_path": rel})
            notes.append(f"Opened today's Daily Note (`{today}.md`) in Second Brain")
            return cmds, notes, active_site_context

        # 6. Open Specific Task Drawer by ID (`TSK-...`) or Task Inspection Phrase
        m_tsk_id = re.search(r"\b(?:open|show|inspect|view|pull\s+up|bring\s+up)\s+(?:task\s+)?(TSK-[\w\-]+)\b", body, flags=re.IGNORECASE)
        if m_tsk_id:
            tid = m_tsk_id.group(1).upper()
            try:
                p = self.vault.find_task_file(tid)
                note_d = self.vault.read_note(self.vault.to_rel_path(p))
                proj = str(note_d["frontmatter"].get("project") or "").strip("[]")
                cmds.append({"type": "navigate_tab", "tab": "projects"})
                if proj:
                    cmds.append({"type": "select_project_scope", "project": proj, "department": "", "list": ""})
                cmds.append({"type": "open_task_drawer", "task_id": tid})
                notes.append(f"Opened task `{tid}` ({note_d['title']}) in Projects")
                return cmds, notes, active_site_context
            except FileNotFoundError:
                pass

        m_tsk_title = re.match(r"^(?:open|inspect|view|pull\s+up|bring\s+up)\s+task\s+(.+)$", body, flags=re.IGNORECASE)
        if m_tsk_title:
            q_title = m_tsk_title.group(1).strip(" '\"")
            all_tasks = self.index.list_tasks()
            best = next((t for t in all_tasks if q_title.lower() in t["title"].lower()), None)
            if best:
                cmds.append({"type": "navigate_tab", "tab": "projects"})
                cmds.append({"type": "select_project_scope", "project": best["project"], "department": best["department"], "list": ""})
                cmds.append({"type": "open_task_drawer", "task_id": best["id"]})
                notes.append(f"Opened task `{best['id']}` ({best['title']})")
                return cmds, notes, active_site_context

        # 7. Browser Clipping & Hands-Free Browser Tab/History Controls
        if re.search(r"\bclip\s+(?:this|current|the)\s+(?:page|webpage|site|tab)\b", low):
            dest = "04_Resources/Code_and_Research" if "resource" in low else "00_Inbox"
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_clip", "dest_folder": dest})
            notes.append(f"Triggered Browser Web Clipper → `{dest}`")
            return cmds, notes, "browser"

        if re.match(
            r"^(?:go\s+back|navigate\s+back|browser\s+back|previous\s+(?:web\s*)?page|back\s+(?:a\s+|one\s+)?page)(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        ):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "back"})
            notes.append("Navigated back in Embedded Browser")
            return cmds, notes, "browser"

        if re.match(
            r"^(?:go\s+forward|navigate\s+forward|browser\s+forward|next\s+(?:web\s*)?page|forward\s+(?:a\s+|one\s+)?page)(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        ):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "forward"})
            notes.append("Navigated forward in Embedded Browser")
            return cmds, notes, "browser"

        if re.match(
            r"^(?:reload|refresh)(?:\s+(?:this|the|current))?(?:\s+(?:web\s*page|page|browser\s+tab|web\s+tab|tab|browser|site|website))?(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        ):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "reload"})
            notes.append("Reloaded active Browser tab")
            return cmds, notes, "browser"

        if re.match(
            r"^(?:open|create|add|launch)\s+(?:a\s+)?new\s+(?:browser\s+|web\s+)?tab(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        ) or low in ("new browser tab", "new web tab", "new tab"):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "new_tab"})
            notes.append("Opened a new Embedded Browser tab")
            return cmds, notes, "browser"

        if re.match(
            r"^close\s+(?:this|the|current)\s+(?:browser\s+|web\s+)?tab(?:\s+in\s+(?:the\s+)?browser)?$",
            low,
        ) or low in ("close browser tab", "close web tab", "close tab"):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "close_tab"})
            notes.append("Closed active Embedded Browser tab")
            return cmds, notes, "browser"

        if re.match(
            r"^(?:go\s+home(?:\s+in\s+(?:the\s+)?browser)?|browser\s+home(?:\s*page)?)$",
            low,
        ):
            cmds.append({"type": "navigate_tab", "tab": "browser"})
            cmds.append({"type": "browser_control", "action": "home"})
            notes.append("Navigated Embedded Browser to Forest City Creators LLC Home")
            return cmds, notes, "github"

        # 8. Second Brain Knowledge Graph (`3D Galaxy` / `2D Map`) & Explicit Vault Folder / Note Navigation
        if re.search(r"\b(?:3d\s+galaxy|galaxy\s+graph|3d\s+graph|3d\s+knowledge\s+graph|orbit\s+graph)\b", low) and any(
            v in low for v in ("open", "show", "switch", "go to", "view", "display", "pull up", "bring up", "check out", "look at")
        ):
            cmds.append({"type": "navigate_tab", "tab": "second-brain"})
            cmds.append({"type": "set_second_brain_graph", "show": True, "mode": "3d"})
            notes.append("Opened Second Brain 3D Galaxy Knowledge Graph")
            return cmds, notes, active_site_context

        if re.search(r"\b(?:2d\s+graph|2d\s+map|wikilink\s+map|2d\s+network)\b", low) and any(
            v in low for v in ("open", "show", "switch", "go to", "view", "display", "pull up", "bring up", "check out")
        ):
            cmds.append({"type": "navigate_tab", "tab": "second-brain"})
            cmds.append({"type": "set_second_brain_graph", "show": True, "mode": "2d"})
            notes.append("Switched Second Brain Knowledge Graph to 2D WikiLink Map")
            return cmds, notes, active_site_context

        if re.search(r"\bhide\s+(?:the\s+)?(?:knowledge\s+)?graph\b", low):
            cmds.append({"type": "set_second_brain_graph", "show": False, "mode": "3d"})
            notes.append("Collapsed Second Brain Knowledge Graph panel")
            return cmds, notes, active_site_context

        # Vault Search in Second Brain ("Search vault for ...")
        m_vsearch = re.match(
            r"^(?:search\s+(?:the\s+)?(?:vault|second\s+brain|notes)\s+for|find\s+notes?\s+(?:about|on|matching))\s+(.+)$",
            body,
            flags=re.IGNORECASE,
        )
        if m_vsearch:
            q_vault = m_vsearch.group(1).strip(" '\"")
            hits = self.index.search_vault(query=q_vault, limit=5)
            cmds.append({"type": "navigate_tab", "tab": "second-brain"})
            cmds.append({"type": "filter_second_brain", "query": q_vault, "folder": ""})
            if hits:
                cmds.append({"type": "open_note", "rel_path": hits[0]["rel_path"]})
                notes.append(f"Searched Second Brain for '{q_vault}' ({len(hits)} match(es); opened `{hits[0]['title']}`)")
            else:
                notes.append(f"Searched Second Brain for '{q_vault}' (0 matches)")
            return cmds, notes, active_site_context

        # Specific Well-Known Notes / Vault Folders ("Open AGENTS.md", "Open Change Ledger", "Open Finance folder")
        if any(v in low for v in ("open", "show", "go to", "view", "pull up", "bring up", "read", "look at", "check", "take me to")):
            if "agents.md" in low or "operating constitution" in low or "vault constitution" in low:
                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                cmds.append({"type": "open_note", "rel_path": "AGENTS.md"})
                notes.append("Opened `AGENTS.md` Operating Constitution in Second Brain")
                return cmds, notes, active_site_context
            if "change ledger" in low or "os updates" in low or "changelog" in low:
                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                cmds.append({"type": "open_note", "rel_path": "01_Business/OS_Updates/KAIROS_2_0_Change_Ledger.md"})
                notes.append("Opened `KAIROS_2_0_Change_Ledger.md` in Second Brain")
                return cmds, notes, active_site_context
            if "operator memory" in low:
                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                cmds.append({"type": "open_note", "rel_path": "03_Personal/Personal_Growth/KAIROS_Operator_Memory.md"})
                notes.append("Opened `KAIROS_Operator_Memory.md` in Second Brain")
                return cmds, notes, active_site_context
            if "architecture diagram" in low or ("architecture" in low and "canvas" in low):
                proj_match = self._match_project_name(low) or current_project or "KAIROS_2_0"
                canvas_rel = f"02_Projects/{proj_match}/Docs/Architecture_Diagram.canvas"
                if (self.vault.vault_path / canvas_rel).is_file():
                    cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                    cmds.append({"type": "open_note", "rel_path": canvas_rel})
                    notes.append(f"Opened `{canvas_rel}` whiteboard in Second Brain")
                    return cmds, notes, active_site_context
            if "finance folder" in low or "finance notes" in low or "personal finance" in low or "private finance" in low:
                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                cmds.append({"type": "filter_second_brain", "query": "", "folder": "03_Personal/Finance"})
                fin_hits = self.index.search_vault(folder="03_Personal/Finance", limit=1)
                if fin_hits:
                    cmds.append({"type": "open_note", "rel_path": fin_hits[0]["rel_path"]})
                notes.append("Opened `03_Personal/Finance` in Second Brain (🔒 Local Gemma 4 Privacy Shield Active)")
                return cmds, notes, active_site_context

            m_note = re.match(
                r"^(?:open|show|view|pull\s+up|bring\s+up|read)\s+note\s+(.+)$",
                body,
                flags=re.IGNORECASE,
            )
            if m_note:
                nq = m_note.group(1).strip(" '\"")
                hits = self.index.search_vault(query=nq, limit=3)
                if hits:
                    cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                    cmds.append({"type": "open_note", "rel_path": hits[0]["rel_path"]})
                    notes.append(f"Opened note `{hits[0]['title']}` (`{hits[0]['rel_path']}`)")
                    return cmds, notes, active_site_context

            # 8b. Vault Master Catalog & Dynamic Obsidian Section Hub Navigation ("Open Music Studio", "Open Music Studio catalog", "Open Music Studio canvas")
            if "vault master catalog" in low or "master catalog" in low:
                master_rel = "_System/Dashboards/Vault_Master_Catalog.base"
                if (self.vault.vault_path / master_rel).is_file():
                    cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                    cmds.append({"type": "open_note", "rel_path": master_rel})
                    notes.append(f"Opened `{master_rel}` in Second Brain")
                    return cmds, notes, active_site_context

            m_sec_nav = re.match(
                r"^(?:open(?:\s+up)?|show(?:\s+me)?|go\s+to|view|pull\s+up|bring\s+up|take\s+me\s+to|look\s+at|check(?:\s+out)?)\s+(?:my\s+|the\s+)?(.+?)(?:\s+in\s+(?:my\s+|the\s+)?(?:second\s+brain|vault|obsidian))?$",
                body,
                flags=re.IGNORECASE,
            )
            if m_sec_nav:
                raw_sec_target = m_sec_nav.group(1).strip(" '\"")
                raw_sec_low = raw_sec_target.lower()
                wants_canvas = any(w in raw_sec_low for w in ("canvas", "ecosystem", "whiteboard", "map"))
                wants_base = any(w in raw_sec_low for w in ("base", "catalog", "database", "table"))
                cleaned_hub_q = re.sub(
                    r"\s+(?:section\s+hub|knowledge\s+hub|section|hub|live\s+base|live\s+catalog|catalog|base|database|table|ecosystem\s+canvas|ecosystem\s+map|ecosystem|canvas|whiteboard|map)$",
                    "",
                    raw_sec_low,
                ).strip()
                if len(cleaned_hub_q) >= 3:
                    discovered_secs = (self.index.discover_vault_structure().get("sections") or [])
                    for sec in discovered_secs:
                        sec_rel = str(sec.get("section_rel") or "")
                        sec_slug = sec_rel.rsplit("/", 1)[-1].lower().replace("_", " ")
                        sec_title = str(sec.get("title") or "").lower()
                        if (
                            cleaned_hub_q == sec_slug
                            or cleaned_hub_q == sec_title
                            or (len(cleaned_hub_q) >= 5 and cleaned_hub_q in sec_title)
                        ):
                            target_rel = str(sec.get("hub_index_rel") or "")
                            mode_lbl = "Hub MOC"
                            if wants_canvas and sec.get("canvas_rel"):
                                target_rel = str(sec["canvas_rel"])
                                mode_lbl = "Ecosystem Canvas"
                            elif wants_base and sec.get("base_rel"):
                                target_rel = str(sec["base_rel"])
                                mode_lbl = "Live .base Catalog"
                            if target_rel:
                                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                                cmds.append({"type": "open_note", "rel_path": target_rel})
                                notes.append(f"Opened `{sec.get('title')}` ({mode_lbl}) in Second Brain")
                                return cmds, notes, active_site_context

        # 9. YouTube, Highlights, Media, Known Websites & Natural Web Search
        media_cmds, media_notes, next_site = self._resolve_media_or_web_navigation(
            body,
            low,
            active_site_context=active_site_context,
            prior_turns=prior_turns,
            is_private_context=is_private_context,
            live_sports_hint_fn=live_sports_hint_fn,
        )
        if media_cmds:
            return media_cmds, media_notes, next_site

        # 10. Task Filtering inside Projects ("Filter tasks by CrewAI-Dev", "Show urgent tasks", "Clear filters")
        if re.search(r"\b(?:clear|reset)\s+(?:all\s+)?(?:task\s+)?filters\b", low):
            cmds.append({"type": "navigate_tab", "tab": "projects"})
            cmds.append({"type": "filter_projects_tasks", "keyword": "", "ai_agent": "ALL", "priority": 0})
            notes.append("Cleared all Projects task filters")
            return cmds, notes, active_site_context

        m_agent_filter = re.search(
            r"\b(?:filter|show)\s+tasks?\s+(?:assigned\s+to|by|for)\s+(CrewAI-Research|CrewAI-Dev|CrewAI-PM|Hermes-Agent|Hermes-Synthesizer|Gemma-4|Gemini-Pro|None)\b",
            body,
            flags=re.IGNORECASE,
        )
        if m_agent_filter:
            ag_canon = {
                "crewai-research": "CrewAI-Research",
                "crewai-dev": "CrewAI-Dev",
                "crewai-pm": "CrewAI-PM",
                "hermes-agent": "Hermes-Agent",
                "hermes-synthesizer": "Hermes-Synthesizer",
                "gemma-4": "Gemma-4",
                "gemini-pro": "Gemini-Pro",
                "none": "None",
            }[m_agent_filter.group(1).lower()]
            cmds.append({"type": "navigate_tab", "tab": "projects"})
            cmds.append({"type": "filter_projects_tasks", "ai_agent": ag_canon})
            notes.append(f"Filtered Projects tasks to AI Agent `{ag_canon}`")
            return cmds, notes, active_site_context

        if re.search(r"\b(?:show|filter)\s+(?:only\s+)?(urgent|high[-\s]+priority)\s+tasks?\b", low):
            prio_num = 1 if "urgent" in low else 2
            cmds.append({"type": "navigate_tab", "tab": "projects"})
            cmds.append({"type": "filter_projects_tasks", "priority": prio_num})
            notes.append(f"Filtered Projects tasks to Priority P{prio_num}")
            return cmds, notes, active_site_context

        # 11. Top-Level Non-Project Workspace Navigation (`Inbox`, `Second Brain`, `Browser`, `Paperclip`, `Settings`, `Assistant`)
        nav_verb = bool(
            re.match(
                r"^(?:go\s+to|open(?:\s+up)?|show(?:\s+me)?|switch\s+to|navigate\s+to|take\s+me\s+to|pull\s+up|bring\s+up|view|launch|display|verify|check(?:\s+out)?|look\s+at|head\s+to)\b",
                low,
            )
        )
        if nav_verb or low in (
            "inbox",
            "second brain",
            "my notes",
            "projects",
            "browser",
            "paperclip",
            "settings",
            "everything",
            "everything view",
            "kanban",
            "gantt",
            "rollup",
        ):
            if any(k in low for k in ("verify api", "api diagnostics", "check apis", "settings", "sync settings")):
                cmds.append({"type": "navigate_tab", "tab": "settings"})
                if "api" in low or "verify" in low:
                    cmds.append({"type": "trigger_api_verify", "live": "live" in low})
                    notes.append("Opened Settings & triggered `.env` API Diagnostics")
                else:
                    notes.append("Navigated to Settings & Sync")
                return cmds, notes, active_site_context

            if any(k in low for k in ("inbox", "00_inbox", "unprocessed captures", "triage hub")):
                cmds.append({"type": "navigate_tab", "tab": "inbox"})
                notes.append("Navigated to `00_Inbox` Triage Hub")
                return cmds, notes, active_site_context

            if any(
                k in low
                for k in (
                    "paperclip",
                    "crewai studio",
                    "hermes",
                    "hermes memory",
                    "hermes skills",
                    "agent locks",
                    "lock monitor",
                    "control plane",
                    "swarm hub",
                )
            ):
                cmds.append({"type": "navigate_tab", "tab": "paperclip"})
                notes.append("Navigated to Paperclip, CrewAI & Hermes Hub")
                return cmds, notes, active_site_context

            if re.search(r"\b(?:web\s+)?browser\b", low):
                cmds.append({"type": "navigate_tab", "tab": "browser"})
                notes.append("Navigated to Embedded Multi-Tab Browser")
                return cmds, notes, "browser"

            if any(k in low for k in ("second brain", "vault notes", "my notes", "knowledge base")):
                cmds.append({"type": "navigate_tab", "tab": "second-brain"})
                notes.append("Navigated to Second Brain (Canopy Vault)")
                return cmds, notes, active_site_context

            if any(k in low for k in ("assistant workspace", "full assistant", "full chat", "chat workspace", "sessions history")):
                cmds.append({"type": "navigate_tab", "tab": "assistant"})
                notes.append("Navigated to full KAIROS Assistant Workspace")
                return cmds, notes, active_site_context

            # 12. Projects Scope (`Everything`, `KAIROS`, `KAIROS_2_0`, Departments, Lists) + Sub-Views (`Board`, `Gantt`, `List`, `Calendar`, `Docs`, `Rollup`)
            matched_proj = self._match_project_name(low)
            matched_dept, matched_list, dept_label = self._match_department(low)
            matched_view, view_label = self._match_projects_subview(low)
            wants_everything = bool(re.search(r"\beverything(?:\s+view)?\b|\ball\s+projects\b", low))
            wants_projects_root = bool(
                re.match(
                    r"^(?:go\s+to\s+|open\s+|show(?:\s+me)?\s+|switch\s+to\s+|take\s+me\s+to\s+|pull\s+up\s+)?(?:my\s+)?projects(?:\s+workspace)?$",
                    low,
                )
            )
            wants_calendar_short = bool(
                not matched_view
                and re.match(
                    r"^(?:open|show(?:\s+me)?|pull\s+up|bring\s+up|check|take\s+me\s+to|go\s+to)\s+(?:my\s+|the\s+)?(?:calendar|schedule)$",
                    low,
                )
            )
            if wants_calendar_short:
                matched_view, view_label = "calendar", "Calendar View"

            if wants_everything or wants_projects_root or matched_proj or matched_dept or matched_view:
                cmds.append({"type": "navigate_tab", "tab": "projects"})
                if wants_everything or wants_projects_root:
                    cmds.append({"type": "select_project_scope", "project": "", "department": "", "list": ""})
                    notes.append("Opened Projects → Everything View")
                elif matched_proj or matched_dept:
                    eff_proj = matched_proj or current_project
                    eff_dept = matched_dept if matched_dept else ("" if matched_proj else current_department)
                    eff_list = matched_list if matched_list == "Fabrication_Swarm" else ""
                    cmds.append(
                        {
                            "type": "select_project_scope",
                            "project": eff_proj,
                            "department": eff_dept,
                            "list": eff_list,
                        }
                    )
                    scope_desc = eff_proj.replace("_", " ") if eff_proj else "All Projects"
                    if dept_label:
                        scope_desc += f" / {dept_label}"
                    notes.append(f"Selected Project Scope: {scope_desc}")

                if matched_view:
                    cmds.append({"type": "set_projects_view", "view": matched_view})
                    notes.append(f"Switched Projects view to {view_label}")

                return cmds, notes, active_site_context

        return [], [], active_site_context

    def resolve_utterance(
        self,
        prompt: str,
        *,
        current_project: str = "",
        current_department: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
        is_private_context: bool = False,
        live_sports_hint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Resolve single or multi-step spoken navigation utterances (`"Go to YouTube and pull up highlights of the game"`)."""
        clean_full = normalize_kairos_phonetics(prompt.strip())
        stripped_full = _strip_conversational_wrappers(clean_full)
        if not stripped_full or MUTATION_OR_QUESTION_GUARD_RE.match(stripped_full):
            return [], []

        parts = re.split(
            r"\s+(?:and\s+then\s+|then\s+|and\s+(?=(?:(?:please\s+|(?:can|could|would|will)\s+you\s+)?(?:switch|open|show|go\s+to|go\s+back|go\s+forward|go\s+home|reload|refresh|close|take\s+me|pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|cue\s+up|queue\s+up|filter|set|view|display|activate|turn|search|google|look\s+up|play|watch|find|browse|visit|clip|check))))|,\s*then\s+",
            clean_full,
            flags=re.IGNORECASE,
        )
        all_cmds: List[Dict[str, Any]] = []
        all_notes: List[str] = []
        running_proj = current_project
        running_dept = current_department
        running_site = ""

        for part in parts:
            c_list, n_list, running_site = self.resolve_clause(
                part,
                current_project=running_proj,
                current_department=running_dept,
                active_site_context=running_site,
                prior_turns=prior_turns,
                is_private_context=is_private_context,
                live_sports_hint_fn=live_sports_hint_fn,
            )
            if not c_list:
                # Only treat as pure deterministic navigation if every clause in the utterance resolved cleanly
                return [], []
            for cmd in c_list:
                if cmd.get("type") == "select_project_scope":
                    running_proj = str(cmd.get("project") or "")
                    running_dept = str(cmd.get("department") or "")
                all_cmds.append(cmd)
            all_notes.extend(n_list)

        # If a multi-clause command opened a root site ("Go to YouTube") and then searched on it ("pull up highlights"),
        # keep only the more specific action note so the spoken confirmation is concise.
        if len(all_notes) >= 2 and any("Opened YouTube (" in n for n in all_notes) and any("YouTube" in n for n in all_notes[1:]):
            all_notes = [n for n in all_notes if not n.startswith("Opened YouTube (`")]

        return deduplicate_ui_commands(all_cmds), all_notes

    def resolve_trailing_navigation(
        self,
        prompt: str,
        *,
        current_project: str = "",
        current_department: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
        is_private_context: bool = False,
        live_sports_hint_fn: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Extract a trailing spoken navigation clause from a hybrid question+nav prompt.

        Example: `"What's the score of the Browns game and can you pull up the highlights?"`
        answers the score via Live Sports/LLM AND returns Browser YouTube navigation commands!
        """
        clean_full = prompt.strip()
        if not clean_full:
            return [], []

        m_tail = re.search(
            r"(?:,\s*and\s+|\s+and\s+then\s+|\s+and\s+|;\s*|\?\s+)"
            r"((?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
            r"(?:please\s+)?"
            r"(?:(?:pull\s+up|pull\s+op|pull-up|bring\s+up|put\s+on|cue\s+up|queue\s+up|open(?:\s+up)?|show(?:\s+me)?|switch\s+to|go\s+to|take\s+me\s+to|navigate\s+to|watch|play|search|google|look\s+up|browse\s+to)\b.+|(?:go\s+back|go\s+forward|reload|refresh)\b.*))$",
            clean_full,
            flags=re.IGNORECASE,
        )
        if not m_tail:
            return [], []

        tail_clause = m_tail.group(1).strip()
        lead_clause = clean_full[: m_tail.start()].strip()
        enriched_turns = list(prior_turns or [])
        if lead_clause and not is_private_context and "#private" not in lead_clause.lower():
            enriched_turns.append({"role": "user", "content": lead_clause})

        return self.resolve_utterance(
            tail_clause,
            current_project=current_project,
            current_department=current_department,
            prior_turns=enriched_turns,
            is_private_context=is_private_context,
            live_sports_hint_fn=live_sports_hint_fn,
        )

    def build_spoken_navigation_summary(
        self,
        ui_commands: List[Dict[str, Any]],
        action_notes: List[str],
        *,
        fallback_project: str = "",
    ) -> str:
        """Build a concise, intelligent executive voice response summarizing what's on the screen."""
        target_tab = ""
        scoped_proj: Optional[str] = None
        scoped_dept: str = ""
        scoped_list: str = ""
        opened_task_id: str = ""
        opened_note_path: str = ""
        active_view: str = ""
        browser_nav_url: str = ""
        browser_nav_title: str = ""

        for cmd in ui_commands:
            ctype = cmd.get("type")
            if ctype == "navigate_tab":
                target_tab = str(cmd.get("tab") or "")
            elif ctype == "select_project_scope":
                scoped_proj = str(cmd.get("project") or "")
                scoped_dept = str(cmd.get("department") or "")
                scoped_list = str(cmd.get("list") or "")
            elif ctype == "set_projects_view":
                active_view = str(cmd.get("view") or "")
            elif ctype == "open_task_drawer":
                opened_task_id = str(cmd.get("task_id") or "")
            elif ctype == "open_note":
                opened_note_path = str(cmd.get("rel_path") or "")
            elif ctype == "browser_navigate":
                browser_nav_url = str(cmd.get("url") or "")
                browser_nav_title = str(cmd.get("title") or "")

        lead = " • ".join(action_notes) + "." if action_notes else "Navigation complete."

        if browser_nav_url:
            if "youtube.com/results" in browser_nav_url:
                clean_lbl = browser_nav_title.replace("▶ YouTube:", "").strip() or "your requested video"
                return f"{lead} Loaded **{clean_lbl}** on YouTube in the Browser."
            return lead

        if opened_task_id:
            try:
                p = self.vault.find_task_file(opened_task_id)
                nd = self.vault.read_note(self.vault.to_rel_path(p))
                fm = nd["frontmatter"]
                return (
                    f"{lead} Task `{opened_task_id}` is currently **{fm.get('status', 'To Do')}** "
                    f"(Priority P{fm.get('priority', 3)}, assigned to `{fm.get('ai_agent', 'None')}`)."
                )
            except Exception:
                return lead

        if target_tab == "projects" or scoped_proj is not None or active_view:
            eff_p = scoped_proj if scoped_proj is not None else fallback_project
            rollup = self.index.get_rollup(project=eff_p, department=scoped_dept, list_name=scoped_list)
            scope_title = (
                f"{eff_p.replace('_', ' ')}"
                + (f" / {scoped_dept.replace('_', ' ')}" if scoped_dept else "")
                if eff_p
                else "Everything View"
            )
            in_prog = rollup["by_status"].get("In Progress", 0)
            rev = rollup["by_status"].get("Review", 0)
            done = rollup["by_status"].get("Done", 0)
            return (
                f"{lead} **{scope_title}** is at **{rollup['progress_pct']}%** completion "
                f"({rollup['total_tasks']} total tasks: {done} Done, {in_prog} In Progress, {rev} in Review)."
            )

        if target_tab == "inbox":
            inbox_notes = self.index.search_vault(query="", folder="00_Inbox", limit=50)
            return f"{lead} You have **{len(inbox_notes)}** unprocessed item(s) ready for triage in `00_Inbox`."

        if target_tab == "paperclip":
            skills_dir = self.vault.vault_path / "04_Resources" / "Hermes" / "Skills"
            sk_count = len(list(skills_dir.glob("SKL-*.md"))) if skills_dir.is_dir() else 0
            return (
                f"{lead} Paperclip task locks, CrewAI dispatch, and Hermes Continuity "
                f"({sk_count} reusable skill{'s' if sk_count != 1 else ''}) are ready."
            )

        if opened_note_path:
            try:
                nd = self.vault.read_note(opened_note_path)
                priv_tag = " Privacy lock to Local Gemma 4 is active." if nd["is_private"] else ""
                return f"{lead}{priv_tag}"
            except Exception:
                return lead

        return lead
