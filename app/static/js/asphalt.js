import {
  $,
  api,
  on,
  escapeHtml,
  injectChrome,
  alertDialog,
  confirmDialog,
  showPageError,
  userName,
} from "./common.js";

const state = {
  sites: [],
  subcontractors: [],
  rates: [],
  lines: [],
  lastResult: null,
  lastInputs: null,
};

function money(n) {
  if (n == null) return "—";
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fillSites(selected) {
  const sel = $("siteSelect");
  sel.innerHTML =
    `<option value="">Select site…</option>` +
    state.sites
      .map(
        (s) =>
          `<option value="${s.id}" ${String(selected) === String(s.id) ? "selected" : ""}>${escapeHtml(
            s.road_name
          )} · ${escapeHtml(s.site_number)}</option>`
      )
      .join("");
}

function fillSubs(selected) {
  const sel = $("subSelect");
  sel.innerHTML =
    `<option value="">Select…</option>` +
    state.subcontractors
      .filter((s) => s.active)
      .map(
        (s) =>
          `<option value="${s.id}" ${String(selected) === String(s.id) ? "selected" : ""}>${escapeHtml(
            s.name
          )}</option>`
      )
      .join("");
}

function rateOptions(selectedRateId) {
  const subId = Number($("subSelect").value || 0);
  const rates = state.rates.filter((r) => r.active && (!subId || r.subcontractor_id === subId));
  return (
    `<option value="">Custom…</option>` +
    rates
      .map(
        (r) =>
          `<option value="${r.id}" ${String(selectedRateId) === String(r.id) ? "selected" : ""}>${escapeHtml(
            r.name
          )} (${escapeHtml(r.unit)})</option>`
      )
      .join("")
  );
}

function renderLines() {
  const wrap = $("linesWrap");
  if (!state.lines.length) {
    wrap.innerHTML = `<p class="hint">No lines yet — add mill / pave / supply items from the subcontractor rate card.</p>`;
    return;
  }
  wrap.innerHTML = `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>Rate</th><th>Name</th><th>Unit</th><th>Qty</th><th></th></tr></thead>
    <tbody>
      ${state.lines
        .map(
          (line, idx) => `<tr>
        <td><select data-line-rate="${idx}">${rateOptions(line.rate_id)}</select></td>
        <td><input data-line-name="${idx}" value="${escapeHtml(line.name || "")}" /></td>
        <td><input data-line-unit="${idx}" value="${escapeHtml(line.unit || "m2")}" style="width:5rem" /></td>
        <td><input data-line-qty="${idx}" type="number" min="0" step="0.01" value="${line.quantity ?? 0}" style="width:7rem" /></td>
        <td><button type="button" class="btn btn-danger btn-sm" data-rm-line="${idx}">Remove</button></td>
      </tr>`
        )
        .join("")}
    </tbody>
  </table></div>`;
}

function applyRateToLine(idx, rateId) {
  const rate = state.rates.find((r) => r.id === Number(rateId));
  if (!rate) {
    state.lines[idx].rate_id = null;
    return;
  }
  state.lines[idx] = {
    ...state.lines[idx],
    rate_id: rate.id,
    name: rate.name,
    unit: rate.unit,
    day_rate: rate.day_rate,
    night_rate: rate.night_rate,
    saturday_rate: rate.saturday_rate,
    sunday_rate: rate.sunday_rate,
    public_holiday_rate: rate.public_holiday_rate,
  };
}

function collectLinesFromDom() {
  state.lines = state.lines.map((line, idx) => {
    const name = document.querySelector(`[data-line-name="${idx}"]`)?.value ?? line.name;
    const unit = document.querySelector(`[data-line-unit="${idx}"]`)?.value ?? line.unit;
    const qty = Number(document.querySelector(`[data-line-qty="${idx}"]`)?.value ?? line.quantity);
    const rateId = document.querySelector(`[data-line-rate="${idx}"]`)?.value || "";
    const next = { ...line, name, unit, quantity: qty, rate_id: rateId ? Number(rateId) : null };
    if (rateId) {
      const rate = state.rates.find((r) => r.id === Number(rateId));
      if (rate) {
        next.day_rate = rate.day_rate;
        next.night_rate = rate.night_rate;
        next.saturday_rate = rate.saturday_rate;
        next.sunday_rate = rate.sunday_rate;
        next.public_holiday_rate = rate.public_holiday_rate;
        next.name = name || rate.name;
        next.unit = unit || rate.unit;
      }
    }
    return next;
  });
}

async function loadHistory() {
  const siteId = $("siteSelect").value;
  const box = $("historyList");
  if (!siteId) {
    box.innerHTML = `<p class="hint">Select a site to load history.</p>`;
    return;
  }
  const rows = await api(`/api/asphalt/estimates?site_id=${siteId}`);
  box.innerHTML = rows.length
    ? `<ul class="plain-list">${rows
        .map(
          (r) => `<li>
          <strong>${escapeHtml(r.name)}</strong> — ${money(r.summary_total)}
          <span class="hint"> · ${r.created_at ? new Date(r.created_at).toLocaleString() : ""}</span>
          <button type="button" class="btn btn-sm btn-danger" data-del-est="${r.id}">Delete</button>
        </li>`
        )
        .join("")}</ul>`
    : `<p class="hint">No asphalt estimates for this site yet.</p>`;
}

async function calculate() {
  collectLinesFromDom();
  const subId = Number($("subSelect").value || 0) || null;
  const payload = {
    subcontractor_id: subId,
    shift_type: $("shiftType").value,
    contingency_pct: Number($("contingency").value || 0),
    lines: state.lines,
  };
  const result = await api("/api/asphalt/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.lastResult = result;
  state.lastInputs = payload;
  const box = $("resultBox");
  box.hidden = false;
  box.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Item</th><th>Qty</th><th>Unit rate</th><th>Total</th></tr></thead>
      <tbody>
        ${(result.lines || [])
          .map(
            (l) => `<tr>
            <td>${escapeHtml(l.name)} <span class="hint">${escapeHtml(l.unit)}</span></td>
            <td>${l.quantity}</td>
            <td>${money(l.unit_rate)}</td>
            <td>${money(l.line_total)}</td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>
    <p style="margin:0.75rem 0 0"><strong>Subtotal</strong> ${money(result.subtotal)}
      · Contingency ${money(result.contingency)}
      · <strong>Total ${money(result.total)}</strong></p>`;
  $("btnSave").disabled = false;
  if (!$("estimateName").value.trim()) {
    const site = state.sites.find((s) => String(s.id) === $("siteSelect").value);
    $("estimateName").value = site ? `${site.road_name} asphalt` : "Asphalt estimate";
  }
}

async function saveEstimate() {
  if (!state.lastResult || !state.lastInputs) return;
  const siteId = Number($("siteSelect").value);
  if (!siteId) {
      alertDialog("Select a site");
      return;
    }
  const name = $("estimateName").value.trim() || "Asphalt estimate";
  await api("/api/asphalt/estimates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      site_id: siteId,
      subcontractor_id: state.lastInputs.subcontractor_id,
      name,
      inputs: state.lastInputs,
      results: state.lastResult,
      summary_total: state.lastResult.total,
      created_by: userName(),
    }),
  });
  await loadHistory();
  alertDialog("Asphalt estimate saved.");
}

async function init() {
  await injectChrome({ active: "/asphalt", mode: "ops" });
  const params = new URLSearchParams(location.search);
  const siteId = params.get("site_id");
  const [sites, subs, rates] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/asphalt/subcontractors?active_only=true"),
    api("/api/asphalt/rates?active_only=true"),
  ]);
  state.sites = sites;
  state.subcontractors = subs;
  state.rates = rates;
  fillSites(siteId);
  fillSubs();
  state.lines = [];
  renderLines();
  if (siteId) await loadHistory();

  on("btnAddLine", "click", () => {
    state.lines.push({
      rate_id: null,
      name: "",
      unit: "m2",
      quantity: 0,
      day_rate: 0,
      night_rate: 0,
      saturday_rate: 0,
      sunday_rate: 0,
      public_holiday_rate: 0,
    });
    renderLines();
  });
  on("linesWrap", "click", (ev) => {
    const btn = ev.target.closest("[data-rm-line]");
    if (!btn) return;
    state.lines.splice(Number(btn.dataset.rmLine), 1);
    renderLines();
  });
  on("linesWrap", "change", (ev) => {
    const sel = ev.target.closest("[data-line-rate]");
    if (!sel) return;
    const idx = Number(sel.getAttribute("data-line-rate"));
    applyRateToLine(idx, sel.value);
    renderLines();
  });
  on("subSelect", "change", () => renderLines());
  on("siteSelect", "change", () => loadHistory().catch((e) => { alertDialog(e.message); }));
  on("btnCalculate", "click", () => calculate().catch((e) => { alertDialog(e.message); }));
  on("btnSave", "click", () => saveEstimate().catch((e) => { alertDialog(e.message); }));
  on("historyList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-est]");
    if (!btn) return;
    if (!await confirmDialog("Delete this estimate?")) return;
    await api(`/api/asphalt/estimates/${btn.dataset.delEst}`, { method: "DELETE" });
    await loadHistory();
  });
}

init().catch((e) => showPageError("linesWrap", e, "Could not load asphalt costing"));
