"""Server-Sent Events for live multi-user data refresh."""

from __future__ import annotations

import asyncio
import json
import queue
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..live_hub import hub, live_identity

router = APIRouter(prefix="/api/live", tags=["live"])

HEARTBEAT_SECONDS = 15.0


@router.get("/revision")
def live_revision():
    """Lightweight poll target when SSE is blocked or reconnecting."""
    return JSONResponse(
        live_identity(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/events")
async def live_events(
    request: Request,
    client_id: str | None = Query(default=None, max_length=64),
):
    """SSE stream. Auth is enforced by AuthGateMiddleware (session cookie)."""
    cid = (client_id or "").strip()
    if not cid:
        return JSONResponse({"detail": "client_id required"}, status_code=400)

    user_id = request.session.get("user_id")
    username = request.session.get("display_name") or request.session.get("username")
    conn_id, q = hub.subscribe(cid, user_id=user_id, username=username)

    async def gen() -> AsyncIterator[str]:
        try:
            hello = {"type": "hello", "client_id": cid, **live_identity()}
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.to_thread(q.get, True, HEARTBEAT_SECONDS)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    ping = {"type": "ping", **live_identity()}
                    yield f"data: {json.dumps(ping)}\n\n"
        finally:
            hub.unsubscribe(conn_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
