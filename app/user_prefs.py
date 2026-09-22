"""Per-user UI preferences stored on User.prefs."""

from __future__ import annotations

from typing import Any

DEFAULT_HOME_WIDGETS = [
    "approvals",
    "status",
    "comms",
    "costs",
    "spend",
    "stages",
]

DEFAULT_QUICK_LINKS = ["/dashboard", "/", "/lists", "/map"]

ALLOWED_WIDGETS = {
    "approvals",
    "status",
    "comms",
    "costs",
    "spend",
    "stages",
    "programs",
    "councils",
}

ALLOWED_LINK_HREFS = {
    "/dashboard",
    "/",
    "/lists",
    "/generics",
    "/tracking",
    "/gantt",
    "/documents",
    "/map",
    "/costs",
    "/asphalt",
    "/spend",
    "/comms",
    "/calendar",
    "/archive",
    "/shifts",
    "/account",
}


def default_prefs() -> dict[str, Any]:
    return {
        "theme": "system",
        "colors": {"accent": "", "bg": "", "ink": "", "panel": ""},
        "quick_links": list(DEFAULT_QUICK_LINKS),
        "home_widgets": list(DEFAULT_HOME_WIDGETS),
        "comms_sort": "group",
        "comms_sheets": [],
    }


def _hex(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3 and all(c in "0123456789abcdefABCDEF" for c in raw):
        raw = "".join(c * 2 for c in raw)
    if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return f"#{raw.lower()}"
    return ""


def normalize_prefs(raw) -> dict[str, Any]:
    base = default_prefs()
    data = raw if isinstance(raw, dict) else {}
    theme = str(data.get("theme") or "system").strip().lower()
    if theme not in {"light", "dark", "system"}:
        theme = "system"
    base["theme"] = theme
    colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    base["colors"] = {
        "accent": _hex(colors.get("accent")),
        "bg": _hex(colors.get("bg")),
        "ink": _hex(colors.get("ink")),
        "panel": _hex(colors.get("panel")),
    }
    links = []
    for href in data.get("quick_links") or []:
        path = str(href or "").strip()
        if path in ALLOWED_LINK_HREFS and path not in links:
            links.append(path)
        if len(links) >= 8:
            break
    base["quick_links"] = links or list(DEFAULT_QUICK_LINKS)
    widgets = []
    for key in data.get("home_widgets") or []:
        slug = str(key or "").strip()
        if slug in ALLOWED_WIDGETS and slug not in widgets:
            widgets.append(slug)
    base["home_widgets"] = widgets or list(DEFAULT_HOME_WIDGETS)
    sort_mode = str(data.get("comms_sort") or "group").strip().lower()
    base["comms_sort"] = "date" if sort_mode == "date" else "group"
    sheets = []
    for item in data.get("comms_sheets") or []:
        try:
            sid = int(item)
        except (TypeError, ValueError):
            continue
        if sid > 0 and sid not in sheets:
            sheets.append(sid)
    base["comms_sheets"] = sheets
    return base
