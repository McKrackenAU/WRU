import { $, api, on, escapeHtml, injectChrome, confirmDialog, alertDialog, showPageError } from "./common.js";

const state = { subcontractors: [], rates: [], matrix: null };

function money(n) {
  if (n == null || n === "") return "—";
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function parseDates(raw) {
  return String(raw || "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function inferTypeFromForm() {
  const unit = $("rateUnit")?.value || "m2";
  const name = ($("rateName")?.value || "").toLowerCase();
  if (/mobilis|mobiliz|crew|establishment/.test(name)) return "shift";
  if (["shift", "day"].includes(unit)) return "shift";
  return "unit";
}

function syncRateTypeFields(fromUnit) {
  if (fromUnit && $("rateType")) $("rateType").value = inferTypeFromForm();
  const type = $("rateType")?.value || "unit";
  const unitWrap = $("unitRateWrap");
  const shiftWrap = $("shiftRateWrap");
  if (unitWrap) unitWrap.hidden = type !== "unit";
  if (shiftWrap) shiftWrap.hidden = type !== "shift";
}

function fillTreatmentNames() {
  const names = [...new Set(state.rates.map((r) => r.name).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b)
  );
  $("treatmentNames").innerHTML = names.map((n) => `<option value="${escapeHtml(n)}"></option>`).join("");
}

function renderMatrix() {
  const wrap = $("matrixWrap");
  const m = state.matrix;
  if (!m || !m.subcontractors?.length) {
    wrap.innerHTML = `<p class="hint">Add subcontractors and rates to compare cards.</p>`;
    return;
  }
  const head = m.subcontractors.map((s) => `<th>${escapeHtml(s.name)}</th>`).join("");
  const body = (m.treatments || [])
    .map((t) => {
      const cells = (t.cells || [])
        .map((c) => {
          if (c.missing) return `<td class="hint">—</td>`;
          const cls = c.best ? "best-rate" : "";
          return `<td class="${cls}">${money(c.unit_rate)}${c.best ? ` <span class="best-badge">best</span>` : ""}</td>`;
        })
        .join("");
      return `<tr>
        <td><strong>${escapeHtml(t.name)}</strong><div class="hint">${escapeHtml(t.unit)} · ${t.rate_type === "shift" ? "shift" : "unit"}</div></td>
        ${cells}
      </tr>`;
    })
    .join("");
  wrap.innerHTML = `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>Treatment</th>${head}</tr></thead>
    <tbody>${body || `<tr><td colspan="${m.subcontractors.length + 1}"><span class="hint">No rates yet.</span></td></tr>`}</tbody>
  </table></div>`;
}

async function loadMatrix() {
  const tier = $("matrixTier")?.value || "weekday";
  state.matrix = await api(`/api/asphalt/rates/matrix?rate_tier=${encodeURIComponent(tier)}`);
  renderMatrix();
}

async function reload() {
  const [subs, rates] = await Promise.all([
    api("/api/asphalt/subcontractors"),
    api("/api/asphalt/rates"),
  ]);
  state.subcontractors = subs;
  state.rates = rates;
  $("rateSub").innerHTML = subs
    .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
    .join("");
  fillTreatmentNames();
  $("subList").innerHTML = subs.length
    ? `<div class="table-scroll"><table class="data-table">
        <thead><tr><th>Name</th><th>RDOs</th><th>Active</th><th></th></tr></thead>
        <tbody>
          ${subs
            .map(
              (s) => `<tr>
              <td><strong>${escapeHtml(s.name)}</strong>${
                s.notes ? `<div class="hint">${escapeHtml(s.notes)}</div>` : ""
              }</td>
              <td class="mono">${escapeHtml((s.rdo_dates || []).join(", ") || "—")}</td>
              <td>${s.active ? "Yes" : "No"}</td>
              <td><button type="button" class="btn btn-danger btn-sm" data-del-sub="${s.id}">Delete</button></td>
            </tr>`
            )
            .join("")}
        </tbody></table></div>`
    : `<p class="hint">No subcontractors yet.</p>`;

  $("rateList").innerHTML = rates.length
    ? `<div class="table-scroll"><table class="data-table">
        <thead><tr><th>Subcontractor</th><th>Treatment</th><th>Unit</th><th>Type</th><th>Unit / day</th><th>Night</th><th>Weekend</th><th>PH</th><th></th></tr></thead>
        <tbody>
          ${rates
            .map((r) => {
              const sub = subs.find((s) => s.id === r.subcontractor_id);
              const isUnit = (r.rate_type || "unit") === "unit";
              return `<tr>
                <td>${escapeHtml(sub?.name || "—")}</td>
                <td>${escapeHtml(r.name)}</td>
                <td>${escapeHtml(r.unit)}</td>
                <td>${isUnit ? "Unit" : "Shift"}</td>
                <td>${money(isUnit ? r.day_rate : r.day_rate)}</td>
                <td>${isUnit ? "—" : money(r.night_rate)}</td>
                <td>${isUnit ? "—" : money(r.weekend_rate)}</td>
                <td>${isUnit ? "—" : money(r.public_holiday_rate)}</td>
                <td><button type="button" class="btn btn-danger btn-sm" data-del-rate="${r.id}">Delete</button></td>
              </tr>`;
            })
            .join("")}
        </tbody></table></div>`
    : `<p class="hint">No rates yet.</p>`;
  await loadMatrix();
}

async function init() {
  await injectChrome({ active: "/admin/asphalt", mode: "admin" });
  await reload();
  syncRateTypeFields(true);

  on("rateUnit", "change", () => syncRateTypeFields(true));
  on("rateName", "change", () => syncRateTypeFields(true));
  on("rateType", "change", () => syncRateTypeFields(false));
  on("matrixTier", "change", () => loadMatrix().catch((e) => alertDialog(e.message)));

  on("subForm", "submit", async (e) => {
    e.preventDefault();
    await api("/api/asphalt/subcontractors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("subName").value.trim(),
        notes: $("subNotes").value.trim() || null,
        rdo_dates: parseDates($("subRdos").value),
      }),
    });
    $("subForm").reset();
    await reload();
  });

  on("rateForm", "submit", async (e) => {
    e.preventDefault();
    const rateType = $("rateType").value;
    const unitRate = Number($("rateUnitAmt").value || 0);
    const weekend = Number($("rateWeekend").value || 0);
    await api("/api/asphalt/rates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subcontractor_id: Number($("rateSub").value),
        name: $("rateName").value.trim(),
        unit: $("rateUnit").value,
        rate_type: rateType,
        unit_rate: rateType === "unit" ? unitRate : null,
        day_rate: rateType === "unit" ? unitRate : Number($("rateDay").value || 0),
        night_rate: rateType === "unit" ? unitRate : Number($("rateNight").value || 0),
        weekend_rate: rateType === "unit" ? unitRate : weekend,
        sunday_rate: rateType === "unit" ? unitRate : weekend,
        saturday_rate: rateType === "unit" ? unitRate : weekend,
        public_holiday_rate: rateType === "unit" ? unitRate : Number($("ratePh").value || 0),
      }),
    });
    $("rateName").value = "";
    await reload();
  });

  on("btnImportRates", "click", async () => {
    const file = $("rateFile").files?.[0];
    if (!file) {
      alertDialog("Choose a CSV or Excel rate card");
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    $("importStatus").textContent = "Importing…";
    try {
      const res = await fetch("/api/asphalt/rates/import", { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Import failed");
      $("importStatus").textContent = `Imported · ${body.created} new, ${body.updated} updated${
        body.subcontractors_created ? `, ${body.subcontractors_created} subbies created` : ""
      }`;
      await reload();
    } catch (e) {
      $("importStatus").textContent = "";
      alertDialog(e.message);
    }
  });

  on("subList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-sub]");
    if (!btn) return;
    if (!(await confirmDialog("Delete this subcontractor and its rates?"))) return;
    await api(`/api/asphalt/subcontractors/${btn.dataset.delSub}`, { method: "DELETE" });
    await reload();
  });
  on("rateList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-rate]");
    if (!btn) return;
    if (!(await confirmDialog("Delete this rate?"))) return;
    await api(`/api/asphalt/rates/${btn.dataset.delRate}`, { method: "DELETE" });
    await reload();
  });
}

init().catch((e) => showPageError("subList", e, "Could not load asphalt rates"));
