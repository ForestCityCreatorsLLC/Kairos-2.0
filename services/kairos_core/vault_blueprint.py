"""State-of-the-Art Expandable Obsidian Vault Blueprint, `.base` Query Engine & JSON Canvas 1.0 Validator (`vault_blueprint.py`).

Implements official Obsidian specifications (`obsidian-markdown`, `obsidian-bases`, `json-canvas`):
1. Adaptable Domain Section Hubs (`_Hub_Index.md` MOC + typed Collection subfolders + reusable `_System/Templates/` templates).
2. Official Obsidian Bases (`.base`) YAML generator and safe `< 5ms` live filter/formula/view/summary evaluator.
3. Official JSON Canvas Spec 1.0 (`.canvas`) generator (16-char lowercase hex IDs, `group`/`file`/`text`/`link` nodes, validated `edges`) and normalizer.
4. Built-in Domain Blueprints (including **Music Studio, Plugins & Distribution** for plugins, add-ons, samples, support portals, and YouTube/Spotify/SoundCloud distribution) plus 100% custom/AI-inferred blueprints for any domain.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import yaml


def generate_canvas_hex_id(seed_index: Optional[int] = None) -> str:
    """Generate a JSON Canvas Spec 1.0 compliant 16-character lowercase hexadecimal ID."""
    if seed_index is not None:
        raw = uuid.uuid4().hex[:12]
        return f"{seed_index & 0xFFFF:04x}{raw}"
    return uuid.uuid4().hex[:16].lower()


def sanitize_vault_segment(raw: str, fallback: str = "General") -> str:
    """Normalize a folder or note slug into a clean, cross-platform Obsidian path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9_\- ]+", "", (raw or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_-")
    return cleaned[:64] or fallback


# ---------------------------------------------------------------------------
# 1. Adaptable Domain Blueprints + Custom Blueprint Synthesis
# ---------------------------------------------------------------------------

