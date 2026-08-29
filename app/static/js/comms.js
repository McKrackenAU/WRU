import {
  $,
  api,
  alertDialog,
  confirmDialog,
  escapeHtml,
  injectChrome,
  on,
  promptDialog,
  showPageError,
  uploadFileChunked,
  userName,
  errorMessage,
  onLiveSitesChanged,
} from "./common.js";

const state = {
  sheets: [],
  sheet: null,
  search: "",
  docsRowId: null,
  jobTimer: null,
};

function sheetIdFromUrl() {
  const raw = new URLSearchParams(location.search).get("sheet");
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function setSheetUrl(id) {
  const url = new URL(location.href);
  if (id) url.searchParams.set("sheet", String(id));
  else url.searchParams.delete("sheet");
  history.replaceState(null, "", url);
}

function fmtCell(value) {
  if (value == null || value === "") return "";
  return String(value);
}

function cellInput(col, value) {
  const v = value == null ? "" : String(value);
  if (col.field_type === "checkbox") {
    return `<input type="checkbox" data-field="${escapeHtml(col.field_key)}" ${
      v === "true" || v === "1" || v.toLowerCase() === "yes" ? "checked" : ""
    } />`;
  }
  if (col.field_type === "select") {
    const opts = ["", ...(col.options || [])];
    return `<select data-field="${escapeHtml(col.field_key)}">${opts
      .map(
        (o) =>
          `<option value="${escapeHtml(o)}" ${o === v ? "selected" : ""}>${escapeHtml(o || "—")}</option>`
      )
      .join("")}</select>`;
  }
  const type = col.field_type === "number" ? "number" : col.field_type === "date" ? "date" : "text";
  return `<input type="${type}" data-field="${escapeHtml(col.field_key)}" value="${escapeHtml(v)}" />`;
}

function jobLabel(site) {
  if (!site) return "Link job…";
  return `${site.road_name || "Site"} · ${site.site_number || ""}`.trim();
}

function renderTabs() {
  const wrap = $("sheetTabs");
  if (!wrap) return;
  wrap.innerHTML = state.sheets
    .map(
      (s) =>
        `<button type="button" data-sheet="${s.id}" class="${
          state.sheet?.id === s.id ? "active" : ""
        }" role="tab" aria-selected="${state.sheet?.id === s.id}">${escapeHtml(s.title)}</button>`
    )
    .join("");
}

function filteredRows() {
  const rows = state.sheet?.rows || [];
  const q = state.search.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) => {
    const hay = [
      row.section,
      row.site?.road_name,
      row.site?.site_number,
      row.site?.moa_number,
      ...Object.values(row.values || {}),
    ]
      .filter((v) => v != null && v !== "")
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

function renderTable() {
  const wrap = $("commsTableWrap");
  if (!wrap || !state.sheet) {
    if (wrap) wrap.innerHTML = `<p class="hint">No planner tab selected.</p>`;
    return;
  }
  const cols = state.sheet.columns || [];
  const rows = filteredRows();
  $("commsCount").textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;
  if (!cols.length && !rows.length) {
    wrap.innerHTML = `<p class="hint">No columns yet. Use Columns to add fields, then Add row.</p>`;
    return;
  }
  wrap.innerHTML = `
    <table class="data-table comms-table">
      <thead>
        <tr>
          <th class="comms-sticky">Job</th>
          ${cols.map((c) => `<th title="${escapeHtml(c.field_key)}">${escapeHtml(c.name)}</th>`).join("")}
          <th>Docs</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map((row) => {
                  const linked = row.site
                    ? `<a class="comms-job-link" href="/?highlight=${row.site.id}">${escapeHtml(jobLabel(row.site))}</a>`
                    : `<span class="hint">Not linked</span>`;
                  return `<tr data-row="${row.id}">
                    <td class="comms-sticky">
                      ${linked}
                      <button type="button" class="btn btn-sm" data-docs="${row.id}">Link / files</button>
                    </td>
                    ${cols
                      .map(
                        (c) =>
                          `<td class="comms-cell">${cellInput(c, (row.values || {})[c.field_key])}</td>`
                      )
                      .join("")}
                    <td>
                      <button type="button" class="btn btn-sm" data-docs="${row.id}">${
                        row.document_count || 0
                      } file${row.document_count === 1 ? "" : "s"}</button>
                    </td>
                    <td><button type="button" class="btn btn-danger btn-sm" data-del-row="${row.id}">Delete</button></td>
                  </tr>`;
                })
                .join("")
            : `<tr><td class="empty" colspan="${cols.length + 3}">No rows match.</td></tr>`
        }
      </tbody>
    </table>
  `;
}

async function loadSheets(preferredId) {
  state.sheets = await api("/api/comms/sheets");
  const want = preferredId || sheetIdFromUrl() || state.sheet?.id;
  const pick = state.sheets.find((s) => s.id === want) || state.sheets[0] || null;
  if (pick) await loadSheet(pick.id);
  else {
    state.sheet = null;
    renderTabs();
    renderTable();
  }
}

async function loadSheet(id) {
  state.sheet = await api(`/api/comms/sheets/${id}`);
  setSheetUrl(id);
  renderTabs();
  renderTable();
}

async function saveCell(rowId, field, value) {
  await api(`/api/comms/rows/${rowId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values: { [field]: value } }),
  });
}

function renderColumnList() {
  const cols = state.sheet?.columns || [];
  $("columnList").innerHTML = cols.length
    ? cols
        .map(
          (c) => `<li>
            <div>
              <strong>${escapeHtml(c.name)}</strong>
              <div class="meta">${escapeHtml(c.field_type)} · ${escapeHtml(c.field_key)}</div>
            </div>
            <button type="button" class="btn btn-danger" data-del-col="${c.id}">Remove</button>
          </li>`
        )
        .join("")
    : `<li><div class="meta">No columns yet.</div></li>`;
}

function currentDocsRow() {
  return (state.sheet?.rows || []).find((r) => r.id === state.docsRowId) || null;
}

function renderJobLinked() {
  const row = currentDocsRow();
  const el = $("jobLinked");
  if (!el) return;
  if (!row?.site) {
    el.textContent = "No job linked — user-visible files will appear on a job once you link one.";
    return;
  }
  el.innerHTML = `Linked to <a href="/?highlight=${row.site.id}">${escapeHtml(jobLabel(row.site))}</a>
    · <button type="button" class="btn btn-sm" id="btnUnlinkJob">Unlink</button>`;
  $("btnUnlinkJob")?.addEventListener("click", async () => {
    await api(`/api/comms/rows/${row.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_site: true }),
    });
    await loadSheet(state.sheet.id);
    await refreshDocsDialog();
  });
}

