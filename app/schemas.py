from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FieldType = Literal["text", "number", "date", "checkbox", "select"]
DocCategory = Literal[
    "email", "tgs", "plan", "moa", "correspondence", "photo", "other"
]


class WorkflowStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    completed: bool
    completed_at: datetime | None = None
    note: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    moa_number: str | None = None
    category: str
    description: str | None = None
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    uploaded_by: str | None = None
    uploaded_at: datetime
    road_name: str | None = None
    site_number: str | None = None


class DocumentUpdate(BaseModel):
    category: str | None = None
    description: str | None = None


class TrackingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_id: int
    event_type: str
    message: str
    created_by: str | None = None
    created_at: datetime


class TrackingEventCreate(BaseModel):
    event_type: str = "note"
    message: str = Field(min_length=1)
    created_by: str | None = None


class CouncilIn(BaseModel):
    council_name: str = Field(min_length=1, max_length=128)
    submitted_to_council_date: date | None = None
    no_objection_date: date | None = None


class CouncilOut(CouncilIn):
    id: int | None = None


class SiteBase(BaseModel):
    road_name: str = Field(min_length=1, max_length=255)
    site_number: str = Field(min_length=1, max_length=64)
    program: str | None = None
    register_order: int | None = None
    tgs_reference: str | None = None
    indicative_site_start_date: date | None = None
    indicative_shifts_count: int | None = Field(default=None, ge=1, le=365)
    moa_must_have_received_date: date | None = None
    must_have_manual: bool = False
    priority_manual: int | None = Field(default=None, ge=1, le=2)
    comments: str | None = None
    moa_number: str | None = None
    moa_submission_date: date | None = None
    moa_received_date: date | None = None
    moa_start_date: date | None = None
    moa_expiry_date: date | None = None
    extension_flag: str | None = None
    extension_submission_date: date | None = None
    extension_received_date: date | None = None
    extension_start_date: date | None = None
    extension_expiry_date: date | None = None
    job_completed_date: date | None = None
    include_in_totals: bool = True
    is_generic_moa: bool = False
    linked_generic_moa_id: int | None = None
    financial_year: str | None = None
    councils: list[str] = Field(default_factory=list)
    council_details: list[CouncilOut] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class SiteCreate(BaseModel):
    road_name: str = Field(min_length=1, max_length=255)
    site_number: str = Field(min_length=1, max_length=64)
    program: str | None = None
    register_order: int | None = None
    tgs_reference: str | None = None
    indicative_site_start_date: date | None = None
    indicative_shifts_count: int | None = Field(default=None, ge=1, le=365)
    moa_must_have_received_date: date | None = None
    must_have_manual: bool = False
    priority_manual: int | None = Field(default=None, ge=1, le=2)
    comments: str | None = None
    moa_number: str | None = None
    moa_submission_date: date | None = None
    moa_received_date: date | None = None
    moa_start_date: date | None = None
    moa_expiry_date: date | None = None
    extension_flag: str | None = None
    extension_submission_date: date | None = None
    extension_received_date: date | None = None
    extension_start_date: date | None = None
    extension_expiry_date: date | None = None
    job_completed_date: date | None = None
    include_in_totals: bool = True
    is_generic_moa: bool = False
    linked_generic_moa_id: int | None = None
    financial_year: str | None = None
    councils: list[str | CouncilIn] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, bool] | None = None
    geometry: dict[str, Any] | None = None
    geometry_name: str | None = None


class SiteUpdate(BaseModel):
    road_name: str | None = None
    site_number: str | None = None
    program: str | None = None
    register_order: int | None = None
    tgs_reference: str | None = None
    indicative_site_start_date: date | None = None
    indicative_shifts_count: int | None = Field(default=None, ge=1, le=365)
    moa_must_have_received_date: date | None = None
    must_have_manual: bool | None = None
    priority_manual: int | None = Field(default=None, ge=1, le=2)
    comments: str | None = None
    moa_number: str | None = None
    moa_submission_date: date | None = None
    moa_received_date: date | None = None
    moa_start_date: date | None = None
    moa_expiry_date: date | None = None
    extension_flag: str | None = None
    extension_submission_date: date | None = None
    extension_received_date: date | None = None
    extension_start_date: date | None = None
    extension_expiry_date: date | None = None
    job_completed_date: date | None = None
    include_in_totals: bool | None = None
    is_generic_moa: bool | None = None
    linked_generic_moa_id: int | None = None
    financial_year: str | None = None
    councils: list[str | CouncilIn] | None = None
    custom_fields: dict[str, Any] | None = None
    workflow: dict[str, bool] | None = None
    geometry: dict[str, Any] | None = None
    geometry_name: str | None = None