DOMAIN_BLUEPRINTS: Dict[str, Dict[str, Any]] = {
    "music_production": {
        "key": "music_production",
        "label": "Music Studio, Plugins & Distribution",
        "icon": "🎵",
        "default_parent": "04_Resources",
        "default_folder": "Music_Studio",
        "description": (
            "Centralized audio production hub for VST/AU plug-ins, expansions/add-ons, sample packs, "
            "vendor support portals, and online release distribution across YouTube, Spotify, SoundCloud, and DSPs."
        ),
        "schema_fields": [
            "category",
            "vendor",
            "format",
            "version",
            "platform",
            "status",
            "support_url",
            "dashboard_url",
        ],
        "collections": [
            {
                "folder": "Plugins",
                "title": "Plug-ins & Virtual Instruments",
                "icon": "🎛️",
                "item_type": "plugin",
                "description": "Synths, EQs, compressors, mastering suites, formats (VST3/AU/AAX), versions & license portals.",
                "fields": ["category", "vendor", "format", "version", "license_status", "support_url", "download_url"],
            },
            {
                "folder": "Addons_and_Presets",
                "title": "Add-ons, Presets & Expansions",
                "icon": "🧩",
                "item_type": "addon",
                "description": "Synth preset banks, Kontakt libraries, MIDI packs, impulse responses & DAW scripts.",
                "fields": ["parent_plugin", "category", "vendor", "version", "support_url", "install_path"],
            },
            {
                "folder": "Samples_and_Packs",
                "title": "Samples, Stems & Drum Kits",
                "icon": "🥁",
                "item_type": "sample_pack",
                "description": "Drum kits, vocal chops, melodic loops, foley, BPM/key metadata & sample subscriptions.",
                "fields": ["category", "genre", "bpm_range", "key_signature", "vendor", "support_url", "local_path"],
            },
            {
                "folder": "Support_and_Websites",
                "title": "Support Portals & Music Websites",
                "icon": "🌐",
                "item_type": "support_portal",
                "description": "License managers (iLok, Native Access, Splice), support desks, manuals & download hubs.",
                "fields": ["category", "vendor", "support_url", "dashboard_url", "installer_app", "status"],
            },
            {
                "folder": "Distribution",
                "title": "Online Distribution & Streaming Setup",
                "icon": "📡",
                "item_type": "distribution_platform",
                "description": "Release specs, loudness targets, artwork dimensions, ISRC/splits & upload checklists for YouTube, Spotify, SoundCloud & aggregators.",
                "fields": ["platform", "category", "support_url", "dashboard_url", "audio_spec", "artwork_spec", "status"],
            },
        ],
        "external_links": [
            {"label": "YouTube Studio", "url": "https://studio.youtube.com"},
            {"label": "Spotify for Artists", "url": "https://artists.spotify.com"},
            {"label": "SoundCloud Creators", "url": "https://artists.soundcloud.com"},
            {"label": "Splice Sounds & Plugins", "url": "https://splice.com"},
        ],
        "starter_entries": [
            {
                "collection": "Distribution",
                "title": "YouTube Music & Official Artist Channel Setup",
                "frontmatter": {
                    "type": "distribution_platform",
                    "platform": "YouTube",
                    "category": "Streaming & Video Distribution",
                    "status": "Active",
                    "support_url": "https://support.google.com/youtube",
                    "dashboard_url": "https://studio.youtube.com",
                    "audio_spec": "24-bit / 48 kHz WAV (-14 LUFS integrated, -1.0 dBTP)",
                    "artwork_spec": "3000x3000 px Art Track + 1920x1080 16:9 Video / 1080x1920 Shorts",
                    "tags": ["music", "distribution", "youtube"],
                },
                "body": (
                    "# 📺 YouTube Music & Official Artist Channel Setup\n\n"
                    "> [!important] Mastering & Delivery Spec\n"
                    "> Export **24-bit / 48 kHz uncompressed WAV** targeting **-14 LUFS integrated** and **-1.0 dB True Peak** to prevent YouTube loudness normalization clipping.\n\n"
                    "## Quick Portals\n"
                    "- **Creator Dashboard:** [YouTube Studio](https://studio.youtube.com)\n"
                    "- **Artist Support & OAC Claiming:** [YouTube Help Center](https://support.google.com/youtube)\n"
                    "- **YouTube for Artists:** [artists.youtube](https://artists.youtube)\n\n"
                    "## Release & Monetization Checklist\n"
                    "- [ ] Link distributor Art Track channel with primary YouTube channel for **Official Artist Channel (OAC)** badge\n"
                    "- [ ] Configure Content ID opt-in policy & allowlist collaborator channels\n"
                    "- [ ] Upload 4K/1080p visualizer + 9:16 YouTube Short teaser with pinned streaming links\n"
                    "- [ ] Verify ISRC, songwriter credits, lyrics, and chapter timestamps in description\n"
                ),
            },
            {
                "collection": "Distribution",
                "title": "Spotify for Artists & Release Pipeline",
                "frontmatter": {
                    "type": "distribution_platform",
                    "platform": "Spotify",
                    "category": "DSP Streaming Distribution",
                    "status": "Active",
                    "support_url": "https://support.spotify.com/us/artists/",
                    "dashboard_url": "https://artists.spotify.com",
                    "audio_spec": "24-bit / 44.1-48 kHz WAV or FLAC (-14 LUFS, -1.0 dBTP)",
                    "artwork_spec": "3000x3000 px RGB PNG/JPG + 9:16 Spotify Canvas (3-8s MP4)",
                    "tags": ["music", "distribution", "spotify"],
                },
                "body": (
                    "# 🟢 Spotify for Artists & Release Pipeline\n\n"
                    "> [!tip] Editorial Playlist Pitch Window\n"
                    "> Submit upcoming releases via **Spotify for Artists** at least **7–14 days prior to release day** so tracks qualify for editorial consideration and Release Radar.\n\n"
                    "## Quick Portals\n"
                    "- **Artist Portal:** [Spotify for Artists](https://artists.spotify.com)\n"
                    "- **Support & Loudness FAQ:** [Spotify Artist Support](https://support.spotify.com/us/artists/)\n\n"
                    "## Release Setup Checklist\n"
                    "- [ ] Deliver 24-bit WAV master + 3000x3000 px cover art via aggregator (DistroKid / TuneCore / CD Baby / Symphonic)\n"
                    "- [ ] Upload looping 3–8s vertical **Spotify Canvas** (1080x1920 MP4, no URL overlays)\n"
                    "- [ ] Pitch primary track metadata (genre, mood, instrumentation, hometown, story) in Spotify for Artists\n"
                    "- [ ] Sync time-coded lyrics (Musixmatch) and update Artist Pick + Merch/Bio links\n"
                ),
            },
            {
                "collection": "Distribution",
                "title": "SoundCloud Next Pro & Creator Distribution",
                "frontmatter": {
                    "type": "distribution_platform",
                    "platform": "SoundCloud",
                    "category": "Direct Upload & Fan-Powered Royalties",
                    "status": "Active",
                    "support_url": "https://help.soundcloud.com",
                    "dashboard_url": "https://artists.soundcloud.com",
                    "audio_spec": "Lossless 24-bit / 48 kHz WAV (-14 to -9 LUFS, -1.0 dBTP)",
                    "artwork_spec": "3000x3000 px Track Art + 2480x520 Profile Banner",
                    "tags": ["music", "distribution", "soundcloud"],
                },
                "body": (
                    "# 🟠 SoundCloud Next Pro & Creator Distribution\n\n"
                    "> [!note] Lossless Streaming & File Replacement\n"
                    "> Always upload uncompressed **WAV/FLAC** masters. SoundCloud Next Pro supports replacing audio masters in-place without losing play counts or timed comments.\n\n"
                    "## Quick Portals\n"
                    "- **SoundCloud for Artists (Monetization & Splits):** [artists.soundcloud.com](https://artists.soundcloud.com)\n"
                    "- **Direct Upload:** [soundcloud.com/upload](https://soundcloud.com/upload)\n"
                    "- **Help & Copyright Support:** [SoundCloud Help Center](https://help.soundcloud.com)\n\n"
                    "## Setup & Release Checklist\n"
                    "- [ ] Configure Fan-Powered Royalties & payout tax profile in SoundCloud for Artists\n"
                    "- [ ] Set custom permalink slug, genre tags, ISRC code, and Buy/Pre-save external link\n"
                    "- [ ] Enable mastered file replacement if updating mixdowns post-release\n"
                    "- [ ] Submit new uploads to First Fans / Repost Exchange discovery queue\n"
                ),
            },
            {
                "collection": "Support_and_Websites",
                "title": "Master Plug-in Managers & Support Directory",
                "frontmatter": {
                    "type": "support_portal",
                    "category": "License & Installer Portals",
                    "vendor": "Multi-Vendor",
                    "status": "Active",
                    "support_url": "https://www.ilok.com",
                    "dashboard_url": "https://splice.com",
                    "installer_app": "iLok License Manager / Native Access / Splice",
                    "tags": ["music", "plugins", "support-websites"],
                },
                "body": (
                    "# 🌐 Master Plug-in Managers & Support Directory\n\n"
                    "> [!info] Studio Recovery & License Hub\n"
                    "> Keep vendor support portals, installer apps, and activation methods indexed here so machine migrations and plugin updates take minutes.\n\n"
                    "| Ecosystem / Vendor | Support & Account Website | Installer / License App | Notes |\n"
                    "| :--- | :--- | :--- | :--- |\n"
                    "| **Pace iLok** | [ilok.com](https://www.ilok.com) | iLok License Manager | Cloud & machine activations |\n"
                    "| **Splice** | [splice.com](https://splice.com) | Splice Desktop | Rent-to-Own plugins & sample library |\n"
                    "| **Native Instruments** | [native-instruments.com/support](https://support.native-instruments.com) | Native Access 2 | Kontakt, Komplete & NKS expansions |\n"
                    "| **Plugin Boutique** | [pluginboutique.com](https://www.pluginboutique.com) | My Account Vault | Cross-vendor serials & updates |\n"
                    "| **Xfer Records** | [xferrecords.com](https://xferrecords.com) | Direct Account Download | Serum, OTT, LFO Tool |\n"
                    "| **FabFilter** | [fabfilter.com/support](https://www.fabfilter.com/support) | Account License Key | Pro-Q, Pro-L, Pro-C, Saturn |\n"
                ),
            },
        ],
    },
    "creator_media": {
        "key": "creator_media",
        "label": "Creator & Media Production Hub",
        "icon": "🎬",
        "default_parent": "04_Resources",
        "default_folder": "Creator_Media",
        "description": "Video editing assets, LUTs, SFX, camera/lighting setups, tool portals, and multi-channel publishing specs.",
        "schema_fields": ["category", "platform", "format", "vendor", "status", "support_url"],
        "collections": [
            {
                "folder": "Assets_and_Templates",
                "title": "LUTs, Motion Graphics & Presets",
                "icon": "🎨",
                "item_type": "media_asset",
                "description": "Color grading LUTs, title templates, transitions, overlays & sound effects.",
                "fields": ["category", "format", "vendor", "support_url", "local_path"],
            },
            {
                "folder": "Gear_and_Rig",
                "title": "Cameras, Audio & Studio Rig",
                "icon": "📷",
                "item_type": "gear",
                "description": "Camera bodies, lenses, microphones, capture cards, firmware & settings.",
                "fields": ["category", "vendor", "version", "support_url", "status"],
            },
            {
                "folder": "Publishing_Channels",
                "title": "Publishing Platforms & Specs",
                "icon": "📡",
                "item_type": "channel_spec",
                "description": "Export bitrates, aspect ratios, thumbnails & upload checklists across YouTube, TikTok, Instagram & Podcast RSS.",
                "fields": ["platform", "category", "format", "support_url", "dashboard_url", "status"],
            },
        ],
        "external_links": [
            {"label": "YouTube Studio", "url": "https://studio.youtube.com"},
        ],
        "starter_entries": [],
    },
    "hardware_lab": {
        "key": "hardware_lab",
        "label": "Hardware, Fabrication & Electronics Lab",
        "icon": "🛠️",
        "default_parent": "04_Resources",
        "default_folder": "Hardware_Lab",
        "description": "Machines, 3D printer slicer profiles, MCUs/electronics BOM, vendor portals, and maintenance SOPs.",
        "schema_fields": ["category", "vendor", "model", "status", "support_url", "firmware"],
        "collections": [
            {
                "folder": "Machines_and_Profiles",
                "title": "Machines & Slicer Profiles",
                "icon": "⚙️",
                "item_type": "machine",
                "description": "Printers, CNCs, Klipper/Moonraker configs, nozzle/filament profiles & calibration.",
                "fields": ["category", "vendor", "model", "firmware", "support_url", "status"],
            },
            {
                "folder": "Components_and_BOM",
                "title": "Components, Filaments & Parts",
                "icon": "🔩",
                "item_type": "component",
                "description": "Sensors, microcontrollers, filaments, fasteners, datasheets & reorder URLs.",
                "fields": ["category", "vendor", "part_number", "support_url", "status"],
            },
            {
                "folder": "Vendor_and_Support_Sites",
                "title": "Suppliers & Technical Portals",
                "icon": "🌐",
                "item_type": "support_portal",
                "description": "Datasheet portals, CAD repositories, firmware wikis & supplier accounts.",
                "fields": ["category", "vendor", "support_url", "dashboard_url", "status"],
            },
        ],
        "external_links": [],
        "starter_entries": [],
    },
    "research_library": {
        "key": "research_library",
        "label": "Research, AI Models & Reference Library",
        "icon": "🔬",
        "default_parent": "04_Resources",
        "default_folder": "Research_Library",
        "description": "Structured knowledge base for papers, SDK documentation, local AI models, datasets, and benchmarks.",
        "schema_fields": ["category", "source", "status", "support_url", "rating"],
        "collections": [
            {
                "folder": "Papers_and_Articles",
                "title": "Papers, Guides & Deep Dives",
                "icon": "📄",
                "item_type": "reference",
                "description": "Annotated research papers, architecture notes & technical breakdowns.",
                "fields": ["category", "author", "year", "support_url", "status"],
            },
            {
                "folder": "Tools_and_APIs",
                "title": "SDKs, Models & Web Portals",
                "icon": "🧪",
                "item_type": "tool_reference",
                "description": "Libraries, model weights, API docs, benchmarks & support websites.",
                "fields": ["category", "vendor", "version", "support_url", "status"],
            },
        ],
        "external_links": [],
        "starter_entries": [],
    },
    "business_crm": {
        "key": "business_crm",
        "label": "Vendors, SaaS Stack & Partner Directory",
        "icon": "🤝",
        "default_parent": "01_Business",
        "default_folder": "Vendors_and_Partners",
        "description": "Operational directory of software subscriptions, vendor support portals, partners, and fulfillment workflows.",
        "schema_fields": ["category", "vendor", "status", "support_url", "dashboard_url"],
        "collections": [
            {
                "folder": "SaaS_and_Tools",
                "title": "Software Stack & Portals",
                "icon": "💻",
                "item_type": "saas_tool",
                "description": "Active platforms, support URLs, admin dashboards & renewal notes.",
                "fields": ["category", "vendor", "plan", "support_url", "dashboard_url", "status"],
            },
            {
                "folder": "Partners_and_Suppliers",
                "title": "Partners, Print-on-Demand & Suppliers",
                "icon": "📦",
                "item_type": "partner",
                "description": "Fulfillment partners, contacts, SLA specs & support desks.",
                "fields": ["category", "vendor", "contact", "support_url", "status"],
            },
        ],
        "external_links": [],
        "starter_entries": [],
    },
}


