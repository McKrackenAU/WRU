export const THEME_KEY = "wru-tgs-theme";

export function $(id) {
  return document.getElementById(id);
}

export function on(id, event, handler) {
  const el = $(id);
  if (!el) return false;
  el.addEventListener(event, handler);
  return true;
}

let _sessionUser = null;

export function setSessionUser(user) {
  _sessionUser = user || null;
  try {
    if (user) {
      localStorage.setItem("wru_user", user.display_name || user.username || "");
      localStorage.setItem("wru_role", user.role || "user");
    }
  } catch {
    /* ignore */
  }
}

export function currentUser() {
  return _sessionUser;
}

export function isAdminUser() {
  if (_sessionUser) return _sessionUser.role === "admin";
  try {
    return localStorage.getItem("wru_role") === "admin";
  } catch {
    return false;
  }
}

/** Turn FastAPI / fetch failure payloads into a readable message (never blank). */
export function formatApiDetail(detail, fallback = "Request failed") {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail.trim() || fallback;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item == null) return "";
      if (typeof item === "string") return item;
      const loc = Array.isArray(item.loc)
        ? item.loc.filter((p) => p !== "body" && p !== "query").join(".")
        : "";
      const msg = item.msg || item.message || "";
      if (loc && msg) return `${loc}: ${msg}`;
      return msg || loc || "";
    }).filter(Boolean);
    return parts.join("; ") || fallback;
  }
  if (typeof detail === "object") {
    if (detail.msg || detail.message) return String(detail.msg || detail.message);
    try {
      const raw = JSON.stringify(detail);
      return raw && raw !== "{}" ? raw : fallback;
    } catch {
      return fallback;
    }
  }
  return String(detail) || fallback;
}

export function errorMessage(err, fallback = "Something went wrong") {
  if (err == null) return fallback;
  if (typeof err === "string") return err.trim() || fallback;
  const msg = err.message || err.detail || "";
  if (typeof msg === "string" && msg.trim()) return msg.trim();
  return formatApiDetail(msg, fallback);
}

export async function api(path, options = {}) {
  const ctrl = new AbortController();
  const timeoutMs = options.timeoutMs ?? 45000;
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      cache: "no-store",
      credentials: "include",
      ...options,
      signal: options.signal || ctrl.signal,
    });
    if (res.status === 401 && !String(path).startsWith("/api/auth/")) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `/login?next=${next}`;
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      let detail = res.statusText || `HTTP ${res.status}`;
      try {
        const body = await res.json();
        detail = formatApiDetail(body?.detail ?? body, detail);
      } catch (_) {
        /* ignore non-JSON error bodies */
      }
      throw new Error(detail || `Request failed (${res.status})`);
    }
    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    return res;
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new Error(`Request timed out (${path}). Check the server or try again.`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function fmtDate(value) {
  if (!value) return "";
  const [y, m, d] = String(value).split("-");
  if (!y || !m || !d) return value;
  return `${d}/${m}/${y}`;
}

/** Actor name for audit fields — prefers the signed-in session display name. */
export function userName() {
  const fromSession = (_sessionUser?.display_name || _sessionUser?.username || "").trim();
  if (fromSession) return fromSession;
  try {
    return (localStorage.getItem("wru_user") || "").trim() || null;
  } catch {
    return null;
  }
}

export function saveUserName() {
  /* session identity is authoritative */
}

export function loadUserName() {
  /* session identity is authoritative */
}

export async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include", cache: "no-store" });
  } catch {
    /* ignore */
  }
  try {
    localStorage.removeItem("wru_role");
  } catch {
    /* ignore */
  }
  location.href = "/login";
}

function currentTheme() {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
  root.style.colorScheme = mode;
  document.querySelectorAll("#themeToggle, [data-theme-toggle]").forEach((btn) => {
    btn.textContent = mode === "dark" ? "Light" : "Dark";
    btn.setAttribute(
      "aria-label",
      mode === "dark" ? "Switch to light mode" : "Switch to dark mode"
    );
  });
}

