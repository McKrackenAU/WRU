import {
  $,
  api,
  on,
  escapeHtml,
  fmtDate,
  injectChrome,
  alertDialog,
  confirmDialog,
  showPageError,
  userName,
} from "./common.js";

const state = {
  sites: [],
  traffic: [],
  asphalt: [],
  rates: [],
  asphaltLines: [],
  rows: [],
  previewAmount: null,
};

function money(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function kindLabel(kind) {
  return kind === "asphalt" ? "Pavements" : "Traffic";
}

function sourceLabel(source) {
  if (source === "calculated") return "From rates";
  if (source === "from_estimate") return "From estimate";
  return "Manual";
}

function filterParams() {
  const params = new URLSearchParams();
  const kind = $("filterKind")?.value || "";
  const site = $("filterSite")?.value || "";
  const traffic = $("filterTraffic")?.value || "";
  const asphalt = $("filterAsphalt")?.value || "";
  const from = $("filterFrom")?.value || "";
  const to = $("filterTo")?.value || "";
  if (kind) params.set("kind", kind);
  if (site) params.set("site_id", site);
  if (traffic) params.set("traffic_contractor_id", traffic);
  if (asphalt) params.set("asphalt_subcontractor_id", asphalt);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  return params;
}

function isCalculated() {
  return ($("spendSource")?.value || "calculated") === "calculated";
}

function syncModeFields() {
  const kind = $("spendKind")?.value || "traffic";
  const calc = isCalculated();
  const trafficWrap = $("spendTrafficWrap");
  const asphaltWrap = $("spendAsphaltWrap");
  const amountWrap = $("spendAmountWrap");
  const calcTraffic = $("calcTrafficFields");
  const calcAsphalt = $("calcAsphaltFields");
  const previewWrap = $("previewWrap");
  if (trafficWrap) trafficWrap.hidden = kind !== "traffic";
  if (asphaltWrap) asphaltWrap.hidden = kind !== "asphalt";
  if (amountWrap) amountWrap.hidden = calc;
  if (calcTraffic) calcTraffic.hidden = !(calc && kind === "traffic");
  if (calcAsphalt) calcAsphalt.hidden = !(calc && kind === "asphalt");
  if (previewWrap) previewWrap.hidden = !calc;
  const amount = $("spendAmount");
  if (amount) amount.required = !calc;
  if (calc && kind === "asphalt") renderAsphaltLines();
  state.previewAmount = null;
  if ($("spendPreview")) {
    $("spendPreview").textContent = calc
      ? "Calculated amount will appear here."
      : "";
  }
}

function rateOptions(selectedRateId) {
  const subId = Number($("spendAsphalt")?.value || 0);
  const rates = state.rates.filter((r) => r.active && (!subId || r.subcontractor_id === subId));
  return (
    `<option value="">Select rate…</option>` +
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

function renderAsphaltLines() {
  const wrap = $("asphaltLinesWrap");
  if (!wrap) return;
  if (!state.asphaltLines.length) {
    wrap.innerHTML = `<p class="hint">Add mill / pave / supply lines from the subcontractor rate card.</p>`;
    return;
  }
  wrap.innerHTML = `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>Rate</th><th>Qty</th><th></th></tr></thead>
    <tbody>
      ${state.asphaltLines
        .map(
          (line, idx) => `<tr>
        <td><select data-aline-rate="${idx}">${rateOptions(line.rate_id)}</select></td>
        <td><input data-aline-qty="${idx}" type="number" min="0" step="0.01" value="${line.quantity ?? 0}" style="width:7rem" /></td>
        <td><button type="button" class="btn btn-danger btn-sm" data-rm-aline="${idx}">Remove</button></td>
      </tr>`
        )
        .join("")}
    </tbody>
  </table></div>`;
}

function collectAsphaltLinesFromDom() {
  state.asphaltLines = state.asphaltLines.map((line, idx) => {
    const rateId = document.querySelector(`[data-aline-rate="${idx}"]`)?.value || "";
    const qty = Number(document.querySelector(`[data-aline-qty="${idx}"]`)?.value ?? line.quantity);
    return {
      ...line,
      rate_id: rateId ? Number(rateId) : null,
      quantity: qty,
    };
  });
}

function fillSelects() {
  const siteOpts =
    `<option value="">Select site…</option>` +
    state.sites
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.road_name)} · ${escapeHtml(s.site_number)}</option>`
      )
      .join("");
  $("spendSite").innerHTML = siteOpts;
  $("filterSite").innerHTML =
    `<option value="">All sites</option>` +
    state.sites
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.road_name)} · ${escapeHtml(s.site_number)}</option>`
      )
      .join("");

  const trafficOpts = state.traffic
    .filter((t) => t.active)
    .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`)
    .join("");
  $("spendTraffic").innerHTML = `<option value="">None</option>${trafficOpts}`;
  $("filterTraffic").innerHTML = `<option value="">Any</option>${trafficOpts}`;

  const asphaltOpts = state.asphalt
    .filter((a) => a.active)
    .map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`)
    .join("");
  $("spendAsphalt").innerHTML = `<option value="">None</option>${asphaltOpts}`;
  $("filterAsphalt").innerHTML = `<option value="">Any</option>${asphaltOpts}`;
}

