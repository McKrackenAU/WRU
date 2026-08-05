"""Singleton app settings — spreadsheet SLA rules, admin-tunable."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from .models import AppSettings

# Defaults match WRU Traffic TGS-MOA Tracker V6 spreadsheet formulas.
DEFAULTS = {
    "must_have_offset_business_days": 20,  # WORKDAY(start, -20)
    "priority_must_have_days": 14,  # priority 1 if must-have within/past this window
    "must_have_warn_days": 14,  # yellow band when past must-have by ≤ this
    "must_have_critical_days": 7,  # red band when past must-have by > warn? sheet: yellow 7-14, red >7
    "council_no_objection_business_days": 10,  # WORKDAY(submit, +10)
    "moa_wait_sla_business_days": 20,  # CF alert when wait > 20
    "permit_validity_warn_days": 10,
    "permit_validity_critical_days": 20,
    "auto_compute_must_have": True,
    "auto_archive_on_job_complete": True,
}


@dataclass
class Rules:
    must_have_offset_business_days: int = 20
    priority_must_have_days: int = 14
    must_have_warn_days: int = 14
    must_have_critical_days: int = 7
    council_no_objection_business_days: int = 10
    moa_wait_sla_business_days: int = 20
    permit_validity_warn_days: int = 10
    permit_validity_critical_days: int = 20
    auto_compute_must_have: bool = True
    auto_archive_on_job_complete: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def ensure_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1, **DEFAULTS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_rules(db: Session | None = None) -> Rules:
    if db is None:
        return Rules(**DEFAULTS)
    row = ensure_settings(db)
    return Rules(
        must_have_offset_business_days=int(row.must_have_offset_business_days),
        priority_must_have_days=int(row.priority_must_have_days),
        must_have_warn_days=int(row.must_have_warn_days),
        must_have_critical_days=int(row.must_have_critical_days),
        council_no_objection_business_days=int(row.council_no_objection_business_days),
        moa_wait_sla_business_days=int(row.moa_wait_sla_business_days),
        permit_validity_warn_days=int(row.permit_validity_warn_days),
        permit_validity_critical_days=int(row.permit_validity_critical_days),
        auto_compute_must_have=bool(row.auto_compute_must_have),
        auto_archive_on_job_complete=bool(row.auto_archive_on_job_complete),
    )


def update_settings(db: Session, data: dict) -> AppSettings:
    row = ensure_settings(db)
    for key, value in data.items():
        if hasattr(row, key) and value is not None:
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row
