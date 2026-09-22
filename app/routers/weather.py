from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..models import User
from ..weather import fetch_weather

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("")
def current_weather(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    _: User = Depends(get_current_user),
):
    try:
        return fetch_weather(lat, lng)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Weather lookup failed: {exc}") from exc