function renderRows() {
  const body = $("spendBody");
  const total = state.rows.reduce((sum, r) => sum + Number(r.amount || 0), 0);
  $("spendTotal").textContent = money(total);
  $("spendStatus").textContent = `${state.rows.length} row(s)`;
  if (!state.rows.length) {
    body.innerHTML = `<tr><td colspan="9"><span class="hint">No spend rows match these filters.</span></td></tr>`;
    return;
  }
  body.innerHTML = state.rows
    .map(
      (r) => `<tr data-id="${r.id}">
      <td>${escapeHtml(kindLabel(r.kind))}</td>
      <td class="mono">${fmtDate(r.work_date) || "—"}</td>
      <td>
        <div class="site-title">${escapeHtml(r.road_name || "Site")}</div>
        <div class="site-meta mono">${escapeHtml(r.site_number || "")}${r.program ? ` · ${escapeHtml(r.program)}` : ""}</div>
      </td>
      <td>${escapeHtml(r.contractor_name || "—")}</td>
      <td>${escapeHtml(sourceLabel(r.source))}</td>
      <td>${escapeHtml(r.category || "—")}</td>
      <td class="mono">${escapeHtml(r.invoice_ref || "—")}</td>
      <td class="mono">${money(r.amount)}</td>
      <td><button type="button" class="btn btn-danger btn-sm" data-del="${r.id}">Delete</button></td>
    </tr>`
    )
    .join("");
}

function syncExportLinks() {
  const q = filterParams().toString();
  const suffix = q ? `?${q}` : "";
  $("btnExportXlsx").href = `/api/spend/export.xlsx${suffix}`;
  $("btnExportPdf").href = `/api/spend/export.pdf${suffix}`;
}

function buildCalcInputs(kind) {
  if (kind === "traffic") {
    return {
      people: Number($("tPeople").value || 0),
      vehicles: Number($("tVehicles").value || 0),
      tmas: Number($("tTmas").value || 0),
      spotters: Number($("tSpotters").value || 0),
      shift_hours: Number($("tShiftHours").value || 10),
      shift_type: $("tShiftType").value || "day",
      shifts_per_day: 1,
    };
  }
  collectAsphaltLinesFromDom();
  return {
    shift_type: $("aShiftType").value || "day",
    lines: state.asphaltLines
      .filter((l) => l.rate_id)
      .map((l) => ({ rate_id: l.rate_id, quantity: Number(l.quantity || 0) })),
  };
}

async function previewSpend() {
  const kind = $("spendKind").value;
  const inputs = buildCalcInputs(kind);
  if (kind === "asphalt" && !inputs.lines.length) {
    alertDialog("Add at least one asphalt rate line");
    return;
  }
  const res = await api("/api/spend/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      kind,
      work_date: $("spendDate").value || null,
      asphalt_subcontractor_id: kind === "asphalt" ? Number($("spendAsphalt").value || 0) || null : null,
      inputs,
    }),
  });
  state.previewAmount = res.amount;
  $("spendPreview").textContent = `Calculated: ${money(res.amount)}`;
}

async function loadRows() {
  const q = filterParams().toString();
  state.rows = await api(`/api/spend${q ? `?${q}` : ""}`);
  renderRows();
  syncExportLinks();
}

