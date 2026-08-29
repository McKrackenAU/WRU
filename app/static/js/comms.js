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

const JOB_FILTER_KEY = "job";
const BLANK = "(Blank)";
const WP_TONES = 8;

const state = {
  sheets: [],
  sheet: null,
  search: "",
  docsRowId: null,
  jobTimer: null,
  filters: {},
  knownFilterValues: {},
  filterSheetId: null,
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
  if (!site) return "Link";
  const road = (site.road_name || "Site").trim();
  const no = (site.site_number || "").trim();
  return no ? `${road} · ${no}` : road;
}

function workpackColumn() {
  return (state.sheet?.columns || []).find(
    (c) => c.field_key === "workpack" || /work\s*pack/i.test(c.name || "")
  );
}

function rowValue(row, key) {
  if (key === JOB_FILTER_KEY) return row.site ? "Linked" : "Not linked";
  const raw = (row.values || {})[key];
  if (raw == null || String(raw).trim() === "") return BLANK;
  return String(raw);
}

function uniqueValues(key) {
  const set = new Set();
  for (const row of state.sheet?.rows || []) set.add(rowValue(row, key));
  return [...set].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
}

function filterableColumns() {
  const cols = state.sheet?.columns || [];
  const ranked = [{ key: JOB_FILTER_KEY, name: "Job", rank: 0 }];
  for (const col of cols) {
    if (col.field_type === "date" || col.field_type === "number") continue;
    const values = uniqueValues(col.field_key);
    const isWorkpack = col.field_key === "workpack" || /work\s*pack/i.test(col.name || "");
    const isSelect = col.field_type === "select";
    const isPlace = /government|council|lga|suburb|crew/i.test(`${col.field_key} ${col.name}`);
    if (!isWorkpack && !isSelect && !isPlace && (values.length < 2 || values.length > 24)) continue;
    ranked.push({
      key: col.field_key,
      name: col.name,
      rank: isWorkpack ? 1 : isSelect ? 2 : isPlace ? 3 : 10,
    });
  }
  return ranked.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name)).slice(0, 6);
}

function syncFilters() {
  const sheetId = state.sheet?.id ?? null;
  if (state.filterSheetId !== sheetId) {
    state.filters = {};
    state.knownFilterValues = {};
    state.filterSheetId = sheetId;
  }
  for (const col of filterableColumns()) {
    const values = uniqueValues(col.key);
    const known = state.knownFilterValues[col.key] || new Set();
    if (!state.filters[col.key]) {
      state.filters[col.key] = new Set(values);
    } else {
      for (const value of values) {
        if (!known.has(value)) state.filters[col.key].add(value);
      }
      for (const value of [...state.filters[col.key]]) {
        if (!values.includes(value)) state.filters[col.key].delete(value);
      }
    }
    state.knownFilterValues[col.key] = new Set(values);
  }
}

