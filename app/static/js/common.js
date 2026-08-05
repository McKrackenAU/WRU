export const THEME_KEY = "wru-tgs-theme";

export function $(id) {
  return document.getElementById(id);
}

export async function api(path, options = {}) {
  const res = await fetch(path, options);
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

/** Admin console navigation (VenInspect-style separate shell) */
export const ADMIN_NAV = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/stages", label: "Stages & programs" },
  { href: "/admin/settings", label: "Rules & import" },
  { href: "/admin/rates", label: "Rates" },
  { href: "/admin/system", label: "System" },
];

function navHtml(links, path) {
  return links
    .map((l) => {
      const isActive =
        l.href === "/"
          ? path === "/"
          : l.href === "/admin"
            ? path === "/admin"
            : path === l.href || path.startsWith(`${l.href}/`);
      return `<a href="${l.href}" class="${isActive ? "active" : ""}">${escapeHtml(l.label)}</a>`;
    })
    .join("");
}

/**
 * Inject top chrome.
 * @param {{ active?: string, mode?: 'ops'|'admin' }} opts
 */
export function injectChrome({ active, mode } = {}) {
  const path = active || location.pathname;
  const isAdmin =
    mode === "admin" || path === "/admin" || path.startsWith("/admin/");
  const links = isAdmin ? ADMIN_NAV : OPS_NAV;
  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.toggle("topbar-admin", isAdmin);
    header.innerHTML = `
      <div class="brand-block">
        <img class="brand-mark" src="/static/brand/veninspect-mark.png" width="36" height="36" alt="" />
        <div class="brand-text">
          <p class="app-name">${isAdmin ? "WRU Admin" : "WRU TGS Tracker"}</p>
          <p class="tagline">${isAdmin ? "Configuration · imports · system" : "Traffic guidance · MoA workflow"}</p>
        </div>
        <img class="ventia-logo" src="/static/brand/ventia-logo.png" alt="Ventia" />
      </div>
      <nav class="main-nav" aria-label="${isAdmin ? "Admin" : "Primary"}">
        ${navHtml(links, path)}
      </nav>
      <div class="toolbar header-tools">
        ${
          isAdmin
            ? `<a class="btn" href="/">← Back to tracker</a>`
            : `<a class="btn btn-admin-link" href="/admin">Admin</a>`
        }
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
        <span>${isAdmin ? "WRU Admin console" : "WRU TGS Tracker · Traffic guidance schedules"}</span>
      </div>
    `;
  }
  document.body.classList.toggle("admin-mode", isAdmin);
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
