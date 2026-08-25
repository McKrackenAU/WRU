import { $, api, escapeHtml, injectChrome, alertDialog } from "./common.js";

function progressBar(pct) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="progress-bar thin" title="${p}%"><span style="width:${p}%;background:hsl(${(p * 1.2).toFixed(0)},65%,40%)"></span></div>`;
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

function renderRows(tbodyId, sites) {
  const tbody = $(tbodyId);
  if (!sites.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="6">No applications on this list.</td></tr>`;
    return;
  }
  tbody.innerHTML = sites
    .map(
      (s) => `<tr>
      <td class="col-pri"><span class="priority p${s.today_priority}">${s.today_priority}</span></td>
      <td class="col-road"><strong>${escapeHtml(s.road_name)}</strong>${progressBar(s.metrics?.workflow_progress_pct)}</td>
      <td class="col-site mono">${escapeHtml(s.site_number)}</td>
      <td class="col-program">${escapeHtml(s.program || "")}</td>
      <td class="col-council">${escapeHtml(councilWait(s))}</td>
      <td class="col-moa mono">${escapeHtml(s.moa_number || "")}</td>
    </tr>`
    )
    .join("");
}

async function init() {
  injectChrome({ active: "/lists" });
  const [permits, trims] = await Promise.all([
    api("/api/sites?archived=false&client_list=permits"),
    api("/api/sites?archived=false&client_list=trims"),
  ]);
  $("permitsHint").textContent = `${permits.length} application${permits.length === 1 ? "" : "s"} with the Permits team`;
  $("trimsHint").textContent = `${trims.length} application${trims.length === 1 ? "" : "s"} with the TRIMS team`;
  renderRows("permitsBody", permits);
  renderRows("trimsBody", trims);
}

init().catch((e) => { alertDialog(e.message); });
