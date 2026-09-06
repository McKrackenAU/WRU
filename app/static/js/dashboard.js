import { $, api, escapeHtml, injectChrome, onLiveSitesChanged, syncLiveRevision } from "./common.js";

function barRows(items, max) {
  const m = max || Math.max(1, ...items.map((i) => i.count));
  return items
    .map(
      (i) => `
    <div class="bar-row">
      <span>${escapeHtml(i.label || i.name)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round((100 * i.count) / m)}%"></div></div>
      <strong>${i.count}</strong>
    </div>`
    )
    .join("");
}

function fmtWhen(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

function fmtDay(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

function emptyItem(text) {
  return `<li><p class="meta">${escapeHtml(text)}</p></li>`;
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  const tags = data.focus_tags || [];
  const hint = $("dashFocusHint");
  if (hint) {
    hint.textContent = tags.length
      ? `Showing work tagged ${tags.join(", ")}.`
      : "Recently approved MoAs, status changes, and comms. Add tags on your account to focus this page.";
  }

  $("approvalList").innerHTML = (data.recent_approvals || []).length
    ? data.recent_approvals
        .map(
          (s) => `
      <li>
        <div class="top">${escapeHtml(fmtDay(s.moa_received_date) || "Approved")}</div>
        <p><a href="/?highlight=${s.id}">${escapeHtml(s.road_name || "")} <span class="mono">${escapeHtml(s.site_number || "")}</span></a>
        ${s.moa_number ? ` · MoA ${escapeHtml(s.moa_number)}` : ""}
        ${s.program ? ` · ${escapeHtml(s.program)}` : ""}</p>
      </li>`
        )
        .join("")
    : emptyItem("No recently approved MoAs for your tags.");

  $("statusList").innerHTML = (data.recent_status_changes || []).length
    ? data.recent_status_changes
        .map(
          (e) => `
      <li>
        <div class="top">${escapeHtml(fmtWhen(e.created_at))}${e.site_number ? ` · ${escapeHtml(e.site_number)}` : ""}</div>
        <p>${e.site_id ? `<a href="/?highlight=${e.site_id}">${escapeHtml(e.message)}</a>` : escapeHtml(e.message)}</p>
      </li>`
        )
        .join("")
    : emptyItem("No recent status changes for your tags.");

  $("commsPreview").innerHTML = (data.comms_preview || []).length
    ? data.comms_preview
        .map(
          (row) => `
      <li>
        <div class="top">${escapeHtml(fmtWhen(row.updated_at))}</div>
        <p><a href="/comms">${escapeHtml(row.section || row.road_name || "Comms job")}
        ${row.site_number ? ` <span class="mono">${escapeHtml(row.site_number)}</span>` : ""}</a></p>
      </li>`
        )
        .join("")
    : emptyItem("No matching comms jobs.");

  $("statGrid").innerHTML = [
    ["Active sites", data.totals.active_sites],
    ["Archived", data.totals.archived_sites],
    ["Priority 1", data.priority.priority_1],
    ["Priority 2", data.priority.priority_2],
    ["Permits list", data.permits_priority_count],
    ["TRIMS list", data.trims_priority_count || 0],
    ["Must-have overdue", data.must_have.overdue],
    ["Must-have not submitted", data.must_have.late],
    ["Documents", data.totals.documents],
  ]
    .map(
      ([label, value]) => `
    <div class="stat-card">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${value}</div>
    </div>`
    )
    .join("");

  $("stageBars").innerHTML = barRows(
    data.by_stage.map((s) => ({ label: s.label, count: s.count }))
  );
  $("councilBars").innerHTML = barRows(data.by_council) || `<p class="hint">No councils attributed yet.</p>`;
  $("programBars").innerHTML = barRows(data.by_program) || `<p class="hint">No programs set.</p>`;
  $("recentList").innerHTML = data.recent_tracking.length
    ? data.recent_tracking
        .map(
          (e) => `
      <li>
        <div class="top">${new Date(e.created_at).toLocaleString()}</div>
        <p>${escapeHtml(e.message)}</p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No recent activity.</p></li>`;
}

async function init() {
  await injectChrome({ active: "/dashboard" });
  onLiveSitesChanged(() => loadDashboard().catch(() => {}));
  await loadDashboard();
  await syncLiveRevision();
}

init().catch((err) => {
  const host = $("approvalList") || $("statGrid");
  if (host) host.innerHTML = `<p class="hint">${escapeHtml(err.message)}</p>`;
});