def list_blueprint_catalog() -> List[Dict[str, Any]]:
    """Return lightweight metadata for all built-in domain blueprints for UI & AI discovery."""
    out: List[Dict[str, Any]] = []
    for key, spec in DOMAIN_BLUEPRINTS.items():
        out.append(
            {
                "key": key,
                "label": spec["label"],
                "icon": spec["icon"],
                "default_parent": spec["default_parent"],
                "default_folder": spec["default_folder"],
                "description": spec["description"],
                "schema_fields": list(spec["schema_fields"]),
                "collections": [
                    {
                        "folder": c["folder"],
                        "title": c["title"],
                        "icon": c["icon"],
                        "item_type": c["item_type"],
                        "description": c["description"],
                        "fields": list(c["fields"]),
                    }
                    for c in spec["collections"]
                ],
            }
        )
    return out


def infer_blueprint_key_from_text(text: str) -> str:
    """Infer the closest domain blueprint key from natural language (falls back to `'custom'`)."""
    low = (text or "").lower()
    if any(
        kw in low
        for kw in (
            "music",
            "plugin",
            "plug-in",
            "vst",
            "sample",
            "daw",
            "spotify",
            "soundcloud",
            "audio",
            "synth",
            "beat",
            "mastering",
        )
    ):
        return "music_production"
    if any(kw in low for kw in ("video", "film", "camera", "lut", "creator", "podcast", "editing")):
        return "creator_media"
    if any(kw in low for kw in ("hardware", "3d print", "klipper", "cnc", "electronics", "filament", "maker")):
        return "hardware_lab"
    if any(kw in low for kw in ("research", "paper", "literature", "study", "dataset", "benchmark")):
        return "research_library"
    if any(kw in low for kw in ("crm", "vendor", "partner", "client", "supplier", "saas stack")):
        return "business_crm"
    return "custom"


def resolve_section_blueprint(
    *,
    section_name: str,
    blueprint_key: str = "auto",
    parent_folder: str = "",
    icon: str = "",
    description: str = "",
    collections: Optional[Sequence[Any]] = None,
    schema_fields: Optional[Sequence[str]] = None,
    external_links: Optional[Sequence[Dict[str, str]]] = None,
    seed_starters: bool = True,
) -> Dict[str, Any]:
    """Synthesize a complete Section Hub specification from a preset blueprint, custom user args, or a hybrid of both."""
    eff_key = (blueprint_key or "auto").strip().lower()
    if eff_key in ("", "auto"):
        eff_key = infer_blueprint_key_from_text(f"{section_name} {description}")

    preset = DOMAIN_BLUEPRINTS.get(eff_key)
    raw_title = (section_name or (preset["label"] if preset else "Knowledge Hub")).strip()
    if preset and (not section_name.strip() or section_name.strip().lower() == preset["label"].lower()):
        folder_slug = sanitize_vault_segment(preset["default_folder"], fallback="Knowledge_Hub")
    else:
        folder_slug = sanitize_vault_segment(
            section_name or (preset["default_folder"] if preset else "Knowledge_Hub"),
            fallback="Knowledge_Hub",
        )
    eff_parent = (parent_folder if parent_folder is not None else "").strip().strip("/\\")
    if not eff_parent and preset:
        eff_parent = preset["default_parent"]
    elif not eff_parent:
        eff_parent = "04_Resources"

    if eff_parent.lower() in ("root", ".", "/"):
        section_rel = folder_slug
    elif folder_slug.lower().startswith(f"{eff_parent.lower()}/"):
        section_rel = folder_slug.replace("\\", "/").strip("/")
    else:
        section_rel = f"{eff_parent}/{folder_slug}".replace("\\", "/").strip("/")

    eff_icon = (icon or (preset["icon"] if preset else "🧩")).strip() or "🧩"
    eff_desc = (
        description.strip()
        or (preset["description"] if preset else f"Structured Obsidian knowledge hub for {raw_title}.")
    )

    resolved_collections: List[Dict[str, Any]] = []
    if collections:
        for idx, raw_col in enumerate(collections):
            if isinstance(raw_col, str):
                c_title = raw_col.strip()
                if not c_title:
                    continue
                c_slug = sanitize_vault_segment(c_title, fallback=f"Collection_{idx + 1}")
                resolved_collections.append(
                    {
                        "folder": c_slug,
                        "title": c_title.replace("_", " "),
                        "icon": "📂",
                        "item_type": c_slug.lower().rstrip("s") or "entry",
                        "description": f"Structured `{c_title.replace('_', ' ')}` notes and links for {raw_title}.",
                        "fields": list(schema_fields or ["category", "status", "vendor", "support_url"]),
                    }
                )
            elif isinstance(raw_col, dict):
                c_title = str(raw_col.get("title") or raw_col.get("folder") or f"Collection {idx + 1}").strip()
                c_slug = sanitize_vault_segment(str(raw_col.get("folder") or c_title), fallback=f"Collection_{idx + 1}")
                resolved_collections.append(
                    {
                        "folder": c_slug,
                        "title": c_title.replace("_", " "),
                        "icon": str(raw_col.get("icon") or "📂"),
                        "item_type": sanitize_vault_segment(
                            str(raw_col.get("item_type") or c_slug.lower().rstrip("s") or "entry"),
                            fallback="entry",
                        ).lower(),
                        "description": str(
                            raw_col.get("description")
                            or f"Structured `{c_title.replace('_', ' ')}` notes for {raw_title}."
                        ),
                        "fields": [
                            sanitize_vault_segment(str(f), fallback="field").lower()
                            for f in (raw_col.get("fields") or schema_fields or ["category", "status", "support_url"])
                            if str(f).strip()
                        ],
                    }
                )

    if not resolved_collections:
        if preset:
            resolved_collections = [dict(c, fields=list(c["fields"])) for c in preset["collections"]]
        else:
            resolved_collections = [
                {
                    "folder": "Catalog",
                    "title": "Core Catalog & Inventory",
                    "icon": "📦",
                    "item_type": "catalog_item",
                    "description": f"Primary items, tools, and structured entries in {raw_title}.",
                    "fields": ["category", "vendor", "version", "status", "support_url"],
                },
                {
                    "folder": "Resources_and_Portals",
                    "title": "Support Websites & Portals",
                    "icon": "🌐",
                    "item_type": "support_portal",
                    "description": f"Reference websites, documentation portals, and accounts for {raw_title}.",
                    "fields": ["category", "support_url", "dashboard_url", "status"],
                },
                {
                    "folder": "Guides_and_Workflows",
                    "title": "Setup Guides & Workflows",
                    "icon": "📘",
                    "item_type": "workflow_guide",
                    "description": f"Step-by-step checklists, distribution/publishing specs, and SOPs for {raw_title}.",
                    "fields": ["category", "platform", "status", "support_url"],
                },
            ]

    merged_fields: List[str] = []
    for f in (schema_fields or (preset["schema_fields"] if preset else ["category", "status", "support_url"])):
        clean_f = sanitize_vault_segment(str(f), fallback="").lower()
        if clean_f and clean_f not in merged_fields:
            merged_fields.append(clean_f)
    for col in resolved_collections:
        for cf in col.get("fields", []):
            clean_cf = sanitize_vault_segment(str(cf), fallback="").lower()
            if clean_cf and clean_cf not in merged_fields:
                merged_fields.append(clean_cf)

    eff_links = list(external_links) if external_links else list(preset.get("external_links", []) if preset else [])
    starters = list(preset.get("starter_entries", [])) if (preset and seed_starters) else []

    return {
        "blueprint_key": eff_key if preset else "custom",
        "title": raw_title,
        "folder_slug": folder_slug,
        "parent_folder": eff_parent,
        "section_rel": section_rel,
        "icon": eff_icon,
        "description": eff_desc,
        "schema_fields": merged_fields,
        "collections": resolved_collections,
        "external_links": eff_links,
        "starter_entries": starters,
    }


