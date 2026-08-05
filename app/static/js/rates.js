import { $, api, escapeHtml, injectChrome } from "./common.js";

async function loadSettings() {
  const s = await api("/api/costs/settings");
  $("otHours").value = s.overtime_after_hours;
  $("travelAllow").value = s.travel_allowance;
  $("mealAllow").value = s.meal_allowance;
  $("mealAfter").value = s.meal_after_hours;
  $("dayStart").value = s.day_start_hour ?? 6;
  $("dayEnd").value = s.day_end_hour ?? 18;
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
      travel_allowance: Number($("travelAllow").value),
      meal_allowance: Number($("mealAllow").value),
      meal_after_hours: Number($("mealAfter").value),
      day_start_hour: Number($("dayStart").value),
      day_end_hour: Number($("dayEnd").value),
      vms_lead_days_default: Number($("vmsLead").value),
      vms_delivery_rate: Number($("vmsDelivery").value),
      vms_collection_rate: Number($("vmsCollection").value),
      vms_day_rate: Number($("vmsDay").value),
    }),
  });
  $("settingsStatus").textContent = "Saved.";
  setTimeout(() => ($("settingsStatus").textContent = ""), 2000);
}

function kindOptions(selected) {
  const labels = {
    crew_pack: "TC pack",
    tma: "TMA",
    spotter: "Spotter",
    legacy: "Legacy",
  };
  return Object.keys(labels)
    .map(
      (k) =>
        `<option value="${k}" ${k === selected ? "selected" : ""}>${labels[k]}</option>`
    )
    .join("");
}

async function loadRates() {
  const rates = await api("/api/costs/rates");
  $("rateBody").innerHTML = rates
    .map(
      (r) => `<tr data-id="${r.id}">
      <td><input data-f="name" value="${escapeHtml(r.name)}" /></td>
      <td><select data-f="rate_kind">${kindOptions(r.rate_kind || "legacy")}</select></td>
      <td><input data-f="pack_people" type="number" min="0" max="4" step="1" value="${r.pack_people ?? 1}" /></td>
      <td><input data-f="includes_vehicle" type="checkbox" ${r.includes_vehicle ? "checked" : ""} /></td>
      <td><input data-f="day_ordinary" type="number" min="0" step="0.01" value="${r.day_ordinary}" /></td>
      <td><input data-f="day_overtime" type="number" min="0" step="0.01" value="${r.day_overtime}" /></td>
      <td><input data-f="night_ordinary" type="number" min="0" step="0.01" value="${r.night_ordinary}" /></td>
      <td><input data-f="night_overtime" type="number" min="0" step="0.01" value="${r.night_overtime}" /></td>
      <td><input data-f="saturday_ordinary" type="number" min="0" step="0.01" value="${r.saturday_ordinary ?? 0}" /></td>
      <td><input data-f="saturday_overtime" type="number" min="0" step="0.01" value="${r.saturday_overtime ?? 0}" /></td>
      <td><input data-f="sunday_ordinary" type="number" min="0" step="0.01" value="${r.sunday_ordinary ?? 0}" /></td>
      <td><input data-f="sunday_overtime" type="number" min="0" step="0.01" value="${r.sunday_overtime ?? 0}" /></td>
      <td><input data-f="public_holiday_ordinary" type="number" min="0" step="0.01" value="${r.public_holiday_ordinary ?? 0}" /></td>
      <td><input data-f="public_holiday_overtime" type="number" min="0" step="0.01" value="${r.public_holiday_overtime ?? 0}" /></td>
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
    rate_kind: tr.querySelector('[data-f="rate_kind"]').value,
    pack_people: Number(tr.querySelector('[data-f="pack_people"]').value),
    includes_vehicle: tr.querySelector('[data-f="includes_vehicle"]').checked,
    day_ordinary: Number(tr.querySelector('[data-f="day_ordinary"]').value),
    day_overtime: Number(tr.querySelector('[data-f="day_overtime"]').value),
    night_ordinary: Number(tr.querySelector('[data-f="night_ordinary"]').value),
    night_overtime: Number(tr.querySelector('[data-f="night_overtime"]').value),
    saturday_ordinary: Number(tr.querySelector('[data-f="saturday_ordinary"]').value),
    saturday_overtime: Number(tr.querySelector('[data-f="saturday_overtime"]').value),
    sunday_ordinary: Number(tr.querySelector('[data-f="sunday_ordinary"]').value),
    sunday_overtime: Number(tr.querySelector('[data-f="sunday_overtime"]').value),
    public_holiday_ordinary: Number(tr.querySelector('[data-f="public_holiday_ordinary"]').value),
    public_holiday_overtime: Number(tr.querySelector('[data-f="public_holiday_overtime"]').value),
    active: tr.querySelector('[data-f="active"]').checked,
  };
}

function syncNewKind() {
  const kind = $("rKind").value;
  if (kind === "tma") {
    $("rPeople").value = 0;
    $("rVehicle").checked = true;
  } else if (kind === "spotter") {
    $("rPeople").value = 1;
    $("rVehicle").checked = false;
  } else if (kind === "crew_pack" && Number($("rPeople").value) < 1) {
    $("rPeople").value = 1;
  }
}

async function init() {
  injectChrome({ active: "/admin/rates", mode: "admin" });
  await loadSettings();
  await loadRates();

  $("btnSaveSettings").addEventListener("click", () =>
    saveSettings().catch((e) => alert(e.message))
  );
  $("rKind").addEventListener("change", syncNewKind);

  $("btnAddRate").addEventListener("click", async () => {
    try {
      const kind = $("rKind").value;
      await api("/api/costs/rates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: $("rName").value.trim(),
          rate_kind: kind,
          pack_people: kind === "tma" ? 0 : kind === "spotter" ? 1 : Number($("rPeople").value),
          includes_vehicle: $("rVehicle").checked,
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
        if (!confirm("Delete this rate?")) return;
        await api(`/api/costs/rates/${del.dataset.del}`, { method: "DELETE" });
        await loadRates();
      }
    } catch (e) {
      alert(e.message);
    }
  });
}

init().catch((e) => alert(e.message));
