import { $, api, escapeHtml, injectChrome, alertDialog, confirmDialog } from "./common.js";

async function loadRules() {
  const r = await api("/api/admin/settings");
  $("rMustOffset").value = r.must_have_offset_business_days;
  $("rPriority").value = r.priority_must_have_days;
  $("rMustWarn").value = r.must_have_warn_days;
  $("rMustCrit").value = r.must_have_critical_days;
  $("rCouncil").value = r.council_no_objection_business_days;
  $("rMoaSla").value = r.moa_wait_sla_business_days;
  $("rValWarn").value = r.permit_validity_warn_days;
  $("rValCrit").value = r.permit_validity_critical_days;
  $("rAutoMust").checked = !!r.auto_compute_must_have;
  $("rAutoArchive").checked = !!r.auto_archive_on_job_complete;
}

async function saveRules(ev) {
  ev.preventDefault();
  await api("/api/admin/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      must_have_offset_business_days: Number($("rMustOffset").value),
      priority_must_have_days: Number($("rPriority").value),
      must_have_warn_days: Number($("rMustWarn").value),
      must_have_critical_days: Number($("rMustCrit").value),
      council_no_objection_business_days: Number($("rCouncil").value),
      moa_wait_sla_business_days: Number($("rMoaSla").value),
      permit_validity_warn_days: Number($("rValWarn").value),
      permit_validity_critical_days: Number($("rValCrit").value),
      auto_compute_must_have: $("rAutoMust").checked,
      auto_archive_on_job_complete: $("rAutoArchive").checked,
    }),
  });
  $("rulesStatus").textContent = `Saved ${new Date().toLocaleTimeString()}`;
}

async function loadLookups() {
  const kind = $("lookupKind").value;
  const rows = await api(`/api/admin/lookups?kind=${encodeURIComponent(kind)}&active_only=false`);
  $("lookupList").innerHTML = rows.length
    ? rows
        .map(
          (r) => `<li>
          <div class="top">
            <span>${r.active ? "" : "<em>inactive · </em>"}${escapeHtml(r.value)}</span>
            <button type="button" class="btn btn-danger" data-del-lookup="${r.id}" ${r.active ? "" : "disabled"}>Remove</button>
          </div>
        </li>`
        )
        .join("")
    : `<li><p class="meta">No ${kind} values yet.</p></li>`;
}

async function addLookup() {
  const value = $("lookupValue").value.trim();
  if (!value) return;
  await api("/api/admin/lookups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: $("lookupKind").value, value }),
  });
  $("lookupValue").value = "";
  await loadLookups();
}

async function runImport(dryRun) {
  const file = $("importFile").files?.[0];
  if (!file) {
      alertDialog("Choose an Excel tracker file");
      return;
    }
  const fd = new FormData();
  fd.append("file", file);
  const params = new URLSearchParams({
    dry_run: dryRun ? "true" : "false",
    update_existing: $("importUpdate").checked ? "true" : "false",
  });
  $("importStatus").textContent = dryRun ? "Previewing…" : "Importing…";
  $("importLog").hidden = true;
  const res = await fetch(`/api/import/tracker?${params}`, { method: "POST", body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    $("importStatus").textContent = "";
    alertDialog(body.detail || "Import failed");
    return;
  }
  $("importStatus").textContent = dryRun
    ? `Preview: ${body.parsed} rows${body.unmatched_statuses?.length ? ` · unmatched statuses: ${body.unmatched_statuses.join(", ")}` : ""}`
    : `Imported · created ${body.created}, updated ${body.updated}, archived ${body.archived}${
        body.unmatched_statuses?.length ? ` · unmatched statuses listed below` : ""
      }`;
  $("importLog").hidden = false;
  $("importLog").textContent = JSON.stringify(body, null, 2);
}

async function init() {
  injectChrome({ active: "/admin/settings", mode: "admin" });
  $("rulesForm").addEventListener("submit", (e) => saveRules(e).catch((err) => { alertDialog(err.message); }));
  $("lookupKind").addEventListener("change", () => loadLookups().catch((e) => { alertDialog(e.message); }));
  $("btnAddLookup").addEventListener("click", () => addLookup().catch((e) => { alertDialog(e.message); }));
  $("lookupList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-lookup]");
    if (!btn) return;
    await api(`/api/admin/lookups/${btn.dataset.delLookup}`, { method: "DELETE" });
    await loadLookups();
  });
  $("btnDryRun").addEventListener("click", () => runImport(true).catch((e) => { alertDialog(e.message); }));
  $("btnImport").addEventListener("click", async () => {
    if (!(await confirmDialog("Import tracker rows into the live register?"))) return;
    runImport(false).catch((e) => { alertDialog(e.message); });
  });
  await loadRules();
  await loadLookups();
}

init().catch((e) => { alertDialog(e.message); });