# ---------------------------------------------------------------------------
# 2. Official Obsidian Bases (`.base`) Generator & Safe Live Evaluator
# ---------------------------------------------------------------------------

def build_master_vault_base_yaml() -> str:
    """Build `_System/Dashboards/Vault_Master_Catalog.base` adhering strictly to Obsidian Bases YAML syntax."""
    base_doc: Dict[str, Any] = {
        "filters": {
            "and": [
                'file.ext == "md"',
                {
                    "not": [
                        'file.inFolder("05_Archives")',
                        'file.inFolder("01_Business/KAIROS_Sessions")',
                    ]
                },
            ]
        },
        "formulas": {
            "days_since_update": "(now() - file.mtime).days.round(0)",
            "kind_badge": 'if(type == "section_hub", "🧩 Hub", if(type == "task", "🎯 Task", "📝 Note"))',
        },
        "properties": {
            "type": {"displayName": "Type"},
            "status": {"displayName": "Status"},
            "category": {"displayName": "Category"},
            "support_url": {"displayName": "Support URL"},
            "formula.kind_badge": {"displayName": "Kind"},
            "formula.days_since_update": {"displayName": "Days Ago"},
        },
        "views": [
            {
                "type": "table",
                "name": "Section Hubs & MOCs",
                "filters": {"and": ['type == "section_hub"']},
                "order": ["file.name", "icon", "domain", "status", "file.folder"],
            },
            {
                "type": "table",
                "name": "All Active Notes",
                "limit": 80,
                "order": [
                    "file.name",
                    "formula.kind_badge",
                    "type",
                    "category",
                    "status",
                    "support_url",
                    "file.folder",
                ],
            },
            {
                "type": "table",
                "name": "Active Project Tasks",
                "filters": {"and": ['type == "task"', 'status != "Done"']},
                "order": ["file.name", "status", "priority", "project", "department", "due_date"],
            },
        ],
    }
    return yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def build_section_base_yaml(spec: Dict[str, Any]) -> str:
    """Build a spec-compliant Obsidian `.base` database for any Section Hub (`table` + `cards` + per-collection views)."""
    section_rel = spec["section_rel"]
    schema_fields: List[str] = list(spec.get("schema_fields") or ["category", "status", "support_url"])
    primary_cols = ["file.name"]
    for candidate in schema_fields[:6]:
        if candidate not in primary_cols:
            primary_cols.append(candidate)
    if "formula.status_badge" not in primary_cols:
        primary_cols.append("formula.status_badge")

    properties_cfg: Dict[str, Dict[str, str]] = {
        "formula.status_badge": {"displayName": "State"},
        "formula.days_since_update": {"displayName": "Updated (d)"},
    }
    for f_name in schema_fields:
        pretty = f_name.replace("_url", " URL").replace("_", " ").title().replace("Url", "URL")
        properties_cfg[f_name] = {"displayName": pretty}

    views: List[Dict[str, Any]] = [
        {
            "type": "table",
            "name": f"All {spec['title']} Items",
            "order": primary_cols,
            "summaries": {
                schema_fields[0] if schema_fields else "type": "Filled",
            },
        },
        {
            "type": "cards",
            "name": "Cards Gallery",
            "order": primary_cols[:5],
        },
    ]

    for col in spec.get("collections", []):
        col_folder = f"{section_rel}/{col['folder']}"
        col_order = ["file.name"] + [f for f in col.get("fields", [])[:6]]
        views.append(
            {
                "type": "table",
                "name": f"{col['icon']} {col['title']}",
                "filters": {
                    "and": [
                        f'file.inFolder("{col_folder}")',
                    ]
                },
                "order": col_order,
            }
        )

    base_doc: Dict[str, Any] = {
        "filters": {
            "and": [
                f'file.inFolder("{section_rel}")',
                'file.ext == "md"',
                {
                    "not": [
                        'file.basename.startsWith("_")',
                    ]
                },
            ]
        },
        "formulas": {
            "status_badge": 'if(status == "Active", "✅ Active", if(status, status, "📦 Indexed"))',
            "days_since_update": "(now() - file.mtime).days.round(0)",
        },
        "properties": properties_cfg,
        "views": views,
    }
    return yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def build_project_tasks_base_yaml(project_name: str) -> str:
    """Build an official Obsidian `.base` YAML database for `02_Projects/<Project>/Docs/Project_Tasks.base`."""
    safe_proj = sanitize_vault_segment(project_name, fallback="KAIROS_2_0")
    proj_folder = f"02_Projects/{safe_proj}"
    base_doc: Dict[str, Any] = {
        "filters": {
            "and": [
                f'file.inFolder("{proj_folder}")',
                'file.ext == "md"',
            ]
        },
        "formulas": {
            "priority_badge": 'if(priority == 1, "🔴 P1 Urgent", if(priority == 2, "🟠 P2 High", if(priority == 3, "🔵 P3 Normal", "⚪ P4 Low")))',
            "days_until_due": "(date(due_date) - today()).days",
            "days_since_update": "(now() - file.mtime).days.round(0)",
        },
        "properties": {
            "status": {"displayName": "Status"},
            "formula.priority_badge": {"displayName": "Priority"},
            "department": {"displayName": "Department"},
            "list": {"displayName": "List"},
            "ai_agent": {"displayName": "AI Agent"},
            "due_date": {"displayName": "Due Date"},
            "formula.days_until_due": {"displayName": "Due (d)"},
            "time_estimate_hrs": {"displayName": "Est (h)"},
            "time_logged_hrs": {"displayName": "Logged (h)"},
            "formula.days_since_update": {"displayName": "Updated (d)"},
        },
        "views": [
            {
                "type": "table",
                "name": "All Project Tasks",
                "filters": {
                    "and": [
                        'type == "task" || type == "subtask"',
                    ]
                },
                "order": [
                    "file.name",
                    "status",
                    "formula.priority_badge",
                    "department",
                    "list",
                    "ai_agent",
                    "due_date",
                    "formula.days_until_due",
                    "time_estimate_hrs",
                    "time_logged_hrs",
                ],
                "summaries": {
                    "time_estimate_hrs": "Sum",
                    "time_logged_hrs": "Sum",
                    "status": "Unique",
                },
            },
            {
                "type": "table",
                "name": "Active Sprint",
                "filters": {
                    "and": [
                        'type == "task" || type == "subtask"',
                        'status != "Done"',
                    ]
                },
                "order": [
                    "file.name",
                    "status",
                    "formula.priority_badge",
                    "department",
                    "ai_agent",
                    "due_date",
                    "time_estimate_hrs",
                ],
                "summaries": {
                    "time_estimate_hrs": "Sum",
                },
            },
            {
                "type": "table",
                "name": "Project Wiki & Docs",
                "filters": {
                    "and": [
                        'type != "task"',
                        'type != "subtask"',
                    ]
                },
                "order": [
                    "file.name",
                    "type",
                    "category",
                    "formula.days_since_update",
                    "file.folder",
                ],
            },
        ],
    }
    return yaml.safe_dump(base_doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _parse_iso_date_safe(val: Any) -> Optional[date]:
    if not val:
        return None
    s = str(val).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _split_top_level_logical(expr: str, op: str) -> List[str]:
    """Split a filter string on top-level `&&` or `||` outside quotes and parentheses."""
    parts: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    buf: List[str] = []
    i = 0
    op_len = len(op)
    while i < len(expr):
        ch = expr[i]
        if in_quote:
            buf.append(ch)
            if ch == in_quote and (i == 0 or expr[i - 1] != "\\"):
                in_quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and expr[i : i + op_len] == op:
            parts.append("".join(buf).strip())
            buf = []
            i += op_len
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _unquote_literal(raw: str) -> Any:
    s = raw.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return ""
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _resolve_record_value(prop_expr: str, rec: Dict[str, Any]) -> Any:
    p = prop_expr.strip()
    fm = rec.get("frontmatter") or {}
    if p == "file.name":
        return rec["file_name"]
    if p == "file.basename":
        return rec["file_basename"]
    if p == "file.path":
        return rec["rel_path"]
    if p == "file.folder":
        return rec["file_folder"]
    if p == "file.ext":
        return rec["file_ext"]
    if p == "file.size":
        return rec.get("file_size", 0)
    if p in ("file.mtime", "file.ctime"):
        return datetime.fromtimestamp(float(rec.get("mtime") or 0.0)).strftime("%Y-%m-%d")
    if p == "file.tags":
        return rec.get("tags") or []
    if p == "file.links":
        return rec.get("wikilinks") or []
    if p.startswith("note."):
        p = p[5:]
    if p in fm:
        return fm[p]
    if p == "title":
        return rec.get("title", "")
    if p == "type":
        return rec.get("type", "")
    return ""


def _eval_single_filter_expr(expr: str, rec: Dict[str, Any]) -> bool:
    s = (expr or "").strip()
    if not s:
        return True

    # Logical OR / AND precedence
    or_parts = _split_top_level_logical(s, "||")
    if len(or_parts) > 1:
        return any(_eval_single_filter_expr(p, rec) for p in or_parts)

    and_parts = _split_top_level_logical(s, "&&")
    if len(and_parts) > 1:
        return all(_eval_single_filter_expr(p, rec) for p in and_parts)

    if s.startswith("(") and s.endswith(")"):
        return _eval_single_filter_expr(s[1:-1], rec)

    if s.startswith("!"):
        return not _eval_single_filter_expr(s[1:], rec)

    # Built-in Obsidian Bases `file.*` predicates
    m_folder = re.match(r'^file\.inFolder\(\s*["\']([^"\']+)["\']\s*\)$', s)
    if m_folder:
        target_fld = m_folder.group(1).strip().strip("/").lower()
        rec_fld = str(rec["file_folder"]).strip("/").lower()
        return rec_fld == target_fld or rec_fld.startswith(f"{target_fld}/")

    m_tag = re.match(r'^file\.hasTag\(\s*["\']([^"\']+)["\']\s*\)$', s)
    if m_tag:
        want = m_tag.group(1).strip().lstrip("#").lower()
        tags_low = [str(t).lstrip("#").lower() for t in (rec.get("tags") or [])]
        return any(t == want or t.startswith(f"{want}/") for t in tags_low)

    m_link = re.match(r'^file\.hasLink\(\s*["\']([^"\']+)["\']\s*\)$', s)
    if m_link:
        want_lnk = m_link.group(1).strip().lower()
        links_low = [str(l).strip().lower() for l in (rec.get("wikilinks") or [])]
        return any(want_lnk == l or l.endswith(f"/{want_lnk}") for l in links_low)

    m_starts = re.match(r'^(file\.(?:name|basename|path|folder))\.startsWith\(\s*["\']([^"\']*)["\']\s*\)$', s)
    if m_starts:
        val = str(_resolve_record_value(m_starts.group(1), rec) or "")
        return val.startswith(m_starts.group(2))

    m_contains = re.match(r'^([A-Za-z0-9_.]+)\.contains\(\s*["\']([^"\']*)["\']\s*\)$', s)
    if m_contains:
        val = _resolve_record_value(m_contains.group(1), rec)
        needle = m_contains.group(2).lower()
        if isinstance(val, list):
            return any(needle in str(x).lower() for x in val)
        return needle in str(val or "").lower()

    m_regex = re.match(r"^/(.+)/\.matches\(\s*([A-Za-z0-9_.]+)\s*\)$", s)
    if m_regex:
        val = str(_resolve_record_value(m_regex.group(2), rec) or "")
        try:
            return bool(re.search(m_regex.group(1), val))
        except re.error:
            return False

    # Binary comparison operators (`==`, `!=`, `>=`, `<=`, `>`, `<`)
    for op in ("==", "!=", ">=", "<=", ">", "<"):
        parts = _split_top_level_logical(s, op)
        if len(parts) == 2:
            lhs_raw, rhs_raw = parts[0], parts[1]
            lhs_val = _resolve_record_value(lhs_raw, rec)
            rhs_val = (
                date.today().isoformat()
                if rhs_raw.strip() == "today()"
                else _unquote_literal(rhs_raw)
            )
            if lhs_raw.strip().startswith("date(") and lhs_raw.strip().endswith(")"):
                inner_prop = lhs_raw.strip()[5:-1].strip()
                lhs_val = str(_resolve_record_value(inner_prop, rec) or "")[:10]

            if op == "==":
                return str(lhs_val).lower() == str(rhs_val).lower()
            if op == "!=":
                return str(lhs_val).lower() != str(rhs_val).lower()

            try:
                lf = float(lhs_val)
                rf = float(rhs_val)
                if op == ">=":
                    return lf >= rf
                if op == "<=":
                    return lf <= rf
                if op == ">":
                    return lf > rf
                if op == "<":
                    return lf < rf
            except (TypeError, ValueError):
                ls = str(lhs_val or "")
                rs = str(rhs_val or "")
                if op == ">=":
                    return ls >= rs
                if op == "<=":
                    return ls <= rs
                if op == ">":
                    return ls > rs
                if op == "<":
                    return ls < rs

    # Bare truthiness check (e.g. `done` or `support_url`)
    val = _resolve_record_value(s, rec)
    if isinstance(val, bool):
        return val
    return bool(str(val or "").strip())


def evaluate_filter_node(node: Any, rec: Dict[str, Any]) -> bool:
    """Recursively evaluate an Obsidian Bases `filters` YAML node (`str` or `{and|or|not: [...]}`)."""
    if node is None:
        return True
    if isinstance(node, str):
        return _eval_single_filter_expr(node, rec)
    if isinstance(node, list):
        return all(evaluate_filter_node(item, rec) for item in node)
    if isinstance(node, dict):
        if "and" in node:
            items = node["and"] if isinstance(node["and"], list) else [node["and"]]
            return all(evaluate_filter_node(x, rec) for x in items)
        if "or" in node:
            items = node["or"] if isinstance(node["or"], list) else [node["or"]]
            return any(evaluate_filter_node(x, rec) for x in items)
        if "not" in node:
            items = node["not"] if isinstance(node["not"], list) else [node["not"]]
            return not any(evaluate_filter_node(x, rec) for x in items)
    return True


def _split_top_level_args(arg_str: str) -> List[str]:
    args: List[str] = []
    depth = 0
    in_quote: Optional[str] = None
    buf: List[str] = []
    for i, ch in enumerate(arg_str):
        if in_quote:
            buf.append(ch)
            if ch == in_quote and (i == 0 or arg_str[i - 1] != "\\"):
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return args


def evaluate_base_formula(expr: str, rec: Dict[str, Any]) -> Any:
    """Safely evaluate common Obsidian Bases formula expressions without `eval()`."""
    s = (expr or "").strip()
    if not s:
        return ""

    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    # `if(cond, trueVal, falseVal)`
    if s.startswith("if(") and s.endswith(")"):
        parts = _split_top_level_args(s[3:-1])
        if len(parts) >= 2:
            cond_ok = _eval_single_filter_expr(parts[0], rec)
            chosen = parts[1] if cond_ok else (parts[2] if len(parts) >= 3 else '""')
            return evaluate_base_formula(chosen, rec)

    # `(now() - file.mtime).days.round(0)` or `(now() - file.ctime).days`
    m_age = re.match(r"^\(now\(\)\s*-\s*file\.(?:mtime|ctime)\)\.days(?:\.round\((\d+)\))?$", s)
    if m_age:
        mtime_val = float(rec.get("mtime") or datetime.now().timestamp())
        days = max(0.0, (datetime.now().timestamp() - mtime_val) / 86400.0)
        prec = int(m_age.group(1)) if m_age.group(1) is not None else None
        return round(days, prec) if (prec is not None and prec > 0) else (int(round(days)) if prec == 0 else round(days, 1))

    # `(date(due_date) - today()).days`
    m_due = re.match(r"^\(date\(([A-Za-z0-9_.]+)\)\s*-\s*today\(\)\)\.days(?:\.round\((\d+)\))?$", s)
    if m_due:
        dt = _parse_iso_date_safe(_resolve_record_value(m_due.group(1), rec))
        if not dt:
            return ""
        return (dt - date.today()).days

    # `(file.size / 5).round(0)`
    m_words = re.match(r"^\(file\.size\s*/\s*(\d+(?:\.\d+)?)\)\.round\((\d+)\)$", s)
    if m_words:
        divisor = max(1.0, float(m_words.group(1)))
        prec = int(m_words.group(2))
        val = float(rec.get("file_size") or 0) / divisor
        return int(round(val)) if prec == 0 else round(val, prec)

    # Simple arithmetic `a * b` or string concatenation `a + b`
    plus_parts = _split_top_level_logical(s, "+")
    if len(plus_parts) > 1:
        evaluated = [evaluate_base_formula(p, rec) for p in plus_parts]
        if all(isinstance(v, (int, float)) for v in evaluated):
            return sum(float(v) for v in evaluated)
        return "".join(str(v) for v in evaluated)

    mul_parts = _split_top_level_logical(s, "*")
    if len(mul_parts) == 2:
        try:
            return round(
                float(evaluate_base_formula(mul_parts[0], rec))
                * float(evaluate_base_formula(mul_parts[1], rec)),
                3,
            )
        except (TypeError, ValueError):
            return ""

    val = _resolve_record_value(s, rec)
    if val != "":
        return val
    return _unquote_literal(s)


def _compute_summary(values: List[Any], summary_kind: str) -> Any:
    kind = (summary_kind or "").strip().lower()
    non_empty = [v for v in values if v not in ("", None, [])]
    if kind in ("count", "total"):
        return len(values)
    if kind == "filled":
        return len(non_empty)
    if kind == "empty":
        return len(values) - len(non_empty)
    if kind == "unique":
        return len({json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v) for v in non_empty})
    if kind == "checked":
        return sum(1 for v in values if v is True or str(v).lower() == "true")
    if kind == "unchecked":
        return sum(1 for v in values if v is False or str(v).lower() == "false")

    nums: List[float] = []
    for v in non_empty:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            continue

    if kind == "sum":
        return round(sum(nums), 2) if nums else 0
    if kind in ("average", "mean"):
        return round(sum(nums) / len(nums), 2) if nums else 0
    if kind == "min":
        return min(nums) if nums else ""
    if kind == "max":
        return max(nums) if nums else ""
    if kind == "earliest":
        strs = sorted(str(v) for v in non_empty if str(v))
        return strs[0] if strs else ""
    if kind == "latest":
        strs = sorted(str(v) for v in non_empty if str(v))
        return strs[-1] if strs else ""
    return len(non_empty)


