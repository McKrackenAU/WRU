"""In-process live event hub for multi-user register refresh.

Single uvicorn worker assumed (current deploy). Thread-safe so sync
route handlers can publish after commits.
"""

from __future__ import annotations

import queue
import secrets
import threading
import time
from typing import Any

from starlette.requests import Request

_revision = 0
_revision_lock = threading.Lock()


def bump_revision() -> int:
    global _revision
    with _revision_lock:
        _revision += 1
        return _revision


def current_revision() -> int:
    with _revision_lock:
        return _revision


class LiveHub:
    def __init__(self) -> None:
        self._subs: dict[str, queue.Queue] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def subscribe(
        self,
        client_id: str,
        *,
        user_id: int | None = None,
        username: str | None = None,
    ) -> tuple[str, queue.Queue]:
        """Return (connection_id, queue). Each SSE connection gets its own conn id."""
        conn_id = secrets.token_urlsafe(16)
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subs[conn_id] = q
            self._meta[conn_id] = {
                "client_id": client_id,
                "user_id": user_id,
                "username": username,
                "connected_at": time.time(),
            }
        return conn_id, q

    def unsubscribe(self, conn_id: str) -> None:
        with self._lock:
            self._subs.pop(conn_id, None)
            self._meta.pop(conn_id, None)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(
        self,
        event: dict[str, Any],
        *,
        skip_client_id: str | None = None,
    ) -> int:
        """Fan out to all subscribers. Returns how many queues accepted the event."""
        with self._lock:
            items = list(self._subs.items())
            meta_by_conn = dict(self._meta)
        sent = 0
        for conn_id, q in items:
            if skip_client_id:
                meta = meta_by_conn.get(conn_id) or {}
                if meta.get("client_id") == skip_client_id:
                    continue
            try:
                q.put_nowait(event)
                sent += 1
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(event)
                    sent += 1
                except queue.Full:
                    pass
        return sent


hub = LiveHub()


def live_actor_from_request(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {"actor_user_id": None, "actor_name": None, "client_id": None}
    client_id = (
        request.headers.get("X-WRU-Client-Id")
        or request.query_params.get("client_id")
        or ""
    ).strip() or None
    return {
        "actor_user_id": request.session.get("user_id"),
        "actor_name": request.session.get("display_name") or request.session.get("username"),
        "client_id": client_id,
    }


def notify_sites_changed(
    *,
    site_ids: list[int] | None = None,
    reason: str = "update",
    actor_user_id: int | None = None,
    actor_name: str | None = None,
    client_id: str | None = None,
) -> int:
    """Broadcast a soft invalidate. ``site_ids=None`` means full reload."""
    revision = bump_revision()
    event = {
        "type": "sites_changed",
        "site_ids": site_ids,
        "reason": reason,
        "actor_user_id": actor_user_id,
        "actor_name": actor_name,
        "client_id": client_id,
        "revision": revision,
        "ts": time.time(),
    }
    return hub.publish(event, skip_client_id=client_id)


def notify_from_request(
    request: Request | None,
    *,
    site_ids: list[int] | None = None,
    reason: str = "update",
) -> int:
    return notify_sites_changed(
        site_ids=site_ids,
        reason=reason,
        **live_actor_from_request(request),
    )
