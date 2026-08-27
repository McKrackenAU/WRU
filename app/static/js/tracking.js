import {
  $,
  api,
  escapeHtml,
  injectChrome,
  onLiveSitesChanged,
  syncLiveRevision,
} from "./common.js";

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function fmtWhen(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

async function load() {
  const params = new URLSearchParams({ limit: "200" });
  const mine = new URLSearchParams(location.search).get("mine") === "1";
  const q = $("search")?.value?.trim() || "";
  const program = $("programFilter")?.value || "";
  const eventType = $("typeFilter")?.value || "";
  if (mine) params.set("mine", "1");
  if (q) params.set("q", q);
  if (program) params.set("program", program);
  if (eventType) params.set("event_type", eventType);

  const rows = await api(`/api/activity?${params}`);
  const list = Array.isArray(rows) ? rows : [];
  $("tbody").innerHTML = list.length
    ? list
        .map((e) => {
          const openHref = e.archived
            ? `/?view=${e.site_id}`
            : `/?highlight=${e.site_id}`;
          return `<tr>
            <td class="mono activity-when">${escapeHtml(fmtWhen(e.created_at))}</td>
            <td>
              <div class="activity-message">${escapeHtml(e.message)}</div>
              <div class="hint">${escapeHtml(e.event_type || "edit")}${
                e.created_by ? ` · ${escapeHtml(e.created_by)}` : ""
              }</div>
            </td>
            <td>${escapeHtml(e.program || "—")}</td>
            <td class="row-actions">
              <a class="btn btn-sm btn-primary" href="${openHref}">Open</a>
            </td>
          </tr>`;
        })
        .join("")
    : `<tr><td class="empty" colspan="4">No activity matches these filters yet. Change a site status or save costs to start the feed.</td></tr>`;
  $("statusLine").textContent = `${list.length} event${list.length === 1 ? "" : "s"}`;
}

async function init() {
  await injectChrome({ active: "/tracking" });
  const mine = new URLSearchParams(location.search).get("mine") === "1";
  if (mine) {
    const h1 = document.querySelector(".page-head h1");
    const blurb = document.querySelector(".page-head p");
    if (h1) h1.textContent = "My activity";
    if (blurb) blurb.textContent = "Your own change log — status moves, notes, costs, and archive actions you saved.";
    document.title = "My activity · WRU TGS Tracker";
  }
  const meta = await api("/api/meta");
  $("programFilter").innerHTML =
    `<option value="">All programs</option>` +
    (meta.programs || [])
      .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
      .join("");

  onLiveSitesChanged(() => load().catch(() => {}));
  $("programFilter")?.addEventListener("change", () => load().catch(() => {}));
  $("typeFilter")?.addEventListener("change", () => load().catch(() => {}));
  $("search")?.addEventListener("input", debounce(() => load().catch(() => {}), 250));
  await load();
  await syncLiveRevision();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="4">${escapeHtml(err.message)}</td></tr>`;
});
