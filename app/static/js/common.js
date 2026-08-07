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
