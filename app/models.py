from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .database import Base


class User(Base):
    """Application login account (single-org deployment)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # admin | user | comms
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Fallback constants — live config is WorkflowStageDef (seeded from these keys).
WORKFLOW_STAGES = [
    "tgs_markup_completed",
    "submitted_to_tmd",
    "ventia_review",
    "plan_received",
    "ready_to_submit_moa",
    "moa_submitted",
    "moa_with_trims",
    "revision_needed",
    "moa_received",
    "ready_for_works",
]

WORKFLOW_LABELS = {
    "tgs_markup_completed": "TGS Markup Complete",
    "submitted_to_tmd": "Submitted to TMD",
    "ventia_review": "Ventia review",
    "plan_received": "Plan Received",
    "ready_to_submit_moa": "Ready to Submit MoA",
    "moa_submitted": "MoA Submitted",
    "moa_with_trims": "MoA With TRIMS",
    "revision_needed": "Revision Needed",
    "moa_received": "MoA Received",
    "ready_for_works": "Ready for Works",
}

DOC_CATEGORIES = [
    "email",
    "tgs",
    "plan",
    "moa",
    "correspondence",
    "photo",
    "other",
]

DOC_CATEGORY_LABELS = {
    "email": "Email",
    "tgs": "TGS",
    "plan": "Plan",
    "moa": "MoA",
    "correspondence": "Correspondence",
    "photo": "Photo",
    "other": "Other",
}


class WorkflowStageDef(Base):
    """Admin-configurable workflow stages (order, labels, client-list roles)."""

    __tablename__ = "workflow_stage_defs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # none | permits | trims | complete
    list_role: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    counts_toward_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProgramCategory(Base):
    """Parent application categories (Lifecycle pavements, Assets, etc.)."""

    __tablename__ = "program_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AppSettings(Base):
    """Singleton (id=1) tracker SLA / rule settings — admin configurable."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    must_have_offset_business_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    priority_must_have_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    must_have_warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    must_have_critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    council_no_objection_business_days: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    moa_wait_sla_business_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    permit_validity_warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    permit_validity_critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    auto_compute_must_have: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_archive_on_job_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DocumentCategoryDef(Base):
    """Admin-configurable document types (email, TGS, custom labels, …)."""

    __tablename__ = "document_category_defs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Protected rows (the fallback "other") cannot be deleted or have their key changed.
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LookupItem(Base):
    """Admin-managed dropdown lists (roads, councils, etc.)."""

    __tablename__ = "lookup_items"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_lookup_kind_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # road | council
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    road_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    site_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    program: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    register_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    tgs_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    indicative_site_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    indicative_shifts_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indicative_shift_type: Mapped[str] = mapped_column(String(16), nullable=False, default="day")
    moa_must_have_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    must_have_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_manual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    moa_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    moa_submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    moa_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    moa_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    moa_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Extension / change track (spreadsheet AB–AG)
    extension_flag: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Yes|No|N/A
    extension_submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    extension_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    extension_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    extension_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    job_completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    include_in_totals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_generic_moa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_generic_moa_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    financial_year: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_fy: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    custom_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    councils: Mapped[list[SiteCouncil]] = relationship(
        back_populates="site", cascade="all, delete-orphan", lazy="selectin"
    )
    workflow_steps: Mapped[list[WorkflowStep]] = relationship(
        back_populates="site", cascade="all, delete-orphan", lazy="joined"
    )
    tracking_events: Mapped[list[TrackingEvent]] = relationship(
        back_populates="site", cascade="all, delete-orphan", lazy="selectin"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="site", cascade="all, delete-orphan", lazy="selectin"
    )
    map_features: Mapped[list[MapFeature]] = relationship(
        back_populates="site", lazy="selectin"
    )
    cost_estimates: Mapped[list[CostEstimate]] = relationship(
        back_populates="site", cascade="all, delete-orphan", lazy="selectin"
    )


