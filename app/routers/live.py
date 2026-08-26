"""Server-Sent Events for live multi-user data refresh."""

from __future__ import annotations

import asyncio
import json
import queue
import secrets
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..live_hub import hub

router = APIRouter(prefix="/api/live", tags=["live"])

HEARTBEAT_SECONDS = 20.0


@router.get("/events")
async def live_events(
    request: Request,
    client_id: str | None = Query(default=None, max_length=64),
):
    """SSE stream. Auth is enforced by AuthGateMiddleware (session cookie)."""
    cid = (client_id or "").strip() or secrets.token_urlsafe(12)
    user_id = request.session.get("user_id")
    username = request.session.get("display_name") or request.session.get("username")
    q = hub.subscribe(cid, user_id=user_id, username=username)

    async def gen() -> AsyncIterator[str]:
        try:
            hello = {
                "type": "hello",
                "client_id": cid,
                "subscribers": hub.subscriber_count(),
            }
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.to_thread(q.get, True, HEARTBEAT_SECONDS)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(cid)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
