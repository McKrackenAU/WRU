import { $, api, escapeHtml, injectChrome, userName } from "./common.js";

let settings = null;
let rates = [];
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

function renderCrew(containerId) {
  const el = $(containerId);
  el.innerHTML = rates
    .filter((r) => r.active)
    .map(
      (r) => `
      <label>${escapeHtml(r.name)}</label>
      <input type="number" min="0" step="1" value="${r.name.includes("Controller") ? 2 : r.name.includes("Leader") ? 1 : 0}" data-rate-id="${r.id}" />`
    )
    .join("");
}

function crewFrom(containerId) {
  return [...$(containerId).querySelectorAll("[data-rate-id]")].map((input) => ({
    rate_id: Number(input.dataset.rateId),
    quantity: Number(input.value || 0),
  }));
}

function labourTable(lines) {
  if (!lines?.length) return "<p class='hint'>No crew quantities entered.</p>";
  return `<div class="table-card" style="box-shadow:none"><div class="table-scroll" style="max-height:240px">
    <table class="data-table">
      <thead><tr><th>Category</th><th>Qty</th><th>Ord h</th><th>OT h</th><th>Ord $</th><th>OT $</th><th>Line</th></tr></thead>
      <tbody>
        ${lines
          .map(
            (l) => `<tr>
            <td>${escapeHtml(l.name)}</td>
            <td class="mono">${l.quantity}</td>
            <td class="mono">${l.ordinary_hours}</td>
            <td class="mono">${l.overtime_hours}</td>
            <td class="money">${money(l.ordinary_rate)}</td>
            <td class="money">${money(l.overtime_rate)}</td>
            <td class="money">${money(l.line_total)}</td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table></div></div>`;
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
    <div class="stat-grid">
      <div class="stat-card"><div class="label">Per shift labour</div><div class="value money-total">${money(p.shift_labour_total)}</div></div>
      <div class="stat-card"><div class="label">Site labour (${result.inputs_echo.total_shifts} shifts)</div><div class="value money-total">${money(result.site_labour_total)}</div></div>
      <div class="stat-card"><div class="label">VMS total</div><div class="value money-total">${money(result.vms.vms_total)}</div></div>
      <div class="stat-card"><div class="label">Site traffic total</div><div class="value money-total">${money(result.site_traffic_total)}</div></div>
    </div>
    <div>
      <strong>Per-shift labour breakdown</strong>
      (${escapeHtml(result.inputs_echo.shift_type)}, ${result.inputs_echo.shift_hours}h, OT after ${result.inputs_echo.overtime_after_hours}h)
      ${labourTable(p.lines)}
    </div>
    ${vmsBlock(result.vms)}
  `;
}

function optionCard(opt, winner) {
  return `
    <div class="panel-card compare-card ${winner ? "winner" : ""}" style="margin:0;box-shadow:none">
      <h2>${escapeHtml(opt.label)}</h2>
      <div class="hint">${opt.shifts_required} shifts · ${opt.day_shifts} day / ${opt.night_shifts} night · ${opt.duration_hours}h coverage</div>
      <div class="stat-grid" style="margin-top:0.75rem">
        <div class="stat-card"><div class="label">Labour</div><div class="value money-total" style="font-size:1.2rem">${money(opt.labour_total)}</div></div>
        <div class="stat-card"><div class="label">VMS</div><div class="value money-total" style="font-size:1.2rem">${money(opt.vms_total)}</div></div>
        <div class="stat-card"><div class="label">Grand total</div><div class="value money-total" style="font-size:1.2rem">${money(opt.grand_total)}</div></div>
      </div>
    </div>`;
}

function renderClosure(result) {
  lastClosure = result;
  const rec = result.recommendation;
  const win3 = rec.cheaper === "3x8";
  const win2 = rec.cheaper === "2x12";
  $("cResults").innerHTML = `
    <h2>Comparison</h2>
    <p><strong>${escapeHtml(rec.summary)}</strong></p>
    <div class="compare-grid">
      ${optionCard(result.option_3x8, win3)}
      ${optionCard(result.option_2x12, win2)}
    </div>
    ${vmsBlock(result.vms)}
    <details>
      <summary>3×8 shift list</summary>
      <div class="table-card" style="box-shadow:none;margin-top:0.5rem">
        <div class="table-scroll" style="max-height:220px">
          <table class="data-table">
            <thead><tr><th>#</th><th>Type</th><th>Hours</th><th>Labour</th></tr></thead>
            <tbody>
              ${result.option_3x8.per_shift
                .map(
                  (s) => `<tr><td>${s.index}</td><td>${s.shift_type}</td><td>${s.hours}</td><td class="money">${money(s.labour_total)}</td></tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </details>
    <details>
      <summary>2×12 shift list</summary>
      <div class="table-card" style="box-shadow:none;margin-top:0.5rem">
        <div class="table-scroll" style="max-height:220px">
          <table class="data-table">
            <thead><tr><th>#</th><th>Type</th><th>Hours</th><th>Labour</th></tr></thead>
            <tbody>
              ${result.option_2x12.per_shift
                .map(
                  (s) => `<tr><td>${s.index}</td><td>${s.shift_type}</td><td>${s.hours}</td><td class="money">${money(s.labour_total)}</td></tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  `;
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
            <button type="button" class="btn btn-danger" data-del-est="${r.id}">Delete</button>
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
    crew: crewFrom("sCrew"),
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
    crew: crewFrom("cCrew"),
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
          crew: crewFrom("sCrew"),
        }
      : {
          closure_start: $("cStart").value,
          closure_end: $("cEnd").value,
          vms_quantity: Number($("cVmsQty").value),
          crew: crewFrom("cCrew"),
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
  rates = await api("/api/costs/rates?active_only=true");
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

  renderCrew("sCrew");
  renderCrew("cCrew");
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
