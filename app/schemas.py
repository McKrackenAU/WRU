from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FieldType = Literal["text", "number", "date", "checkbox", "select"]


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
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    uploaded_by: str | None = None
    uploaded_at: datetime


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


class SiteBase(BaseModel):
    road_name: str = Field(min_length=1, max_length=255)
    site_number: str = Field(min_length=1, max_length=64)
    indicative_site_start_date: date | None = None
    moa_must_have_received_date: date | None = None
    comments: str | None = None
    moa_number: str | None = None
    moa_submission_date: date | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class SiteCreate(SiteBase):
    workflow: dict[str, bool] | None = None


class SiteUpdate(BaseModel):
    road_name: str | None = None
    site_number: str | None = None
    indicative_site_start_date: date | None = None
    moa_must_have_received_date: date | None = None
    comments: str | None = None
    moa_number: str | None = None
    moa_submission_date: date | None = None
    custom_fields: dict[str, Any] | None = None
    workflow: dict[str, bool] | None = None


class SiteOut(SiteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    today_priority: int
    workflow: list[WorkflowStepOut]
    document_count: int = 0
    tracking_count: int = 0
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
    workflow_stages: list[dict[str, str]]
    priority_threshold_days: int = 21
