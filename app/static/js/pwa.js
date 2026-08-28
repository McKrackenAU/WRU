/** Progressive Web App helpers: install to desktop + background live alerts. */

const INSTALL_DISMISSED_KEY = "wru-pwa-install-dismissed";

export function isStandalonePwa() {
  try {
    if (window.matchMedia?.("(display-mode: standalone)")?.matches) return true;
    if (window.matchMedia?.("(display-mode: window-controls-overlay)")?.matches) return true;
  } catch {
    /* ignore */
  }
  return Boolean(window.navigator.standalone);
}

export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const ver = window.__WRU_ASSET_V || "";
  const url = `/sw.js?v=${encodeURIComponent(ver)}`;
  navigator.serviceWorker.register(url, { scope: "/", updateViaCache: "none" }).catch(() => {});
}

let deferredInstall = null;
let pwaWired = false;

function isIosSafari() {
  const ua = navigator.userAgent || "";
  const iOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const webkit = /WebKit/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  return iOS && webkit;
}

function show(el, on) {
  if (!el) return;
  el.hidden = !on;
}

function syncStandaloneClass() {
  document.documentElement.classList.toggle("pwa-standalone", isStandalonePwa());
}

function syncInstallButtons() {
  const installed = isStandalonePwa();
  const canPrompt = Boolean(deferredInstall);
  const ios = isIosSafari() && !installed;
  document.querySelectorAll("#btnInstallApp").forEach((btn) => {
    show(btn, !installed && (canPrompt || ios));
  });
}

function syncAlertButtons() {
  const alerts = typeof Notification !== "undefined";
  const need = alerts && Notification.permission === "default";
  document.querySelectorAll("#btnLiveAlerts").forEach((btn) => {
    show(btn, need);
  });
}

async function requestLiveAlerts() {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  try {
    const result = await Notification.requestPermission();
    syncAlertButtons();
    return result === "granted";
  } catch {
    return false;
  }
}

async function runInstall(btn) {
  if (deferredInstall) {
    const ev = deferredInstall;
    deferredInstall = null;
    syncInstallButtons();
    try {
      const choice = await ev.prompt();
      if (choice?.outcome === "accepted") {
        await requestLiveAlerts();
      }
    } catch {
      /* user dismissed */
    }
    return;
  }
  if (isIosSafari()) {
    window.alert("On iPhone or iPad: tap Share, then Add to Home Screen.");
    return;
  }
  if (btn) btn.hidden = true;
}

export function initPwaChrome() {
  syncStandaloneClass();
  if (!pwaWired) {
    pwaWired = true;
    window.addEventListener("beforeinstallprompt", (ev) => {
      ev.preventDefault();
      try {
        if (sessionStorage.getItem(INSTALL_DISMISSED_KEY) === "1") return;
      } catch {
        /* ignore */
      }
      deferredInstall = ev;
      syncInstallButtons();
    });
    window.addEventListener("appinstalled", () => {
      deferredInstall = null;
      syncInstallButtons();
      requestLiveAlerts();
    });
    window.matchMedia?.("(display-mode: standalone)")?.addEventListener?.("change", () => {
      syncStandaloneClass();
      syncInstallButtons();
    });
  }

  document.querySelectorAll("#btnInstallApp").forEach((btn) => {
    if (btn.dataset.pwaBound) return;
    btn.dataset.pwaBound = "1";
    btn.addEventListener("click", () => runInstall(btn));
  });
  document.querySelectorAll("#btnLiveAlerts").forEach((btn) => {
    if (btn.dataset.pwaBound) return;
    btn.dataset.pwaBound = "1";
    btn.addEventListener("click", () => requestLiveAlerts());
  });

  syncInstallButtons();
  syncAlertButtons();
}

/** OS notification when another user saves and this window is in the background. */
export function notifyLiveIfBackground(event) {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  if (document.visibilityState === "visible") return;
  const who = event?.actor_name || "A teammate";
  const reason = event?.reason || "update";
  const body =
    reason === "gantt"
      ? `${who} updated the Gantt`
      : reason === "restart"
        ? "Tracker reconnected — refreshing"
        : `${who} saved — live update`;
  try {
    const n = new Notification("WRU TGS Tracker", {
      body,
      icon: "/static/brand/pwa-192.png",
      badge: "/static/brand/pwa-192.png",
      tag: "wru-live",
    });
    n.onclick = () => {
      try {
        window.focus();
      } catch {
        /* ignore */
      }
      n.close();
    };
  } catch {
    /* Notifications can fail in insecure contexts */
  }
}
