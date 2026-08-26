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

async function loadDashboard() {
  const data = await api("/api/dashboard");
  $("statGrid").innerHTML = [
    ["Active sites", data.totals.active_sites],
    ["Archived", data.totals.archived_sites],
    ["Priority 1", data.priority.priority_1],
    ["Priority 2", data.priority.priority_2],
    ["Permits list", data.permits_priority_count],
    ["TRIMS list", data.trims_priority_count || 0],
    ["Must-have overdue", data.must_have.overdue],
    ["Must-have late (14+)", data.must_have.late],
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
  $("statGrid").innerHTML = `<p class="hint">${escapeHtml(err.message)}</p>`;
});
