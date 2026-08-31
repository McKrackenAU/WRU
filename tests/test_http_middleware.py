"""Pure-ASGI middleware: no BaseHTTPMiddleware body pump, auth + live headers still work."""

from __future__ import annotations

import asyncio
import inspect
import json
from base64 import b64encode

from itsdangerous import TimestampSigner
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from app.http_middleware import AuthGateMiddleware, LiveIdentityMiddleware, NoCacheStaticMiddleware

SECRET = "test-http-middleware-secret"


def _session_cookie(data: dict) -> str:
    payload = b64encode(json.dumps(data).encode("utf-8"))
    return TimestampSigner(SECRET).sign(payload).decode("utf-8")


async def _ok(request):
    return JSONResponse({"ok": True})


async def _sse(request):
    async def gen():
        yield "data: hello\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _static_js(request):
    return JSONResponse({"js": True})


def _stack() -> SessionMiddleware:
    inner = Starlette(
        routes=[
            Route("/api/ping", _ok),
            Route("/api/live/events", _sse),
            Route("/api/admin/users", _ok),
            Route("/comms", _ok),
            Route("/login", _ok),
            Route("/static/js/app.js", _static_js),
        ]
    )
    app = LiveIdentityMiddleware(inner)
    app = NoCacheStaticMiddleware(app)
    app = AuthGateMiddleware(app)
    return SessionMiddleware(app, secret_key=SECRET, session_cookie="wru_session")


def _call(app, path: str, cookie: str | None = None) -> tuple[int, dict[str, str], bytes]:
    headers = [(b"host", b"test")]
    if cookie:
        headers.append((b"cookie", f"wru_session={cookie}".encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    messages: list[dict] = []
    body_sent = False
    hang = asyncio.Event()

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        # StreamingResponse listens for disconnect on a side task. A
        # receive() that returns immediately busy-loops the event loop.
        await hang.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in start["headers"]}
    return int(start["status"]), hdrs, body


def _authed_cookie(role: str = "admin", **extra) -> str:
    return _session_cookie(
        {
            "user_id": 1,
            "username": "admin",
            "display_name": "Admin",
            "role": role,
            "must_change_password": False,
            **extra,
        }
    )


def test_middleware_is_not_base_http_wrapper():
    for cls in (AuthGateMiddleware, LiveIdentityMiddleware, NoCacheStaticMiddleware):
        assert not issubclass(cls, BaseHTTPMiddleware)
        assert inspect.iscoroutinefunction(cls.__call__)


def test_unauthenticated_api_is_401():
    status, _headers, body = _call(_stack(), "/api/ping")
    assert status == 401
    assert json.loads(body)["detail"] == "Not authenticated"


def test_unauthenticated_page_redirects_to_login():
    status, headers, _body = _call(_stack(), "/comms")
    assert status == 302
    assert "/login?next=" in headers["location"]


def test_public_login_is_open():
    status, _headers, _body = _call(_stack(), "/login")
    assert status == 200


def test_live_headers_on_authed_api():
    status, headers, body = _call(_stack(), "/api/ping", _authed_cookie())
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert headers.get("x-wru-revision")
    assert headers.get("x-wru-boot-id")
    assert headers.get("x-wru-asset-version")


def test_sse_streams_with_live_headers():
    status, headers, body = _call(_stack(), "/api/live/events", _authed_cookie())
    assert status == 200
    assert "text/event-stream" in headers["content-type"]
    assert b"data: hello" in body
    assert headers.get("x-wru-revision")


def test_static_js_is_uncached():
    status, headers, _body = _call(_stack(), "/static/js/app.js", _authed_cookie())
    assert status == 200
    assert "no-store" in headers.get("cache-control", "")


def test_non_admin_blocked_from_admin_api():
    status, _headers, body = _call(_stack(), "/api/admin/users", _authed_cookie(role="user"))
    assert status == 403
    assert json.loads(body)["detail"] == "Admin access required"


def test_ops_blocked_from_comms_page():
    status, headers, _body = _call(_stack(), "/comms", _authed_cookie(role="user"))
    assert status == 302
    assert headers["location"] == "/"


def test_password_change_required_redirects():
    status, _headers, body = _call(_stack(), "/api/ping", _authed_cookie(must_change_password=True))
    assert status == 403
    assert json.loads(body)["detail"] == "Password change required"
