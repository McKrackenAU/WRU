"""Lifecycle lot numbers: date-road-year-site-HMA/PRO-mix-initials."""

from __future__ import annotations

import re


def compact_fmrp(value: str | None) -> str:
    """Turn ``FMRP 2025/26`` into ``2526``."""
    years = re.findall(r"\d{2,4}", value or "")
    if len(years) >= 2:
        return f"{years[0][-2:]}{years[1][-2:]}"
    if not years:
        return ""
    token = years[0]
    return token[-4:] if len(token) > 4 else token


def road_number_from_name(road_name: str | None) -> str:
    nums = re.findall(r"\d+", road_name or "")
    return nums[-1] if nums else ""


def supervisor_initials(name: str | None) -> str:
    return "".join(part[0] for part in str(name or "").split() if part).upper()


def work_kind_code(kind: str | None) -> str:
    text = (kind or "hma").strip().lower()
    if text in {"pro", "profiling", "profile"}:
        return "PRO"
    return "HMA"


def build_lot_number(
    *,
    work_date: str | None,
    road_number: str | None,
    fmrp_year: str | None,
    site_number: str | None,
    work_kind: str | None = "hma",
    mix: str | None = None,
    supervisor: str | None = None,
) -> str:
    """``20260225-5443-2526-030-HMA-14HP-WM``. Profiling drops the mix."""
    date = str(work_date or "").replace("-", "")[:8]
    year = compact_fmrp(fmrp_year)
    kind = work_kind_code(work_kind)
    parts = [
        date,
        str(road_number or "").strip(),
        year,
        str(site_number or "").strip(),
        kind,
    ]
    if kind == "HMA":
        mix_token = str(mix or "").strip()
        if mix_token:
            parts.append(mix_token)
    initials = supervisor_initials(supervisor)
    if initials:
        parts.append(initials)
    return "-".join(part for part in parts if part)
