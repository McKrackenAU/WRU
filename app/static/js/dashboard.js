import { $, api, currentUser, escapeHtml, injectChrome, onLiveSitesChanged, syncLiveRevision } from "./common.js";

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

function money(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function widgetSet() {
  const prefs = currentUser()?.prefs || {};
  const list = prefs.home_widgets || ["approvals", "status", "comms", "costs", "spend", "stages"];
  return new Set(list);
}

function moneyCard(title, rows) {
  return `<section class="panel-card">
    <h2>${escapeHtml(title)}</h2>
    <div class="stat-grid money-grid">
      ${rows
        .map(
          ([label, value]) => `<div class="stat-card">
        <div class="label">${escapeHtml(label)}</div>
        <div class="value">${typeof value === "number" ? money(value) : escapeHtml(value)}</div>
      </div>`
        )
        .join("")}
    </div>
  </section>`;
}

function renderHomeChrome() {
  const host = $("homeGrid");
  if (!host) return;
  const on = widgetSet();
  const parts = [];
  if (on.has("approvals")) {
    parts.push(`<section class="panel-card"><h2>Recently approved MoAs</h2><ul class="event-list" id="approvalList"></ul></section>`);
  }
  if (on.has("status")) {
    parts.push(`<section class="panel-card"><h2>Status changes</h2><ul class="event-list" id="statusList"></ul></section>`);
  }
  if (on.has("comms")) {
    parts.push(`<section class="panel-card landing-comms">
      <div class="page-head lists-panel-head">
        <div>
          <h2>Comms</h2>
          <p class="hint">Jobs that match your tags</p>
        </div>
        <a class="btn btn-sm" href="/comms">Open planner</a>
      </div>
      <ul class="event-list" id="commsPreview"></ul>
    </section>`);
  }
  if (on.has("costs")) parts.push(`<div id="costTotalsCard"></div>`);
  if (on.has("spend")) parts.push(`<div id="spendTotalsCard"></div>`);
  host.innerHTML = parts.join("") || `<p class="hint">Choose Home widgets on <a href="/account">Account &amp; look</a>.</p>`;
  const more = $("landingMore");
  if (more) more.hidden = !(on.has("stages") || on.has("programs") || on.has("councils"));
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  const on = widgetSet();
  const tags = data.focus_tags || [];
  const hint = $("dashFocusHint");
  if (hint) {
    hint.textContent = tags.length
      ? `Showing work tagged ${tags.join(", ")}.`
      : "Recently approved MoAs, status changes, comms, and traffic costs. Customise widgets on Account.";
  }

  if (on.has("approvals") && $("approvalList")) {
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
  }

  if (on.has("status") && $("statusList")) {
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
  }

  if (on.has("comms") && $("commsPreview")) {
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
  }

  if (on.has("costs") && $("costTotalsCard")) {
    const c = data.cost_totals || {};
    $("costTotalsCard").innerHTML = moneyCard("Estimated traffic costs", [
      ["Latest estimates", c.estimated || 0],
      ["Sites with costs", String(c.sites_with_cost || 0)],
    ]);
  }
  if (on.has("spend") && $("spendTotalsCard")) {
    const s = data.spend_totals || {};
    $("spendTotalsCard").innerHTML = moneyCard("Actual spend", [
      ["Traffic", s.traffic || 0],
      ["Pavements", s.asphalt || 0],
      ["Total", s.total || 0],
    ]);
  }

  if ($("statGrid")) {
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
  }

  if ($("stageBars") && on.has("stages")) {
    $("stageBars").innerHTML = barRows(data.by_stage.map((s) => ({ label: s.label, count: s.count })));
  }
  if ($("councilBars") && on.has("councils")) {
    $("councilBars").innerHTML = barRows(data.by_council) || `<p class="hint">No councils attributed yet.</p>`;
  }
  if ($("programBars") && on.has("programs")) {
    $("programBars").innerHTML = barRows(data.by_program) || `<p class="hint">No programs set.</p>`;
  }
  if ($("recentList")) {
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
}

async function init() {
  await injectChrome({ active: "/dashboard" });
  renderHomeChrome();
  onLiveSitesChanged(() => loadDashboard().catch(() => {}));
  await loadDashboard();
  await syncLiveRevision();
}

init().catch((err) => {
  const host = $("homeGrid") || $("approvalList") || $("statGrid");
  if (host) host.innerHTML = `<p class="hint">${escapeHtml(err.message)}</p>`;
});
