import {
  $,
  api,
  confirmDialog,
  currentUser,
  escapeHtml,
  injectChrome,
  on,
  onLiveSitesChanged,
  saveUserPrefs,
  syncLiveRevision,
} from "./common.js";

const CHART_METRICS = {
  stages: "Stages",
  programs: "Programs",
  councils: "Councils",
  priority: "Priority",
  must_have: "Must-have status",
  lists: "Client lists",
  costs: "Traffic estimates",
  spend: "Actual spend",
  sites: "Site totals",
};

const PIE_COLORS = [
  "#2563eb",
  "#dc2626",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#0891b2",
  "#db2777",
  "#4b5563",
  "#65a30d",
  "#ea580c",
  "#0f766e",
  "#9333ea",
];
const MAX_HOME_CHARTS = 8;

let chartMeta = { programs: [], councils: [] };

function barRows(items, max) {
  const m = max || Math.max(1, ...items.map((i) => Number(i.count) || 0));
  return items
    .map(
      (i) => `
    <div class="bar-row">
      <span>${escapeHtml(i.label || i.name)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round((100 * (Number(i.count) || 0)) / m)}%"></div></div>
      <strong>${formatChartValue(i)}</strong>
    </div>`
    )
    .join("");
}

function formatChartValue(item) {
  const n = Number(item.count) || 0;
  if (item.money) {
    return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return String(n);
}

function pieSvg(items) {
  const rows = items.map((item, idx) => ({
    label: item.label || item.name || "",
    count: Number(item.count) || 0,
    money: !!item.money,
    color: PIE_COLORS[idx % PIE_COLORS.length],
  }));
  const usable = rows.filter((i) => i.count > 0);
  const total = usable.reduce((sum, i) => sum + i.count, 0);
  if (!total) return `<p class="hint">No data yet.</p>`;
  const r = 42;
  const cx = 50;
  const cy = 50;
  let angle = -Math.PI / 2;
  const slices = [];
  usable.forEach((item) => {
    const value = item.count;
    const color = item.color;
    if (value === total) {
      slices.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}"></circle>`);
      return;
    }
    const sweep = (value / total) * Math.PI * 2;
    const end = angle + sweep;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(end);
    const y2 = cy + r * Math.sin(end);
    const large = sweep > Math.PI ? 1 : 0;
    slices.push(
      `<path d="M ${cx} ${cy} L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z" fill="${color}"></path>`
    );
    angle = end;
  });
  const legend = usable
    .map((item) => {
      const pct = Math.round((100 * item.count) / total);
      return `<div><span class="pie-swatch" style="background:${item.color}"></span>${escapeHtml(item.label)} <strong>${formatChartValue(item)}</strong> <span class="meta">${pct}%</span></div>`;
    })
    .join("");
  return `<div class="pie-chart">
    <svg viewBox="0 0 100 100" class="pie-svg" role="img" aria-label="Pie chart">${slices.join("")}</svg>
    <div class="pie-legend">${legend}</div>
  </div>`;
}

function filteredJobs(data, chart) {
  const jobs = Array.isArray(data.jobs) ? data.jobs : [];
  const program = String(chart?.program || "")
    .trim()
    .toLowerCase();
  const council = String(chart?.council || "")
    .trim()
    .toLowerCase();
  const includeArchived = !!chart?.include_archived;
  return jobs.filter((job) => {
    if (!includeArchived && job.archived) return false;
    if (program && String(job.program || "").trim().toLowerCase() !== program) return false;
    if (
      council &&
      !(job.councils || []).some((name) => String(name || "").trim().toLowerCase() === council)
    ) {
      return false;
    }
    return true;
  });
}

