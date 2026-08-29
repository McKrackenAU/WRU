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
const COLOR_PALETTE = ["#2fbf78", "#5aa0d6", "#a78bfa", "#fb7185", "#fbbf24", "#2dd4bf", "#fb923c", "#94a3b8", "#f472b6", "#38bdf8"];

const DRAWER_TAB_RULES = [
  { id: "notes", label: "Notes", test: /(^|_)(notes|other_details|scoping|comment)|dtp.comment/i },
  { id: "comms", label: "Comms", test: /comms|stakeholder|notification|distribution|dtp|cecp|website|phonecall|mail|artwork|pcr|invoice|proof|sensitive|noise|tgs.received|letter|published|detour.map|maps.generated/i },
  { id: "works", label: "Works", test: /moa|works_start|work_end|start_date|finish_date|day.?night|shift|disruption|delay|interface|duration|^crew$|crew /i },
  { id: "overview", label: "Overview", test: /workpack|structure|location|road|street|suburb|council|lga|government|site.number|asset.vision/i },
];

const state = {
  sheets: [],
  sheet: null,
  search: "",
  openRowId: null,
  drawerTab: "overview",
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

function rowIdFromUrl() {
  const raw = new URLSearchParams(location.search).get("row");
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function setSheetUrl(id, rowId) {
  const url = new URL(location.href);
  if (id) url.searchParams.set("sheet", String(id));
  else url.searchParams.delete("sheet");
  if (rowId) url.searchParams.set("row", String(rowId));
  else url.searchParams.delete("row");
  history.replaceState(null, "", url);
}

function cssKey(key) {
  return typeof CSS !== "undefined" && CSS.escape ? CSS.escape(key) : String(key).replace(/"/g, '\\"');
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
      .map((o) => `<option value="${escapeHtml(o)}" ${o === v ? "selected" : ""}>${escapeHtml(o || "—")}</option>`)
      .join("")}</select>`;
  }
  const type = col.field_type === "number" ? "number" : col.field_type === "date" ? "date" : "text";
  const area = col.field_type === "text" && (v.length > 80 || /detail|note|comment/i.test(col.field_key + col.name));
  if (area) {
    return `<textarea data-field="${escapeHtml(col.field_key)}" rows="3">${escapeHtml(v)}</textarea>`;
  }
  return `<input type="${type}" data-field="${escapeHtml(col.field_key)}" value="${escapeHtml(v)}" />`;
}

function jobLabel(site) {
  if (!site) return "";
  const road = (site.road_name || "Site").trim();
  const no = (site.site_number || "").trim();
  return no ? `${road} · ${no}` : road;
}

function findColumn(...tests) {
  return (state.sheet?.columns || []).find((c) => tests.some((t) => t.test(c.field_key) || t.test(c.name || "")));
}

function workpackColumn() {
  return findColumn(/work\s*pack/i);
}

function siteNumberColumn() {
  return findColumn(/^site_number$/i, /site number/i);
}

function statusColumn() {
  return findColumn(/comms_required/i, /comms required/i, /comms_status/i, /level_of_disruption/i);
}

function groupColumn() {
  return (
    workpackColumn() ||
    findColumn(/^suburb$/i) ||
    findColumn(/^crew$/i) ||
    findColumn(/council|lga|local_government/i) ||
    siteNumberColumn() ||
    findColumn(/location/i, /road/i)
  );
}

function listTitle(row) {
  if (row.site) return jobLabel(row.site);
  const loc = findColumn(/^location$/i, /road_street_name/i, /road \/ street/i, /^road$/i, /street/i);
  const fromValues = loc ? fmtCell((row.values || {})[loc.field_key]) : "";
  return fromValues || row.section || "Unlinked";
}

function secondaryColumn() {
  return workpackColumn() || siteNumberColumn();
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
    const isWorkpack = /work\s*pack/i.test(`${col.field_key} ${col.name}`);
    const isSelect = col.field_type === "select";
    const isPlace = /government|council|lga|suburb|crew|site.number/i.test(`${col.field_key} ${col.name}`);
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
    if (!state.filters[col.key]) state.filters[col.key] = new Set(values);
    else {
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
    const hay = [row.section, row.site?.road_name, row.site?.site_number, row.site?.moa_number, ...Object.values(row.values || {})]
      .filter((v) => v != null && v !== "")
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

function groupKey(row) {
  const col = groupColumn();
  return col ? rowValue(row, col.field_key) : BLANK;
}

function autoColor(value) {
  const s = String(value || "");
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) hash = (hash * 33 + s.charCodeAt(i)) >>> 0;
  return COLOR_PALETTE[hash % COLOR_PALETTE.length];
}

function groupColor(value) {
  const colors = state.sheet?.settings?.colors || {};
  return colors[value] || autoColor(value);
}

function drawerTabs() {
  const cols = state.sheet?.columns || [];
  const buckets = { overview: [], works: [], comms: [], notes: [], more: [] };
  for (const col of cols) {
    const hay = `${col.field_key} ${col.name}`;
    const hit = DRAWER_TAB_RULES.find((rule) => rule.test.test(hay));
    buckets[hit?.id || "more"].push(col);
  }
  const tabs = [
    { id: "overview", label: "Overview", columns: [...buckets.overview, ...buckets.more] },
    { id: "works", label: "Works", columns: buckets.works },
    { id: "comms", label: "Comms", columns: buckets.comms },
    { id: "notes", label: "Notes", columns: buckets.notes },
    { id: "job", label: "Job & files", columns: [] },
  ];
  return tabs.filter((tab) => tab.id === "overview" || tab.id === "job" || tab.columns.length);
}

function currentRow() {
  return (state.sheet?.rows || []).find((r) => r.id === state.openRowId) || null;
}

function renderSheetTabs() {
  const wrap = $("sheetTabs");
  if (!wrap) return;
  wrap.innerHTML = state.sheets
    .map(
      (s) =>
        `<button type="button" data-sheet="${s.id}" class="${state.sheet?.id === s.id ? "active" : ""}" role="tab" aria-selected="${
          state.sheet?.id === s.id
        }">${escapeHtml(s.title)}</button>`
    )
    .join("");
}