def evaluate_obsidian_base(
    *,
    raw_yaml: str,
    base_rel_path: str,
    note_records: List[Dict[str, Any]],
    selected_view: str = "",
) -> Dict[str, Any]:
    """Parse an Obsidian `.base` YAML file and evaluate its views, filters, formulas, and summaries."""
    errors: List[str] = []
    try:
        parsed = yaml.safe_load(raw_yaml or "")
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            errors.append("Root of `.base` file must be a YAML mapping.")
            parsed = {}
    except Exception as exc:
        return {
            "ok": False,
            "valid_yaml": False,
            "base_rel_path": base_rel_path,
            "errors": [f"YAML parse error: {exc}"],
            "views": [],
            "active_view": None,
            "columns": [],
            "rows": [],
            "summaries": {},
            "inferred_folder": str(Path(base_rel_path).parent).replace("\\", "/").strip("."),
        }

    global_filters = parsed.get("filters")
    formulas_map: Dict[str, str] = (
        {str(k): str(v) for k, v in parsed.get("formulas", {}).items()}
        if isinstance(parsed.get("formulas"), dict)
        else {}
    )
    props_cfg: Dict[str, Dict[str, Any]] = (
        parsed.get("properties") if isinstance(parsed.get("properties"), dict) else {}
    )
    raw_views = parsed.get("views") if isinstance(parsed.get("views"), list) else []

    if not raw_views:
        raw_views = [
            {
                "type": "table",
                "name": "Default Table",
                "order": ["file.name", "type", "status", "category", "file.folder"],
            }
        ]

    # Check formula references for validation diagnostics
    for v_obj in raw_views:
        if not isinstance(v_obj, dict):
            continue
        for col_ref in v_obj.get("order") or []:
            col_s = str(col_ref)
            if col_s.startswith("formula.") and col_s[8:] not in formulas_map:
                errors.append(f"View '{v_obj.get('name', 'Unnamed')}' references undefined `{col_s}`.")

    views_meta: List[Dict[str, Any]] = []
    chosen_view_obj: Dict[str, Any] = {}
    for idx, v_obj in enumerate(raw_views):
        if not isinstance(v_obj, dict):
            continue
        v_name = str(v_obj.get("name") or f"View {idx + 1}")
        v_type = str(v_obj.get("type") or "table").lower()
        if v_type not in ("table", "cards", "list", "map"):
            v_type = "table"
        views_meta.append({"name": v_name, "type": v_type})
        if not chosen_view_obj or (selected_view and v_name.lower() == selected_view.strip().lower()):
            chosen_view_obj = v_obj

    active_view_name = str(chosen_view_obj.get("name") or views_meta[0]["name"])
    active_view_type = str(chosen_view_obj.get("type") or "table").lower()
    view_filters = chosen_view_obj.get("filters")
    limit_val = chosen_view_obj.get("limit")
    group_by = chosen_view_obj.get("groupBy") if isinstance(chosen_view_obj.get("groupBy"), dict) else None

    # Infer default folder from `file.inFolder("...")` in view or global filters (falls back to `.base` parent folder)
    raw_dump = json.dumps({"g": global_filters, "v": view_filters})
    m_inf = re.search(r'file\.inFolder\(\s*\\"([^\\"]+)\\"\s*\)', raw_dump) or re.search(
        r"file\.inFolder\(\s*['\"]([^'\"]+)['\"]\s*\)", raw_dump
    )
    parent_dir = str(Path(base_rel_path).parent).replace("\\", "/")
    inferred_folder = (
        m_inf.group(1).strip("/")
        if m_inf
        else ("" if parent_dir in (".", "_System/Dashboards") else parent_dir)
    )

    matched_records: List[Dict[str, Any]] = []
    for rec in note_records:
        if rec["rel_path"].lower() == base_rel_path.lower():
            continue
        if not evaluate_filter_node(global_filters, rec):
            continue
        if not evaluate_filter_node(view_filters, rec):
            continue
        matched_records.append(rec)

    if group_by and group_by.get("property"):
        g_prop = str(group_by["property"])
        rev = str(group_by.get("direction") or "ASC").upper() == "DESC"
        matched_records.sort(key=lambda r: str(_resolve_record_value(g_prop, r) or "").lower(), reverse=rev)
    else:
        matched_records.sort(key=lambda r: float(r.get("mtime") or 0.0), reverse=True)

    if isinstance(limit_val, int) and limit_val > 0:
        matched_records = matched_records[:limit_val]

    order_cols: List[str] = [str(c) for c in (chosen_view_obj.get("order") or []) if str(c).strip()]
    if not order_cols:
        discovered_keys: List[str] = ["file.name"]
        for rec in matched_records[:25]:
            for fk in (rec.get("frontmatter") or {}).keys():
                if fk not in ("title", "tags", "turns") and fk not in discovered_keys:
                    discovered_keys.append(fk)
                if len(discovered_keys) >= 7:
                    break
        order_cols = discovered_keys

    columns_meta: List[Dict[str, str]] = []
    for col_key in order_cols:
        disp = ""
        if col_key in props_cfg and isinstance(props_cfg[col_key], dict):
            disp = str(props_cfg[col_key].get("displayName") or "")
        if not disp:
            if col_key == "file.name":
                disp = "Note"
            elif col_key == "file.folder":
                disp = "Folder"
            elif col_key.startswith("formula."):
                disp = col_key[8:].replace("_", " ").title()
            else:
                disp = col_key.replace("_url", " URL").replace("_", " ").title().replace("Url", "URL")
        columns_meta.append({"key": col_key, "label": disp})

    evaluated_rows: List[Dict[str, Any]] = []
    col_values_for_summary: Dict[str, List[Any]] = {c["key"]: [] for c in columns_meta}

    for rec in matched_records:
        cells: Dict[str, Any] = {}
        for col_key in order_cols:
            if col_key.startswith("formula."):
                f_name = col_key[8:]
                val = evaluate_base_formula(formulas_map.get(f_name, ""), rec) if f_name in formulas_map else ""
            else:
                val = _resolve_record_value(col_key, rec)
            cells[col_key] = val
            col_values_for_summary[col_key].append(val)

        fm = rec.get("frontmatter") or {}
        raw_id = str(fm.get("id") or Path(rec["rel_path"]).stem)
        task_id = raw_id if re.match(r"^TSK-\d{8}-\d{3}$", raw_id, flags=re.IGNORECASE) else ""
        evaluated_rows.append(
            {
                "rel_path": rec["rel_path"],
                "title": rec["title"],
                "is_private": bool(rec.get("is_private")),
                "type": rec.get("type", "note"),
                "folder": rec["file_folder"],
                "tags": rec.get("tags") or [],
                "task_id": task_id.upper() if task_id else "",
                "cells": cells,
            }
        )

    summaries_out: Dict[str, Any] = {}
    view_summaries = chosen_view_obj.get("summaries") if isinstance(chosen_view_obj.get("summaries"), dict) else {}
    for prop_key, sum_formula_name in view_summaries.items():
        vals = col_values_for_summary.get(str(prop_key), [])
        summaries_out[str(prop_key)] = {
            "formula": str(sum_formula_name),
            "value": _compute_summary(vals, str(sum_formula_name)),
        }

    editable_fields = [
        c["key"]
        for c in columns_meta
        if not c["key"].startswith("file.") and not c["key"].startswith("formula.")
    ]

    return {
        "ok": True,
        "valid_yaml": len(errors) == 0,
        "base_rel_path": base_rel_path,
        "errors": errors,
        "views": views_meta,
        "active_view": {"name": active_view_name, "type": active_view_type},
        "columns": columns_meta,
        "rows": evaluated_rows,
        "total_rows": len(evaluated_rows),
        "summaries": summaries_out,
        "inferred_folder": inferred_folder,
        "editable_fields": editable_fields,
    }