class SiteArchiveRequest(BaseModel):
    financial_year: str | None = None


class SiteBulkArchiveRequest(BaseModel):
    site_ids: list[int] = Field(min_length=1)
    financial_year: str | None = None


class SiteBulkArchiveOut(BaseModel):
    archived: int
    site_ids: list[int]
    financial_year: str | None = None


class SiteBulkPurgeRequest(BaseModel):
    site_ids: list[int] = Field(min_length=1)


class SiteBulkPurgeOut(BaseModel):
    purged: int
    site_ids: list[int]


class SiteReorderRequest(BaseModel):
    program: str | None = None
    site_ids: list[int] = Field(min_length=1)


class SiteReorderOut(BaseModel):
    program: str | None = None
    site_ids: list[int]


class SiteOut(SiteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    register_order: int | None = None
    archived: bool = False
    archived_at: datetime | None = None
    archived_fy: str | None = None
    today_priority: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    workflow: list[WorkflowStepOut]
    document_count: int = 0
    tracking_count: int = 0
    cost_estimate_count: int = 0
    latest_cost_total: float | None = None
    created_at: datetime
    updated_at: datetime


class CustomColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    field_type: FieldType = "text"
    options: list[str] | None = None
    created_by: str | None = None


class CustomColumnUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    field_type: FieldType | None = None
    options: list[str] | None = None
    position: int | None = None


class CustomColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    field_key: str
    field_type: str
    options: list[str] | None = None
    position: int
    created_by: str | None = None
    created_at: datetime


class MetaOut(BaseModel):
    workflow_stages: list[dict[str, Any]]
    doc_categories: list[str]
    priority_threshold_days: int = 14
    priority_must_have_days: int = 14
    must_have_offset_business_days: int = 20
    council_no_objection_business_days: int = 10
    moa_wait_sla_business_days: int = 20
    financial_years: list[str]
    programs: list[str] = Field(default_factory=list)
    councils: list[str] = Field(default_factory=list)
    roads: list[str] = Field(default_factory=list)
    rules: dict[str, Any] = Field(default_factory=dict)
    asset_version: str = "0"


class AppSettingsOut(BaseModel):
    must_have_offset_business_days: int
    priority_must_have_days: int
    must_have_warn_days: int
    must_have_critical_days: int
    council_no_objection_business_days: int
    moa_wait_sla_business_days: int
    permit_validity_warn_days: int
    permit_validity_critical_days: int
    auto_compute_must_have: bool
    auto_archive_on_job_complete: bool


class AppSettingsUpdate(BaseModel):
    must_have_offset_business_days: int | None = Field(default=None, ge=0, le=365)
    priority_must_have_days: int | None = Field(default=None, ge=0, le=365)
    must_have_warn_days: int | None = Field(default=None, ge=0, le=365)
    must_have_critical_days: int | None = Field(default=None, ge=0, le=365)
    council_no_objection_business_days: int | None = Field(default=None, ge=0, le=365)
    moa_wait_sla_business_days: int | None = Field(default=None, ge=0, le=365)
    permit_validity_warn_days: int | None = Field(default=None, ge=0, le=365)
    permit_validity_critical_days: int | None = Field(default=None, ge=0, le=365)
    auto_compute_must_have: bool | None = None
    auto_archive_on_job_complete: bool | None = None


class LookupIn(BaseModel):
    kind: str = Field(pattern="^(road|council)$")
    value: str = Field(min_length=1, max_length=255)
    position: int | None = None
    active: bool = True


class LookupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    value: str
    position: int
    active: bool
    usage_count: int = 0
    sites_updated: int = 0
    merged: bool = False


class MapLayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    financial_year: str
    original_filename: str
    feature_count: int
    uploaded_by: str | None = None
    uploaded_at: datetime


class MapFeatureOut(BaseModel):
    id: int
    layer_id: int
    site_id: int | None = None
    name: str | None = None
    description: str | None = None
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)
    financial_year: str | None = None
    site: dict[str, Any] | None = None


class MapFeatureLink(BaseModel):
    site_id: int | None = None


class DashboardOut(BaseModel):
    totals: dict[str, Any]
    by_stage: list[dict[str, Any]]
    by_council: list[dict[str, Any]]
    by_program: list[dict[str, Any]]
    priority: dict[str, Any]
    must_have: dict[str, Any]
    permits_priority_count: int
    trims_priority_count: int = 0
    recent_tracking: list[dict[str, Any]]
