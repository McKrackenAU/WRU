"""Live event hub for multi-user refresh.

Revision is persisted on disk so all workers (and process restarts / system
updates) share a monotonically increasing counter. SSE still fans out in
this process; clients also poll ``/api/live/revision`` as a backup.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from typing import Any

from starlette.requests import Request

from .database import DATA_DIR

STATE_PATH = DATA_DIR / "live_state.json"

_revision = 0
_revision_lock = threading.Lock()
_boot_id = ""
_started_at = time.time()
_state_mtime_ns = 0
_ident_cache_mono = 0.0
_ident_cache: dict[str, Any] | None = None
_IDENT_CACHE_SECONDS = 0.75


def boot_id() -> str:
    return _boot_id


def asset_version() -> str:
    from .version import version_string

    return version_string()


def _read_disk_state() -> tuple[int, int, str]:
    try:
        st = STATE_PATH.stat()
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return (
            int(data.get("revision") or 0),
            int(getattr(st, "st_mtime_ns", 0) or 0),
            str(data.get("boot_id") or "").strip(),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 0, 0, ""


def _read_disk_revision() -> tuple[int, int]:
    rev, mtime_ns, _boot = _read_disk_state()
    return rev, mtime_ns


def _refresh_from_disk_locked() -> None:
    global _revision, _state_mtime_ns, _boot_id
    disk_rev, mtime_ns, disk_boot = _read_disk_state()
    if disk_boot:
        _boot_id = disk_boot
    if mtime_ns != _state_mtime_ns and disk_rev > _revision:
        _revision = disk_rev
        _state_mtime_ns = mtime_ns
    elif mtime_ns != _state_mtime_ns:
        _state_mtime_ns = mtime_ns


def _write_state_locked() -> None:
    global _state_mtime_ns
    payload = {
        "revision": _revision,
        "boot_id": _boot_id,
        "asset_version": asset_version(),
        "updated_at": time.time(),
    }
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(STATE_PATH)
    try:
        _state_mtime_ns = int(STATE_PATH.stat().st_mtime_ns)
    except OSError:
        _state_mtime_ns = 0


def bump_revision() -> int:
    global _revision, _ident_cache, _ident_cache_mono
    with _revision_lock:
        _refresh_from_disk_locked()
        _revision += 1
        _write_state_locked()
        _ident_cache = None
        _ident_cache_mono = 0.0
        return _revision


def current_revision() -> int:
    with _revision_lock:
        _refresh_from_disk_locked()
        return _revision


def live_identity() -> dict[str, Any]:
    """Public fields every client needs to stay in sync across restarts."""
    return {
        "revision": current_revision(),
        "boot_id": _boot_id,
        "asset_version": asset_version(),
        "started_at": _started_at,
        "subscribers": hub.subscriber_count(),
    }


def cached_live_identity() -> dict[str, Any]:
    """Same as live_identity, but skip disk/lock on the hot API-header path."""
    global _ident_cache, _ident_cache_mono
    now = time.monotonic()
    cached = _ident_cache
    if cached is not None and (now - _ident_cache_mono) < _IDENT_CACHE_SECONDS:
        return cached
    ident = live_identity()
    _ident_cache = ident
    _ident_cache_mono = now
    return ident


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
        only_user_ids: list[int] | None = None,
    ) -> int:
        """Fan out to all subscribers. Returns how many queues accepted the event."""
        wanted = None
        if only_user_ids:
            wanted = {int(x) for x in only_user_ids if x}
        with self._lock:
            items = list(self._subs.items())
            meta_by_conn = dict(self._meta)
        sent = 0
        for conn_id, q in items:
            meta = meta_by_conn.get(conn_id) or {}
            if skip_client_id and meta.get("client_id") == skip_client_id:
                continue
            if wanted is not None:
                try:
                    uid = int(meta.get("user_id") or 0)
                except (TypeError, ValueError):
                    uid = 0
                if uid not in wanted:
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


def _init_cluster_state() -> None:
    """Share one boot_id + revision across workers so clients do not flap."""
    global _boot_id
    with _revision_lock:
        _refresh_from_disk_locked()
        if not _boot_id:
            _boot_id = secrets.token_urlsafe(12)
            _write_state_locked()


_init_cluster_state()


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
        "boot_id": _boot_id,
        "asset_version": asset_version(),
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


def publish_inbox_event(user_ids: list[int] | None = None) -> int:
    """Push a bell refresh to matching SSE clients. Does not bump revision."""
    ids = []
    seen: set[int] = set()
    for raw in user_ids or []:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        ids.append(uid)
    event = {
        "type": "notification",
        "user_ids": ids,
        "revision": current_revision(),
        "boot_id": _boot_id,
        "asset_version": asset_version(),
        "ts": time.time(),
    }
    return hub.publish(event, only_user_ids=ids or None)