async function init() {
  await injectChrome({ active: "/spend", mode: "ops" });
  const [sites, traffic, asphalt, rates] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/traffic-contractors?active_only=true"),
    api("/api/asphalt/subcontractors?active_only=true"),
    api("/api/asphalt/rates"),
  ]);
  state.sites = Array.isArray(sites) ? sites : [];
  state.traffic = Array.isArray(traffic) ? traffic : [];
  state.asphalt = Array.isArray(asphalt) ? asphalt : [];
  state.rates = Array.isArray(rates) ? rates : [];
  const params = new URLSearchParams(location.search);
  const siteFromUrl = params.get("site_id");
  if (siteFromUrl && !state.sites.some((s) => String(s.id) === String(siteFromUrl))) {
    try {
      const extra = await api(`/api/sites/${siteFromUrl}`);
      if (extra?.id) state.sites = [extra, ...state.sites];
    } catch {
      /* ignore */
    }
  }
  fillSelects();
  if (siteFromUrl && $("filterSite")) $("filterSite").value = siteFromUrl;
  if (siteFromUrl && $("spendSite")) $("spendSite").value = siteFromUrl;
  syncModeFields();
  await loadRows();

  on("spendKind", "change", syncModeFields);
  on("spendSource", "change", syncModeFields);
  on("spendAsphalt", "change", () => {
    if (isCalculated() && $("spendKind").value === "asphalt") renderAsphaltLines();
  });
  on("btnAddAsphaltLine", "click", () => {
    collectAsphaltLinesFromDom();
    state.asphaltLines.push({ rate_id: null, quantity: 0 });
    renderAsphaltLines();
  });
  on("asphaltLinesWrap", "click", (ev) => {
    const btn = ev.target.closest("[data-rm-aline]");
    if (!btn) return;
    collectAsphaltLinesFromDom();
    state.asphaltLines.splice(Number(btn.dataset.rmAline), 1);
    renderAsphaltLines();
  });
  on("asphaltLinesWrap", "change", (ev) => {
    const sel = ev.target.closest("[data-aline-rate]");
    if (!sel) return;
    const idx = Number(sel.dataset.alineRate);
    state.asphaltLines[idx].rate_id = sel.value ? Number(sel.value) : null;
  });
  on("btnPreview", "click", () => previewSpend().catch((e) => alertDialog(e.message)));
  on("btnSyncEstimates", "click", async () => {
    try {
      const site = $("filterSite")?.value || "";
      const q = site ? `?site_id=${encodeURIComponent(site)}` : "";
      const res = await api(`/api/spend/sync-from-estimates${q}`, { method: "POST" });
      await loadRows();
      alertDialog(
        `Estimates synced — ${res.created || 0} created, ${res.updated || 0} updated, ${res.skipped || 0} skipped.`
      );
    } catch (e) {
      alertDialog(e.message);
    }
  });
  on("btnApplyFilters", "click", () =>
    loadRows().catch((e) => {
      alertDialog(e.message);
    })
  );
  on("spendForm", "submit", async (ev) => {
    ev.preventDefault();
    const kind = $("spendKind").value;
    const source = $("spendSource").value || "manual";
    const siteId = Number($("spendSite").value || 0);
    if (!siteId) {
      alertDialog("Select a site");
      return;
    }
    const body = {
      kind,
      site_id: siteId,
      work_date: $("spendDate").value || null,
      source,
      category: $("spendCategory").value.trim() || null,
      traffic_contractor_id: kind === "traffic" ? Number($("spendTraffic").value || 0) || null : null,
      asphalt_subcontractor_id: kind === "asphalt" ? Number($("spendAsphalt").value || 0) || null : null,
      invoice_ref: $("spendInvoice").value.trim() || null,
      notes: $("spendNotes").value.trim() || null,
      created_by: userName(),
    };
    if (source === "calculated") {
      body.inputs = buildCalcInputs(kind);
      if (kind === "asphalt" && !body.inputs.lines.length) {
        alertDialog("Add at least one asphalt rate line");
        return;
      }
    } else {
      body.amount = Number($("spendAmount").value || 0);
    }
    await api("/api/spend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    $("spendAmount").value = "";
    $("spendNotes").value = "";
    $("spendInvoice").value = "";
    $("spendCategory").value = "";
    state.asphaltLines = [];
    state.previewAmount = null;
    syncModeFields();
    await loadRows();
  });
  on("spendBody", "click", async (ev) => {
    const btn = ev.target.closest("[data-del]");
    if (!btn) return;
    if (!(await confirmDialog("Delete this spend row?"))) return;
    await api(`/api/spend/${btn.dataset.del}`, { method: "DELETE" });
    await loadRows();
  });
}

init().catch((e) => showPageError("spendBody", e, "Could not load spend"));
