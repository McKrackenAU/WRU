import { initPwaChrome, notifyLiveIfBackground, registerServiceWorker } from "./pwa.js";

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

export function safeNextUrl(raw, fallback = "/") {
  const n = String(raw || "");
  if (!n.startsWith("/") || n.startsWith("//") || n.startsWith("/login") || n.startsWith("/password")) {
    return fallback;
  }
  return n;
}

export function isAdminUser() {
  if (_sessionUser) return _sessionUser.role === "admin";
  try {
    return localStorage.getItem("wru_role") === "admin";
  } catch {
    return false;
  }
}

export function isCommsUser() {
  const role = _sessionUser?.role || (function () {
    try {
      return localStorage.getItem("wru_role") || "";
    } catch {
      return "";
    }
  })();
  return role === "comms" || role === "admin";
}

/** True when a response body is a proxy/login HTML page rather than an API payload. */
export function looksLikeHtmlOrProxyPage(text) {
  return /<!DOCTYPE|<html[\s>]|<head[\s>]|<!--#|\bzscaler\b/i.test(String(text || ""));
}

/**
 * Never dump proxy HTML (Zscaler, Cloudflare, login pages) into the Notice dialog.
 */
export function humanizeHttpError(status, text, fallback = "Request failed") {
  const raw = String(text || "");
  const code = Number(status) || 0;
  if (/zscaler/i.test(raw) || (looksLikeHtmlOrProxyPage(raw) && /zscaler|z-?scaler/i.test(raw))) {
    return "Workplace security (Zscaler) blocked this request. File uploads and downloads from this network are being intercepted. Check for updates, then retry — files now travel as small JSON chunks instead of a raw transfer. If it still fails, try from a network that is not filtered.";
  }
  if (/cloudflare|cf-ray|error code 52|attention required/i.test(raw)) {
    return "Cloudflare or the tunnel blocked this request. Check for updates and retry, or import from the LAN.";
  }
  if (looksLikeHtmlOrProxyPage(raw)) {
    const http = code ? `HTTP ${code}` : "a web page";
    return `A network filter or login page intercepted this request (${http}). The response was a web page, not an API result.`;
  }
  if (code === 413) {
    return "A proxy rejected the request as too large. Retry — uploads send small JSON chunks.";
  }
  const trimmed = raw.trim();
  if (!trimmed) {
    return fallback || (code ? `Request failed (HTTP ${code})` : "Request failed");
  }
  if (trimmed.length > 240) return `${trimmed.slice(0, 240)}…`;
  return trimmed;
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
  if (typeof err === "string") {
    const t = err.trim();
    if (!t) return fallback;
    if (looksLikeHtmlOrProxyPage(t)) return humanizeHttpError(0, t, fallback);
    return t;
  }
  const msg = err.message || err.detail || "";
  if (typeof msg === "string" && msg.trim()) {
    if (looksLikeHtmlOrProxyPage(msg)) return humanizeHttpError(0, msg, fallback);
    return msg.trim();
  }
  return formatApiDetail(msg, fallback);
}

