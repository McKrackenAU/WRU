import { $, api, on, escapeHtml, injectChrome, confirmDialog, showPageError } from "./common.js";

const state = { subcontractors: [], rates: [] };

function parseDates(raw) {
  return String(raw || "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
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
        <thead><tr><th>Subcontractor</th><th>Name</th><th>Unit</th><th>Day</th><th>Night</th><th>Sat</th><th>Sun</th><th>PH</th><th></th></tr></thead>
        <tbody>
          ${rates
            .map((r) => {
              const sub = subs.find((s) => s.id === r.subcontractor_id);
              return `<tr>
                <td>${escapeHtml(sub?.name || "—")}</td>
                <td>${escapeHtml(r.name)}</td>
                <td>${escapeHtml(r.unit)}</td>
                <td>${r.day_rate}</td>
                <td>${r.night_rate}</td>
                <td>${r.saturday_rate}</td>
                <td>${r.sunday_rate}</td>
                <td>${r.public_holiday_rate}</td>
                <td><button type="button" class="btn btn-danger btn-sm" data-del-rate="${r.id}">Delete</button></td>
              </tr>`;
            })
            .join("")}
        </tbody></table></div>`
    : `<p class="hint">No rates yet.</p>`;
}

async function init() {
  await injectChrome({ active: "/admin/asphalt", mode: "admin" });
  await reload();

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
    await api("/api/asphalt/rates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subcontractor_id: Number($("rateSub").value),
        name: $("rateName").value.trim(),
        unit: $("rateUnit").value,
        day_rate: Number($("rateDay").value || 0),
        night_rate: Number($("rateNight").value || 0),
        saturday_rate: Number($("rateSat").value || 0),
        sunday_rate: Number($("rateSun").value || 0),
        public_holiday_rate: Number($("ratePh").value || 0),
      }),
    });
    $("rateName").value = "";
    await reload();
  });

  on("subList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-sub]");
    if (!btn) return;
    if (!await confirmDialog("Delete this subcontractor and its rates?")) return;
    await api(`/api/asphalt/subcontractors/${btn.dataset.delSub}`, { method: "DELETE" });
    await reload();
  });
  on("rateList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-rate]");
    if (!btn) return;
    if (!await confirmDialog("Delete this rate?")) return;
    await api(`/api/asphalt/rates/${btn.dataset.delRate}`, { method: "DELETE" });
    await reload();
  });
}

init().catch((e) => showPageError("subList", e, "Could not load asphalt rates"));