class SiteCouncil(Base):
    __tablename__ = "site_councils"
    __table_args__ = (UniqueConstraint("site_id", "council_name", name="uq_site_council"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    council_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    submitted_to_council_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    no_objection_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    site: Mapped[Site] = relationship(back_populates="councils")


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("site_id", "stage", name="uq_site_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    site: Mapped[Site] = relationship(back_populates="workflow_steps")


class CustomColumn(Base):
    __tablename__ = "custom_columns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="note")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    site: Mapped[Site] = relationship(back_populates="tracking_events")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True
    )
    moa_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="other", index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # users = everyone on the linked job; comms = comms/admin only
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="users", index=True)
    # site = uploaded on a job; comms = uploaded from the comms planner
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="site")
    comms_row_id: Mapped[int | None] = mapped_column(
        ForeignKey("comms_rows.id", ondelete="SET NULL"), nullable=True, index=True
    )

    site: Mapped[Site | None] = relationship(back_populates="documents")
    comms_row: Mapped["CommsRow | None"] = relationship(back_populates="documents")


class MapLayer(Base):
    __tablename__ = "map_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    features: Mapped[list[MapFeature]] = relationship(
        back_populates="layer", cascade="all, delete-orphan", lazy="selectin"
    )


class MapFeature(Base):
    __tablename__ = "map_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    layer_id: Mapped[int] = mapped_column(ForeignKey("map_layers.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False)
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    layer: Mapped[MapLayer] = relationship(back_populates="features")
    site: Mapped[Site | None] = relationship(back_populates="map_features")


class CostSettings(Base):
    """Singleton-ish settings row (id=1) for calculator defaults."""

    __tablename__ = "cost_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    overtime_after_hours: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)
    vms_lead_days_default: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    vms_delivery_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vms_collection_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vms_day_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Per-head allowances (TCs + TMA drivers + spotters)
    travel_allowance: Mapped[float] = mapped_column(Float, nullable=False, default=45.0)
    meal_allowance: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    meal_after_hours: Mapped[float] = mapped_column(Float, nullable=False, default=9.5)
    # Day window [day_start_hour, day_end_hour); outside = night (defaults 06:00–18:00)
    day_start_hour: Mapped[float] = mapped_column(Float, nullable=False, default=6.0)
    day_end_hour: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LabourRate(Base):
    """Rate card: TC packs (1–4 ± vehicle), TMA, spotter, or legacy per-head."""

    __tablename__ = "labour_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # crew_pack | tma | spotter | legacy
    rate_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="crew_pack")
    # TCs covered by one unit (1–4 for crew_pack; 0 for tma; 1 for spotter/legacy)
    pack_people: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    includes_vehicle: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    day_ordinary: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    day_overtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    night_ordinary: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    night_overtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Weekend / PH — 0 means “use engine fallback” (night / Sunday rates)
    saturday_ordinary: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saturday_overtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sunday_ordinary: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sunday_overtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    public_holiday_ordinary: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    public_holiday_overtime: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ShiftExtraRate(Base):
    """Per-shift plant / add-on (arrowboard, etc.): qty × unit_rate × shifts."""

    __tablename__ = "shift_extra_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    unit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CostEstimate(Base):
    """Saved traffic management cost estimate linked to a site / MoA."""

    __tablename__ = "cost_estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    moa_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    site: Mapped[Site | None] = relationship(back_populates="cost_estimates")
    attachments: Mapped[list[CostEstimateAttachment]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan", lazy="selectin"
    )


class CostEstimateAttachment(Base):
    """Files attached to a cost estimate (quotes, emails, PDFs, etc.)."""

    __tablename__ = "cost_estimate_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("cost_estimates.id", ondelete="CASCADE"), index=True
    )
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    estimate: Mapped[CostEstimate] = relationship(back_populates="attachments")


class TrafficContractor(Base):
    """Traffic management contractor / TM company."""

    __tablename__ = "traffic_contractors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AsphaltSubcontractor(Base):
    """Asphalt crew / subcontractor with optional RDO calendar."""

    __tablename__ = "asphalt_subcontractors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Python weekday ints 0=Mon … 6=Sun (default Mon–Fri)
    work_weekdays: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: [0, 1, 2, 3, 4])
    # ISO date strings for standing RDOs for this subcontractor
    rdo_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    skip_public_holidays: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    skip_sunday_before_monday_ph: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rates: Mapped[list[AsphaltRate]] = relationship(
        back_populates="subcontractor", cascade="all, delete-orphan", lazy="selectin"
    )


