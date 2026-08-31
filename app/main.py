from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .auth import require_admin, require_comms, secret_key
from .database import get_db
from .financial_year import fy_choices
from .http_middleware import AuthGateMiddleware, LiveIdentityMiddleware, NoCacheStaticMiddleware
from .migrate import run_migrations
from .doc_categories import category_meta, ensure_doc_category_seed
from .models import LookupItem, Site, SiteCouncil, User
from .routers import (
    activity,
    asphalt,
    auth as auth_router,
    backup,
    calendar,
    columns,
    comms,
    costs,
    dashboard,
    documents,
    export,
    gantt,
    import_tracker,
    live,
    map_layers,
    notifications,
    settings_admin,
    sites,
    spend,
    stages,
    system,
    tags,
    tracking,
    users as users_router,
)
from .schemas import MetaOut
from .settings_store import get_rules
from .stage_registry import active_programs, ensure_lookup_seed, stage_meta
from .upload_limits import configure_multipart_limits
from .version import version_string

STATIC_DIR = Path(__file__).resolve().parent / "static"
_ASSET_BUST_RE = re.compile(
    r'((?:href|src)=")(/static/(?:css|js|brand|vendor)/[^"?#]+)(")',
    re.IGNORECASE,
)

app = FastAPI(
    title="WRU TGS Tracker",
    description="Ventia-styled traffic guidance / MoA workflow tracker with custom columns, tracking, documents, archive, and map.",
    version=version_string(),
)

configure_multipart_limits()

run_migrations()

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(notifications.inbox_router)
app.include_router(notifications.admin_router)
app.include_router(tags.public_router)
app.include_router(tags.admin_router)
app.include_router(live.router)
app.include_router(activity.router)
app.include_router(sites.router)
app.include_router(columns.router)
app.include_router(tracking.router)
app.include_router(documents.router)
app.include_router(comms.router)
app.include_router(calendar.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(map_layers.router)
app.include_router(costs.router)
app.include_router(asphalt.router)
app.include_router(gantt.router)
app.include_router(spend.router)
app.include_router(stages.router)
app.include_router(settings_admin.router)
app.include_router(import_tracker.router)
app.include_router(system.router)
app.include_router(backup.router)


# Starlette runs last-added middleware first on the request.
# These are pure ASGI (not BaseHTTPMiddleware) so SSE is not pumped
# through in-memory streams — that wrapper was pinning uvicorn at 100%+.
app.add_middleware(LiveIdentityMiddleware)
app.add_middleware(NoCacheStaticMiddleware)
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key(),
    session_cookie="wru_session",
    same_site="lax",
    https_only=os.environ.get("WRU_COOKIE_HTTPS", "").strip().lower() in {"1", "true", "yes"},
    max_age=60 * 60 * 12,
)


@app.get("/api/meta", response_model=MetaOut)
def meta(db: Session = Depends(get_db)):
    # Auth is enforced by middleware; meta is available to any logged-in user.
    rules = get_rules(db)
    ensure_lookup_seed(db)
    ensure_doc_category_seed(db)
    doc_defs = category_meta(db)
    seeded_programs = active_programs(db)
    used_programs = [
        p
        for (p,) in db.query(distinct(Site.program)).filter(Site.program.isnot(None)).order_by(Site.program).all()
        if p
    ]
    programs = list(dict.fromkeys([*seeded_programs, *used_programs]))
    lookup_councils = [
        r.value
        for r in db.query(LookupItem)
        .filter(LookupItem.kind == "council", LookupItem.active.is_(True))
        .order_by(LookupItem.position.asc(), LookupItem.value.asc())
        .all()
    ]
    used_councils = [
        c
        for (c,) in db.query(distinct(SiteCouncil.council_name)).order_by(SiteCouncil.council_name).all()
        if c
    ]
    councils = list(dict.fromkeys([*lookup_councils, *used_councils]))
    lookup_roads = [
        r.value
        for r in db.query(LookupItem)
        .filter(LookupItem.kind == "road", LookupItem.active.is_(True))
        .order_by(LookupItem.value.asc())
        .all()
    ]
    roads = list(dict.fromkeys(lookup_roads))
    return {
        "workflow_stages": stage_meta(db),
        "doc_categories": [d["key"] for d in doc_defs],
        "doc_category_defs": doc_defs,
        "priority_threshold_days": rules.priority_must_have_days,
        "priority_must_have_days": rules.priority_must_have_days,
        "must_have_offset_business_days": rules.must_have_offset_business_days,
        "council_no_objection_business_days": rules.council_no_objection_business_days,
        "moa_wait_sla_business_days": rules.moa_wait_sla_business_days,
        "financial_years": fy_choices(),
        "programs": programs,
        "councils": councils,
        "roads": roads,
        "rules": rules.as_dict(),
        "asset_version": version_string(),
    }


def _import_map(ver: str) -> str:
    imports: dict[str, str] = {}
    js_dir = STATIC_DIR / "js"
    if js_dir.is_dir():
        for path in sorted(js_dir.glob("*.js")):
            url = f"/static/js/{path.name}"
            imports[url] = f"{url}?v={ver}"
    return json.dumps({"imports": imports}, separators=(",", ":"))


