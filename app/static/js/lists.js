import { $, api, escapeHtml, injectChrome, stageLabel } from "./common.js";

function progressBar(pct) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="progress-bar" title="${p}%"><span style="width:${p}%;background:hsl(${(p * 1.2).toFixed(0)},65%,40%)"></span></div>`;
}

function councilWait(site) {
  const wait = site.metrics?.max_council_business_days_waiting;
  if (wait != null) return `${wait} bus. days`;
  const rows = site.metrics?.councils || [];
  if (!rows.length) return "—";
  const assumed = rows.find((c) => c.status === "assumed_no_objection");
  if (assumed) return "Assumed OK";
  if (rows.every((c) => c.status === "no_objection" || c.status === "assumed_no_objection")) {
    return "No objection";
  }
  return "—";
}

function renderRows(tbodyId, sites, meta) {
  const tbody = $(tbodyId);
  if (!sites.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="7">No applications on this list.</td></tr>`;
    return;
  }
  tbody.innerHTML = sites
    .map(
      (s) => `<tr>
      <td><span class="priority p${s.today_priority}">${s.today_priority}</span></td>
      <td><strong>${escapeHtml(s.road_name)}</strong>${progressBar(s.metrics?.workflow_progress_pct)}</td>
      <td class="mono">${escapeHtml(s.site_number)}</td>
      <td>${escapeHtml(s.program || "")}</td>
      <td>${escapeHtml(stageLabel(meta, s.metrics?.current_stage))}</td>
      <td class="mono">${escapeHtml(councilWait(s))}</td>
      <td class="mono">${escapeHtml(s.moa_number || "")}</td>
    </tr>`
    )
    .join("");
}

async function init() {
  injectChrome({ active: "/lists" });
  const [meta, permits, trims] = await Promise.all([
    api("/api/meta"),
    api("/api/sites?archived=false&client_list=permits"),
    api("/api/sites?archived=false&client_list=trims"),
  ]);
  $("permitsHint").textContent = `${permits.length} application${permits.length === 1 ? "" : "s"} with the Permits team`;
  $("trimsHint").textContent = `${trims.length} application${trims.length === 1 ? "" : "s"} with the TRIMS team`;
  renderRows("permitsBody", permits, meta);
  renderRows("trimsBody", trims, meta);
}

init().catch((e) => alert(e.message));