class AsphaltRate(Base):
    """Unit rate card for an asphalt subcontractor."""

    __tablename__ = "asphalt_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subcontractor_id: Mapped[int] = mapped_column(
        ForeignKey("asphalt_subcontractors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="m2")  # m2|tonne|lm|shift|day|lump
    # unit = single $/qty; shift = day/night/weekend/PH (mobilisation, crew, etc.)
    rate_type: Mapped[str] = mapped_column(String(16), nullable=False, default="unit")
    day_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    night_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saturday_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sunday_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    public_holiday_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    subcontractor: Mapped[AsphaltSubcontractor] = relationship(back_populates="rates")


class AsphaltEstimate(Base):
    """Saved asphalt cost estimate linked to a site."""

    __tablename__ = "asphalt_estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subcontractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("asphalt_subcontractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ActualSpend(Base):
    """Recorded actual spend against a site (traffic or pavements/asphalt)."""

    __tablename__ = "actual_spends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # traffic | asphalt
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # manual | calculated | from_estimate
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    traffic_contractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("traffic_contractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asphalt_subcontractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("asphalt_subcontractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invoice_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    results: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    site: Mapped[Site] = relationship(lazy="selectin")
    traffic_contractor: Mapped[TrafficContractor | None] = relationship(lazy="selectin")
    asphalt_subcontractor: Mapped[AsphaltSubcontractor | None] = relationship(lazy="selectin")


class CommsSheet(Base):
    """A comms planner workbook tab (FMRP, Maintenance, or user-created)."""

    __tablename__ = "comms_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    columns: Mapped[list["CommsColumn"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", lazy="selectin"
    )
    rows: Mapped[list["CommsRow"]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", lazy="selectin"
    )


class CommsColumn(Base):
    __tablename__ = "comms_columns"
    __table_args__ = (UniqueConstraint("sheet_id", "field_key", name="uq_comms_sheet_field"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("comms_sheets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sheet: Mapped[CommsSheet] = relationship(back_populates="columns")


class CommsRow(Base):
    __tablename__ = "comms_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("comms_sheets.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sheet: Mapped[CommsSheet] = relationship(back_populates="rows")
    site: Mapped[Site | None] = relationship(lazy="selectin")
    documents: Mapped[list[Document]] = relationship(back_populates="comms_row", lazy="selectin")


class GanttBoard(Base):
    """Program-level works sequence / Gantt settings."""

    __tablename__ = "gantt_boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    anchor_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_weekdays: Mapped[list] = mapped_column(JSON, nullable=False, default=lambda: [0, 1, 2, 3, 4])
    skip_public_holidays: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    skip_sunday_before_monday_ph: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Board-level RDO / exclude / include ISO dates
    rdo_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclude_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    include_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # When true, GET no longer reshuffles items from site indicative starts
    # so a saved works sequence can be edited (weather, missed days).
    schedule_saved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list[GanttItem]] = relationship(
        back_populates="board", cascade="all, delete-orphan", lazy="selectin"
    )


class GanttItem(Base):
    """One site bar on a program Gantt — order drives reactive dates."""

    __tablename__ = "gantt_items"
    __table_args__ = (UniqueConstraint("board_id", "site_id", name="uq_gantt_board_site"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int] = mapped_column(
        ForeignKey("gantt_boards.id", ondelete="CASCADE"), index=True
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shifts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # day | night — night shifts finish the following calendar morning
    shift_type: Mapped[str] = mapped_column(String(16), nullable=False, default="day")
    # after_previous | fixed_start
    link_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="after_previous")
    fixed_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    subcontractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("asphalt_subcontractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    traffic_contractor_id: Mapped[int | None] = mapped_column(
        ForeignKey("traffic_contractors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    planned_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Item-level date overrides (ISO strings)
    rdo_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    exclude_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    include_dates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    board: Mapped[GanttBoard] = relationship(back_populates="items")
    site: Mapped[Site] = relationship(lazy="selectin")
    subcontractor: Mapped[AsphaltSubcontractor | None] = relationship(lazy="selectin")
    traffic_contractor: Mapped[TrafficContractor | None] = relationship(lazy="selectin")
