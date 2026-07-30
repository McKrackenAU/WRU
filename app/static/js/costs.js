import { $, api, escapeHtml, injectChrome, userName } from "./common.js";

let settings = null;
let sites = [];
let lastStandard = null;
let lastClosure = null;

const money = (n) =>
  `$${Number(n || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function selectedSiteId() {
  const v = $("costSite")?.value;
  return v ? Number(v) : null;
}

function selectedSite() {
  const id = selectedSiteId();
  return id ? sites.find((s) => s.id === id) : null;
}

function updateSiteHint() {
  const site = selectedSite();
  const hint = $("costSiteHint");
  if (!hint) return;
  if (!site) {
    hint.textContent =
      "Select a MoA/site before saving. Estimates and attachments are stored against that site for planning.";
    return;
  }
  const parts = [
    site.road_name,
    site.site_number,
    site.moa_number ? `MoA ${site.moa_number}` : "No MoA # yet",
    site.tgs_reference ? `TGS ${site.tgs_reference}` : null,
  ].filter(Boolean);
  hint.textContent = `Saving to: ${parts.join(" · ")}`;
}

function fillSiteSelect(preselectId = null) {
  const sel = $("costSite");
  const cur = preselectId != null ? String(preselectId) : sel.value;
  sel.innerHTML =
    `<option value="">Select a site…</option>` +
    sites
      .map((s) => {
        const label = [
          s.road_name,
          s.site_number,
          s.moa_number ? `MoA ${s.moa_number}` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        return `<option value="${s.id}">${escapeHtml(label)}</option>`;
      })
      .join("");
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
  updateSiteHint();
}

function defaultClosureTimes() {
  const now = new Date();
  const day = now.getDay();
  const daysToFri = (5 - day + 7) % 7 || 7;
  const fri = new Date(now);
  fri.setDate(now.getDate() + daysToFri);
  fri.setHours(18, 0, 0, 0);
  const mon = new Date(fri);
  mon.setDate(fri.getDate() + 3);
  mon.setHours(6, 0, 0, 0);
  const toLocal = (d) => {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  return { start: toLocal(fri), end: toLocal(mon) };
}

function resourcesFrom(prefix) {
  return {
    people: Number($(prefix + "People").value || 0),
    vehicles: Number($(prefix + "Vehicles").value || 0),
    tmas: Number($(prefix + "Tmas").value || 0),
    spotters: Number($(prefix + "Spotters").value || 0),
  };
}

function labourTable(lines) {
  if (!lines?.length) return "<p class='hint'>No resources allocated.</p>";
  return `<div class="table-card" style="box-shadow:none"><div class="table-scroll" style="max-height:280px">
    <table class="data-table">
      <thead><tr><th>Pack / unit</th><th>Qty</th><th>People</th><th>Veh</th><th>Ord h</th><th>OT h</th><th>Ord $</th><th>OT $</th><th>Line</th></tr></thead>
      <tbody>
        ${lines
          .map((l) => {
            const ppl =
              l.people_covered != null
                ? l.people_covered
                : l.rate_kind === "tma"
                  ? "—"
                  : (l.pack_people || 1) * l.quantity;
            const veh =
              l.vehicles_covered != null
                ? l.vehicles_covered
                : l.includes_vehicle
                  ? l.quantity
                  : 0;
            return `<tr>
            <td>${escapeHtml(l.name)}${l.note ? `<div class="meta">${escapeHtml(l.note)}</div>` : ""}</td>
            <td class="mono">${l.quantity}</td>
            <td class="mono">${ppl}</td>
            <td class="mono">${veh}</td>
            <td class="mono">${l.ordinary_hours}</td>
            <td class="mono">${l.overtime_hours}</td>
            <td class="money">${money(l.ordinary_rate)}</td>
            <td class="money">${money(l.overtime_rate)}</td>
            <td class="money">${money(l.line_total)}</td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table></div></div>`;
}

function bookingBlock(result) {
  const items = result.booking_requirements || result.per_shift?.booking_requirements || [];
  const summary = result.booking_summary || result.per_shift?.booking_summary || "";
  if (!items.length && !summary) return "";
  const list = items.length
    ? `<ul class="booking-list">${items
        .map((b) => `<li><strong>${escapeHtml(b.text || `${b.quantity}× ${b.label}`)}</strong></li>`)
        .join("")}</ul>`
    : "";
  return `<div class="booking-box">
    <strong>Booking requirements</strong>
    ${list}
    ${summary ? `<p class="hint" style="margin:0.35rem 0 0">${escapeHtml(summary)}</p>` : ""}
  </div>`;
}

function allocationBlock(alloc) {
  if (!alloc) return "";
  const r = alloc.requested || {};
  const c = alloc.covered || {};
  return `<div class="hint" style="margin:0.5rem 0">
    Requested ${r.people || 0} TCs · ${r.vehicles || 0} vehicles · ${r.tmas || 0} TMAs · ${r.spotters || 0} spotters →
    covered ${c.people || 0} TC seats · ${c.vehicles || 0} vehicles · ${c.tmas || 0} TMAs · ${c.spotters || 0} spotters
    (${alloc.pack_units || 0} TC pack units). ${escapeHtml(alloc.note || "")}
  </div>`;
}

function allowancesBlock(allow) {
  if (!allow) return "";
  return `<div style="margin:0.65rem 0">
    <strong>Allowances (per shift)</strong>
    <div class="hint">${escapeHtml(allow.note || "")}</div>
    <div class="stat-grid" style="margin-top:0.45rem">
      <div class="stat-card"><div class="label">Heads</div><div class="value" style="font-size:1.1rem">${allow.heads}</div></div>
      <div class="stat-card"><div class="label">Travel</div><div class="value money-total" style="font-size:1.1rem">${money(allow.travel_total)}</div></div>
      <div class="stat-card"><div class="label">Meals</div><div class="value money-total" style="font-size:1.1rem">${money(allow.meal_total)}</div></div>
      <div class="stat-card"><div class="label">Allowances total</div><div class="value money-total" style="font-size:1.1rem">${money(allow.allowances_total)}</div></div>
    </div>
  </div>`;
}

function vmsBlock(vms) {
  return `
    <div>
      <strong>VMS</strong>
      <div class="hint">${escapeHtml(vms.note || "")}</div>
      <div>${vms.quantity} board(s) · ${vms.billable_days} calendar days
        (${escapeHtml(vms.deploy_start)} → ${escapeHtml(vms.deploy_end)})</div>
      <div class="money">Delivery ${money(vms.delivery_total)} · Collection ${money(vms.collection_total)} · Hire ${money(vms.hire_total)}</div>
      <div class="money"><strong>VMS total ${money(vms.vms_total)}</strong></div>
    </div>`;
}

function renderStandard(result) {
  lastStandard = result;
  const p = result.per_shift;
  $("sResults").innerHTML = `
    <h2>Results</h2>
    ${bookingBlock(result)}
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Per shift labour</div><div class="value money-total">${money(p.shift_labour_total)}</div></div>
      <div class="stat-card"><div class="label">Per shift total (incl. allowances)</div><div class="value money-total">${money(p.shift_total)}</div></div>
      <div class="stat-card"><div class="label">Site crew (${result.inputs_echo.total_shifts} shifts)</div><div class="value money-total">${money(result.site_crew_total ?? result.site_labour_total)}</div></div>
      <div class="stat-card"><div class="label">VMS total</div><div class="value money-total">${money(result.vms.vms_total)}</div></div>
      <div class="stat-card"><div class="label">Site traffic total</div><div class="value money-total">${money(result.site_traffic_total)}</div></div>
    </div>
    ${allocationBlock(p.allocation)}
    ${allowancesBlock(p.allowances)}
    <div>
      <strong>Best rate mix (per shift)</strong>
      (${escapeHtml(result.inputs_echo.shift_type)}, ${result.inputs_echo.shift_hours}h, OT after ${result.inputs_echo.overtime_after_hours}h)
      ${labourTable(p.lines)}
    </div>
    ${vmsBlock(result.vms)}
  `;
}

function optionCard(opt, winner) {
  const mealNote = opt.meals_apply_per_shift
    ? `Meals included (${money(opt.meal_total)} across shifts)`
    : "No meals (shift ≤ meal threshold)";
  return `
    <div class="panel-card compare-card ${winner ? "winner" : ""}" style="margin:0;box-shadow:none">
      <h2>${escapeHtml(opt.shift_hours)}-hour shifts${
        winner ? '<span class="best-badge">BEST</span>' : ""
      }</h2>
      <div class="hint">${opt.shifts_required} shifts · ${opt.day_shifts} day / ${opt.night_shifts} night · ${opt.duration_hours}h coverage</div>
      <div class="hint">${escapeHtml(mealNote)} · Travel ${money(opt.travel_total)}</div>
      <div class="stat-grid" style="margin-top:0.75rem">
        <div class="stat-card"><div class="label">Pack labour</div><div class="value money-total" style="font-size:1.1rem">${money(opt.pack_labour_total)}</div></div>
        <div class="stat-card"><div class="label">Travel</div><div class="value money-total" style="font-size:1.1rem">${money(opt.travel_total)}</div></div>
        <div class="stat-card"><div class="label">Meals</div><div class="value money-total" style="font-size:1.1rem">${money(opt.meal_total)}</div></div>
        <div class="stat-card"><div class="label">Crew total</div><div class="value money-total" style="font-size:1.1rem">${money(opt.crew_total ?? opt.labour_total)}</div></div>
        <div class="stat-card"><div class="label">VMS</div><div class="value money-total" style="font-size:1.1rem">${money(opt.vms_total)}</div></div>
        <div class="stat-card"><div class="label">Grand total</div><div class="value money-total" style="font-size:1.25rem">${money(opt.grand_total)}</div></div>
      </div>
    </div>`;
}

function renderClosure(result) {
  lastClosure = result;
  const rec = result.recommendation;
  $("cResults").innerHTML = `
    <h2>8h vs 12h comparison</h2>
    <div class="best-banner">BEST: ${escapeHtml(rec.best_label || rec.cheaper)}
      ${rec.cheaper !== "equal" && rec.saving ? ` · saves ${money(rec.saving)}` : ""}</div>
    <p class="hint">${escapeHtml(rec.summary)}</p>
    ${bookingBlock(result)}
    ${allocationBlock(result.option_3x8.allocation)}
    <div class="compare-grid">
      ${optionCard(result.option_3x8, !!result.option_3x8.is_best)}
      ${optionCard(result.option_2x12, !!result.option_2x12.is_best)}
    </div>
    ${vmsBlock(result.vms)}
    <details open>
      <summary>8-hour shift sample (pack mix &amp; allowances)</summary>
      ${allowancesBlock(result.option_3x8.sample_allowances || result.option_3x8.per_shift?.[0]?.allowances)}
      ${labourTable(result.option_3x8.per_shift?.[0]?.lines || [])}
    </details>
    <details open>
      <summary>12-hour shift sample (pack mix &amp; allowances — meals usually apply)</summary>
      ${allowancesBlock(result.option_2x12.sample_allowances || result.option_2x12.per_shift?.[0]?.allowances)}
      ${labourTable(result.option_2x12.per_shift?.[0]?.lines || [])}
    </details>
  `;
}

async function exportResult(result, format) {
  if (!result) return alert("Calculate first");
  const siteId = selectedSiteId();
  const res = await fetch(`/api/costs/export/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      result,
      site_id: siteId,
      title:
        result.mode === "closure_24h"
          ? "24-hour closure cost comparison"
          : "Standard shift cost estimate",
      notes: $("costNotes")?.value.trim() || null,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Export failed");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const match = cd.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || `wru-cost.${format === "pdf" ? "pdf" : "xlsx"}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function modeLabel(mode) {
  return mode === "closure_24h" ? "24h closure" : "Standard";
}

function estimateTotalLabel(r) {
  if (r.summary_total != null) return money(r.summary_total);
  return "—";
}

function attachmentsHtml(r) {
  const atts = r.attachments || [];
  const list = atts.length
    ? `<ul class="attach-mini">${atts
        .map(
          (a) => `<li>
          <a href="/api/costs/attachments/${a.id}/download">${escapeHtml(a.original_filename)}</a>
          <span class="meta">${(a.size_bytes / 1024).toFixed(1)} KB</span>
          <button type="button" class="btn btn-danger" data-del-att="${a.id}">Remove</button>
        </li>`
        )
        .join("")}</ul>`
    : `<p class="meta">No attachments yet.</p>`;
  return `
    <div class="estimate-attach" data-est-id="${r.id}">
      <strong>Attachments</strong>
      ${list}
      <div class="upload-row" style="margin-top:0.5rem;flex-wrap:wrap">
        <input type="file" data-att-file="${r.id}" />
        <input type="text" data-att-desc="${r.id}" placeholder="Description (optional)" />
        <button type="button" class="btn" data-att-upload="${r.id}">Attach file</button>
      </div>
    </div>`;
}

async function loadEstimates() {
  const siteId = selectedSiteId();
  const filter = $("historyFilter")?.value || "assigned";
  const params = new URLSearchParams();
  if (filter === "assigned" && siteId) {
    params.set("site_id", String(siteId));
  } else if (filter === "assigned" && !siteId) {
    $("estimateList").innerHTML =
      `<li><p class="meta">Select a site above to see its cost history, or switch filter to All sites.</p></li>`;
    $("historyHint").textContent = "Select a MoA/site to view its saved traffic cost history.";
    return;
  }
  const rows = await api(`/api/costs/estimates?${params}`);
  const site = selectedSite();
  if (filter === "assigned" && site) {
    $("historyHint").textContent = `History for ${site.road_name} (${site.site_number})${
      site.moa_number ? ` · MoA ${site.moa_number}` : ""
    } — ${rows.length} estimate${rows.length === 1 ? "" : "s"}.`;
  } else {
    $("historyHint").textContent = `${rows.length} saved estimate${rows.length === 1 ? "" : "s"} across sites.`;
  }

  $("estimateList").innerHTML = rows.length
    ? rows
        .map((r) => {
          const siteLabel = r.road_name
            ? `${r.road_name} · ${r.site_number || ""}${r.moa_number ? ` · MoA ${r.moa_number}` : ""}`
            : "Unassigned";
          return `<li>
          <div class="top">
            <span>${escapeHtml(modeLabel(r.mode))} · ${new Date(r.created_at).toLocaleString()}
              ${r.created_by ? ` · ${escapeHtml(r.created_by)}` : ""}</span>
            <span class="row-actions">
              <a class="btn" href="/api/costs/estimates/${r.id}/export.xlsx">Excel</a>
              <a class="btn" href="/api/costs/estimates/${r.id}/export.pdf">PDF</a>
              <button type="button" class="btn btn-danger" data-del-est="${r.id}">Delete</button>
            </span>
          </div>
          <p><strong>${escapeHtml(r.name)}</strong> — <span class="money">${estimateTotalLabel(r)}</span></p>
          <p class="meta">${escapeHtml(siteLabel)}</p>
          ${r.notes ? `<p>${escapeHtml(r.notes)}</p>` : ""}
          ${attachmentsHtml(r)}
        </li>`;
        })
        .join("")
    : `<li><p class="meta">No saved estimates yet for this view.</p></li>`;
}

async function calcStandard() {
  const payload = {
    total_shifts: Number($("sShifts").value),
    shift_hours: Number($("sHours").value),
    shift_type: $("sType").value,
    overtime_after_hours: Number($("sOt").value),
    works_start: $("sStart").value,
    works_end: $("sEnd").value || $("sStart").value,
    vms_quantity: Number($("sVmsQty").value),
    vms_lead_days: Number($("sVmsLead").value),
    resources: resourcesFrom("s"),
  };
  const result = await api("/api/costs/calculate/standard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  renderStandard(result);
}

async function calcClosure() {
  const payload = {
    closure_start: $("cStart").value,
    closure_end: $("cEnd").value,
    overtime_after_hours: Number($("cOt").value),
    vms_quantity: Number($("cVmsQty").value),
    vms_lead_days: Number($("cVmsLead").value),
    resources: resourcesFrom("c"),
  };
  const result = await api("/api/costs/calculate/closure-24h", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  renderClosure(result);
}

async function saveEstimate(mode) {
  const result = mode === "standard" ? lastStandard : lastClosure;
  if (!result) return alert("Calculate first");
  const siteId = selectedSiteId();
  if (!siteId) return alert("Select a MoA / site before saving this estimate.");
  const site = selectedSite();
  const defaultName =
    mode === "standard"
      ? `${site?.site_number || "Site"} standard ${$("sStart").value}`
      : `${site?.site_number || "Site"} 24h ${$("cStart").value.slice(0, 10)}`;
  const name = prompt("Estimate name", defaultName);
  if (!name) return;
  const inputs =
    mode === "standard"
      ? {
          total_shifts: Number($("sShifts").value),
          shift_hours: Number($("sHours").value),
          shift_type: $("sType").value,
          works_start: $("sStart").value,
          works_end: $("sEnd").value,
          vms_quantity: Number($("sVmsQty").value),
          resources: resourcesFrom("s"),
        }
      : {
          closure_start: $("cStart").value,
          closure_end: $("cEnd").value,
          vms_quantity: Number($("cVmsQty").value),
          resources: resourcesFrom("c"),
        };
  await api("/api/costs/estimates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      site_id: siteId,
      mode,
      notes: $("costNotes").value.trim() || null,
      inputs,
      results: result,
      created_by: userName(),
    }),
  });
  $("historyFilter").value = "assigned";
  await loadEstimates();
}

async function uploadAttachment(estimateId) {
  const fileInput = document.querySelector(`[data-att-file="${estimateId}"]`);
  if (!fileInput?.files?.length) return alert("Choose a file first");
  const desc = document.querySelector(`[data-att-desc="${estimateId}"]`);
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  if (desc?.value.trim()) fd.append("description", desc.value.trim());
  if (userName()) fd.append("uploaded_by", userName());
  const res = await fetch(`/api/costs/estimates/${estimateId}/attachments`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Upload failed");
  }
  await loadEstimates();
}

async function init() {
  injectChrome({ active: "/costs" });
  const params = new URLSearchParams(location.search);
  const preselect = params.get("site_id") ? Number(params.get("site_id")) : null;

  settings = await api("/api/costs/settings");
  // Touch rates endpoint so pack/TMA defaults are seeded
  await api("/api/costs/rates?active_only=true");
  sites = await api("/api/sites?archived=false");

  fillSiteSelect(preselect);

  $("sOt").value = settings.overtime_after_hours;
  $("cOt").value = settings.overtime_after_hours;
  $("sVmsLead").value = settings.vms_lead_days_default;
  $("cVmsLead").value = settings.vms_lead_days_default;
  $("sStart").value = todayISO();
  $("sEnd").value = todayISO();
  const clo = defaultClosureTimes();
  $("cStart").value = clo.start;
  $("cEnd").value = clo.end;

  await loadEstimates();

  document.querySelectorAll(".tabs [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tabs [data-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      $("panel-standard").hidden = tab !== "standard";
      $("panel-closure").hidden = tab !== "closure";
    });
  });

  $("costSite").addEventListener("change", () => {
    updateSiteHint();
    if ($("historyFilter").value === "assigned") loadEstimates().catch((e) => alert(e.message));
  });
  $("historyFilter").addEventListener("change", () =>
    loadEstimates().catch((e) => alert(e.message))
  );

  $("btnCalcStandard").addEventListener("click", () =>
    calcStandard().catch((e) => alert(e.message))
  );
  $("btnCalcClosure").addEventListener("click", () =>
    calcClosure().catch((e) => alert(e.message))
  );
  $("btnSaveStandard").addEventListener("click", () =>
    saveEstimate("standard").catch((e) => alert(e.message))
  );
  $("btnSaveClosure").addEventListener("click", () =>
    saveEstimate("closure_24h").catch((e) => alert(e.message))
  );
  $("btnExportStdExcel").addEventListener("click", () =>
    exportResult(lastStandard, "excel").catch((e) => alert(e.message))
  );
  $("btnExportStdPdf").addEventListener("click", () =>
    exportResult(lastStandard, "pdf").catch((e) => alert(e.message))
  );
  $("btnExportCloExcel").addEventListener("click", () =>
    exportResult(lastClosure, "excel").catch((e) => alert(e.message))
  );
  $("btnExportCloPdf").addEventListener("click", () =>
    exportResult(lastClosure, "pdf").catch((e) => alert(e.message))
  );

  $("estimateList").addEventListener("click", async (ev) => {
    const delEst = ev.target.closest("[data-del-est]");
    if (delEst) {
      if (!confirm("Delete saved estimate and its attachments?")) return;
      await api(`/api/costs/estimates/${delEst.dataset.delEst}`, { method: "DELETE" });
      await loadEstimates();
      return;
    }
    const delAtt = ev.target.closest("[data-del-att]");
    if (delAtt) {
      if (!confirm("Remove this attachment?")) return;
      await api(`/api/costs/attachments/${delAtt.dataset.delAtt}`, { method: "DELETE" });
      await loadEstimates();
      return;
    }
    const up = ev.target.closest("[data-att-upload]");
    if (up) {
      await uploadAttachment(Number(up.dataset.attUpload)).catch((e) => alert(e.message));
    }
  });
}

init().catch((e) => alert(e.message));