export async function api(path, options = {}) {
  const ctrl = new AbortController();
  const timeoutMs = options.timeoutMs ?? 45000;
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const headers = new Headers(options.headers || {});
    if (!headers.has("X-WRU-Client-Id")) headers.set("X-WRU-Client-Id", liveClientId());
    const tabVer = loadedAssetVersion();
    if (tabVer && !headers.has("X-WRU-Client-Version")) headers.set("X-WRU-Client-Version", tabVer);
    const res = await fetch(path, {
      cache: "no-store",
      credentials: "include",
      ...options,
      headers,
      signal: options.signal || ctrl.signal,
    });
    try {
      ingestLiveHeaders(res, options.method || "GET");
    } catch {
      /* live headers must never break the request */
    }
    if (res.status === 401 && !String(path).startsWith("/api/auth/")) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `/login?next=${next}`;
      throw new Error("Not authenticated");
    }
    if (
      res.status === 403 &&
      location.pathname !== "/password" &&
      !String(path).startsWith("/api/auth/")
    ) {
      const peek = await res.clone().text().catch(() => "");
      if (/password change required/i.test(peek)) {
        const next = encodeURIComponent(location.pathname + location.search);
        location.href = `/password?next=${next}`;
        throw new Error("Password change required");
      }
    }
    if (!res.ok) {
      const rawText = await res.text().catch(() => "");
      let detail = res.statusText || `HTTP ${res.status}`;
      const trimmed = rawText.trim();
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        try {
          const body = JSON.parse(rawText);
          detail = formatApiDetail(body?.detail ?? body, detail);
        } catch (_) {
          detail = humanizeHttpError(res.status, rawText, detail);
        }
      } else {
        detail = humanizeHttpError(res.status, rawText, detail);
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

function xorBytes(u8, keyU8) {
  const out = new Uint8Array(u8.length);
  const klen = keyU8.length;
  for (let i = 0; i < u8.length; i += 1) out[i] = u8[i] ^ keyU8[i % klen];
  return out;
}

function bytesToB64(u8) {
  let s = "";
  const step = 0x8000;
  for (let i = 0; i < u8.length; i += step) {
    s += String.fromCharCode(...u8.subarray(i, i + step));
  }
  return btoa(s);
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * Upload a file as XOR+base64 JSON chunks (same protocol as tracker import).
 * beginUrl POST { filename, size, ...beginBody } → { id, chunk_size, wrap_key }
 * chunkUrl(id, index) POST { p }
 * commitUrl(id) POST
 */
export async function uploadFileChunked(file, { beginUrl, chunkUrl, commitUrl, beginBody = {}, onProgress, timeoutMs = 45000 }) {
  if (!file?.size) throw new Error("That file is empty");
  const session = await api(beginUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, size: file.size, ...beginBody }),
    timeoutMs: Math.max(timeoutMs, 20000),
  });
  if (!session?.id) throw new Error("Could not start upload session");
  if (!session.wrap_key) {
    throw new Error("This server is still on the old upload protocol. Check for updates, then retry.");
  }
  const keyBytes = b64ToBytes(session.wrap_key);
  const chunkSize = Number(session.chunk_size) || 48 * 1024;
  const total = Math.max(1, Math.ceil(file.size / chunkSize));
  for (let i = 0; i < total; i += 1) {
    onProgress?.(`Uploading… ${i + 1}/${total}`);
    const slice = new Uint8Array(await file.slice(i * chunkSize, (i + 1) * chunkSize).arrayBuffer());
    const wrapped = xorBytes(slice, keyBytes);
    await api(chunkUrl(session.id, i), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ p: bytesToB64(wrapped) }),
      timeoutMs,
    });
  }
  onProgress?.("Saving…");
  return api(commitUrl(session.id), { method: "POST", timeoutMs: Math.max(timeoutMs, 60000) });
}

export const DOC_CATEGORY_LABELS = {
  email: "Email",
  tgs: "TGS",
  plan: "Plan",
  moa: "MoA",
  correspondence: "Correspondence",
  scoping: "Scoping",
  photo: "Photo",
  other: "Other",
};

export function applyDocCategories(defs) {
  const next = {};
  for (const item of defs || []) {
    if (typeof item === "string") {
      next[item] = DOC_CATEGORY_LABELS[item] || titleCaseCategory(item);
    } else if (item && item.key) {
      next[item.key] = item.label || titleCaseCategory(item.key);
    }
  }
  if (!Object.keys(next).length) return DOC_CATEGORY_LABELS;
  for (const key of Object.keys(DOC_CATEGORY_LABELS)) delete DOC_CATEGORY_LABELS[key];
  Object.assign(DOC_CATEGORY_LABELS, next);
  return DOC_CATEGORY_LABELS;
}