function countBy(jobs, keyFn) {
  const counts = {};
  for (const job of jobs) {
    const key = keyFn(job);
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function seriesFor(metric, data, chart = {}) {
  const jobs = filteredJobs(data, chart);
  const useJobs = Array.isArray(data.jobs);
  let series = [];
  switch (metric) {
    case "stages":
      if (useJobs) {
        const counts = countBy(jobs, (j) => j.stage || "not_started");
        series = (data.by_stage || []).map((s) => ({ label: s.label, count: counts[s.key] || 0 }));
      } else {
        series = (data.by_stage || []).map((s) => ({ label: s.label, count: s.count }));
      }
      break;
    case "programs":
      if (useJobs) {
        const counts = countBy(jobs, (j) => j.program || "(no program)");
        series = Object.entries(counts)
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
          .map(([label, count]) => ({ label, count }));
      } else {
        series = (data.by_program || []).map((s) => ({ label: s.name, count: s.count }));
      }
      break;
    case "councils":
      if (useJobs) {
        const counts = {};
        for (const job of jobs) {
          const names = job.councils?.length ? job.councils : ["(unassigned)"];
          for (const name of names) counts[name] = (counts[name] || 0) + 1;
        }
        series = Object.entries(counts)
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
          .map(([label, count]) => ({ label, count }));
      } else {
        series = (data.by_council || []).map((s) => ({ label: s.name, count: s.count }));
      }
      break;
    case "priority":
      if (useJobs) {
        series = [
          { label: "Priority 1", count: jobs.filter((j) => Number(j.priority) === 1).length },
          { label: "Priority 2", count: jobs.filter((j) => Number(j.priority) === 2).length },
        ];
      } else {
        series = [
          { label: "Priority 1", count: data.priority?.priority_1 || 0 },
          { label: "Priority 2", count: data.priority?.priority_2 || 0 },
        ];
      }
      break;
    case "must_have":
      if (useJobs) {
        const counts = countBy(jobs, (j) => j.must_have || "none");
        series = [
          { label: "On time", count: counts.ok || 0 },
          { label: "Not submitted", count: counts.late || 0 },
          { label: "Overdue", count: counts.overdue || 0 },
          { label: "None", count: counts.none || 0 },
        ];
      } else {
        series = [
          { label: "On time", count: data.must_have?.ok || 0 },
          { label: "Not submitted", count: data.must_have?.late || 0 },
          { label: "Overdue", count: data.must_have?.overdue || 0 },
          { label: "None", count: data.must_have?.none || 0 },
        ];
      }
      break;
    case "lists":
      if (useJobs) {
        series = [
          { label: "Permits", count: jobs.filter((j) => j.on_permits).length },
          { label: "TRIMS", count: jobs.filter((j) => j.on_trims).length },
        ];
      } else {
        series = [
          { label: "Permits", count: data.permits_priority_count || 0 },
          { label: "TRIMS", count: data.trims_priority_count || 0 },
        ];
      }
      break;
    case "costs":
      if (useJobs) {
        const estimated = jobs.reduce((sum, j) => sum + (Number(j.estimated) || 0), 0);
        series = [
          { label: "Latest estimates", count: estimated, money: true },
          { label: "Sites with costs", count: jobs.filter((j) => (Number(j.estimated) || 0) > 0).length },
        ];
      } else {
        series = [
          { label: "Latest estimates", count: data.cost_totals?.estimated || 0, money: true },
          { label: "Sites with costs", count: data.cost_totals?.sites_with_cost || 0 },
        ];
      }
      break;
    case "spend":
      series = [
        { label: "Traffic", count: data.spend_totals?.traffic || 0, money: true },
        { label: "Pavements", count: data.spend_totals?.asphalt || 0, money: true },
        { label: "Total", count: data.spend_totals?.total || 0, money: true },
      ];
      break;
    case "sites":
      if (useJobs) {
        series = [
          { label: "Active", count: jobs.filter((j) => !j.archived).length },
          { label: "Archived", count: jobs.filter((j) => j.archived).length },
          { label: "Documents", count: jobs.reduce((sum, j) => sum + (Number(j.documents) || 0), 0) },
        ];
      } else {
        series = [
          { label: "Active", count: data.totals?.active_sites || 0 },
          { label: "Archived", count: data.totals?.archived_sites || 0 },
          { label: "Documents", count: data.totals?.documents || 0 },
        ];
      }
      break;
    default:
      series = [];
  }
  if (chart.hide_empty !== false) {
    const kept = series.filter((i) => (Number(i.count) || 0) > 0);
    if (kept.length) series = kept;
  }
  return series;
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

function homeCharts() {
  return [...(currentUser()?.prefs?.home_charts || [])];
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

function chartScopeHint(chart) {
  const bits = [chart.chart === "pie" ? "Pie" : "Bar", CHART_METRICS[chart.metric] || chart.metric];
  if (chart.program) bits.push(chart.program);
  if (chart.council) bits.push(chart.council);
  if (chart.include_archived) bits.push("incl. archive");
  return bits.join(" · ");
}

function chartCard(chart, data) {
  const metricLabel = CHART_METRICS[chart.metric] || chart.metric;
  const title = chart.title || metricLabel;
  const kind = chart.chart === "pie" ? "pie" : "bar";
  const series = seriesFor(chart.metric, data, chart);
  const body = !series.length
    ? `<p class="hint">No data yet.</p>`
    : kind === "pie"
      ? pieSvg(series)
      : barRows(series) || `<p class="hint">No data yet.</p>`;
  return `<section class="panel-card home-chart-card" data-chart-id="${escapeHtml(chart.id)}">
    <div class="page-head lists-panel-head">
      <div>
        <h2>${escapeHtml(title)}</h2>
        <p class="hint">${escapeHtml(chartScopeHint(chart))}</p>
      </div>
      <div class="toolbar">
        <button type="button" class="btn btn-sm" data-edit-chart="${escapeHtml(chart.id)}">Edit</button>
        <button type="button" class="btn btn-sm" data-remove-chart="${escapeHtml(chart.id)}">Remove</button>
      </div>
    </div>
    ${body}
  </section>`;
}

function renderHomeCharts(data) {
  const host = $("homeCharts");
  if (!host) return;
  const charts = homeCharts();
  host.innerHTML = charts.length
    ? charts.map((chart) => chartCard(chart, data)).join("")
    : `<p class="hint">No custom graphs yet. Use Add graph to pick stages, programs, spend, or other totals.</p>`;
}

function closeChartDialog() {
  const el = $("homeChartDialog");
  if (!el) return;
  if (typeof el.close === "function") el.close();
  else el.removeAttribute("open");
}

function openChartDialog() {
  const el = $("homeChartDialog");
  if (!el) return;
  if (typeof el.showModal === "function") el.showModal();
  else el.setAttribute("open", "");
}

function fillSelect(id, values, selected, allLabel) {
  const el = $(id);
  if (!el) return;
  const opts = [`<option value="">${escapeHtml(allLabel)}</option>`].concat(
    (values || []).map(
      (value) =>
        `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(value)}</option>`
    )
  );
  el.innerHTML = opts.join("");
  if (selected && ![...el.options].some((o) => o.value === selected)) {
    el.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`);
  }
}

function fillChartForm(chart) {
  $("chartEditId").value = chart?.id || "";
  $("chartTitle").value = chart?.title || "";
  $("chartMetric").value = chart?.metric && CHART_METRICS[chart.metric] ? chart.metric : "stages";
  $("chartType").value = chart?.chart === "pie" ? "pie" : "bar";
  fillSelect("chartProgram", chartMeta.programs, chart?.program || "", "All programs / categories");
  fillSelect("chartCouncil", chartMeta.councils, chart?.council || "", "All councils");
  if ($("chartIncludeArchived")) $("chartIncludeArchived").checked = !!chart?.include_archived;
  if ($("chartHideEmpty")) $("chartHideEmpty").checked = chart?.hide_empty !== false;
  $("homeChartDialogTitle").textContent = chart?.id ? "Edit graph" : "Add graph";
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

async function persistCharts(charts) {
  await saveUserPrefs({ home_charts: charts });
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  const on = widgetSet();
  const tags = data.focus_tags || [];
  const hint = $("dashFocusHint");
  if (hint) {
    hint.textContent = tags.length
      ? `Showing work tagged ${tags.join(", ")}.`
      : "Recently approved MoAs, status changes, comms, and traffic costs. Add graphs below, or customise widgets on Account.";
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

  renderHomeCharts(data);
}

function newChartId() {
  return `c${Date.now().toString(36)}${Math.floor(Math.random() * 36).toString(36)}`;
}

function bindChartUi() {
  on("btnAddGraph", "click", () => {
    if (homeCharts().length >= MAX_HOME_CHARTS) {
      $("dashFocusHint").textContent = "You can pin up to eight graphs. Remove one before adding another.";
      return;
    }
    fillChartForm(null);
    openChartDialog();
    $("chartTitle")?.focus();
  });

  async function saveChartFromForm(ev) {
    if (ev) ev.preventDefault();
    const metric = $("chartMetric")?.value || "stages";
    const kind = $("chartType")?.value === "pie" ? "pie" : "bar";
    const title = ($("chartTitle")?.value || "").trim();
    const payload = {
      title,
      metric,
      chart: kind,
      program: $("chartProgram")?.value || "",
      council: $("chartCouncil")?.value || "",
      include_archived: !!$("chartIncludeArchived")?.checked,
      hide_empty: $("chartHideEmpty") ? $("chartHideEmpty").checked : true,
    };
    const editId = $("chartEditId")?.value || "";
    const next = homeCharts();
    if (editId) {
      const idx = next.findIndex((c) => c.id === editId);
      if (idx >= 0) next[idx] = { ...next[idx], ...payload };
    } else {
      if (next.length >= MAX_HOME_CHARTS) return;
      next.push({ id: newChartId(), ...payload });
    }
    const saveBtn = $("homeChartSave");
    if (saveBtn) saveBtn.disabled = true;
    try {
      await persistCharts(next);
      closeChartDialog();
      await loadDashboard();
    } catch (err) {
      if ($("dashFocusHint")) $("dashFocusHint").textContent = err.message || String(err);
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  on("homeChartForm", "submit", saveChartFromForm);
  on("homeChartSave", "click", saveChartFromForm);

  document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => closeChartDialog());
  });

  $("homeCharts")?.addEventListener("click", async (ev) => {
    const edit = ev.target.closest("[data-edit-chart]");
    if (edit) {
      const chart = homeCharts().find((c) => c.id === edit.getAttribute("data-edit-chart"));
      if (!chart) return;
      fillChartForm(chart);
      openChartDialog();
      $("chartTitle")?.focus();
      return;
    }
    const remove = ev.target.closest("[data-remove-chart]");
    if (!remove) return;
    const id = remove.getAttribute("data-remove-chart");
    const ok = await confirmDialog("Remove this graph from Home? You can add it again later.", {
      title: "Remove graph",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    await persistCharts(homeCharts().filter((c) => c.id !== id));
    await loadDashboard();
  });
}

async function init() {
  await injectChrome({ active: "/dashboard" });
  try {
    const meta = await api("/api/meta");
    chartMeta = { programs: meta.programs || [], councils: meta.councils || [] };
  } catch {
    chartMeta = { programs: [], councils: [] };
  }
  renderHomeChrome();
  bindChartUi();
  onLiveSitesChanged(() => loadDashboard().catch(() => {}));
  await loadDashboard();
  await syncLiveRevision();
}

init().catch((err) => {
  const host = $("homeGrid") || $("approvalList") || $("statGrid");
  if (host) host.innerHTML = `<p class="hint">${escapeHtml(err.message)}</p>`;
});