function workpackTone(value) {
  const s = String(value || "");
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) hash = (hash * 33 + s.charCodeAt(i)) >>> 0;
  return hash % WP_TONES;
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
  syncFilters();
  const rows = state.sheet?.rows || [];
  const q = state.search.trim().toLowerCase();
  return rows.filter((row) => {
    for (const col of filterableColumns()) {
      const allowed = state.filters[col.key];
      if (allowed && !allowed.has(rowValue(row, col.key))) return false;
    }
    if (!q) return true;
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

function setFilterDropOpen(drop, open) {
  if (!drop) return;
  drop.classList.toggle("is-open", open);
  const btn = drop.querySelector(".filter-drop-btn");
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  const panel = drop.querySelector(".filter-drop-panel");
  if (panel) {
    panel.style.left = "0";
    panel.style.right = "auto";
    if (open) {
      requestAnimationFrame(() => {
        const rect = panel.getBoundingClientRect();
        if (rect.right > window.innerWidth - 8) {
          panel.style.left = "auto";
          panel.style.right = "0";
        }
      });
    }
  }
}

function closeFilterDrops(except) {
  document.querySelectorAll("#commsFilters .filter-drop.is-open").forEach((drop) => {
    if (drop !== except) setFilterDropOpen(drop, false);
  });
}

function cssKey(key) {
  return typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : String(key).replace(/"/g, '\\"');
}

function syncFilterDropLabels() {
  const root = $("commsFilters");
  if (!root) return;
  for (const col of filterableColumns()) {
    const values = uniqueValues(col.key);
    const selected = state.filters[col.key] || new Set();
    const meta = root.querySelector(`[data-drop-meta="${cssKey(col.key)}"]`);
    const btn = root.querySelector(`[data-drop="${cssKey(col.key)}"] .filter-drop-btn`);
    const n = selected.size;
    const total = values.length;
    if (meta) {
      if (!total) meta.textContent = "";
      else if (n === 0) meta.textContent = "none";
      else if (n === total) meta.textContent = "all";
      else meta.textContent = `${n}/${total}`;
    }
    if (btn) btn.classList.toggle("is-filtered", Boolean(total) && n !== total);
  }
}

function renderFilters() {
  const host = $("commsFilters");
  if (!host) return;
  if (!state.sheet) {
    host.innerHTML = "";
    return;
  }
  syncFilters();
  const cols = filterableColumns();
  host.innerHTML = cols
    .map((col) => {
      const values = uniqueValues(col.key);
      const selected = state.filters[col.key] || new Set();
      return `<div class="filter-drop" data-drop="${escapeHtml(col.key)}">
        <button type="button" class="filter-drop-btn" aria-expanded="false" aria-haspopup="true">
          <span class="filter-drop-label">${escapeHtml(col.name)}</span>
          <span class="filter-drop-meta" data-drop-meta="${escapeHtml(col.key)}"></span>
        </button>
        <div class="filter-drop-panel" role="group" aria-label="${escapeHtml(col.name)}">
          <div class="filter-drop-tools">
            <button type="button" class="filter-drop-tool" data-drop-select="all" data-drop-key="${escapeHtml(col.key)}">All</button>
            <button type="button" class="filter-drop-tool" data-drop-select="none" data-drop-key="${escapeHtml(col.key)}">None</button>
          </div>
          <div class="filter-drop-col">
            ${values
              .map(
                (value) => `<label class="lists-check">
                  <input type="checkbox" data-filter-key="${escapeHtml(col.key)}" value="${escapeHtml(value)}" ${
                    selected.has(value) ? "checked" : ""
                  } />
                  <span>${escapeHtml(value)}</span>
                </label>`
              )
              .join("")}
          </div>
        </div>
      </div>`;
    })
    .join("");
  syncFilterDropLabels();
}

function jobCell(row) {
  const files = Number(row.document_count || 0);
  if (row.site) {
    return `<a class="comms-job-name" href="/?highlight=${row.site.id}">${escapeHtml(jobLabel(row.site))}</a>
      <button type="button" class="comms-job-files" data-docs="${row.id}" title="Files and job link">${files}</button>`;
  }
  return `<button type="button" class="comms-job-link-btn" data-docs="${row.id}">Link</button>`;
}

function sortedRows(rows) {
  const wp = workpackColumn();
  if (!wp) return rows;
  return [...rows]
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const cmp = rowValue(a.row, wp.field_key).localeCompare(rowValue(b.row, wp.field_key), undefined, {
        numeric: true,
        sensitivity: "base",
      });
      return cmp || a.index - b.index;
    })
    .map((item) => item.row);
}

function renderTable({ refreshFilters = false } = {}) {
  const wrap = $("commsTableWrap");
  if (!wrap || !state.sheet) {
    if (wrap) wrap.innerHTML = `<p class="hint">No planner tab selected.</p>`;
    if (refreshFilters) renderFilters();
    return;
  }
  const cols = state.sheet.columns || [];
  const wp = workpackColumn();
  const rows = sortedRows(filteredRows());
  const total = (state.sheet.rows || []).length;
  $("commsCount").textContent =
    rows.length === total ? `${rows.length} row${rows.length === 1 ? "" : "s"}` : `${rows.length} of ${total}`;
  if (refreshFilters) renderFilters();
  else syncFilterDropLabels();
  if (!cols.length && !total) {
    wrap.innerHTML = `<p class="hint">No columns yet. Use Columns to add fields, then Add row.</p>`;
    return;
  }
  const colSpan = cols.length + 3;
  let lastGroup = null;
  const body = [];
  if (!rows.length) {
    body.push(`<tr><td class="empty" colspan="${colSpan}">No rows match these filters.</td></tr>`);
  } else {
    for (const row of rows) {
      const pack = wp ? rowValue(row, wp.field_key) : "";
      const tone = wp ? workpackTone(pack) : "";
      if (wp && pack !== lastGroup) {
        lastGroup = pack;
        const count = rows.filter((r) => rowValue(r, wp.field_key) === pack).length;
        body.push(`<tr class="comms-group comms-wp-${tone}">
          <td colspan="${colSpan}">
            <span class="comms-group-label">${escapeHtml(pack)}</span>
            <span class="hint">${count}</span>
          </td>
        </tr>`);
      }
      body.push(`<tr data-row="${row.id}" class="${wp ? `comms-wp-${tone}` : ""}">
        <td class="comms-sticky comms-job">${jobCell(row)}</td>
        ${cols
          .map((c) => {
            const isWp = wp && c.field_key === wp.field_key;
            return `<td class="comms-cell${isWp ? " comms-workpack-cell" : ""}">${cellInput(
              c,
              (row.values || {})[c.field_key]
            )}</td>`;
          })
          .join("")}
        <td>
          <button type="button" class="btn btn-sm" data-docs="${row.id}">${
            row.document_count || 0
          }</button>
        </td>
        <td><button type="button" class="btn btn-danger btn-sm" data-del-row="${row.id}">Delete</button></td>
      </tr>`);
    }
  }
  wrap.innerHTML = `
    <table class="data-table comms-table">
      <thead>
        <tr>
          <th class="comms-sticky">Job</th>
          ${cols.map((c) => `<th title="${escapeHtml(c.field_key)}">${escapeHtml(c.name)}</th>`).join("")}
          <th>Files</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${body.join("")}</tbody>
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
    renderTable({ refreshFilters: true });
  }
}

async function loadSheet(id) {
  state.sheet = await api(`/api/comms/sheets/${id}`);
  setSheetUrl(id);
  renderTabs();
  renderTable({ refreshFilters: true });
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

  document.addEventListener("click", (ev) => {
    const host = $("commsFilters");
    if (!host) return;
    const selectBtn = ev.target.closest("[data-drop-select]");
    if (selectBtn && host.contains(selectBtn)) {
      const key = selectBtn.dataset.dropKey;
      const values = uniqueValues(key);
      state.filters[key] = selectBtn.dataset.dropSelect === "all" ? new Set(values) : new Set();
      host.querySelectorAll(`input[data-filter-key="${cssKey(key)}"]`).forEach((box) => {
        box.checked = selectBtn.dataset.dropSelect === "all";
      });
      renderTable();
      return;
    }
    const btn = ev.target.closest("#commsFilters .filter-drop-btn");
    if (btn) {
      const drop = btn.closest(".filter-drop");
      const open = !drop.classList.contains("is-open");
      closeFilterDrops(drop);
      setFilterDropOpen(drop, open);
      return;
    }
    if (!ev.target.closest("#commsFilters .filter-drop")) closeFilterDrops();
  });

  $("commsFilters")?.addEventListener("change", (ev) => {
    const box = ev.target.closest("input[data-filter-key]");
    if (!box) return;
    const key = box.dataset.filterKey;
    if (!state.filters[key]) state.filters[key] = new Set();
    if (box.checked) state.filters[key].add(box.value);
    else state.filters[key].delete(box.value);
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
      const row = (state.sheet?.rows || []).find((r) => r.id === Number(tr.dataset.row));
      if (row) row.values = { ...(row.values || {}), [field]: value };
      const wp = workpackColumn();
      if (wp && field === wp.field_key) renderTable({ refreshFilters: true });
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
