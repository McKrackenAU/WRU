import { $, api, escapeHtml, injectChrome, userName } from "./common.js";

let settings = null;
let rates = [];
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

function defaultClosureTimes() {
  // Next Friday 18:00 → Monday 06:00
  const now = new Date();
  const day = now.getDay(); // 0 Sun
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

async function loadEstimates() {
  const rows = await api("/api/costs/estimates");
  $("estimateList").innerHTML = rows.length
    ? rows
        .map(
          (r) => `<li>
          <div class="top">
            <span>${escapeHtml(r.mode)} · ${new Date(r.created_at).toLocaleString()}</span>
            <button type="button" class="btn btn-danger" data-del-est="${r.id}">Delete</button>
          </div>
          <p><strong>${escapeHtml(r.name)}</strong>
            ${
              r.mode === "standard"
                ? ` — total ${money(r.results?.site_traffic_total)}`
                : ` — 3×8 ${money(r.results?.option_3x8?.grand_total)} / 2×12 ${money(r.results?.option_2x12?.grand_total)}`
            }
          </p>
        </li>`
        )
        .join("")
    : `<li><p class="meta">No saved estimates yet.</p></li>`;
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
  const name = prompt(
    "Estimate name",
    mode === "standard" ? `Standard ${$("sStart").value}` : `24h ${$("cStart").value}`
  );
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
      mode,
      inputs,
      results: result,
      created_by: userName(),
    }),
  });
  await loadEstimates();
}

async function init() {
  injectChrome({ active: "/costs" });
  settings = await api("/api/costs/settings");
  rates = await api("/api/costs/rates?active_only=true");

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
    const btn = ev.target.closest("[data-del-est]");
    if (!btn) return;
    if (!confirm("Delete saved estimate?")) return;
    await api(`/api/costs/estimates/${btn.dataset.delEst}`, { method: "DELETE" });
    await loadEstimates();
  });
}

init().catch((e) => alert(e.message));