# ---------------------------------------------------------------------------
# 3. Official JSON Canvas Spec 1.0 Builder & Validator
# ---------------------------------------------------------------------------

VALID_CANVAS_NODE_TYPES = frozenset({"text", "file", "link", "group"})
VALID_CANVAS_SIDES = frozenset({"top", "right", "bottom", "left"})
VALID_CANVAS_ENDS = frozenset({"none", "arrow"})


def build_section_canvas_json(spec: Dict[str, Any], hub_index_rel: str, base_rel: str) -> str:
    """Build a JSON Canvas Spec 1.0 visual ecosystem map for a Section Hub."""
    collections = spec.get("collections") or []
    ext_links = spec.get("external_links") or []

    total_height = max(560, len(collections) * 170 + 100)
    group_id = generate_canvas_hex_id(1)
    hub_node_id = generate_canvas_hex_id(2)
    base_node_id = generate_canvas_hex_id(3)

    nodes: List[Dict[str, Any]] = [
        {
            "id": group_id,
            "type": "group",
            "x": -620,
            "y": -total_height // 2 - 40,
            "width": 1520,
            "height": total_height + 80,
            "label": f"{spec['icon']} {spec['title']} — Ecosystem Map",
            "color": "5",
        },
        {
            "id": hub_node_id,
            "type": "file",
            "file": hub_index_rel,
            "x": -560,
            "y": -150,
            "width": 360,
            "height": 220,
            "color": "4",
        },
        {
            "id": base_node_id,
            "type": "file",
            "file": base_rel,
            "x": -560,
            "y": 110,
            "width": 360,
            "height": 160,
            "color": "6",
        },
    ]

    edges: List[Dict[str, Any]] = [
        {
            "id": generate_canvas_hex_id(90),
            "fromNode": hub_node_id,
            "fromSide": "bottom",
            "toNode": base_node_id,
            "toSide": "top",
            "toEnd": "arrow",
            "label": "Live .base Catalog",
        }
    ]

    start_y = -((max(1, len(collections)) - 1) * 170) // 2 - 60
    palette = ["4", "5", "3", "6", "2", "1"]

    for idx, col in enumerate(collections):
        cid = generate_canvas_hex_id(10 + idx)
        cy = start_y + idx * 170
        fields_preview = ", ".join(f"`{f}`" for f in col.get("fields", [])[:5])
        nodes.append(
            {
                "id": cid,
                "type": "text",
                "x": -60,
                "y": cy,
                "width": 390,
                "height": 140,
                "color": palette[idx % len(palette)],
                "text": (
                    f"# {col['icon']} {col['title']}\n"
                    f"`{spec['section_rel']}/{col['folder']}/`\n\n"
                    f"{col['description']}\n"
                    f"Fields: {fields_preview}"
                ),
            }
        )
        edges.append(
            {
                "id": generate_canvas_hex_id(100 + idx),
                "fromNode": hub_node_id,
                "fromSide": "right",
                "toNode": cid,
                "toSide": "left",
                "toEnd": "arrow",
                "label": col["folder"],
            }
        )

    link_start_y = -((max(1, len(ext_links)) - 1) * 150) // 2 - 40
    for l_idx, lk in enumerate(ext_links[:6]):
        url = str(lk.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        lid = generate_canvas_hex_id(50 + l_idx)
        nodes.append(
            {
                "id": lid,
                "type": "link",
                "url": url,
                "x": 450,
                "y": link_start_y + l_idx * 150,
                "width": 360,
                "height": 120,
                "color": "2",
            }
        )
        anchor_from = nodes[3 + min(l_idx, len(collections) - 1)]["id"] if collections else hub_node_id
        edges.append(
            {
                "id": generate_canvas_hex_id(200 + l_idx),
                "fromNode": anchor_from,
                "fromSide": "right",
                "toNode": lid,
                "toSide": "left",
                "toEnd": "arrow",
                "label": str(lk.get("label") or "Portal")[:28],
            }
        )

    normalized = validate_and_normalize_canvas({"nodes": nodes, "edges": edges})
    return json.dumps(normalized["canvas"], indent=2, ensure_ascii=False) + "\n"


def validate_and_normalize_canvas(raw_or_dict: str | Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a JSON Canvas Spec 1.0 structure (unique IDs, valid node fields, no dangling edges)."""
    errors: List[str] = []
    if isinstance(raw_or_dict, str):
        try:
            obj = json.loads(raw_or_dict or '{"nodes":[],"edges":[]}')
        except Exception as exc:
            return {
                "valid": False,
                "errors": [f"Invalid JSON: {exc}"],
                "canvas": {"nodes": [], "edges": []},
            }
    elif isinstance(raw_or_dict, dict):
        obj = raw_or_dict
    else:
        return {
            "valid": False,
            "errors": ["Canvas root must be a JSON object."],
            "canvas": {"nodes": [], "edges": []},
        }

    raw_nodes = obj.get("nodes") if isinstance(obj.get("nodes"), list) else []
    raw_edges = obj.get("edges") if isinstance(obj.get("edges"), list) else []

    seen_ids: set[str] = set()
    clean_nodes: List[Dict[str, Any]] = []

    for idx, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            errors.append(f"Node #{idx} is not an object.")
            continue
        nid = str(n.get("id") or "").strip() or generate_canvas_hex_id(idx + 1)
        if nid in seen_ids:
            errors.append(f"Duplicate node id '{nid}'.")
            nid = generate_canvas_hex_id(idx + 500)
        seen_ids.add(nid)

        ntype = str(n.get("type") or "text").strip().lower()
        if ntype not in VALID_CANVAS_NODE_TYPES:
            errors.append(f"Node '{nid}' has invalid type '{ntype}'.")
            ntype = "text"

        node_out: Dict[str, Any] = {
            "id": nid,
            "type": ntype,
            "x": int(round(float(n.get("x", 0) or 0))),
            "y": int(round(float(n.get("y", 0) or 0))),
            "width": max(80, int(round(float(n.get("width", 300) or 300)))),
            "height": max(60, int(round(float(n.get("height", 160) or 160)))),
        }
        if n.get("color"):
            node_out["color"] = str(n["color"])

        if ntype == "text":
            if "text" not in n:
                errors.append(f"Text node '{nid}' missing 'text'.")
            node_out["text"] = str(n.get("text") or "")
        elif ntype == "file":
            if not n.get("file"):
                errors.append(f"File node '{nid}' missing 'file'.")
            node_out["file"] = str(n.get("file") or "").replace("\\", "/")
            if n.get("subpath"):
                node_out["subpath"] = str(n["subpath"])
        elif ntype == "link":
            if not n.get("url"):
                errors.append(f"Link node '{nid}' missing 'url'.")
            node_out["url"] = str(n.get("url") or "")
        elif ntype == "group":
            if n.get("label"):
                node_out["label"] = str(n["label"])
            if n.get("background"):
                node_out["background"] = str(n["background"])
            if n.get("backgroundStyle") in ("cover", "ratio", "repeat"):
                node_out["backgroundStyle"] = str(n["backgroundStyle"])

        clean_nodes.append(node_out)

    valid_node_ids = {n["id"] for n in clean_nodes}
    clean_edges: List[Dict[str, Any]] = []

    for idx, e in enumerate(raw_edges):
        if not isinstance(e, dict):
            continue
        from_node = str(e.get("fromNode") or "").strip()
        to_node = str(e.get("toNode") or "").strip()
        if from_node not in valid_node_ids or to_node not in valid_node_ids:
            errors.append(f"Edge #{idx} has dangling reference ({from_node} -> {to_node}).")
            continue
        eid = str(e.get("id") or "").strip() or generate_canvas_hex_id(1000 + idx)
        if eid in seen_ids:
            eid = generate_canvas_hex_id(2000 + idx)
        seen_ids.add(eid)

        edge_out: Dict[str, Any] = {
            "id": eid,
            "fromNode": from_node,
            "toNode": to_node,
        }
        if e.get("fromSide") in VALID_CANVAS_SIDES:
            edge_out["fromSide"] = str(e["fromSide"])
        if e.get("toSide") in VALID_CANVAS_SIDES:
            edge_out["toSide"] = str(e["toSide"])
        if e.get("fromEnd") in VALID_CANVAS_ENDS:
            edge_out["fromEnd"] = str(e["fromEnd"])
        if e.get("toEnd") in VALID_CANVAS_ENDS:
            edge_out["toEnd"] = str(e["toEnd"])
        if e.get("color"):
            edge_out["color"] = str(e["color"])
        if e.get("label"):
            edge_out["label"] = str(e["label"])
        clean_edges.append(edge_out)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "canvas": {"nodes": clean_nodes, "edges": clean_edges},
    }


def extract_canvas_file_links(raw_json: str) -> List[str]:
    """Extract Vault file paths referenced by `type: 'file'` nodes inside a `.canvas` JSON file."""
    try:
        obj = json.loads(raw_json or "{}")
    except Exception:
        return []
    nodes = obj.get("nodes") if isinstance(obj, dict) and isinstance(obj.get("nodes"), list) else []
    links: List[str] = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") == "file" and n.get("file"):
            clean_f = str(n["file"]).strip().replace("\\", "/")
            if clean_f and clean_f not in links:
                links.append(clean_f)
    return links