def _page(name: str) -> HTMLResponse:
    """Serve HTML with cache-busted assets + import map for ES module graph."""
    path = STATIC_DIR / name
    if not path.exists():
        path = STATIC_DIR / "index.html"
    html = path.read_text(encoding="utf-8")
    ver = version_string()

    def _bust(match: re.Match[str]) -> str:
        url = match.group(2)
        if "?" in url:
            return match.group(0)
        return f"{match.group(1)}{url}?v={ver}{match.group(3)}"

    html = _ASSET_BUST_RE.sub(_bust, html)

    boot = f"""<script type="importmap">{_import_map(ver)}</script>
<meta name="wru-asset-version" content="{ver}" />
<link rel="manifest" href="/manifest.webmanifest" />
<link rel="apple-touch-icon" href="/static/brand/pwa-180.png" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-title" content="WRU TGS" />
<meta name="mobile-web-app-capable" content="yes" />
<script>
window.__WRU_ASSET_V={json.dumps(ver)};
window.addEventListener("error",function(e){{
  var m=String(e&&e.message||"");
  if(m.indexOf("export")===-1&&m.indexOf("Failed to fetch")===-1&&m.indexOf("import")===-1)return;
  if(document.getElementById("wru-boot-error"))return;
  var d=document.createElement("div");
  d.id="wru-boot-error";
  d.setAttribute("role","alert");
  d.className="boot-error";
  d.innerHTML="<strong>App scripts failed to load.</strong> Hard-refresh with <kbd>Ctrl+Shift+R</kbd> (or clear cache), then try again. If this persists, run the shell updater once as root.";
  document.body.prepend(d);
}});
</script>
"""
    if "</head>" in html:
        html = html.replace("</head>", boot + "</head>", 1)
    else:
        html = boot + html

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/login")
def login_page():
    return _page("login.html")


@app.get("/manifest.webmanifest")
def pwa_manifest():
    path = STATIC_DIR / "manifest.webmanifest"
    return Response(
        path.read_text(encoding="utf-8"),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/sw.js")
def pwa_service_worker():
    body = (STATIC_DIR / "sw.js").read_text(encoding="utf-8").replace("__WRU_ASSET_V__", version_string())
    return Response(
        body,
        media_type="text/javascript; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/password")
def password_page():
    return _page("password.html")


@app.get("/account")
def account_page():
    return _page("account.html")


@app.get("/")
def index():
    return _page("index.html")


@app.get("/dashboard")
def dashboard_page():
    return _page("dashboard.html")


@app.get("/tracking")
def tracking_page():
    return _page("tracking.html")


@app.get("/lists")
def lists_page():
    return _page("lists.html")


@app.get("/archive")
def archive_page():
    return _page("archive.html")


@app.get("/map")
def map_page():
    return _page("map.html")


@app.get("/documents")
def documents_page():
    return _page("documents.html")


@app.get("/comms")
def comms_page(_: User = Depends(require_comms)):
    return _page("comms.html")


@app.get("/calendar")
def calendar_page():
    return _page("calendar.html")


@app.get("/costs")
def costs_page():
    return _page("costs.html")


@app.get("/asphalt")
def asphalt_page():
    return _page("asphalt.html")


@app.get("/gantt")
def gantt_page():
    return _page("gantt.html")


@app.get("/spend")
def spend_page():
    return _page("spend.html")


# —— Admin console (separate shell from day-to-day tracker) ——
@app.get("/admin")
def admin_home(_: User = Depends(require_admin)):
    return _page("admin.html")


@app.get("/admin/stages")
def admin_stages_page(_: User = Depends(require_admin)):
    return _page("stages.html")


@app.get("/admin/settings")
def admin_settings_page(_: User = Depends(require_admin)):
    return _page("settings.html")


@app.get("/admin/rates")
def admin_rates_page(_: User = Depends(require_admin)):
    return _page("rates.html")


@app.get("/admin/asphalt")
def admin_asphalt_page(_: User = Depends(require_admin)):
    return _page("asphalt-rates.html")


@app.get("/admin/system")
def admin_system_page(_: User = Depends(require_admin)):
    return _page("system.html")


@app.get("/admin/backup")
def admin_backup_page(_: User = Depends(require_admin)):
    return _page("backup.html")


@app.get("/admin/users")
def admin_users_page(_: User = Depends(require_admin)):
    return _page("users.html")


@app.get("/admin/notifications")
def admin_notifications_page(_: User = Depends(require_admin)):
    return _page("notifications.html")


@app.get("/admin/tags")
def admin_tags_page(_: User = Depends(require_admin)):
    return _page("tags.html")


@app.get("/admin/storage")
def admin_storage_page(_: User = Depends(require_admin)):
    return _page("storage.html")


# Legacy bookmarks → admin
@app.get("/stages")
def stages_redirect():
    return RedirectResponse("/admin/stages", status_code=302)


@app.get("/settings")
def settings_redirect():
    return RedirectResponse("/admin/settings", status_code=302)


@app.get("/rates")
def rates_redirect():
    return RedirectResponse("/admin/rates", status_code=302)


@app.get("/system")
def system_redirect():
    return RedirectResponse("/admin/system", status_code=302)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
