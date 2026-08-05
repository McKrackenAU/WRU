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

export async function api(path, options = {}) {
  const res = await fetch(path, {
    cache: "no-store",
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
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

export function userName() {
  return ($("userName")?.value || "").trim() || null;
}

export function saveUserName() {
  if ($("userName")) localStorage.setItem("wru_user", $("userName").value || "");
}

export function loadUserName() {
  if ($("userName")) $("userName").value = localStorage.getItem("wru_user") || "";
}

function currentTheme() {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
  root.style.colorScheme = mode;
  const btn = $("themeToggle");
  if (btn) {
    btn.textContent = mode === "dark" ? "Light" : "Dark";
    btn.setAttribute(
      "aria-label",
      mode === "dark" ? "Switch to light mode" : "Switch to dark mode"
    );
  }
}

export function initThemeToggle() {
  applyTheme(currentTheme());
  $("themeToggle")?.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

/** Day-to-day tracker navigation */
export const OPS_NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/", label: "Sites" },
  { href: "/lists", label: "Client lists" },
  { href: "/tracking", label: "Tracking" },
  { href: "/costs", label: "Costs" },
  { href: "/documents", label: "Documents" },
  { href: "/map", label: "Map" },
  { href: "/archive", label: "Archive" },
];

/** Admin console navigation */
export const ADMIN_NAV = [
  { href: "/admin", label: "Overview", icon: "◈" },
  { href: "/admin/stages", label: "Stages & programs", icon: "☰" },
  { href: "/admin/settings", label: "Rules & import", icon: "⚙" },
  { href: "/admin/rates", label: "Rates", icon: "$" },
  { href: "/admin/system", label: "System & updates", icon: "↑" },
];

function isActivePath(href, path) {
  if (href === "/") return path === "/";
  if (href === "/admin") return path === "/admin";
  return path === href || path.startsWith(`${href}/`);
}

function opsNavHtml(path) {
  return OPS_NAV.map((l) => {
    const active = isActivePath(l.href, path);
    return `<a href="${l.href}" class="${active ? "active" : ""}">${escapeHtml(l.label)}</a>`;
  }).join("");
}

function adminNavHtml(path) {
  return ADMIN_NAV.map((l) => {
    const active = isActivePath(l.href, path);
    return `<a href="${l.href}" class="admin-nav-link ${active ? "active" : ""}">
      <span class="admin-nav-ico">${l.icon || "•"}</span>
      <span>${escapeHtml(l.label)}</span>
    </a>`;
  }).join("");
}

/**
 * Inject chrome.
 * Ops: top nav. Admin: left sidebar shell (VenInspect-style).
 * @param {{ active?: string, mode?: 'ops'|'admin' }} opts
 */
export function injectChrome({ active, mode } = {}) {
  const path = active || location.pathname;
  const isAdmin =
    mode === "admin" || path === "/admin" || path.startsWith("/admin/");

  document.body.classList.toggle("admin-mode", isAdmin);

  if (isAdmin) {
    injectAdminShell(path);
  } else {
    injectOpsShell(path);
  }

  loadUserName();
  $("userName")?.addEventListener("change", saveUserName);
  initThemeToggle();
}

function injectOpsShell(path) {
  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.remove("topbar-admin");
    header.innerHTML = `
      <div class="brand-block">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="36" height="36" alt="" />
        <div class="brand-text">
          <p class="app-name">WRU TGS Tracker</p>
          <p class="tagline">Traffic guidance · MoA workflow</p>
        </div>
        <img class="ventia-logo" src="/static/brand/ventia-logo.png" alt="Ventia" />
      </div>
      <nav class="main-nav" aria-label="Primary">${opsNavHtml(path)}</nav>
      <div class="toolbar header-tools">
        <a class="btn btn-admin-link" href="/admin">Admin</a>
        <input id="userName" type="text" placeholder="Your name" maxlength="64" aria-label="Your name" />
        <button type="button" class="btn theme-toggle" id="themeToggle">Theme</button>
      </div>
    `;
  }
  const footer = document.querySelector("[data-app-footer]");
  if (footer) {
    footer.innerHTML = `
      <div class="inner">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="18" height="18" alt="" />
        <span>WRU TGS Tracker · Traffic guidance schedules</span>
      </div>
    `;
  }
}

function injectAdminShell(path) {
  // Ensure admin shell wrapper exists around page content
  let shell = document.querySelector(".admin-shell");
  if (!shell) {
    const existing = document.querySelector(".app-shell");
    shell = document.createElement("div");
    shell.className = "admin-shell";
    const sidebar = document.createElement("aside");
    sidebar.className = "admin-sidebar";
    sidebar.setAttribute("data-admin-sidebar", "");
    const mainCol = document.createElement("div");
    mainCol.className = "admin-main-col";
    if (existing) {
      existing.parentNode.insertBefore(shell, existing);
      mainCol.appendChild(existing);
      existing.classList.add("admin-app-shell");
    }
    shell.appendChild(sidebar);
    shell.appendChild(mainCol);
  }

  const sidebar = document.querySelector("[data-admin-sidebar]");
  if (sidebar) {
    sidebar.innerHTML = `
      <div class="admin-brand">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="32" height="32" alt="" />
        <div>
          <p class="app-name">WRU Admin</p>
          <p class="tagline">Configuration</p>
        </div>
      </div>
      <nav class="admin-side-nav" aria-label="Admin">${adminNavHtml(path)}</nav>
      <div class="admin-side-foot">
        <a class="btn" href="/">← Tracker</a>
        <button type="button" class="btn theme-toggle" id="themeToggle">Theme</button>
      </div>
    `;
  }

  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.add("topbar-admin");
    header.innerHTML = `
      <div class="brand-block admin-top-brand">
        <div class="brand-text">
          <p class="app-name">Admin console</p>
          <p class="tagline">Stages · rules · rates · updates</p>
        </div>
        <img class="ventia-logo" src="/static/brand/ventia-logo.png" alt="Ventia" />
      </div>
      <div class="toolbar header-tools">
        <input id="userName" type="text" placeholder="Your name" maxlength="64" aria-label="Your name" />
      </div>
    `;
  }

  const footer = document.querySelector("[data-app-footer]");
  if (footer) {
    footer.innerHTML = `
      <div class="inner">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="18" height="18" alt="" />
        <span>WRU Admin · keep tracker config out of the ops UI</span>
      </div>
    `;
  }
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