export function initThemeToggle() {
  applyTheme(currentTheme());
  document.querySelectorAll("#themeToggle, [data-theme-toggle]").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  });
}

/** Day-to-day tracker navigation */
export const OPS_NAV = [
  { href: "/dashboard", label: "Dashboard", hint: "Program health" },
  { href: "/", label: "Sites", hint: "TGS / MoA register" },
  { href: "/lists", label: "Client lists", hint: "Permits & TRIMS" },
  { href: "/tracking", label: "Tracking", hint: "Activity log" },
  { href: "/costs", label: "Traffic costs", hint: "TM estimates" },
  { href: "/asphalt", label: "Asphalt costs", hint: "Subcontractor rates" },
  { href: "/spend", label: "Actual spend", hint: "Traffic & pavements" },
  { href: "/gantt", label: "Gantt", hint: "Works sequence" },
  { href: "/documents", label: "Documents", hint: "Files" },
  { href: "/map", label: "Map", hint: "Site markups" },
  { href: "/archive", label: "Archive", hint: "Completed jobs" },
];

/** Admin console navigation */
export const ADMIN_NAV = [
  { href: "/admin", label: "Overview", hint: "Admin home" },
  { href: "/admin/users", label: "Users", hint: "Logins & roles" },
  { href: "/admin/stages", label: "Stages & programs", hint: "Workflow" },
  { href: "/admin/settings", label: "Rules & import", hint: "SLAs · spreadsheet" },
  { href: "/admin/rates", label: "Traffic rates", hint: "Crew & allowances" },
  { href: "/admin/asphalt", label: "Asphalt rates", hint: "Subcontractors" },
  { href: "/admin/system", label: "System & updates", hint: "Version · GitHub" },
];

function isActivePath(href, path) {
  if (href === "/") return path === "/";
  if (href === "/admin") return path === "/admin";
  return path === href || path.startsWith(`${href}/`);
}

function sideNavHtml(links, path) {
  return links
    .map((l) => {
      const active = isActivePath(l.href, path);
      return `<a href="${l.href}" class="side-link ${active ? "active" : ""}" ${
        active ? 'aria-current="page"' : ""
      }>
      <span class="side-link-label">${escapeHtml(l.label)}</span>
      ${l.hint ? `<span class="side-link-hint">${escapeHtml(l.hint)}</span>` : ""}
    </a>`;
    })
    .join("");
}

const NAV_COLLAPSE_KEY = "wru-nav-collapsed";
const NAV_MOBILE_MQ = "(max-width: 960px)";

function isMobileNav() {
  return window.matchMedia(NAV_MOBILE_MQ).matches;
}

