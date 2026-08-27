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
  onLiveSitesChanged,
  syncLiveRevision,
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

function rateOptions(selectedName) {
  const names = [...new Set(state.rates.filter((r) => r.active).map((r) => r.name))].sort((a, b) =>
    a.localeCompare(b)
  );
  return (
    `<option value="">Select treatment…</option>` +
    names
      .map(
        (n) =>
          `<option value="${escapeHtml(n)}" ${n === selectedName ? "selected" : ""}>${escapeHtml(n)}</option>`
      )
      .join("")
  );
}

function renderLines() {
  const wrap = $("linesWrap");
  if (!state.lines.length) {
    wrap.innerHTML = `<p class="hint">Add mill / pave / supply / mobilisation lines. Treatments are shared; each subbie has their own rate.</p>`;
    return;
  }
  wrap.innerHTML = `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>Treatment</th><th>Unit</th><th>Qty</th><th></th></tr></thead>
    <tbody>
      ${state.lines
        .map(
          (line, idx) => `<tr>
        <td><select data-line-name="${idx}">${rateOptions(line.name)}</select></td>
        <td class="hint">${escapeHtml(line.unit || "m2")}${line.rate_type === "shift" ? " · shift" : ""}</td>
        <td><input data-line-qty="${idx}" type="number" min="0" step="0.01" value="${line.quantity ?? 0}" style="width:7rem" /></td>
        <td><button type="button" class="btn btn-danger btn-sm" data-rm-line="${idx}">Remove</button></td>
      </tr>`
        )
        .join("")}
    </tbody>
  </table></div>`;
}

function applyTreatmentToLine(idx, name) {
  const subId = Number($("subSelect").value || 0);
  const match =
    state.rates.find((r) => r.active && r.name === name && (!subId || r.subcontractor_id === subId)) ||
    state.rates.find((r) => r.active && r.name === name);
  if (!match) {
    state.lines[idx].name = name;
    return;
  }
  state.lines[idx] = {
    ...state.lines[idx],
    rate_id: match.id,
    name: match.name,
    unit: match.unit,
    rate_type: match.rate_type,
    day_rate: match.day_rate,
    night_rate: match.night_rate,
    saturday_rate: match.saturday_rate,
    sunday_rate: match.sunday_rate,
    weekend_rate: match.weekend_rate,
    public_holiday_rate: match.public_holiday_rate,
  };
}

function collectLinesFromDom() {
  state.lines = state.lines.map((line, idx) => {
    const name = document.querySelector(`[data-line-name="${idx}"]`)?.value ?? line.name;
    const qty = Number(document.querySelector(`[data-line-qty="${idx}"]`)?.value ?? line.quantity);
    const next = { ...line, name, quantity: qty };
    applyTreatmentToLine(idx, name);
    return { ...state.lines[idx], quantity: qty };
  });
}

function shiftPayload() {
  const sel = $("shiftType").value;
  const shift_type = sel === "night" ? "night" : "day";
  const rate_tier = ["weekend", "public_holiday", "night"].includes(sel) ? sel : "weekday";
  return { shift_type, rate_tier };
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
  const { shift_type, rate_tier } = shiftPayload();
  const payload = {
    subcontractor_id: subId,
    shift_type,
    rate_tier,
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

async function compareAll() {
  collectLinesFromDom();
  const { shift_type, rate_tier } = shiftPayload();
  const result = await api("/api/asphalt/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      shift_type,
      rate_tier,
      contingency_pct: Number($("contingency").value || 0),
      lines: state.lines.map((l) => ({ name: l.name, unit: l.unit, quantity: l.quantity })),
    }),
  });
  const box = $("compareBox");
  box.hidden = false;
  const pkgs = result.packages || [];
  box.innerHTML = `
    <h3 style="margin:0 0 0.5rem">Subcontractor comparison</h3>
    <p class="hint">Best complete card: <strong>${escapeHtml(result.best_subcontractor_name || "—")}</strong>
      · ${money(result.best_total)}
      · Mixed-best (cheapest sub per line) ${money(result.mixed_best?.total)}</p>
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th>Subcontractor</th><th>Complete?</th><th>Missing</th><th>Total</th></tr></thead>
      <tbody>
        ${pkgs
          .map(
            (p) => `<tr class="${p.best ? "best-rate" : ""}">
            <td>${escapeHtml(p.subcontractor_name)}${p.best ? ` <span class="best-badge">best</span>` : ""}</td>
            <td>${p.complete ? "Yes" : "No"}</td>
            <td class="hint">${escapeHtml((p.missing || []).join(", ") || "—")}</td>
            <td>${money(p.total)}</td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table></div>
    <h3 style="margin:1rem 0 0.5rem">Mixed best (line by line)</h3>
    <div class="table-scroll"><table class="data-table">
      <thead><tr><th>Treatment</th><th>Qty</th><th>Cheapest sub</th><th>Rate</th><th>Total</th></tr></thead>
      <tbody>
        ${(result.mixed_best?.lines || [])
          .map((l) => {
            const b = l.best;
            return `<tr>
              <td>${escapeHtml(l.name)}</td>
              <td>${l.quantity}</td>
              <td>${b ? escapeHtml(b.subcontractor_name) : "—"}</td>
              <td>${b ? money(b.unit_rate) : "—"}</td>
              <td>${b ? money(b.line_total) : "—"}</td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table></div>`;
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
  if (siteId && !state.sites.some((s) => String(s.id) === String(siteId))) {
    try {
      const extra = await api(`/api/sites/${siteId}`);
      if (extra?.id) state.sites = [extra, ...state.sites];
    } catch {
      /* ignore */
    }
  }
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
      rate_type: "unit",
      quantity: 0,
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
    const sel = ev.target.closest("[data-line-name]");
    if (!sel) return;
    const idx = Number(sel.getAttribute("data-line-name"));
    applyTreatmentToLine(idx, sel.value);
    renderLines();
  });
  on("subSelect", "change", () => {
    state.lines.forEach((line, idx) => {
      if (line.name) applyTreatmentToLine(idx, line.name);
    });
    renderLines();
  });
  on("siteSelect", "change", () => loadHistory().catch((e) => { alertDialog(e.message); }));
  on("btnCalculate", "click", () => calculate().catch((e) => { alertDialog(e.message); }));
  on("btnCompare", "click", () => compareAll().catch((e) => { alertDialog(e.message); }));
  on("btnSave", "click", () => saveEstimate().catch((e) => { alertDialog(e.message); }));
  on("historyList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-est]");
    if (!btn) return;
    if (!await confirmDialog("Delete this estimate?")) return;
    await api(`/api/asphalt/estimates/${btn.dataset.delEst}`, { method: "DELETE" });
    await loadHistory();
  });
  onLiveSitesChanged(() => loadHistory().catch(() => {}));
  await syncLiveRevision();
}

init().catch((e) => showPageError("linesWrap", e, "Could not load asphalt costing"));