export function titleCaseCategory(key) {
  const raw = String(key || "").replaceAll("_", " ").trim();
  if (!raw) return "Other";
  return raw.replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function docCategoryOptionsHtml(current) {
  const labels = { ...DOC_CATEGORY_LABELS };
  if (current && !labels[current]) labels[current] = titleCaseCategory(current);
  return Object.entries(labels)
    .map(
      ([key, label]) =>
        `<option value="${escapeHtml(key)}" ${key === current ? "selected" : ""}>${escapeHtml(label)}</option>`
    )
    .join("");
}

export function fillDocCategorySelect(selectEl, current) {
  if (!selectEl) return;
  const keep = current ?? selectEl.value;
  selectEl.innerHTML = docCategoryOptionsHtml(keep);
  if (keep) selectEl.value = keep;
}

export function docCategorySelectHtml(docId, current, { disabled = false, extraClass = "" } = {}) {
  const opts = docCategoryOptionsHtml(current);
  const cls = ["doc-cat-select", extraClass].filter(Boolean).join(" ");
  const dis = disabled ? "disabled" : "";
  return `<select class="${cls}" data-doc-cat="${docId}" ${dis} aria-label="Document category">${opts}</select>`;
}

export async function downloadChunkedSession({ beginUrl, beginBody = {}, chunkUrl, onProgress, timeoutMs = 45000 }) {
  const session = await api(beginUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(beginBody),
    timeoutMs: Math.max(timeoutMs, 60000),
  });
  if (!session?.id || !session.wrap_key) {
    throw new Error("Could not start a filtered download. Check for updates, then retry.");
  }
  const keyBytes = b64ToBytes(session.wrap_key);
  const total = Math.max(1, Number(session.chunks) || 1);
  const parts = [];
  for (let i = 0; i < total; i += 1) {
    onProgress?.(`Downloading… ${i + 1}/${total}`);
    const piece = await api(chunkUrl(session.id, i), { timeoutMs });
    if (!piece?.p) throw new Error("Download chunk was empty — retry");
    parts.push(xorBytes(b64ToBytes(piece.p), keyBytes));
  }
  onProgress?.("Saving…");
  const blob = new Blob(parts, { type: session.content_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = session.filename || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function downloadDocumentsZip(ids, filename = "documents.zip", onProgress) {
  const list = [...new Set((ids || []).map((n) => Number(n)).filter((n) => n > 0))];
  if (!list.length) throw new Error("Select one or more documents first");
  await downloadChunkedSession({
    beginUrl: "/api/documents/zip/session",
    beginBody: { ids: list },
    chunkUrl: (id, i) => `/api/documents/download-session/${encodeURIComponent(id)}/chunk/${i}`,
    onProgress,
  });
}

export async function downloadDocumentById(documentId, onProgress) {
  const id = Number(documentId);
  if (!id) throw new Error("Missing document");
  await downloadChunkedSession({
    beginUrl: `/api/documents/${id}/download/session`,
    beginBody: {},
    chunkUrl: (sid, i) => `/api/documents/download-session/${encodeURIComponent(sid)}/chunk/${i}`,
    onProgress,
  });
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
  const dark = mode === "dark";
  document.querySelectorAll("#themeToggle, [data-theme-toggle]").forEach((btn) => {
    btn.setAttribute("aria-checked", dark ? "true" : "false");
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    if (!btn.querySelector(".switch-knob")) {
      btn.textContent = dark ? "Light" : "Dark";
    }
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
  { href: "/tracking", label: "Activity", hint: "Who changed what" },
  { href: "/costs", label: "Traffic costs", hint: "TM estimates" },
  { href: "/asphalt", label: "Asphalt costs", hint: "Subcontractor rates" },
  { href: "/spend", label: "Actual spend", hint: "Traffic & pavements" },
  { href: "/gantt", label: "Gantt", hint: "Works sequence" },
  { href: "/documents", label: "Documents", hint: "Files" },
  { href: "/comms", label: "Comms", hint: "Stakeholder planner", commsOnly: true },
  { href: "/map", label: "Map", hint: "Site markups" },
  { href: "/archive", label: "Archive", hint: "Completed jobs" },
];

/** Admin console navigation */
export const ADMIN_NAV = [
  { href: "/admin", label: "Overview", hint: "Admin home" },
  { href: "/admin/users", label: "Users", hint: "Logins & roles" },
  { href: "/admin/notifications", label: "Notifications", hint: "Bell rules & tags" },
  { href: "/admin/stages", label: "Stages & programs", hint: "Workflow" },
  { href: "/admin/settings", label: "Rules & roads", hint: "SLAs · roads · document types" },
  { href: "/admin/rates", label: "Traffic rates", hint: "Crew & allowances" },
  { href: "/admin/asphalt", label: "Asphalt rates", hint: "Subcontractors" },
  { href: "/admin/system", label: "System & updates", hint: "Version · GitHub" },
  { href: "/admin/backup", label: "Backup & migrate", hint: "Export · import" },
  { href: "/admin/storage", label: "File storage", hint: "Disk paths" },
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

function wireUserMenu() {
  const btn = $("userMenuBtn");
  const panel = $("userMenuPanel");
  if (!btn || !panel || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  const close = () => {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  };
  const toggle = (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  };
  btn.addEventListener("click", toggle);
  document.addEventListener("click", (ev) => {
    if (panel.hidden) return;
    if (ev.target.closest(".user-menu")) return;
    close();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") close();
  });
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

const LIVE_CLIENT_KEY = "wru-live-client-id";
const liveHandlers = new Set();
let liveSource = null;
let liveConnecting = false;
let liveRetryTimer = null;
let liveRetryMs = 1500;
let livePollTimer = null;
let liveBootstrapped = false;
let knownRevision = 0;
let pageBootId = null;
let pageAssetVersion = null;
let serverAssetVersion = null;
let refreshDebounce = null;
let refreshRunning = false;
let refreshPending = null;

const LIVE_POLL_MS = 2500;
const LIVE_POLL_HIDDEN_MS = 12000;
const LIVE_REFRESH_DEBOUNCE_MS = 250;
const LIVE_IDENTITY_KEY = "wru-live-identity";

export function liveClientId() {
  try {
    let id = sessionStorage.getItem(LIVE_CLIENT_KEY);
    if (!id) {
      id =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `c-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(LIVE_CLIENT_KEY, id);
    }
    return id;
  } catch {
    return `c-${Date.now()}`;
  }
}

/** Record the revision this tab has already rendered (after a local load/save). */
export function markLiveRevision(revision) {
  if (typeof revision === "number" && revision >= knownRevision) {
    knownRevision = revision;
  }
}

function htmlAssetVersion() {
  try {
    const raw =
      (typeof window !== "undefined" && window.__WRU_ASSET_V) ||
      document.querySelector?.('meta[name="wru-asset-version"]')?.content ||
      "";
    return String(raw || "").trim();
  } catch {
    return "";
  }
}

/** Version baked into this tab's HTML — not the live server version. */
export function loadedAssetVersion() {
  return htmlAssetVersion() || pageAssetVersion || "";
}

/** When this tab is behind a deploy, stay open and flag the bell until refresh. */
export function pendingAppUpdate() {
  const current = loadedAssetVersion();
  const available = serverAssetVersion ? String(serverAssetVersion) : "";
  if (current && available && current !== available) {
    return { current, available };
  }
  return null;
}

function signalAppUpdateIfNeeded() {
  const pending = pendingAppUpdate();
  if (!pending) return;
  try {
    window.dispatchEvent(new CustomEvent("wru:app-update", { detail: pending }));
  } catch {
    /* ignore */
  }
}

/** Hard-reload this tab onto the installed version. Does not run automatically. */
export function applyAppUpdate() {
  const next = (pendingAppUpdate()?.available || serverAssetVersion || loadedAssetVersion() || "").trim();
  try {
    navigator.serviceWorker?.getRegistration?.().then((reg) => {
      try {
        reg?.waiting?.postMessage({ type: "skip-waiting" });
      } catch {
        /* ignore */
      }
    });
  } catch {
    /* ignore */
  }
  const url = new URL(location.href);
  url.searchParams.set("_av", next || String(Date.now()));
  location.replace(url.toString());
}

function hardReloadForUpdate() {
  applyAppUpdate();
}

function rememberServerIdentity(data) {
  if (!data || typeof data !== "object") return "ok";
  const incomingVersion = data.asset_version != null ? String(data.asset_version) : null;
  const incomingBoot = data.boot_id != null ? String(data.boot_id) : null;
  if (pageAssetVersion == null) {
    pageAssetVersion = htmlAssetVersion() || incomingVersion;
  }
  if (pageBootId == null && incomingBoot) pageBootId = incomingBoot;
  if (incomingVersion) serverAssetVersion = incomingVersion;
  try {
    sessionStorage.setItem(
      LIVE_IDENTITY_KEY,
      JSON.stringify({
        boot_id: incomingBoot || pageBootId,
        tab_asset_version: pageAssetVersion,
        server_asset_version: incomingVersion || serverAssetVersion,
        asset_version: incomingVersion || serverAssetVersion || pageAssetVersion,
        revision: data.revision,
      })
    );
  } catch {
    /* ignore */
  }
  const versionDrift = Boolean(
    incomingVersion && pageAssetVersion && incomingVersion !== pageAssetVersion
  );
  let restarted = false;
  if (incomingBoot && pageBootId && incomingBoot !== pageBootId) {
    pageBootId = incomingBoot;
    knownRevision = 0;
    restarted = true;
  }
  if (versionDrift) {
    signalAppUpdateIfNeeded();
    return restarted ? "update_restart" : "update";
  }
  if (restarted) return "restart";
  return "ok";
}

function ingestLiveHeaders(res, method) {
  if (!res || typeof res.headers?.get !== "function") return;
  const revisionRaw = res.headers.get("X-WRU-Revision");
  const boot = res.headers.get("X-WRU-Boot-Id");
  const version = res.headers.get("X-WRU-Asset-Version");
  if (revisionRaw == null && !boot && !version) return;
  const revision = Number(revisionRaw);
  const data = {
    revision: Number.isFinite(revision) ? revision : undefined,
    boot_id: boot || undefined,
    asset_version: version || undefined,
  };
  const ident = rememberServerIdentity(data);
  if (ident === "restart" || ident === "update_restart") {
    knownRevision = 0;
    queueLiveRefresh({ type: "sites_changed", reason: "restart", ...data });
  }
  const verb = String(method || "GET").toUpperCase();
  if (verb !== "GET" && verb !== "HEAD" && verb !== "OPTIONS" && typeof data.revision === "number") {
    markLiveRevision(data.revision);
  }
}

/** Fetch current server revision — used on boot and as SSE fallback. */
export async function syncLiveRevision() {
  try {
    const data = await api("/api/live/revision");
    const ident = rememberServerIdentity(data);
    if (ident === "restart" || ident === "update_restart") {
      queueLiveRefresh({ type: "sites_changed", reason: "restart", revision: data?.revision });
    }
    if (typeof data?.revision === "number") {
      markLiveRevision(data.revision);
    }
    if (ident === "restart") {
      queueLiveRefresh({ type: "sites_changed", reason: "restart", revision: data?.revision });
    }
    return data?.revision ?? knownRevision;
  } catch {
    return knownRevision;
  }
}

/**
 * Subscribe to coalesced live refresh events (SSE + revision polling).
 * Handler receives { type, site_ids, reason, actor_name, client_id, revision, ts }.
 */
export function onLiveSitesChanged(handler) {
  if (typeof handler !== "function") return () => {};
  liveHandlers.add(handler);
  bootstrapLiveSync();
  return () => liveHandlers.delete(handler);
}

function bootstrapLiveSync() {
  if (!liveBootstrapped) {
    liveBootstrapped = true;
    startLivePoll();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") return;
      startLivePoll();
      checkLiveRevision().catch(() => {});
      if (!liveSource && !liveConnecting) ensureLiveSync();
    });
    window.addEventListener("online", () => {
      checkLiveRevision().catch(() => {});
      if (!liveSource && !liveConnecting) ensureLiveSync();
    });
    window.addEventListener("pageshow", () => {
      checkLiveRevision().catch(() => {});
      if (!liveSource && !liveConnecting) ensureLiveSync();
    });
  }
  ensureLiveSync();
}

function livePollDelay() {
  return document.visibilityState === "hidden" ? LIVE_POLL_HIDDEN_MS : LIVE_POLL_MS;
}

function startLivePoll() {
  if (livePollTimer) {
    clearInterval(livePollTimer);
    livePollTimer = null;
  }
  livePollTimer = setInterval(() => {
    checkLiveRevision().catch(() => {});
  }, livePollDelay());
}

async function checkLiveRevision() {
  const data = await api("/api/live/revision");
  const ident = rememberServerIdentity(data);
  const rev = data?.revision;
  if (ident === "restart" || ident === "update_restart") {
    knownRevision = typeof rev === "number" ? rev : 0;
    queueLiveRefresh({ type: "sites_changed", reason: "restart", revision: rev, ...data });
    return;
  }
  if (typeof rev !== "number" || rev <= knownRevision) return;
  knownRevision = rev;
  queueLiveRefresh({ type: "sites_changed", reason: "poll", revision: rev, ...data });
}

function queueLiveRefresh(event) {
  refreshPending = event;
  clearTimeout(refreshDebounce);
  refreshDebounce = setTimeout(() => {
    flushLiveRefresh().catch((err) => console.warn("Live refresh failed", err));
  }, LIVE_REFRESH_DEBOUNCE_MS);
}

async function flushLiveRefresh() {
  if (refreshRunning) return;
  if (!refreshPending) return;
  const event = refreshPending;
  refreshPending = null;
  refreshRunning = true;
  try {
    notifyLiveIfBackground(event);
    const handlers = [...liveHandlers];
    for (const handler of handlers) {
      try {
        await handler(event);
      } catch (err) {
        console.warn("Live refresh handler failed", err);
      }
    }
    if (typeof event?.revision === "number") {
      markLiveRevision(event.revision);
    }
  } finally {
    refreshRunning = false;
    if (refreshPending) {
      await flushLiveRefresh();
    }
  }
}

function ingestLivePayload(data) {
  if (!data || typeof data !== "object") return;
  const ident = rememberServerIdentity(data);
  if (data.type === "hello") {
    if (typeof data.revision === "number") markLiveRevision(data.revision);
    if (ident === "restart" || ident === "update_restart") {
      queueLiveRefresh({ type: "sites_changed", reason: "restart", ...data });
    }
    return;
  }
  if (data.type === "ping") {
    if (ident === "restart" || ident === "update_restart") {
      knownRevision = 0;
      queueLiveRefresh({ type: "sites_changed", reason: "restart", ...data });
      return;
    }
    if (typeof data.revision === "number" && data.revision > knownRevision) {
      knownRevision = data.revision;
      queueLiveRefresh({ type: "sites_changed", reason: "poll", ...data });
    }
    return;
  }
  if (data.type !== "sites_changed") return;
  try {
    window.dispatchEvent(new CustomEvent("wru:sites-changed", { detail: data }));
  } catch {
    /* ignore */
  }
  if (data.client_id && data.client_id === liveClientId() && data.reason !== "restart") return;
  if (typeof data.revision === "number") {
    if (data.revision <= knownRevision && ident !== "restart" && ident !== "update_restart") return;
    knownRevision = data.revision;
  }
  queueLiveRefresh(data);
}

export function ensureLiveSync() {
  if (liveSource || liveConnecting || typeof EventSource === "undefined") return;
  if (document.body?.classList.contains("must-change-password")) return;
  if (location.pathname === "/login") return;

  liveConnecting = true;
  const url = `/api/live/events?client_id=${encodeURIComponent(liveClientId())}`;
  const es = new EventSource(url, { withCredentials: true });
  liveSource = es;

  es.onopen = () => {
    liveConnecting = false;
    liveRetryMs = 1500;
    checkLiveRevision().catch(() => {});
  };
  es.onmessage = (msg) => {
    try {
      ingestLivePayload(JSON.parse(msg.data));
    } catch {
      /* ignore malformed */
    }
  };
  es.onerror = () => {
    liveConnecting = false;
    try {
      es.close();
    } catch {
      /* ignore */
    }
    liveSource = null;
    if (liveRetryTimer) clearTimeout(liveRetryTimer);
    liveRetryTimer = setTimeout(() => {
      liveRetryTimer = null;
      ensureLiveSync();
    }, liveRetryMs);
    liveRetryMs = Math.min(liveRetryMs * 1.7, 8000);
    checkLiveRevision().catch(() => {});
  };
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
  document.body.classList.toggle("must-change-password", Boolean(currentUser()?.must_change_password));
  ensureShellStructure();

  const canComms = isCommsUser();
  const links = isAdmin
    ? ADMIN_NAV
    : OPS_NAV.filter((l) => !l.commsOnly || canComms);
  const sidebar = document.querySelector("[data-app-sidebar]");
  if (sidebar) {
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
    `;
  }

  const who = escapeHtml(userName() || "");
  const roleLabel = escapeHtml(currentUser()?.role || "");
  const header = document.querySelector("[data-app-header]");
  if (header) {
    header.classList.toggle("topbar-admin", isAdmin);
    const adminToggle = canAdmin
      ? `<button type="button" class="admin-switch" id="adminModeToggle" role="switch"
          aria-checked="${isAdmin ? "true" : "false"}"
          aria-label="${isAdmin ? "Admin console on. Switch to tracker" : "Admin console off. Switch to admin"}"
          title="${isAdmin ? "Back to tracker" : "Open admin console"}">
          <span class="admin-switch-thumb admin-switch-label" aria-hidden="true">Admin</span>
        </button>`
      : "";
    const userMenu = who
      ? `<div class="user-menu">
        <button type="button" class="user-menu-btn" id="userMenuBtn" aria-expanded="false" aria-haspopup="menu" aria-controls="userMenuPanel">
          <span class="session-user" title="Signed in">${who}</span>
          <span class="user-menu-caret" aria-hidden="true">▾</span>
        </button>
        <div class="user-menu-panel" id="userMenuPanel" hidden role="menu">
          <p class="user-menu-who">${who}${roleLabel ? ` <span class="hint">${roleLabel}</span>` : ""}</p>
          <a role="menuitem" href="/tracking?mine=1">My activity</a>
          <a role="menuitem" href="/account">Account</a>
          <a role="menuitem" href="/password" id="changePasswordLink">Change password</a>
          <div class="user-menu-row">
            <span>Dark mode</span>
            <button type="button" class="switch" id="themeToggle" data-theme-toggle role="switch" aria-checked="false">
              <span class="switch-knob" aria-hidden="true"></span>
            </button>
          </div>
          <button type="button" class="user-menu-action" id="btnInstallApp" hidden role="menuitem">Install app</button>
          <button type="button" class="user-menu-action" id="btnLiveAlerts" hidden role="menuitem">Live alerts</button>
          <button type="button" class="user-menu-action user-menu-signout" id="logoutBtn" role="menuitem">Sign out</button>
        </div>
      </div>`
      : "";
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
        ${who ? `<div class="notify-bell-wrap" id="notifyBellWrap">
          <button type="button" class="notify-bell-btn" id="notifyBellBtn" aria-expanded="false" aria-controls="notifyPanel" aria-label="Notifications">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 22a2.2 2.2 0 0 0 2.2-2.2H9.8A2.2 2.2 0 0 0 12 22Zm7-6.2V11a7 7 0 0 0-5-6.7V3.8a2 2 0 1 0-4 0v.5A7 7 0 0 0 5 11v4.8L3.4 17.4A1 1 0 0 0 4.1 19h15.8a1 1 0 0 0 .7-1.6Z"/></svg>
            <span class="notify-badge" id="notifyBadge" hidden>0</span>
          </button>
          <div class="notify-panel" id="notifyPanel" hidden role="dialog" aria-label="Notifications">
            <div class="notify-panel-head">
              <strong>Notifications</strong>
              <button type="button" class="btn btn-sm" id="notifyReadAll">Mark all read</button>
            </div>
            <div class="notify-list" id="notifyList">
              <p class="notify-empty">Loading…</p>
            </div>
          </div>
        </div>` : ""}
        ${adminToggle}
        ${userMenu}
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
  wireUserMenu();
  initThemeToggle();
  $("adminModeToggle")?.addEventListener("click", () => {
    location.href = isAdmin ? "/" : "/admin";
  });
  $("logoutBtn")?.addEventListener("click", () => {
    logout();
  });
  enhanceNumberInputs(document);
  watchNumberInputs();
  registerServiceWorker();
  initPwaChrome();
  if (location.pathname !== "/login") {
    bootstrapLiveSync();
    import("./notifications.js")
      .then((m) => m.mountNotifications())
      .catch(() => {});
  }
  if (!document.documentElement.dataset.wruDocDl) {
    document.documentElement.dataset.wruDocDl = "1";
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href") || "";
      const m = href.match(/^\/api\/documents\/(\d+)\/download\/?$/);
      if (!m) return;
      ev.preventDefault();
      downloadDocumentById(m[1]).catch((err) => {
        alertDialog(errorMessage(err, "Could not download"));
      });
    });
  }
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
  if (key == null || key === "") return "Not started";
  return meta?.workflow_stages?.find((s) => s.key === key)?.label || key;
}

export function mustBandClass(band) {
  if (band === "received") return "must-have received";
  if (band === "ok" || band === "warn") return "must-have warn";
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