function ensureShellStructure() {
  if (!document.querySelector(".skip-link")) {
    const skip = document.createElement("a");
    skip.className = "skip-link";
    skip.href = "#main-content";
    skip.textContent = "Skip to main content";
    document.body.prepend(skip);
  }

  let root = document.querySelector("[data-shell]");
  if (!root) {
    const legacy = document.querySelector(".app-shell");
    root = document.createElement("div");
    root.className = "shell";
    root.setAttribute("data-shell", "");

    const sidebar = document.createElement("aside");
    sidebar.className = "shell-sidebar";
    sidebar.setAttribute("data-app-sidebar", "");
    sidebar.setAttribute("aria-label", "Application");

    const mainCol = document.createElement("div");
    mainCol.className = "shell-main";

    if (legacy) {
      legacy.parentNode.insertBefore(root, legacy);
      while (legacy.firstChild) mainCol.appendChild(legacy.firstChild);
      legacy.remove();
    } else {
      document.body.appendChild(root);
    }
    root.appendChild(sidebar);
    root.appendChild(mainCol);
  }

  const mainCol = root.querySelector(".shell-main") || root;
  let header = mainCol.querySelector("[data-app-header]");
  if (!header) {
    header = document.createElement("header");
    header.className = "topbar";
    header.setAttribute("data-app-header", "");
    mainCol.prepend(header);
  }

  let main = mainCol.querySelector("main");
  if (!main) {
    main = document.createElement("main");
    main.className = "main";
    header.after(main);
  }
  main.id = "main-content";
  main.setAttribute("tabindex", "-1");

  if (!mainCol.querySelector("[data-app-footer]")) {
    const footer = document.createElement("footer");
    footer.className = "app-footer";
    footer.setAttribute("data-app-footer", "");
    mainCol.appendChild(footer);
  }

  if (!document.querySelector("[data-app-sidebar]")) {
    const sidebar = document.createElement("aside");
    sidebar.className = "shell-sidebar";
    sidebar.setAttribute("data-app-sidebar", "");
    root.prepend(sidebar);
  }

  if (!document.querySelector("[data-nav-backdrop]")) {
    const backdrop = document.createElement("button");
    backdrop.type = "button";
    backdrop.className = "nav-backdrop";
    backdrop.setAttribute("data-nav-backdrop", "");
    backdrop.setAttribute("aria-label", "Close menu");
    backdrop.hidden = true;
    document.body.appendChild(backdrop);
  }
}

function syncNavChrome() {
  const mobile = isMobileNav();
  const open = mobile
    ? document.body.classList.contains("nav-open")
    : !document.body.classList.contains("nav-collapsed");
  const toggle = $("navToggle");
  const closeBtn = $("navClose");
  const backdrop = document.querySelector("[data-nav-backdrop]");
  const sidebar = document.querySelector("[data-app-sidebar]");

  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  }
  if (closeBtn) closeBtn.hidden = !mobile;
  if (backdrop) {
    const showBackdrop = mobile && document.body.classList.contains("nav-open");
    backdrop.hidden = !showBackdrop;
  }
  if (sidebar) {
    sidebar.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) sidebar.removeAttribute("inert");
    else sidebar.setAttribute("inert", "");
  }
  document.body.classList.toggle("nav-drawer-open", mobile && document.body.classList.contains("nav-open"));
}

function setNavOpen(open) {
  if (isMobileNav()) {
    document.body.classList.toggle("nav-open", open);
    document.body.classList.remove("nav-collapsed");
  } else {
    document.body.classList.toggle("nav-collapsed", !open);
    document.body.classList.remove("nav-open");
    try {
      localStorage.setItem(NAV_COLLAPSE_KEY, !open ? "1" : "0");
    } catch {
      /* ignore */
    }
  }
  syncNavChrome();
  // Let map / layout listeners reflow after the sidebar transition
  window.setTimeout(() => window.dispatchEvent(new Event("resize")), 220);
}

function toggleNav() {
  const open = isMobileNav()
    ? document.body.classList.contains("nav-open")
    : !document.body.classList.contains("nav-collapsed");
  setNavOpen(!open);
}

function wireNavToggle() {
  const toggle = $("navToggle");
  const closeBtn = $("navClose");
  const backdrop = document.querySelector("[data-nav-backdrop]");
  const nav = $("sideNav");

  toggle?.addEventListener("click", toggleNav);
  closeBtn?.addEventListener("click", () => setNavOpen(false));
  backdrop?.addEventListener("click", () => setNavOpen(false));

  nav?.querySelectorAll("a.side-link").forEach((a) => {
    a.addEventListener("click", () => {
      if (isMobileNav()) setNavOpen(false);
    });
  });

  if (!document.body.dataset.navEscWired) {
    document.body.dataset.navEscWired = "1";
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && document.body.classList.contains("nav-open")) {
        setNavOpen(false);
        $("navToggle")?.focus();
      }
    });
    window.matchMedia(NAV_MOBILE_MQ).addEventListener("change", () => {
      document.body.classList.remove("nav-open");
      if (!isMobileNav()) {
        const collapsed = localStorage.getItem(NAV_COLLAPSE_KEY) === "1";
        document.body.classList.toggle("nav-collapsed", collapsed);
      } else {
        document.body.classList.remove("nav-collapsed");
      }
      syncNavChrome();
    });
  }

  // Restore desktop preference; mobile always starts closed
  if (isMobileNav()) {
    document.body.classList.remove("nav-collapsed", "nav-open");
  } else {
    document.body.classList.remove("nav-open");
    const collapsed = localStorage.getItem(NAV_COLLAPSE_KEY) === "1";
    document.body.classList.toggle("nav-collapsed", collapsed);
  }
  syncNavChrome();
}

