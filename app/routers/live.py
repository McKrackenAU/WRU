"""Server-Sent Events for live multi-user data refresh."""

from __future__ import annotations

import asyncio
import json
import queue
import time
from typing import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..live_hub import cached_live_identity, hub, live_identity

router = APIRouter(prefix="/api/live", tags=["live"])

HEARTBEAT_SECONDS = 15.0


@router.get("/revision")
def live_revision():
    """Lightweight poll target when SSE is blocked or reconnecting."""
    return JSONResponse(
        cached_live_identity(),
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
        last_ping = time.monotonic()
        try:
            hello = {"type": "hello", "client_id": cid, **live_identity()}
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = q.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                    continue
                except queue.Empty:
                    pass
                now = time.monotonic()
                if now - last_ping >= HEARTBEAT_SECONDS:
                    last_ping = now
                    ping = {"type": "ping", **cached_live_identity()}
                    yield f"data: {json.dumps(ping)}\n\n"
                else:
                    await asyncio.sleep(0.4)
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
