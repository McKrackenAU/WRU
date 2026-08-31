"""ASGI middleware that does not wrap response bodies.

Starlette's BaseHTTPMiddleware copies every response through an in-memory
stream and a background task. Three of those layers on a long-lived SSE
connection pin a full core (seen as uvicorn at 100%+ in top). These
classes only inspect scope / rewrite response-start headers.
"""

from __future__ import annotations

from urllib.parse import quote

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import (
    ADMIN_ROLE,
    COMMS_ROLE,
    is_admin_path,
    is_comms_path,
    is_password_change_allowed_path,
    is_public_path,
)
from .live_hub import cached_live_identity


class NoCacheStaticMiddleware:
    """Prevent stale JS/CSS after deploys (ES module imports ignore HTML ?v= busting)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not (
            path.startswith("/static/js/")
            or path.startswith("/static/css/")
            or path.startswith("/static/vendor/")
        ):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                headers["Pragma"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_wrapper)


class LiveIdentityMiddleware:
    """Stamp revision / boot / version on API responses so every screen can stay live."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        # Inbox fetches must not carry live-identity headers. After a deploy,
        # leftover tabs treated X-WRU-Asset-Version drift as "app update",
        # refetched /api/notifications, saw the same header, and spun at 100%+.
        if path.startswith("/api/notifications"):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                try:
                    ident = cached_live_identity()
                    headers = MutableHeaders(scope=message)
                    headers["X-WRU-Revision"] = str(ident["revision"])
                    headers["X-WRU-Boot-Id"] = str(ident["boot_id"])
                    headers["X-WRU-Asset-Version"] = str(ident["asset_version"])
                except Exception:
                    pass
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthGateMiddleware:
    """Require a login session for app pages and APIs; admins for admin surfaces."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        method = request.method.upper()

        if method == "OPTIONS" or is_public_path(path):
            await self.app(scope, receive, send)
            return

        async def send_response(response) -> None:
            await response(scope, receive, send)

        user_id = request.session.get("user_id")
        if not user_id:
            if path.startswith("/api/"):
                await send_response(JSONResponse({"detail": "Not authenticated"}, status_code=401))
                return
            next_q = quote(path + (("?" + request.url.query) if request.url.query else ""))
            await send_response(RedirectResponse(f"/login?next={next_q}", status_code=302))
            return

        if is_admin_path(path, method) and request.session.get("role") != "admin":
            if path.startswith("/api/"):
                await send_response(JSONResponse({"detail": "Admin access required"}, status_code=403))
                return
            await send_response(RedirectResponse("/", status_code=302))
            return

        if is_comms_path(path) and request.session.get("role") not in {ADMIN_ROLE, COMMS_ROLE}:
            if path.startswith("/api/"):
                await send_response(JSONResponse({"detail": "Comms access required"}, status_code=403))
                return
            await send_response(RedirectResponse("/", status_code=302))
            return

        if request.session.get("must_change_password") and not is_password_change_allowed_path(path):
            if path.startswith("/api/"):
                await send_response(JSONResponse({"detail": "Password change required"}, status_code=403))
                return
            next_q = quote(path + (("?" + request.url.query) if request.url.query else ""))
            await send_response(RedirectResponse(f"/password?next={next_q}", status_code=302))
            return

        await self.app(scope, receive, send)