/**
 * Inject accessible app chrome (sidebar + compact top bar).
 * @param {{ active?: string, mode?: 'ops'|'admin' }} opts
 */
export async function injectChrome({ active, mode } = {}) {
  const path = active || location.pathname;
  const isAdmin =
    mode === "admin" || path === "/admin" || path.startsWith("/admin/");

  try {
    const me = await api("/api/auth/me", { timeoutMs: 8000 });
    setSessionUser(me);
  } catch {
    /* 401 redirects inside api() */
  }

  const canAdmin = isAdminUser();
  document.body.classList.toggle("admin-mode", isAdmin);
  document.body.classList.toggle("ops-mode", !isAdmin);
  ensureShellStructure();

  const links = isAdmin ? ADMIN_NAV : OPS_NAV;
  const sidebar = document.querySelector("[data-app-sidebar]");
  if (sidebar) {
    const adminLink = canAdmin
      ? `<a class="btn btn-block btn-admin-link" href="/admin">Admin console</a>`
      : "";
    sidebar.innerHTML = `
      <div class="sidebar-brand">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="36" height="36" alt="" />
        <div class="brand-text">
          <p class="app-name">${isAdmin ? "WRU Admin" : "WRU TGS Tracker"}</p>
          <p class="tagline">${isAdmin ? "Configuration" : "Traffic guidance · MoA"}</p>
        </div>
        <button type="button" class="icon-btn sidebar-close" id="navClose" aria-label="Close menu" hidden>
          <span aria-hidden="true">×</span>
        </button>
      </div>
      <nav class="side-nav" id="sideNav" aria-label="${isAdmin ? "Admin" : "Primary"}">
        ${sideNavHtml(links, path)}
      </nav>
      <div class="sidebar-foot">
        ${isAdmin ? `<a class="btn btn-block" href="/">← Back to tracker</a>` : adminLink}
        <button type="button" class="btn btn-block theme-toggle" id="themeToggle" data-theme-toggle>Theme</button>
        <button type="button" class="btn btn-block" id="logoutBtn">Sign out</button>
      </div>
    `;
  }

  const who = escapeHtml(userName() || "");
  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.toggle("topbar-admin", isAdmin);
    header.innerHTML = `
      <div class="topbar-start">
        <button type="button" class="icon-btn nav-burger" id="navToggle" aria-expanded="true" aria-controls="sideNav" aria-label="Menu">
          <span class="nav-burger-icon" aria-hidden="true"></span>
        </button>
        <div class="brand-block top-brand">
          <img class="ventia-logo" src="/static/brand/ventia-logo.png" alt="Ventia" />
          <div class="brand-text">
            <p class="app-name">${isAdmin ? "Admin console" : "Operations"}</p>
          </div>
        </div>
      </div>
      <div class="topbar-end">
        ${who ? `<span class="session-user" title="Signed in">${who}</span>` : ""}
      </div>
    `;
  }

  const footer = document.querySelector("[data-app-footer]");
  if (footer) {
    const rawVer = window.__WRU_ASSET_V || document.querySelector('meta[name="wru-asset-version"]')?.content || "";
    const ver = rawVer ? `v${String(rawVer).replace(/^v/i, "")}` : "";
    footer.innerHTML = `
      <div class="inner">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="18" height="18" alt="" />
        <span>${
          isAdmin
            ? "WRU Admin · configuration stays out of day-to-day tracking"
            : "WRU TGS Tracker · traffic guidance schedules"
        }</span>
        ${ver ? `<span class="footer-version" title="Installed app version">${escapeHtml(ver)}</span>` : ""}
      </div>
    `;
    // Prefer live installed tag from /api/system when available (admins only)
    if (ver && canAdmin) {
      api("/api/system", { timeoutMs: 8000 })
        .then((s) => {
          const live = s?.version_tag || (s?.app_version ? `v${String(s.app_version).replace(/^v/i, "")}` : "");
          const el = footer.querySelector(".footer-version");
          if (el && live) el.textContent = live;
        })
        .catch(() => {});
    }
  }

  wireNavToggle();
  initThemeToggle();
  $("logoutBtn")?.addEventListener("click", () => {
    logout();
  });
  enhanceNumberInputs(document);
  watchNumberInputs();
}

