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

ALLOWED_CHART_METRICS = {
    "stages",
    "programs",
    "councils",
    "priority",
    "must_have",
    "lists",
    "costs",
    "spend",
    "sites",
}

ALLOWED_CHART_TYPES = {"bar", "pie"}

MAX_HOME_CHARTS = 8

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

COLOR_KEYS = ("accent", "bg", "ink", "panel", "border")


def _empty_colors() -> dict[str, str]:
    return {key: "" for key in COLOR_KEYS}


def default_prefs() -> dict[str, Any]:
    return {
        "theme": "system",
        "colors": _empty_colors(),
        "colors_light": _empty_colors(),
        "colors_dark": _empty_colors(),
        "quick_links": list(DEFAULT_QUICK_LINKS),
        "home_widgets": list(DEFAULT_HOME_WIDGETS),
        "home_charts": [],
        "comms_sort": "group",
        "comms_sheets": [],
    }


def _chart_id(raw, used: set[str]) -> str:
    text = "".join(ch for ch in str(raw or "") if ch.isalnum() or ch in "-_")[:24]
    if text and text not in used:
        return text
    n = 1
    while True:
        cid = f"c{n}"
        if cid not in used:
            return cid
        n += 1


def _normalize_charts(raw) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        if metric not in ALLOWED_CHART_METRICS:
            continue
        kind = str(item.get("chart") or item.get("type") or "bar").strip().lower()
        if kind not in ALLOWED_CHART_TYPES:
            kind = "bar"
        cid = _chart_id(item.get("id"), used)
        used.add(cid)
        title = str(item.get("title") or "").strip()[:80]
        program = str(item.get("program") or "").strip()[:128]
        council = str(item.get("council") or "").strip()[:128]
        hide_empty = item.get("hide_empty")
        charts.append(
            {
                "id": cid,
                "title": title,
                "metric": metric,
                "chart": kind,
                "program": program,
                "council": council,
                "include_archived": bool(item.get("include_archived")),
                "hide_empty": True if hide_empty is None else bool(hide_empty),
            }
        )
        if len(charts) >= MAX_HOME_CHARTS:
            break
    return charts


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


def _color_map(raw) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    return {key: _hex(data.get(key)) for key in COLOR_KEYS}


def _has_color(colors: dict[str, str]) -> bool:
    return any(colors.get(key) for key in COLOR_KEYS)


def normalize_prefs(raw) -> dict[str, Any]:
    base = default_prefs()
    data = raw if isinstance(raw, dict) else {}
    theme = str(data.get("theme") or "system").strip().lower()
    if theme not in {"light", "dark", "system"}:
        theme = "system"
    base["theme"] = theme
    legacy = _color_map(data.get("colors"))
    light = _color_map(data.get("colors_light"))
    dark = _color_map(data.get("colors_dark"))
    if _has_color(legacy) and not _has_color(light) and not _has_color(dark):
        light = dict(legacy)
        dark = dict(legacy)
    base["colors"] = legacy
    base["colors_light"] = light
    base["colors_dark"] = dark
    if "quick_links" in data:
        links = []
        for href in data.get("quick_links") or []:
            path = str(href or "").strip()
            if path in ALLOWED_LINK_HREFS and path not in links:
                links.append(path)
            if len(links) >= 8:
                break
        base["quick_links"] = links
    widgets = []
    for key in data.get("home_widgets") or []:
        slug = str(key or "").strip()
        if slug in ALLOWED_WIDGETS and slug not in widgets:
            widgets.append(slug)
    base["home_widgets"] = widgets or list(DEFAULT_HOME_WIDGETS)
    if "home_charts" in data:
        base["home_charts"] = _normalize_charts(data.get("home_charts"))
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
