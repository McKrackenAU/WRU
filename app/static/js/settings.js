import { $, api, escapeHtml, injectChrome, alertDialog, confirmDialog, errorMessage, formatApiDetail, humanizeHttpError } from "./common.js";

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

async function loadLookups(kind, listId, statusId) {
  const rows = await api(`/api/admin/lookups?kind=${encodeURIComponent(kind)}&active_only=false`);
  const list = $(listId);
  const status = $(statusId);
  const noun = kind === "road" ? "road" : "council";
  const active = rows.filter((r) => r.active);
  if (status) {
    const used = active.reduce((n, r) => n + (r.usage_count || 0), 0);
    status.textContent = rows.length
      ? `${active.length} ${noun}${active.length === 1 ? "" : "s"} in the list · ${used} site use${used === 1 ? "" : "s"}`
      : `No ${noun}s yet — add the correct names here.`;
  }
  if (!list) return;
  list.innerHTML = rows.length
    ? rows
        .map((r) => {
          const count = r.usage_count || 0;
          const countLabel = `${count} site${count === 1 ? "" : "s"}`;
          return `<li data-lookup-id="${r.id}" data-kind="${kind}" data-original="${escapeHtml(r.value)}" data-usage="${count}" class="${r.active ? "" : "is-inactive"}">
          <div class="lookup-row">
            <input data-lookup-value value="${escapeHtml(r.value)}" ${r.active ? "" : "disabled"} maxlength="255" aria-label="${escapeHtml(r.value)}" />
            <span class="lookup-count">${escapeHtml(countLabel)}</span>
            ${
              r.active
                ? `<button type="button" class="btn btn-sm" data-save-lookup="${r.id}">Save</button>
                   <button type="button" class="btn btn-sm btn-danger" data-del-lookup="${r.id}">Remove</button>`
                : `<button type="button" class="btn btn-sm" data-restore-lookup="${r.id}">Restore</button>`
            }
          </div>
        </li>`;
        })
        .join("")
    : `<li><p class="meta">No ${noun}s yet.</p></li>`;
}

async function addLookup(kind, inputId) {
  const input = $(inputId);
  const value = input?.value.trim();
  if (!value) return;
  await api("/api/admin/lookups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, value }),
  });
  if (input) input.value = "";
  await refreshLookups();
}

async function refreshLookups() {
  await Promise.all([
    loadLookups("road", "roadLookupList", "roadLookupStatus"),
    loadLookups("council", "councilLookupList", "councilLookupStatus"),
  ]);
}

async function saveLookupRow(li) {
  const id = li?.dataset.lookupId;
  const kind = li?.dataset.kind;
  const original = li?.dataset.original || "";
  const input = li?.querySelector("[data-lookup-value]");
  const value = input?.value.trim();
  if (!id || !kind || !value) return;
  const count = Number(li.dataset.usage || 0);
  if (value !== original && count > 0) {
    const ok = await confirmDialog(
      `Rename “${original}” to “${value}” on ${count} site${count === 1 ? "" : "s"}? The new name will show on the register, lists, and exports.`
    );
    if (!ok) {
      input.value = original;
      return;
    }
  }
  const saved = await api(`/api/admin/lookups/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, value, active: true }),
  });
  await refreshLookups();
  if (saved?.merged) {
    await alertDialog(
      `Merged into “${saved.value}”${
        saved.sites_updated
          ? ` and updated ${saved.sites_updated} site${saved.sites_updated === 1 ? "" : "s"}`
          : ""
      }.`
    );
  } else if (saved?.sites_updated) {
    const statusId = kind === "road" ? "roadLookupStatus" : "councilLookupStatus";
    if ($(statusId)) {
      $(statusId).textContent = `Saved “${saved.value}” · updated ${saved.sites_updated} site${
        saved.sites_updated === 1 ? "" : "s"
      }.`;
    }
  }
}

async function restoreLookup(id, kind, value) {
  await api(`/api/admin/lookups/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, value, active: true }),
  });
  await refreshLookups();
}

function xorBytes(u8, keyU8) {
  const out = new Uint8Array(u8.length);
  const klen = keyU8.length;
  for (let i = 0; i < u8.length; i += 1) out[i] = u8[i] ^ keyU8[i % klen];
  return out;
}

function bytesToB64(u8) {
  let s = "";
  const step = 0x8000;
  for (let i = 0; i < u8.length; i += step) {
    s += String.fromCharCode(...u8.subarray(i, i + step));
  }
  return btoa(s);
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

async function readFetchError(res) {
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const body = await res.json().catch(() => ({}));
    return formatApiDetail(body?.detail ?? body, res.statusText || `HTTP ${res.status}`);
  }
  const text = await res.text().catch(() => "");
  return humanizeHttpError(res.status, text, res.statusText || `HTTP ${res.status}`);
}

