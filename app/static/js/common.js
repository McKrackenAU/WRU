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
  const ctrl = new AbortController();
  const timeoutMs = options.timeoutMs ?? 45000;
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      cache: "no-store",
      ...options,
      signal: options.signal || ctrl.signal,
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
  { href: "/costs", label: "Costs", hint: "Estimates" },
  { href: "/documents", label: "Documents", hint: "Files" },
  { href: "/map", label: "Map", hint: "Site markups" },
  { href: "/archive", label: "Archive", hint: "Completed jobs" },
];

/** Admin console navigation */
export const ADMIN_NAV = [
  { href: "/admin", label: "Overview", hint: "Admin home" },
  { href: "/admin/stages", label: "Stages & programs", hint: "Workflow" },
  { href: "/admin/settings", label: "Rules & import", hint: "SLAs · spreadsheet" },
  { href: "/admin/rates", label: "Rates", hint: "Crew & allowances" },
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
}

/**
 * Inject accessible app chrome (sidebar + compact top bar).
 * @param {{ active?: string, mode?: 'ops'|'admin' }} opts
 */
export function injectChrome({ active, mode } = {}) {
  const path = active || location.pathname;
  const isAdmin =
    mode === "admin" || path === "/admin" || path.startsWith("/admin/");

  document.body.classList.toggle("admin-mode", isAdmin);
  document.body.classList.toggle("ops-mode", !isAdmin);
  ensureShellStructure();

  const links = isAdmin ? ADMIN_NAV : OPS_NAV;
  const sidebar = document.querySelector("[data-app-sidebar]");
  if (sidebar) {
    sidebar.innerHTML = `
      <div class="sidebar-brand">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="36" height="36" alt="" />
        <div class="brand-text">
          <p class="app-name">${isAdmin ? "WRU Admin" : "WRU TGS Tracker"}</p>
          <p class="tagline">${isAdmin ? "Configuration" : "Traffic guidance · MoA"}</p>
        </div>
      </div>
      <button type="button" class="btn sidebar-toggle" id="navToggle" aria-expanded="false" aria-controls="sideNav">
        Menu
      </button>
      <nav class="side-nav" id="sideNav" aria-label="${isAdmin ? "Admin" : "Primary"}">
        ${sideNavHtml(links, path)}
      </nav>
      <div class="sidebar-foot">
        ${
          isAdmin
            ? `<a class="btn btn-block" href="/">← Back to tracker</a>`
            : `<a class="btn btn-block btn-admin-link" href="/admin">Admin console</a>`
        }
        <button type="button" class="btn btn-block theme-toggle" id="themeToggle" data-theme-toggle>Theme</button>
      </div>
    `;
  }

  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.toggle("topbar-admin", isAdmin);
    header.innerHTML = `
      <div class="brand-block top-brand">
        <img class="ventia-logo" src="/static/brand/ventia-logo.png" alt="Ventia" />
        <div class="brand-text">
          <p class="app-name">${isAdmin ? "Admin console" : "Operations"}</p>
          <p class="tagline">${isAdmin ? "Stages · rules · rates · updates" : "Sites · lists · tracking · map"}</p>
        </div>
      </div>
      <div class="toolbar header-tools">
        <label class="user-field">
          <span class="sr-only">Your name</span>
          <input id="userName" type="text" placeholder="Your name" maxlength="64" autocomplete="name" />
        </label>
      </div>
    `;
  }

  const footer = document.querySelector("[data-app-footer]");
  if (footer) {
    footer.innerHTML = `
      <div class="inner">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="18" height="18" alt="" />
        <span>${
          isAdmin
            ? "WRU Admin · configuration stays out of day-to-day tracking"
            : "WRU TGS Tracker · traffic guidance schedules"
        }</span>
      </div>
    `;
  }

  const nav = $("sideNav");
  const toggle = $("navToggle");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = document.body.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  loadUserName();
  $("userName")?.addEventListener("change", saveUserName);
  initThemeToggle();
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
