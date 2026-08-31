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
    """SSE stream. Auth is enforced by the ASGI AuthGateMiddleware (session cookie)."""
    cid = (client_id or "").strip()
    if not cid:
        return JSONResponse({"detail": "client_id required"}, status_code=400)

    user_id = request.session.get("user_id")
    username = request.session.get("display_name") or request.session.get("username")
    loop = asyncio.get_running_loop()
    conn_id, q = hub.subscribe(cid, user_id=user_id, username=username, loop=loop)
    wake = hub.wake_for(conn_id)

    async def gen() -> AsyncIterator[str]:
        last_ping = time.monotonic()
        try:
            hello = {"type": "hello", "client_id": cid, **live_identity()}
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                drained = False
                while True:
                    try:
                        event = q.get_nowait()
                    except queue.Empty:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                    drained = True
                if drained:
                    continue
                # Do not probe client drop via a cancelled receive — under
                # uvloop that helper can busy-spin and skip the wait below.
                # StreamingResponse cancels this generator when the client goes.
                now = time.monotonic()
                wait_for = HEARTBEAT_SECONDS - (now - last_ping)
                if wait_for <= 0:
                    last_ping = time.monotonic()
                    ping = {"type": "ping", **cached_live_identity()}
                    yield f"data: {json.dumps(ping)}\n\n"
                    continue
                if wake is None:
                    await asyncio.sleep(min(2.0, wait_for))
                    continue
                wake.clear()
                try:
                    event = q.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                    continue
                except queue.Empty:
                    pass
                try:
                    await asyncio.wait_for(wake.wait(), timeout=max(0.05, wait_for))
                except asyncio.TimeoutError:
                    pass
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