function setFilterDropOpen(drop, open) {
  if (!drop) return;
  drop.classList.toggle("is-open", open);
  drop.querySelector(".filter-drop-btn")?.setAttribute("aria-expanded", open ? "true" : "false");
}

function closeFilterDrops(except) {
  document.querySelectorAll("#commsFilters .filter-drop.is-open").forEach((drop) => {
    if (drop !== except) setFilterDropOpen(drop, false);
  });
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
    if (meta) {
      if (!values.length) meta.textContent = "";
      else if (n === 0) meta.textContent = "none";
      else if (n === values.length) meta.textContent = "all";
      else meta.textContent = `${n}/${values.length}`;
    }
    if (btn) btn.classList.toggle("is-filtered", Boolean(values.length) && n !== values.length);
  }
}

function renderFilters() {
  const host = $("commsFilters");
  if (!host || !state.sheet) {
    if (host) host.innerHTML = "";
    return;
  }
  syncFilters();
  host.innerHTML = filterableColumns()
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

function colorPicker(value) {
  const current = groupColor(value);
  const custom = /^#[0-9a-fA-F]{6}$/.test(current) ? current : "#2fbf78";
  return `<div class="comms-color-pop" hidden>
    <p class="comms-color-pop-label">Group colour</p>
    <div class="comms-color-grid">
      ${COLOR_PALETTE.map(
        (hex) =>
          `<button type="button" class="comms-color-choice ${hex === current ? "is-on" : ""}" data-color="${hex}" data-group="${escapeHtml(
            value
          )}" style="--swatch:${hex}" aria-label="Use ${hex}"></button>`
      ).join("")}
    </div>
    <div class="comms-color-pop-foot">
      <label class="comms-color-custom">Custom
        <input type="color" data-color-custom data-group="${escapeHtml(value)}" value="${escapeHtml(custom)}" />
      </label>
      <button type="button" class="comms-color-reset" data-color="" data-group="${escapeHtml(value)}">Auto</button>
    </div>
  </div>`;
}

function renderTable({ refreshFilters = false } = {}) {
  const wrap = $("commsTableWrap");
  if (!wrap || !state.sheet) {
    if (wrap) wrap.innerHTML = `<p class="hint">No planner tab selected.</p>`;
    if (refreshFilters) renderFilters();
    return;
  }
  const secondary = secondaryColumn();
  const status = statusColumn();
  const rows = filteredRows()
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const cmp = groupKey(a.row).localeCompare(groupKey(b.row), undefined, { numeric: true, sensitivity: "base" });
      return cmp || a.index - b.index;
    })
    .map((item) => item.row);
  const total = (state.sheet.rows || []).length;
  $("commsCount").textContent = rows.length === total ? `${rows.length} row${rows.length === 1 ? "" : "s"}` : `${rows.length} of ${total}`;
  if (refreshFilters) renderFilters();
  else syncFilterDropLabels();

  if (!total) {
    wrap.innerHTML = `<p class="hint">No rows yet. Use Add row, then open a row to fill it in.</p>`;
    return;
  }

  const secondaryLabel = secondary ? secondary.name : "Group";
  let last = null;
  const body = [];
  if (!rows.length) {
    body.push(`<tr><td class="empty" colspan="5">No rows match these filters.</td></tr>`);
  } else {
    for (const row of rows) {
      const group = groupKey(row);
      const color = groupColor(group);
      if (group !== last) {
        last = group;
        const count = rows.filter((r) => groupKey(r) === group).length;
        body.push(`<tr class="comms-group" style="--comms-wp:${color}">
          <td colspan="5">
            <div class="comms-group-title">
              <button type="button" class="comms-swatch" data-color-group="${escapeHtml(group)}" style="--swatch:${color}" title="Set group colour" aria-label="Set colour for ${escapeHtml(group)}"></button>
              <strong>${escapeHtml(group)}</strong>
              <span class="hint">${count}</span>
            </div>
            ${colorPicker(group)}
          </td>
        </tr>`);
      }
      const extra = secondary ? fmtCell((row.values || {})[secondary.field_key]) : "";
      const statusVal = status ? fmtCell((row.values || {})[status.field_key]) : "";
      body.push(`<tr class="comms-list-row ${state.openRowId === row.id ? "is-open" : ""}" data-open-row="${row.id}" style="--comms-wp:${color}">
        <td class="comms-job-col">
          <span class="comms-row-swatch" style="--swatch:${color}"></span>
          <div>
            <span class="comms-job-title">${escapeHtml(listTitle(row))}</span>
            ${row.site ? "" : `<span class="comms-list-sub">Not linked</span>`}
          </div>
        </td>
        <td>${escapeHtml(extra || "—")}</td>
        <td>${escapeHtml(statusVal || "—")}</td>
        <td class="mono">${row.document_count || 0}</td>
        <td><button type="button" class="btn btn-sm" data-open-row="${row.id}">Open</button></td>
      </tr>`);
    }
  }

  wrap.innerHTML = `
    <table class="data-table comms-table comms-list-table">
      <thead>
        <tr>
          <th>Job</th>
          <th>${escapeHtml(secondaryLabel)}</th>
          <th>${escapeHtml(status ? status.name : "Status")}</th>
          <th>Files</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${body.join("")}</tbody>
    </table>
  `;
}

function openDrawer() {
  const d = $("commsDrawer");
  if (!d) return;
  d.hidden = false;
  d.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
}

function closeDrawer() {
  const d = $("commsDrawer");
  if (!d) return;
  d.hidden = true;
  d.setAttribute("aria-hidden", "true");
  document.body.classList.remove("drawer-open");
  state.openRowId = null;
  if (state.sheet) setSheetUrl(state.sheet.id);
  renderTable();
}

function renderDrawer() {
  const row = currentRow();
  if (!row || !state.sheet) {
    closeDrawer();
    return;
  }
  const tabs = drawerTabs();
  if (!tabs.some((t) => t.id === state.drawerTab)) state.drawerTab = tabs[0].id;
  const group = groupKey(row);
  $("commsDrawerTitle").textContent = listTitle(row);
  $("commsDrawerKicker").textContent = `${state.sheet.title}${group && group !== BLANK ? ` · ${group}` : ""}`;
  $("commsDrawerTabs").innerHTML = tabs
    .map(
      (tab) =>
        `<button type="button" class="drawer-tab ${state.drawerTab === tab.id ? "active" : ""}" data-drawer-tab="${tab.id}">${escapeHtml(
          tab.label
        )}</button>`
    )
    .join("");

  const active = tabs.find((t) => t.id === state.drawerTab) || tabs[0];
  if (active.id === "job") {
    $("commsDrawerBody").innerHTML = `
      <section class="tab-panel active">
        <div class="form-section">
          <h3>Linked job</h3>
          <p class="hint">User-visible files appear on the job’s Documents tab once a site is linked.</p>
          <p id="jobLinked"></p>
          <div class="form-grid">
            <label class="full">Find a job
              <input id="jobSearch" type="search" placeholder="Search road, site, MoA…" autocomplete="off" />
            </label>
          </div>
          <ul class="comms-job-results" id="jobResults" hidden></ul>
        </div>
        <div class="form-section">
          <h3>Files</h3>
          <div class="form-grid">
            <label class="full">File<input id="commsDocFile" type="file" multiple /></label>
            <label>Visibility
              <select id="commsDocVis">
                <option value="comms">Comms only</option>
                <option value="users">Visible to users (job docs)</option>
              </select>
            </label>
            <label>Description<input id="commsDocDesc" maxlength="255" placeholder="Works notification, letter drop…" /></label>
          </div>
          <div class="toolbar" style="margin-top:0.75rem">
            <button type="button" class="btn btn-primary" id="btnUploadCommsDoc">Upload</button>
            <span class="hint" id="commsDocStatus"></span>
          </div>
          <ul class="event-list" id="commsDocList"></ul>
        </div>
      </section>
    `;
    renderJobLinked();
    refreshDocsList().catch(() => {});
    bindDrawerJobHandlers();
  } else {
    $("commsDrawerBody").innerHTML = `
      <section class="tab-panel active">
        <div class="form-section">
          <h3>${escapeHtml(active.label)}</h3>
          <div class="form-grid" id="commsFieldGrid">
            ${active.columns
              .map((col) => `<label class="full">${escapeHtml(col.name)}${cellInput(col, (row.values || {})[col.field_key])}</label>`)
              .join("")}
          </div>
        </div>
      </section>
    `;
  }
  openDrawer();
}

function renderJobLinked() {
  const row = currentRow();
  const el = $("jobLinked");
  if (!el || !row) return;
  if (!row.site) {
    el.textContent = "No job linked yet.";
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
    await loadSheet(state.sheet.id, { keepRow: row.id });
  });
}

async function refreshDocsList() {
  const row = currentRow();
  if (!row || !$("commsDocList")) return;
  const docs = await api(`/api/comms/rows/${row.id}/documents`);
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

function bindDrawerJobHandlers() {
  on("jobSearch", "input", () => {
    clearTimeout(state.jobTimer);
    const q = $("jobSearch").value.trim();
    state.jobTimer = setTimeout(() => {
      searchJobs(q).catch((e) => alertDialog(errorMessage(e, "Could not search jobs")));
    }, 220);
  });
}

async function searchJobs(q) {
  const rows = await api(`/api/comms/sites${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  const box = $("jobResults");
  if (!box) return;
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

async function openRow(rowId) {
  state.openRowId = rowId;
  if (state.sheet) setSheetUrl(state.sheet.id, rowId);
  renderTable();
  renderDrawer();
}

async function loadSheets(preferredId) {
  state.sheets = await api("/api/comms/sheets");
  const want = preferredId || sheetIdFromUrl() || state.sheet?.id;
  const pick = state.sheets.find((s) => s.id === want) || state.sheets[0] || null;
  if (pick) await loadSheet(pick.id, { keepRow: rowIdFromUrl() });
  else {
    state.sheet = null;
    renderSheetTabs();
    renderTable({ refreshFilters: true });
  }
}

async function loadSheet(id, { keepRow } = {}) {
  state.sheet = await api(`/api/comms/sheets/${id}`);
  const keep = keepRow || state.openRowId;
  if (keep && !(state.sheet.rows || []).some((r) => r.id === keep)) state.openRowId = null;
  else if (keep) state.openRowId = keep;
  setSheetUrl(id, state.openRowId);
  renderSheetTabs();
  renderTable({ refreshFilters: true });
  if (state.openRowId) renderDrawer();
}

async function saveCell(rowId, field, value) {
  await api(`/api/comms/rows/${rowId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values: { [field]: value } }),
  });
  const row = (state.sheet?.rows || []).find((r) => r.id === rowId);
  if (row) row.values = { ...(row.values || {}), [field]: value };
}

async function saveGroupColor(group, color) {
  const colors = { ...(state.sheet?.settings?.colors || {}) };
  if (!color) delete colors[group];
  else colors[group] = color;
  const next = await api(`/api/comms/sheets/${state.sheet.id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ settings: { colors } }),
  });
  state.sheet.settings = next.settings || { colors };
  renderTable();
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