const CHEVRON_UP = `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 4.2 2.6 9.6l1.5 1.5L8 7.2l3.9 3.9 1.5-1.5z"/></svg>`;
const CHEVRON_DOWN = `<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 11.8 2.6 6.4l1.5-1.5L8 8.8l3.9-3.9 1.5 1.5z"/></svg>`;

function stepperDecimals(step) {
  const raw = String(step ?? "1");
  if (raw.includes("e-") || raw.includes("E-")) {
    const n = Number(raw.split(/e-/i)[1] || 0);
    return Number.isFinite(n) ? n : 0;
  }
  const i = raw.indexOf(".");
  return i === -1 ? 0 : raw.length - i - 1;
}

function stepperNudge(input, dir) {
  if (!input || input.readOnly || input.disabled) return;
  const step = Number(input.step) || 1;
  const min = input.min === "" ? null : Number(input.min);
  const max = input.max === "" ? null : Number(input.max);
  const current = input.value === "" ? 0 : Number(input.value);
  if (!Number.isFinite(current)) return;
  let next = current + dir * step;
  if (min != null && Number.isFinite(min) && next < min) next = min;
  if (max != null && Number.isFinite(max) && next > max) next = max;
  const places = stepperDecimals(input.step || step);
  input.value = places ? next.toFixed(places) : String(Math.round(next));
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function attachStepperRepeat(btn, fn) {
  let timer = 0;
  const stop = () => {
    if (timer) window.clearTimeout(timer);
    timer = 0;
  };
  const start = (ev) => {
    if (ev.pointerType === "mouse" && ev.button !== 0) return;
    ev.preventDefault();
    fn();
    let delay = 380;
    const tick = () => {
      fn();
      delay = Math.max(55, delay * 0.72);
      timer = window.setTimeout(tick, delay);
    };
    timer = window.setTimeout(tick, delay);
  };
  btn.addEventListener("pointerdown", start);
  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointerleave", stop);
  btn.addEventListener("pointercancel", stop);
}

function shouldSkipStepper(input) {
  if (!input || input.dataset.stepper === "1") return true;
  if (input.type !== "number") return true;
  if (input.closest(".num-stepper")) return true;
  if (input.dataset.noStepper === "1") return true;
  const table = input.closest("table");
  if (table && table.querySelectorAll("thead th").length > 8) return true;
  return false;
}

export function wrapNumberInput(input) {
  if (shouldSkipStepper(input)) return;
  input.dataset.stepper = "1";
  const wrap = document.createElement("div");
  wrap.className = "num-stepper";
  if (input.readOnly || input.disabled) wrap.classList.add("num-stepper--readonly");
  input.classList.add("num-stepper-input");
  if (!input.getAttribute("inputmode")) {
    const step = String(input.step || "1");
    input.setAttribute("inputmode", step.includes(".") ? "decimal" : "numeric");
  }
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  if (input.readOnly || input.disabled) return;

  const name = input.closest("label")?.childNodes[0]?.textContent?.trim() || input.getAttribute("aria-label") || "value";
  const btns = document.createElement("div");
  btns.className = "num-stepper-btns";
  const up = document.createElement("button");
  up.type = "button";
  up.className = "num-stepper-btn";
  up.setAttribute("tabindex", "-1");
  up.setAttribute("aria-label", `Increase ${name}`);
  up.innerHTML = CHEVRON_UP;
  const down = document.createElement("button");
  down.type = "button";
  down.className = "num-stepper-btn";
  down.setAttribute("tabindex", "-1");
  down.setAttribute("aria-label", `Decrease ${name}`);
  down.innerHTML = CHEVRON_DOWN;
  btns.append(up, down);
  wrap.appendChild(btns);
  attachStepperRepeat(up, () => stepperNudge(input, 1));
  attachStepperRepeat(down, () => stepperNudge(input, -1));
}

export function enhanceNumberInputs(root = document) {
  if (!root) return;
  if (root.matches?.('input[type="number"]')) wrapNumberInput(root);
  root.querySelectorAll?.('input[type="number"]').forEach(wrapNumberInput);
}

let _stepperObserver = null;
function watchNumberInputs() {
  if (_stepperObserver || typeof MutationObserver === "undefined" || !document.body) return;
  _stepperObserver = new MutationObserver((muts) => {
    for (const m of muts) {
      for (const node of m.addedNodes) {
        if (node.nodeType !== 1) continue;
        enhanceNumberInputs(node);
      }
    }
  });
  _stepperObserver.observe(document.body, { childList: true, subtree: true });
}

export function stageLabel(meta, key) {
  return meta?.workflow_stages?.find((s) => s.key === key)?.label || key || "—";
}

export function mustBandClass(band) {
  if (band === "received") return "must-have received";
  if (band === "ok") return "must-have soon";
  if (band === "warn") return "must-have warn";
  if (band === "late" || band === "overdue") return "must-have late";
  return "";
}

/** Show a page-level error into a target element. */
export function showPageError(targetId, err, fallbackTitle = "Something went wrong") {
  const el = $(targetId);
  const msg = err?.message || String(err);
  if (!el) {
    console.error(fallbackTitle, msg);
    return;
  }
  el.innerHTML = `<div class="page-error" role="alert">
    <strong>${escapeHtml(fallbackTitle)}</strong>
    <p>${escapeHtml(msg)}</p>
    <p class="hint">Try a hard refresh (Ctrl+Shift+R). If this keeps happening after an update, run the shell updater once as root.</p>
  </div>`;
}

/* —— Centered app dialogs (replace native alert/confirm/prompt) —— */

let _dialogSeq = 0;

function ensureAppDialog() {
  let root = document.getElementById("appDialog");
  if (root) return root;
  root = document.createElement("dialog");
  root.id = "appDialog";
  root.className = "app-dialog";
  root.setAttribute("aria-modal", "true");
  root.innerHTML = `
    <form method="dialog" class="app-dialog-card" id="appDialogForm">
      <header class="app-dialog-head">
        <h2 id="appDialogTitle">Confirm</h2>
      </header>
      <div class="app-dialog-body" id="appDialogBody"></div>
      <div class="app-dialog-prompt" id="appDialogPromptWrap" hidden>
        <label class="app-dialog-prompt-label" for="appDialogInput" id="appDialogPromptLabel">Value</label>
        <input id="appDialogInput" name="value" autocomplete="off" />
      </div>
      <footer class="app-dialog-foot">
        <button type="button" class="btn" id="appDialogCancel" value="cancel">Cancel</button>
        <button type="submit" class="btn btn-primary" id="appDialogOk" value="ok">OK</button>
      </footer>
    </form>
  `;
  document.body.appendChild(root);
  return root;
}

function messageToHtml(message) {
  const parts = String(message ?? "")
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (!parts.length) return "<p></p>";
  return parts
    .map((part, idx) => {
      const html = escapeHtml(part).replaceAll("\n", "<br />");
      return idx === 0 ? `<p class="app-dialog-lead">${html}</p>` : `<p class="hint">${html}</p>`;
    })
    .join("");
}

/**
 * @param {{
 *   mode?: 'alert'|'confirm'|'prompt',
 *   title?: string,
 *   message: string,
 *   confirmLabel?: string,
 *   cancelLabel?: string,
 *   danger?: boolean,
 *   defaultValue?: string,
 *   inputLabel?: string,
 * }} opts
 * @returns {Promise<boolean|string|null>}
 */
function showAppDialog(opts) {
  const {
    mode = "confirm",
    title,
    message,
    confirmLabel = "OK",
    cancelLabel = "Cancel",
    danger = false,
    defaultValue = "",
    inputLabel = "Value",
  } = opts || {};

  const root = ensureAppDialog();
  const form = root.querySelector("#appDialogForm");
  const titleEl = root.querySelector("#appDialogTitle");
  const bodyEl = root.querySelector("#appDialogBody");
  const promptWrap = root.querySelector("#appDialogPromptWrap");
  const promptLabel = root.querySelector("#appDialogPromptLabel");
  const inputEl = root.querySelector("#appDialogInput");
  const okBtn = root.querySelector("#appDialogOk");
  const cancelBtn = root.querySelector("#appDialogCancel");

  const defaultTitle = mode === "alert" ? "Notice" : mode === "prompt" ? "Input" : "Confirm";
  titleEl.textContent = title || defaultTitle;
  bodyEl.innerHTML = messageToHtml(message);
  okBtn.textContent = confirmLabel;
  cancelBtn.textContent = cancelLabel;
  okBtn.classList.toggle("btn-danger", !!danger);
  okBtn.classList.toggle("btn-primary", !danger);
  cancelBtn.hidden = mode === "alert";
  promptWrap.hidden = mode !== "prompt";
  if (mode === "prompt") {
    promptLabel.textContent = inputLabel;
    inputEl.value = defaultValue ?? "";
  }

  const token = ++_dialogSeq;

  return new Promise((resolve) => {
    const cleanup = () => {
      form.removeEventListener("submit", onSubmit);
      cancelBtn.removeEventListener("click", onCancel);
      root.removeEventListener("cancel", onCancelEsc);
    };

    const finish = (value) => {
      if (token !== _dialogSeq) return;
      cleanup();
      if (root.open) root.close();
      resolve(value);
    };

    const onSubmit = (ev) => {
      ev.preventDefault();
      if (mode === "prompt") finish(inputEl.value);
      else if (mode === "confirm") finish(true);
      else finish(undefined);
    };
    const onCancel = (ev) => {
      ev.preventDefault();
      finish(mode === "prompt" ? null : false);
    };
    const onCancelEsc = (ev) => {
      ev.preventDefault();
      finish(mode === "prompt" ? null : mode === "confirm" ? false : undefined);
    };

    form.addEventListener("submit", onSubmit);
    cancelBtn.addEventListener("click", onCancel);
    root.addEventListener("cancel", onCancelEsc);

    if (typeof root.showModal === "function") root.showModal();
    else root.setAttribute("open", "");

    requestAnimationFrame(() => {
      if (mode === "prompt") inputEl.focus();
      else okBtn.focus();
    });
  });
}

/** Centered confirm — resolves true/false. */
export function confirmDialog(message, opts = {}) {
  return showAppDialog({ mode: "confirm", message, ...opts });
}

/** Centered alert — resolves when dismissed. */
export function alertDialog(message, opts = {}) {
  return showAppDialog({ mode: "alert", message, confirmLabel: opts.confirmLabel || "OK", ...opts });
}

/** Centered prompt — resolves string or null if cancelled. */
export function promptDialog(message, defaultValue = "", opts = {}) {
  return showAppDialog({
    mode: "prompt",
    message,
    defaultValue,
    ...opts,
  });
}
