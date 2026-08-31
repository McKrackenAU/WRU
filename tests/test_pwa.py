"""PWA installability: manifest, service worker, live alerts wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = (ROOT / "app/static/manifest.webmanifest").read_text(encoding="utf-8")
SW = (ROOT / "app/static/sw.js").read_text(encoding="utf-8")
PWA_JS = (ROOT / "app/static/js/pwa.js").read_text(encoding="utf-8")
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
LOGIN_JS = (ROOT / "app/static/js/login.js").read_text(encoding="utf-8")
LOGIN_HTML = (ROOT / "app/static/login.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")


def test_manifest_is_installable():
    assert '"display": "standalone"' in MANIFEST
    assert '"start_url": "/"' in MANIFEST
    assert "pwa-192.png" in MANIFEST
    assert "pwa-512.png" in MANIFEST
    assert '"name": "WRU TGS Tracker"' in MANIFEST


def test_service_worker_does_not_cache_api():
    assert 'startsWith("/api/")' in SW
    assert "skipWaiting" in SW
    assert "clients.claim" in SW
    assert "__WRU_ASSET_V__" in SW


def test_pwa_icons_exist():
    for name in ("pwa-192.png", "pwa-512.png", "pwa-180.png"):
        path = ROOT / "app/static/brand" / name
        assert path.is_file()
        assert path.stat().st_size > 100


def test_pages_link_manifest_and_sw_routes():
    assert 'rel="manifest"' in MAIN
    assert '"/manifest.webmanifest"' in MAIN
    assert '"/sw.js"' in MAIN
    assert "Service-Worker-Allowed" in MAIN


def test_client_registers_service_worker():
    assert "registerServiceWorker" in PWA_JS
    assert "notifyLiveIfBackground" in PWA_JS
    assert "initPwaChrome" in PWA_JS
    assert "registerServiceWorker()" in COMMON
    assert "initPwaChrome()" in COMMON
    assert "notifyLiveIfBackground" in COMMON
    assert "registerServiceWorker()" in LOGIN_JS
    assert 'id="btnInstallApp"' in LOGIN_HTML
    assert "login-pwa-hint" not in LOGIN_HTML
    assert "Chrome or Edge can install" not in LOGIN_HTML
    assert "beforeinstallprompt" in PWA_JS
    assert "isStandalonePwa" in PWA_JS
    assert 'id="btnInstallApp"' in COMMON
    assert 'id="btnLiveAlerts"' in COMMON
