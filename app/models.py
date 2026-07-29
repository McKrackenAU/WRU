from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
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

WORKFLOW_STAGES = [
    "tgs_markup_completed",
    "submitted_to_tmd",
    "plan_received",
    "ready_to_submit_moa",
    "moa_submitted",
    "moa_with_trims",
    "revision_needed",
    "moa_received",
    "ready_for_works",
]

WORKFLOW_LABELS = {
    "tgs_markup_completed": "TGS Markup completed",
    "submitted_to_tmd": "Submitted to TMD",
    "plan_received": "Plan Received",
    "ready_to_submit_moa": "Ready To Submit MoA",
    "moa_submitted": "MoA Submitted",
    "moa_with_trims": "MoA WITH TRIMS",
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


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    road_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    site_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    program: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tgs_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    indicative_site_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    moa_must_have_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    moa_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    moa_submission_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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


class SiteCouncil(Base):
    __tablename__ = "site_councils"
    __table_args__ = (UniqueConstraint("site_id", "council_name", name="uq_site_council"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    council_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

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
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    moa_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other", index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    site: Mapped[Site] = relationship(back_populates="documents")


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
