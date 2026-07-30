import { $, api, escapeHtml, injectChrome } from "./common.js";

function roleOptions(selected) {
  return ["none", "permits", "trims", "complete"]
    .map((r) => `<option value="${r}" ${r === selected ? "selected" : ""}>${r}</option>`)
    .join("");
}

async function loadStages() {
  const rows = await api("/api/admin/stages");
  $("stageBody").innerHTML = rows
    .map(
      (s) => `<tr data-id="${s.id}">
      <td><input data-f="label" value="${escapeHtml(s.label)}" /></td>
      <td class="mono">${escapeHtml(s.key)}</td>
      <td><input data-f="position" type="number" value="${s.position}" style="width:5rem" /></td>
      <td><select data-f="list_role">${roleOptions(s.list_role)}</select></td>
      <td><input data-f="counts_toward_progress" type="checkbox" ${s.counts_toward_progress ? "checked" : ""} /></td>
      <td><input data-f="active" type="checkbox" ${s.active ? "checked" : ""} /></td>
      <td>
        <div class="row-actions">
          <button type="button" class="btn" data-save-stage="${s.id}">Save</button>
          <button type="button" class="btn btn-danger" data-del-stage="${s.id}">Remove</button>
        </div>
      </td>
    </tr>`
    )
    .join("");
}

async function loadPrograms() {
  const rows = await api("/api/admin/programs");
  $("programList").innerHTML = rows.length
    ? rows
        .map(
          (p) => `<li>
          <div class="top">
            <span>${escapeHtml(p.name)} ${p.active ? "" : "(inactive)"}</span>
            <button type="button" class="btn btn-danger" data-del-prog="${p.id}">Remove</button>
          </div>
        </li>`
        )
        .join("")
    : `<li><p class="meta">No programs yet.</p></li>`;
}

async function init() {
  injectChrome({ active: "/stages" });
  await Promise.all([loadStages(), loadPrograms()]);

  $("btnAddStage").addEventListener("click", async () => {
    try {
      await api("/api/admin/stages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: $("sLabel").value.trim(),
          key: $("sKey").value.trim() || null,
          list_role: $("sRole").value,
          counts_toward_progress: $("sProgress").checked,
          active: true,
        }),
      });
      $("sLabel").value = "";
      $("sKey").value = "";
      await loadStages();
    } catch (e) {
      alert(e.message);
    }
  });

  $("btnAddProgram").addEventListener("click", async () => {
    try {
      await api("/api/admin/programs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: $("pName").value.trim(), active: true }),
      });
      $("pName").value = "";
      await loadPrograms();
    } catch (e) {
      alert(e.message);
    }
  });

  $("stageBody").addEventListener("click", async (ev) => {
    const save = ev.target.closest("[data-save-stage]");
    const del = ev.target.closest("[data-del-stage]");
    try {
      if (save) {
        const tr = save.closest("tr");
        await api(`/api/admin/stages/${save.dataset.saveStage}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            label: tr.querySelector('[data-f="label"]').value.trim(),
            position: Number(tr.querySelector('[data-f="position"]').value),
            list_role: tr.querySelector('[data-f="list_role"]').value,
            counts_toward_progress: tr.querySelector('[data-f="counts_toward_progress"]').checked,
            active: tr.querySelector('[data-f="active"]').checked,
          }),
        });
        await loadStages();
      }
      if (del) {
        if (!confirm("Deactivate this stage? Historical site steps keep the key.")) return;
        await api(`/api/admin/stages/${del.dataset.delStage}`, { method: "DELETE" });
        await loadStages();
      }
    } catch (e) {
      alert(e.message);
    }
  });

  $("programList").addEventListener("click", async (ev) => {
    const del = ev.target.closest("[data-del-prog]");
    if (!del) return;
    if (!confirm("Deactivate this program category?")) return;
    await api(`/api/admin/programs/${del.dataset.delProg}`, { method: "DELETE" });
    await loadPrograms();
  });
}

init().catch((e) => alert(e.message));
