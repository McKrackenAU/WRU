import { $, api, escapeHtml, injectChrome, alertDialog, confirmDialog } from "./common.js";

function roleOptions(selected) {
  return ["none", "permits", "trims", "complete"]
    .map((r) => `<option value="${r}" ${r === selected ? "selected" : ""}>${r}</option>`)
    .join("");
}

function stageIdsInDom() {
  return [...$("stageBody").querySelectorAll("tr[data-id]")].map((tr) => Number(tr.dataset.id));
}

async function saveStageOrder() {
  const ids = stageIdsInDom();
  if (!ids.length) return;
  await api("/api/admin/stages/order", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  await loadStages();
}

function renderStages(rows) {
  $("stageBody").innerHTML = rows
    .map(
      (s, idx) => `<tr data-id="${s.id}" draggable="true">
      <td class="stage-order-cell">
        <span class="drag-grip" title="Drag to reorder" aria-hidden="true">⋮⋮</span>
        <span class="mono">${idx + 1}</span>
        <span class="stage-order-btns">
          <button type="button" class="btn btn-sm" data-move-stage="-1" aria-label="Move up">↑</button>
          <button type="button" class="btn btn-sm" data-move-stage="1" aria-label="Move down">↓</button>
        </span>
      </td>
      <td><input data-f="label" value="${escapeHtml(s.label)}" /></td>
      <td class="mono">${escapeHtml(s.key)}</td>
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

async function loadStages() {
  const rows = await api("/api/admin/stages");
  renderStages(rows);
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

function bindStageDrag() {
  const tbody = $("stageBody");
  tbody.addEventListener("dragstart", (ev) => {
    const tr = ev.target.closest("tr[data-id]");
    if (!tr || ev.target.closest("input, select, button")) {
      ev.preventDefault();
      return;
    }
    tr.classList.add("is-dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", tr.dataset.id);
  });
  tbody.addEventListener("dragend", (ev) => {
    ev.target.closest("tr")?.classList.remove("is-dragging");
    tbody.querySelectorAll(".drop-before").forEach((el) => el.classList.remove("drop-before"));
  });
  tbody.addEventListener("dragover", (ev) => {
    const over = ev.target.closest("tr[data-id]");
    if (!over || over.classList.contains("is-dragging")) return;
    ev.preventDefault();
    tbody.querySelectorAll(".drop-before").forEach((el) => {
      if (el !== over) el.classList.remove("drop-before");
    });
    over.classList.add("drop-before");
  });
  tbody.addEventListener("drop", async (ev) => {
    ev.preventDefault();
    const over = ev.target.closest("tr[data-id]");
    const dragging = tbody.querySelector("tr.is-dragging");
    tbody.querySelectorAll(".drop-before").forEach((el) => el.classList.remove("drop-before"));
    if (!over || !dragging || over === dragging) return;
    const rect = over.getBoundingClientRect();
    const before = ev.clientY < rect.top + rect.height / 2;
    if (before) over.before(dragging);
    else over.after(dragging);
    dragging.classList.remove("is-dragging");
    try {
      await saveStageOrder();
    } catch (e) {
      alertDialog(e.message);
      await loadStages();
    }
  });
}

async function init() {
  injectChrome({ active: "/admin/stages", mode: "admin" });
  await Promise.all([loadStages(), loadPrograms()]);
  bindStageDrag();

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
      alertDialog(e.message);
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
      alertDialog(e.message);
    }
  });

  $("stageBody").addEventListener("click", async (ev) => {
    const move = ev.target.closest("[data-move-stage]");
    const save = ev.target.closest("[data-save-stage]");
    const del = ev.target.closest("[data-del-stage]");
    try {
      if (move) {
        const tr = move.closest("tr");
        const dir = Number(move.dataset.moveStage);
        if (dir < 0) tr.previousElementSibling?.before(tr);
        else tr.nextElementSibling?.after(tr);
        await saveStageOrder();
        return;
      }
      if (save) {
        const tr = save.closest("tr");
        await api(`/api/admin/stages/${save.dataset.saveStage}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            label: tr.querySelector('[data-f="label"]').value.trim(),
            list_role: tr.querySelector('[data-f="list_role"]').value,
            counts_toward_progress: tr.querySelector('[data-f="counts_toward_progress"]').checked,
            active: tr.querySelector('[data-f="active"]').checked,
          }),
        });
        await loadStages();
      }
      if (del) {
        if (!await confirmDialog("Deactivate this stage? Historical site steps keep the key.")) return;
        await api(`/api/admin/stages/${del.dataset.delStage}`, { method: "DELETE" });
        await loadStages();
      }
    } catch (e) {
      alertDialog(e.message);
    }
  });

  $("programList").addEventListener("click", async (ev) => {
    const del = ev.target.closest("[data-del-prog]");
    if (!del) return;
    if (!await confirmDialog("Deactivate this program category?")) return;
    await api(`/api/admin/programs/${del.dataset.delProg}`, { method: "DELETE" });
    await loadPrograms();
  });
}

init().catch((e) => { alertDialog(e.message); });