async function importTrackerChunked(file, { dryRun, updateExisting, onProgress }) {
  const session = await api("/api/import/tracker/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, size: file.size }),
    timeoutMs: 20000,
  });
  if (!session?.id) throw new Error("Could not start import session");
  if (!session.wrap_key) {
    throw new Error("This server is still on the old import protocol. Check for updates, then retry.");
  }
  const keyBytes = b64ToBytes(session.wrap_key);
  const chunkSize = Number(session.chunk_size) || 48 * 1024;
  const buf = new Uint8Array(await file.arrayBuffer());
  const total = Math.max(1, Math.ceil(buf.length / chunkSize));
  for (let i = 0; i < total; i += 1) {
    onProgress?.(`Uploading… ${i + 1}/${total}`);
    const slice = buf.subarray(i * chunkSize, (i + 1) * chunkSize);
    const wrapped = xorBytes(slice, keyBytes);
    const res = await fetch(`/api/import/tracker/session/${encodeURIComponent(session.id)}/chunk/${i}`, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ p: bytesToB64(wrapped) }),
    });
    if (res.status === 401) {
      const next = encodeURIComponent(location.pathname + location.search);
      location.href = `/login?next=${next}`;
      throw new Error("Not authenticated");
    }
    if (!res.ok) throw new Error(await readFetchError(res));
  }
  onProgress?.(dryRun ? "Parsing preview…" : "Importing…");
  const params = new URLSearchParams({
    dry_run: dryRun ? "true" : "false",
    update_existing: updateExisting ? "true" : "false",
  });
  return api(`/api/import/tracker/session/${encodeURIComponent(session.id)}/commit?${params}`, {
    method: "POST",
    timeoutMs: 120000,
  });
}

async function runImport(dryRun) {
  const file = $("importFile").files?.[0];
  if (!file) {
    alertDialog("Choose an Excel tracker file");
    return;
  }
  if (!file.size) {
    alertDialog("That file is empty");
    return;
  }
  $("importStatus").textContent = dryRun ? "Previewing…" : "Importing…";
  $("importLog").hidden = true;
  try {
    const body = await importTrackerChunked(file, {
      dryRun,
      updateExisting: !!$("importUpdate")?.checked,
      onProgress: (msg) => {
        $("importStatus").textContent = msg;
      },
    });
    $("importStatus").textContent = dryRun
      ? `Preview: ${body.parsed} rows${body.unmatched_statuses?.length ? ` · unmatched statuses: ${body.unmatched_statuses.join(", ")}` : ""}`
      : `Imported · created ${body.created}, updated ${body.updated}, archived ${body.archived}${
          body.unmatched_statuses?.length ? ` · unmatched statuses listed below` : ""
        }`;
    $("importLog").hidden = false;
    $("importLog").textContent = JSON.stringify(body, null, 2);
    if (!dryRun) await refreshLookups();
  } catch (err) {
    $("importStatus").textContent = "";
    alertDialog(errorMessage(err, "Import failed"));
  }
}

async function init() {
  injectChrome({ active: "/admin/settings", mode: "admin" });
  $("rulesForm").addEventListener("submit", (e) => saveRules(e).catch((err) => { alertDialog(err.message); }));
  $("btnAddRoad")?.addEventListener("click", () => addLookup("road", "roadLookupValue").catch((e) => { alertDialog(e.message); }));
  $("btnAddCouncil")?.addEventListener("click", () => addLookup("council", "councilLookupValue").catch((e) => { alertDialog(e.message); }));
  $("roadLookupValue")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      addLookup("road", "roadLookupValue").catch((e) => { alertDialog(e.message); });
    }
  });
  $("councilLookupValue")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      addLookup("council", "councilLookupValue").catch((e) => { alertDialog(e.message); });
    }
  });
  document.addEventListener("click", async (ev) => {
    const saveBtn = ev.target.closest("[data-save-lookup]");
    if (saveBtn) {
      await saveLookupRow(saveBtn.closest("li")).catch((e) => { alertDialog(e.message); });
      return;
    }
    const delBtn = ev.target.closest("[data-del-lookup]");
    if (delBtn) {
      await api(`/api/admin/lookups/${delBtn.dataset.delLookup}`, { method: "DELETE" });
      await refreshLookups();
      return;
    }
    const restoreBtn = ev.target.closest("[data-restore-lookup]");
    if (restoreBtn) {
      const li = restoreBtn.closest("li");
      await restoreLookup(restoreBtn.dataset.restoreLookup, li?.dataset.kind, li?.dataset.original).catch((e) => {
        alertDialog(e.message);
      });
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    const input = ev.target.closest("[data-lookup-value]");
    if (!input) return;
    ev.preventDefault();
    saveLookupRow(input.closest("li")).catch((e) => { alertDialog(e.message); });
  });
  $("btnDryRun").addEventListener("click", () => runImport(true).catch((e) => { alertDialog(e.message); }));
  $("btnImport").addEventListener("click", async () => {
    if (!(await confirmDialog("Import tracker rows into the live register?"))) return;
    runImport(false).catch((e) => { alertDialog(e.message); });
  });
  await loadRules();
  await refreshLookups();
}

init().catch((e) => { alertDialog(e.message); });
