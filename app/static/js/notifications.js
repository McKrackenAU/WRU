import { $, api, escapeHtml, applyAppUpdate, pendingAppUpdate } from "./common.js";

const POLL_MS = 45000;
const BELL_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 22a2.2 2.2 0 0 0 2.2-2.2H9.8A2.2 2.2 0 0 0 12 22Zm7-6.2V11a7 7 0 0 0-5-6.7V3.8a2 2 0 1 0-4 0v.5A7 7 0 0 0 5 11v4.8L3.4 17.4A1 1 0 0 0 4.1 19h15.8a1 1 0 0 0 .7-1.6Z"/></svg>`;

let pollTimer = null;

function fmtWhen(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function setBadge(count) {
  const badge = $("notifyBadge");
  if (!badge) return;
  const extra = pendingAppUpdate() ? 1 : 0;
  const n = (Number(count) || 0) + extra;
  badge.hidden = n <= 0;
  badge.textContent = n > 99 ? "99+" : String(n);
  const btn = $("notifyBellBtn");
  if (btn) {
    btn.setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications");
  }
  $("notifyBellWrap")?.classList.toggle("has-app-update", Boolean(pendingAppUpdate()));
}

function updateCardHtml() {
  const pending = pendingAppUpdate();
  if (!pending) return "";
  return `<div class="notify-item notify-update is-unread" data-app-update>
    <strong>App update ready</strong>
    <span>This tab is still on v${escapeHtml(pending.current)}. The installed app is v${escapeHtml(pending.available)}. Keep working and saving — refresh when you are ready so this flag clears.</span>
    <button type="button" class="btn btn-primary btn-sm" id="notifyApplyUpdate">Refresh now</button>
  </div>`;
}

function renderItems(items) {
  const list = $("notifyList");
  if (!list) return;
  const updateHtml = updateCardHtml();
  const rows = (items || [])
    .map((n) => {
      const unread = n.read ? "" : " is-unread";
      const href = n.link || "/";
      return `<a class="notify-item${unread}" href="${escapeHtml(href)}" data-id="${n.id}">
        <strong>${escapeHtml(n.title || "Update")}</strong>
        <span>${escapeHtml(n.body || "")}</span>
        <time>${escapeHtml(fmtWhen(n.created_at))}</time>
      </a>`;
    })
    .join("");
  if (!updateHtml && !rows) {
    list.innerHTML = `<p class="notify-empty">No notifications yet.</p>`;
    return;
  }
  list.innerHTML = `${updateHtml}${rows}`;
}

export async function refreshNotifications({ render = true } = {}) {
  try {
    const data = await api("/api/notifications?limit=40", { timeoutMs: 8000 });
    setBadge(data.unread_count);
    if (render) renderItems(data.items || []);
    return data;
  } catch {
    return null;
  }
}

function closePanel() {
  const panel = $("notifyPanel");
  const btn = $("notifyBellBtn");
  if (panel) panel.hidden = true;
  btn?.setAttribute("aria-expanded", "false");
}

function togglePanel(ev) {
  ev.preventDefault();
  ev.stopPropagation();
  const panel = $("notifyPanel");
  const btn = $("notifyBellBtn");
  if (!panel || !btn) return;
  const open = panel.hidden;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) refreshNotifications({ render: true });
}

async function markOneRead(id) {
  if (!id) return;
  try {
    await api(`/api/notifications/${id}/read`, { method: "POST", timeoutMs: 8000 });
    await refreshNotifications({ render: true });
  } catch {
    /* ignore */
  }
}

export function mountNotifications() {
  const wrap = $("notifyBellWrap");
  if (!wrap || wrap.dataset.bound) return;
  wrap.dataset.bound = "1";

  $("notifyBellBtn")?.addEventListener("click", togglePanel);
  document.addEventListener("click", (ev) => {
    if (ev.target.closest("#notifyBellWrap")) return;
    closePanel();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closePanel();
  });
  $("notifyReadAll")?.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    try {
      await api("/api/notifications/read-all", { method: "POST", timeoutMs: 8000 });
      await refreshNotifications({ render: true });
    } catch {
      /* ignore */
    }
  });
  $("notifyList")?.addEventListener("click", (ev) => {
    if (ev.target.closest("#notifyApplyUpdate")) {
      ev.preventDefault();
      ev.stopPropagation();
      applyAppUpdate();
      return;
    }
    const item = ev.target.closest(".notify-item[data-id]");
    if (!item) return;
    markOneRead(item.dataset.id);
  });

  window.addEventListener("wru:sites-changed", () => {
    refreshNotifications({ render: !$("notifyPanel")?.hidden });
  });
  window.addEventListener("wru:app-update", () => {
    refreshNotifications({ render: !$("notifyPanel")?.hidden });
  });

  refreshNotifications({ render: false });
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    refreshNotifications({ render: !$("notifyPanel")?.hidden });
  }, POLL_MS);
}

export function notifyBellHtml() {
  return `<div class="notify-bell-wrap" id="notifyBellWrap">
    <button type="button" class="notify-bell-btn" id="notifyBellBtn" aria-expanded="false" aria-controls="notifyPanel" aria-label="Notifications">
      ${BELL_SVG}
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
  </div>`;
}