async function refreshDocsDialog() {
  const row = currentDocsRow();
  if (!row) return;
  const docs = await api(`/api/comms/rows/${row.id}/documents`);
  $("docsDialogTitle").textContent = `Files · ${row.section || "Activity"}`;
  renderJobLinked();
  $("commsDocList").innerHTML = docs.length
    ? docs
        .map(
          (d) => `<li>
            <div class="top">
              <span>${escapeHtml(d.visibility === "users" ? "Visible to users" : "Comms only")}</span>
              <button type="button" class="btn btn-sm" data-vis="${d.id}" data-next="${
                d.visibility === "users" ? "comms" : "users"
              }">${d.visibility === "users" ? "Make comms-only" : "Make visible to users"}</button>
              <button type="button" class="btn btn-danger btn-sm" data-del-doc="${d.id}">Delete</button>
            </div>
            <p><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a></p>
            ${d.description ? `<p class="meta">${escapeHtml(d.description)}</p>` : ""}
          </li>`
        )
        .join("")
    : `<li><p class="meta">No files on this row yet.</p></li>`;
}

async function openDocs(rowId) {
  state.docsRowId = rowId;
  $("jobSearch").value = "";
  $("jobResults").hidden = true;
  $("commsDocFile").value = "";
  $("commsDocDesc").value = "";
  $("commsDocVis").value = "comms";
  $("commsDocStatus").textContent = "";
  await refreshDocsDialog();
  $("docsDialog").showModal();
}

