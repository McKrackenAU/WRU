import { $, api, escapeHtml, injectChrome } from "./common.js";

async function init() {
  injectChrome({ active: "/admin", mode: "admin" });
  const [meta, sites, dash] = await Promise.all([
    api("/api/meta"),
    api("/api/sites?archived=false"),
    api("/api/dashboard").catch(() => null),
  ]);
  const rules = meta.rules || {};
  $("adminStats").innerHTML = `
    <div class="stat"><span class="stat-val">${sites.length}</span><span class="stat-label">Active sites</span></div>
    <div class="stat"><span class="stat-val">${meta.workflow_stages?.length || 0}</span><span class="stat-label">Active stages</span></div>
    <div class="stat"><span class="stat-val">${meta.programs?.length || 0}</span><span class="stat-label">Programs</span></div>
    <div class="stat"><span class="stat-val">${rules.must_have_offset_business_days ?? "—"}</span><span class="stat-label">Must-have offset (bd)</span></div>
    <div class="stat"><span class="stat-val">${rules.council_no_objection_business_days ?? "—"}</span><span class="stat-label">Council assume (bd)</span></div>
    <div class="stat"><span class="stat-val">${dash?.permits_priority_count ?? "—"}</span><span class="stat-label">On Permits list</span></div>
  `;
}

init().catch((e) => {
  $("adminStats").innerHTML = `<p class="hint">${escapeHtml(e.message)}</p>`;
});
