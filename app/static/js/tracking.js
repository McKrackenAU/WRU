import {
  $,
  api,
  escapeHtml,
  fmtDate,
  injectChrome,
  mustBandClass,
  stageLabel,
} from "./common.js";

let meta = { workflow_stages: [], councils: [], programs: [] };

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function load() {
  const params = new URLSearchParams({ archived: "false" });
  const q = $("search").value.trim();
  if (q) params.set("q", q);
  if ($("stageFilter").value) params.set("stage", $("stageFilter").value);
  if ($("councilFilter").value) params.set("council", $("councilFilter").value);
  if ($("programFilter").value) params.set("program", $("programFilter").value);
  if ($("priorityFilter").value) params.set("priority", $("priorityFilter").value);
  if ($("listFilter")?.value) params.set("client_list", $("listFilter").value);

  const sites = await api(`/api/sites?${params}`);
  $("tbody").innerHTML = sites.length
    ? sites
        .map((s) => {
          const m = s.metrics || {};
          const must = m.must_have_status || {};
          const wait =
            m.max_council_business_days_waiting != null
              ? `${m.max_council_business_days_waiting}d`
              : "—";
          return `<tr>
            <td><span class="priority p${s.today_priority}">${s.today_priority}</span></td>
            <td><strong>${escapeHtml(s.road_name)}</strong></td>
            <td class="mono">${escapeHtml(s.site_number)}</td>
            <td>${escapeHtml(s.program || "")}</td>
            <td>${(s.councils || []).map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join(" ") || "—"}</td>
            <td>${escapeHtml(stageLabel(meta, m.current_stage))}</td>
            <td class="progress-mini">${m.workflow_progress_pct ?? 0}%</td>
            <td class="mono">${escapeHtml(wait)}</td>
            <td class="mono">${fmtDate(s.indicative_site_start_date)}</td>
            <td class="mono"><span class="${mustBandClass(must.band)}">${fmtDate(s.moa_must_have_received_date)} ${must.label && must.label !== "—" ? `(${escapeHtml(must.label)})` : ""}</span></td>
            <td class="mono">${escapeHtml(s.moa_number || "")}</td>
            <td class="mono">${escapeHtml(s.tgs_reference || "")}</td>
            <td class="mono">${escapeHtml(m.client_list || "none")}</td>
          </tr>`;
        })
        .join("")
    : `<tr><td class="empty" colspan="13">No sites match filters.</td></tr>`;
  $("statusLine").textContent = `${sites.length} site${sites.length === 1 ? "" : "s"} shown`;
}

async function init() {
  injectChrome({ active: "/tracking" });
  meta = await api("/api/meta");
  $("stageFilter").innerHTML =
    `<option value="">All stages</option>` +
    meta.workflow_stages
      .map((s) => `<option value="${s.key}">${escapeHtml(s.label)}</option>`)
      .join("");
  $("councilFilter").innerHTML =
    `<option value="">All councils</option>` +
    (meta.councils || [])
      .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
      .join("");
  $("programFilter").innerHTML =
    `<option value="">All programs</option>` +
    (meta.programs || [])
      .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
      .join("");

  for (const id of ["stageFilter", "councilFilter", "programFilter", "priorityFilter", "listFilter"]) {
    $(id)?.addEventListener("change", load);
  }
  $("search").addEventListener("input", debounce(load, 250));
  await load();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="12">${escapeHtml(err.message)}</td></tr>`;
});
