import { $, api, escapeHtml, injectChrome } from "./common.js";

async function loadSettings() {
  const s = await api("/api/costs/settings");
  $("otHours").value = s.overtime_after_hours;
  $("vmsLead").value = s.vms_lead_days_default;
  $("vmsDelivery").value = s.vms_delivery_rate;
  $("vmsCollection").value = s.vms_collection_rate;
  $("vmsDay").value = s.vms_day_rate;
}

async function saveSettings() {
  await api("/api/costs/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      overtime_after_hours: Number($("otHours").value),
      vms_lead_days_default: Number($("vmsLead").value),
      vms_delivery_rate: Number($("vmsDelivery").value),
      vms_collection_rate: Number($("vmsCollection").value),
      vms_day_rate: Number($("vmsDay").value),
    }),
  });
  $("settingsStatus").textContent = "Saved.";
  setTimeout(() => ($("settingsStatus").textContent = ""), 2000);
}

async function loadRates() {
  const rates = await api("/api/costs/rates");
  $("rateBody").innerHTML = rates
    .map(
      (r) => `<tr data-id="${r.id}">
      <td><input data-f="name" value="${escapeHtml(r.name)}" /></td>
      <td><input data-f="day_ordinary" type="number" min="0" step="0.01" value="${r.day_ordinary}" /></td>
      <td><input data-f="day_overtime" type="number" min="0" step="0.01" value="${r.day_overtime}" /></td>
      <td><input data-f="night_ordinary" type="number" min="0" step="0.01" value="${r.night_ordinary}" /></td>
      <td><input data-f="night_overtime" type="number" min="0" step="0.01" value="${r.night_overtime}" /></td>
      <td><input data-f="active" type="checkbox" ${r.active ? "checked" : ""} /></td>
      <td>
        <div class="row-actions">
          <button type="button" class="btn" data-save="${r.id}">Save</button>
          <button type="button" class="btn btn-danger" data-del="${r.id}">Delete</button>
        </div>
      </td>
    </tr>`
    )
    .join("");
}

function rowPayload(tr) {
  return {
    name: tr.querySelector('[data-f="name"]').value.trim(),
    day_ordinary: Number(tr.querySelector('[data-f="day_ordinary"]').value),
    day_overtime: Number(tr.querySelector('[data-f="day_overtime"]').value),
    night_ordinary: Number(tr.querySelector('[data-f="night_ordinary"]').value),
    night_overtime: Number(tr.querySelector('[data-f="night_overtime"]').value),
    active: tr.querySelector('[data-f="active"]').checked,
  };
}

async function init() {
  injectChrome({ active: "/rates" });
  await loadSettings();
  await loadRates();

  $("btnSaveSettings").addEventListener("click", () =>
    saveSettings().catch((e) => alert(e.message))
  );
  $("btnAddRate").addEventListener("click", async () => {
    try {
      await api("/api/costs/rates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: $("rName").value.trim(),
          day_ordinary: Number($("rDayO").value),
          day_overtime: Number($("rDayOt").value),
          night_ordinary: Number($("rNightO").value),
          night_overtime: Number($("rNightOt").value),
          active: true,
        }),
      });
      $("rName").value = "";
      await loadRates();
    } catch (e) {
      alert(e.message);
    }
  });

  $("rateBody").addEventListener("click", async (ev) => {
    const save = ev.target.closest("[data-save]");
    const del = ev.target.closest("[data-del]");
    try {
      if (save) {
        const tr = save.closest("tr");
        await api(`/api/costs/rates/${save.dataset.save}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(rowPayload(tr)),
        });
      }
      if (del) {
        if (!confirm("Delete this rate category?")) return;
        await api(`/api/costs/rates/${del.dataset.del}`, { method: "DELETE" });
        await loadRates();
      }
    } catch (e) {
      alert(e.message);
    }
  });
}

init().catch((e) => alert(e.message));