async function init() {
  await injectChrome({ active: "/comms" });
  await loadSheets();

  $("sheetTabs")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-sheet]");
    if (!btn) return;
    closeDrawer();
    await loadSheet(Number(btn.dataset.sheet));
  });

  on("commsSearch", "input", () => {
    state.search = $("commsSearch").value;
    renderTable();
  });

  document.addEventListener("click", (ev) => {
    const host = $("commsFilters");
    if (host) {
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
    }

    const swatch = ev.target.closest("[data-color-group]");
    if (swatch && $("commsTableWrap")?.contains(swatch)) {
      ev.preventDefault();
      ev.stopPropagation();
      const pop = swatch.closest("td")?.querySelector(".comms-color-pop");
      document.querySelectorAll(".comms-color-pop").forEach((el) => {
        if (el !== pop) el.hidden = true;
      });
      if (pop) {
        const open = pop.hidden;
        pop.hidden = !open;
        if (open) {
          const r = swatch.getBoundingClientRect();
          pop.style.position = "fixed";
          pop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 230))}px`;
          pop.style.top = `${Math.min(r.bottom + 8, window.innerHeight - 220)}px`;
        }
      }
      return;
    }
    const choice = ev.target.closest("[data-color][data-group]");
    if (choice && $("commsTableWrap")?.contains(choice)) {
      ev.preventDefault();
      ev.stopPropagation();
      saveGroupColor(choice.dataset.group, choice.dataset.color).catch((e) => alertDialog(e.message));
      return;
    }
    if (!ev.target.closest(".comms-color-pop")) {
      document.querySelectorAll(".comms-color-pop").forEach((el) => {
        el.hidden = true;
      });
    }
  });

  document.addEventListener("change", (ev) => {
    const custom = ev.target.closest("[data-color-custom]");
    if (!custom || !$("commsTableWrap")?.contains(custom)) return;
    saveGroupColor(custom.dataset.group, custom.value).catch((e) => alertDialog(e.message));
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (document.querySelector("dialog[open]")) return;
    const openPop = document.querySelector(".comms-color-pop:not([hidden])");
    if (openPop) {
      openPop.hidden = true;
      return;
    }
    if (state.openRowId) closeDrawer();
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
    closeDrawer();
    await loadSheets();
  });

  on("btnAddRow", "click", async () => {
    if (!state.sheet) return;
    const created = await api(`/api/comms/sheets/${state.sheet.id}/rows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values: {}, created_by: userName() }),
    });
    await loadSheet(state.sheet.id, { keepRow: created.id });
    await openRow(created.id);
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
    const options = field_type === "select" ? $("colOptions").value.split(",").map((s) => s.trim()).filter(Boolean) : null;
    await api(`/api/comms/sheets/${state.sheet.id}/columns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, field_type, options, created_by: userName() }),
    });
    await loadSheet(state.sheet.id, { keepRow: state.openRowId });
    renderColumnList();
    $("colName").value = "";
  });

  $("columnsDialog")?.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-col]");
    if (!btn) return;
    if (!await confirmDialog("Remove this column from every row on this tab?")) return;
    await api(`/api/comms/columns/${btn.dataset.delCol}`, { method: "DELETE" });
    await loadSheet(state.sheet.id, { keepRow: state.openRowId });
    renderColumnList();
  });

  $("commsTableWrap")?.addEventListener("click", async (ev) => {
    if (ev.target.closest("[data-color-group], .comms-color-pop")) return;
    const open = ev.target.closest("[data-open-row]");
    if (open) {
      await openRow(Number(open.dataset.openRow));
    }
  });

  $("commsDrawer")?.addEventListener("click", async (ev) => {
    if (ev.target.closest("[data-close-comms-drawer]")) {
      closeDrawer();
      return;
    }
    const tab = ev.target.closest("[data-drawer-tab]");
    if (tab) {
      state.drawerTab = tab.dataset.drawerTab;
      renderDrawer();
      return;
    }
    const link = ev.target.closest("[data-link-site]");
    if (link && state.openRowId) {
      await api(`/api/comms/rows/${state.openRowId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site_id: Number(link.dataset.linkSite) }),
      });
      await loadSheet(state.sheet.id, { keepRow: state.openRowId });
      return;
    }
    const vis = ev.target.closest("[data-vis]");
    if (vis) {
      await api(`/api/documents/${vis.dataset.vis}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility: vis.dataset.next }),
      });
      await refreshDocsList();
      return;
    }
    const del = ev.target.closest("[data-del-doc]");
    if (del) {
      if (!await confirmDialog("Delete this file?")) return;
      await api(`/api/documents/${del.dataset.delDoc}`, { method: "DELETE" });
      await loadSheet(state.sheet.id, { keepRow: state.openRowId });
    }
  });

  $("commsDrawer")?.addEventListener("change", async (ev) => {
    const field = ev.target.dataset.field;
    if (!field || !state.openRowId) return;
    const value = ev.target.type === "checkbox" ? (ev.target.checked ? "Yes" : "No") : ev.target.value;
    try {
      await saveCell(state.openRowId, field, value);
      renderTable();
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not save cell"));
    }
  });

  on("btnDrawerDelete", "click", async () => {
    if (!state.openRowId) return;
    if (!await confirmDialog("Delete this planner row?")) return;
    await api(`/api/comms/rows/${state.openRowId}`, { method: "DELETE" });
    closeDrawer();
    await loadSheet(state.sheet.id);
  });

  document.querySelectorAll("[data-close-dialog]").forEach((btn) => {
    btn.addEventListener("click", () => $(btn.dataset.closeDialog)?.close());
  });

  document.body.addEventListener("click", async (ev) => {
    if (ev.target.id !== "btnUploadCommsDoc") return;
    const row = currentRow();
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
          commitUrl: (id) => `/api/comms/rows/${row.id}/documents/session/${encodeURIComponent(id)}/commit`,
          beginBody: { category: "correspondence", description, uploaded_by: userName(), visibility },
        });
      } catch (err) {
        errors.push(`${file.name}: ${errorMessage(err, "Upload failed")}`);
      }
    }
    $("commsDocFile").value = "";
    await loadSheet(state.sheet.id, { keepRow: row.id });
    if (errors.length) {
      status.textContent = `${files.length - errors.length} uploaded · ${errors.length} failed`;
      await alertDialog(errors.join("\n"));
      return;
    }
    status.textContent = files.length === 1 ? "Uploaded." : `Uploaded ${files.length} files.`;
  });

  onLiveSitesChanged(() => {
    if (state.sheet) loadSheet(state.sheet.id, { keepRow: state.openRowId }).catch(() => {});
  });
}

init().catch((e) => {
  showPageError("commsTableWrap", e, "Could not load comms planner");
});