async function searchJobs(q) {
  const rows = await api(`/api/comms/sites${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const box = $("jobResults");
  if (!rows.length) {
    box.hidden = false;
    box.innerHTML = `<li class="hint">No matching jobs.</li>`;
    return;
  }
  box.hidden = false;
  box.innerHTML = rows
    .map(
      (s) => `<li>
        <button type="button" data-link-site="${s.id}">
          ${escapeHtml(s.road_name || "")} <span class="mono">${escapeHtml(s.site_number || "")}</span>
          ${s.program ? `<span class="hint">${escapeHtml(s.program)}</span>` : ""}
        </button>
      </li>`
    )
    .join("");
}

async function init() {
  await injectChrome({ active: "/comms" });
  await loadSheets();

  $("sheetTabs")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-sheet]");
    if (!btn) return;
    await loadSheet(Number(btn.dataset.sheet));
  });

  on("commsSearch", "input", () => {
    state.search = $("commsSearch").value;
    renderTable();
  });

  on("btnAddSheet", "click", async () => {
    const title = await promptDialog("New planner tab name:", "New planner");
    if (!title) return;
    const sheet = await api("/api/comms/sheets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    await loadSheets(sheet.id);
  });

  on("btnRenameSheet", "click", async () => {
    if (!state.sheet) return;
    const title = await promptDialog("Rename this tab:", state.sheet.title);
    if (!title) return;
    await api(`/api/comms/sheets/${state.sheet.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    await loadSheets(state.sheet.id);
  });

  on("btnDeleteSheet", "click", async () => {
    if (!state.sheet) return;
    if (!await confirmDialog(`Remove the “${state.sheet.title}” tab and all of its rows?`)) return;
    await api(`/api/comms/sheets/${state.sheet.id}`, { method: "DELETE" });
    state.sheet = null;
    await loadSheets();
  });

  on("btnAddRow", "click", async () => {
    if (!state.sheet) return;
    await api(`/api/comms/sheets/${state.sheet.id}/rows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: {}, created_by: userName() }),
    });
    await loadSheet(state.sheet.id);
  });

  on("btnColumns", "click", () => {
    renderColumnList();
    $("colName").value = "";
    $("colOptions").value = "";
    $("colType").value = "text";
    $("colOptionsWrap").hidden = true;
    $("columnsDialog").showModal();
  });

  on("colType", "change", () => {
    $("colOptionsWrap").hidden = $("colType").value !== "select";
  });

  on("btnAddColumn", "click", async () => {
    const name = $("colName").value.trim();
    if (!name) {
      await alertDialog("Column name is required");
      return;
    }
    const field_type = $("colType").value;
    const options =
      field_type === "select"
        ? $("colOptions").value.split(",").map((s) => s.trim()).filter(Boolean)
        : null;
    await api(`/api/comms/sheets/${state.sheet.id}/columns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, field_type, options, created_by: userName() }),
    });
    await loadSheet(state.sheet.id);
    renderColumnList();
    $("colName").value = "";
  });

  $("columnsDialog")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-col]");
    if (!btn) return;
    if (!await confirmDialog("Remove this column from every row on this tab?")) return;
    await api(`/api/comms/columns/${btn.dataset.delCol}`, { method: "DELETE" });
    await loadSheet(state.sheet.id);
    renderColumnList();
  });

  $("commsTableWrap")?.addEventListener("change", async (ev) => {
    const field = ev.target.dataset.field;
    const tr = ev.target.closest("tr[data-row]");
    if (!field || !tr) return;
    const value = ev.target.type === "checkbox" ? (ev.target.checked ? "Yes" : "No") : ev.target.value;
    try {
      await saveCell(Number(tr.dataset.row), field, value);
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not save cell"));
    }
  });

  $("commsTableWrap")?.addEventListener("click", async (ev) => {
    const docs = ev.target.closest("[data-docs]");
    if (docs) {
      await openDocs(Number(docs.dataset.docs));
      return;
    }
    const del = ev.target.closest("[data-del-row]");
    if (del) {
      if (!await confirmDialog("Delete this planner row?")) return;
      await api(`/api/comms/rows/${del.dataset.delRow}`, { method: "DELETE" });
      await loadSheet(state.sheet.id);
    }
  });

  document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => $(btn.dataset.closeDialog)?.close());
  });

  on("jobSearch", "input", () => {
    clearTimeout(state.jobTimer);
    const q = $("jobSearch").value.trim();
    state.jobTimer = setTimeout(() => {
      searchJobs(q).catch((e) => alertDialog(errorMessage(e, "Could not search jobs")));
    }, 220);
  });

  $("jobResults")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-link-site]");
    if (!btn || !state.docsRowId) return;
    await api(`/api/comms/rows/${state.docsRowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id: Number(btn.dataset.linkSite) }),
    });
    $("jobResults").hidden = true;
    $("jobSearch").value = "";
    await loadSheet(state.sheet.id);
    await refreshDocsDialog();
  });

  on("btnUploadCommsDoc", "click", async () => {
    const row = currentDocsRow();
    const files = [...($("commsDocFile")?.files || [])].filter((f) => f && f.size);
    if (!row) return;
    if (!files.length) {
      await alertDialog("Choose one or more files first");
      return;
    }
    const visibility = $("commsDocVis").value;
    const description = $("commsDocDesc").value.trim() || null;
    const status = $("commsDocStatus");
    const errors = [];
    for (let i = 0; i < files.length; i += 1) {
      const file = files[i];
      status.textContent = `${i + 1}/${files.length} · ${file.name}`;
      try {
        await uploadFileChunked(file, {
          beginUrl: `/api/comms/rows/${row.id}/documents/session`,
          chunkUrl: (id, idx) =>
            `/api/comms/rows/${row.id}/documents/session/${encodeURIComponent(id)}/chunk/${idx}`,
          commitUrl: (id) =>
            `/api/comms/rows/${row.id}/documents/session/${encodeURIComponent(id)}/commit`,
          beginBody: { category: "correspondence", description, uploaded_by: userName(), visibility },
        });
      } catch (err) {
        errors.push(`${file.name}: ${errorMessage(err, "Upload failed")}`);
      }
    }
    $("commsDocFile").value = "";
    await loadSheet(state.sheet.id);
    await refreshDocsDialog();
    if (errors.length) {
      status.textContent = `${files.length - errors.length} uploaded · ${errors.length} failed`;
      await alertDialog(errors.join("\n"));
      return;
    }
    status.textContent = files.length === 1 ? "Uploaded." : `Uploaded ${files.length} files.`;
  });

  $("commsDocList")?.addEventListener("click", async (ev) => {
    const vis = ev.target.closest("[data-vis]");
    if (vis) {
      await api(`/api/documents/${vis.dataset.vis}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility: vis.dataset.next }),
      });
      await refreshDocsDialog();
      return;
    }
    const del = ev.target.closest("[data-del-doc]");
    if (del) {
      if (!await confirmDialog("Delete this file?")) return;
      await api(`/api/documents/${del.dataset.delDoc}`, { method: "DELETE" });
      await loadSheet(state.sheet.id);
      await refreshDocsDialog();
    }
  });

  onLiveSitesChanged(() => {
    if (state.sheet) loadSheet(state.sheet.id).catch(() => {});
  });
}

init().catch((e) => {
  showPageError("commsTableWrap", e, "Could not load comms planner");
});
