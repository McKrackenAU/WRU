"""Parse MS Project XML (MSPDI) and match tasks to WRU sites."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

NS = {"p": "http://schemas.microsoft.com/project"}


def _text(node, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(f"p:{tag}", NS)
    if child is None:
        child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _parse_date(raw: str) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _duration_days(raw: str) -> int | None:
    text = (raw or "").strip().upper()
    if not text:
        return None
    match = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if match:
        hours = int(match.group(1) or 0)
        return max(1, round(hours / 8) or 1)
    match = re.search(r"P(\d+)D", text)
    if match:
        return max(1, int(match.group(1)))
    return None


def _site_token(name: str) -> str | None:
    match = re.search(r"\b(S\d{1,4}|[A-Z]{1,3}\d{1,4})\b", name or "", re.I)
    return match.group(1).upper() if match else None


def parse_msp_xml(content: bytes) -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Not a valid MS Project XML file ({exc})") from exc
    tasks = root.findall(".//p:Task", NS) or root.findall(".//Task")
    out = []
    for task in tasks:
        name = _text(task, "Name")
        if not name or _text(task, "Summary") in {"1", "true", "True"}:
            continue
        start = _parse_date(_text(task, "Start"))
        finish = _parse_date(_text(task, "Finish"))
        days = _duration_days(_text(task, "Duration"))
        if start and not days and finish:
            days = max(1, (finish - start).days + 1)
        if not start and not days:
            continue
        out.append(
            {
                "name": name,
                "site_token": _site_token(name),
                "start": start.isoformat() if start else None,
                "finish": finish.isoformat() if finish else None,
                "shifts_count": days or 1,
            }
        )
    return out


def match_tasks_to_sites(tasks: list[dict], sites: list) -> list[dict]:
    by_number = {}
    for site in sites:
        key = str(getattr(site, "site_number", "") or "").strip().upper()
        if key:
            by_number[key] = site
    matched = []
    for task in tasks:
        token = (task.get("site_token") or "").upper()
        site = by_number.get(token)
        if not site:
            continue
        start = task.get("start")
        matched.append(
            {
                "site_id": site.id,
                "site_number": site.site_number,
                "road_name": site.road_name,
                "start": start,
                "shifts_count": int(task.get("shifts_count") or 1),
                "name": task.get("name"),
            }
        )
    return matched
