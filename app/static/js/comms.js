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
  view: "planner",
  search: "",
  resourceSearch: "",
  resources: [],
  openRowId: null,
  drawerTab: "overview",
  jobTimer: null,
  filters: {},
  knownFilterValues: {},
  filterSheetId: null,
  formFields: [],
  notes: [],
  jobCategories: [],
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

function viewFromUrl() {
  return new URLSearchParams(location.search).get("view") === "resources" ? "resources" : "planner";
}

function setSheetUrl(id, rowId) {
  const url = new URL(location.href);
  url.searchParams.delete("view");
  if (id) url.searchParams.set("sheet", String(id));
  else url.searchParams.delete("sheet");
  if (rowId) url.searchParams.set("row", String(rowId));
  else url.searchParams.delete("row");
  history.replaceState(null, "", url);
}

function setResourcesUrl() {
  const url = new URL(location.href);
  url.searchParams.set("view", "resources");
  url.searchParams.delete("sheet");
  url.searchParams.delete("row");
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
  const workpack = workpackColumn();
  if (workpack) return workpack;
  const candidates = [
    findColumn(/^suburb$/i),
    findColumn(/^crew$/i),
    findColumn(/council|lga|local_government/i),
    siteNumberColumn(),
    findColumn(/location/i, /road/i),
  ].filter(Boolean);
  let best = candidates[0] || null;
  let bestScore = -1;
  for (const col of candidates) {
    const values = (state.sheet?.rows || []).map((row) => rowValue(row, col.field_key));
    const filled = values.filter((v) => v && v !== BLANK);
    const unique = new Set(filled);
    if (unique.size > 24 && candidates.length > 1) continue;
    const score = filled.length + (unique.size >= 2 ? 20 : 0);
    if (score > bestScore) {
      bestScore = score;
      best = col;
    }
  }
  return best;
}

function listTitle(row) {
  const loc = findColumn(/^location$/i, /road_street_name/i, /road \/ street/i, /^road$/i, /street/i);
  const fromValues = loc ? fmtCell((row.values || {})[loc.field_key]) : "";
  if (fromValues) return fromValues;
  if (row.site) return jobLabel(row.site);
  return row.section || "Unlinked";
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
  return tabs.filter(
    (tab) => tab.id === "overview" || tab.id === "job" || tab.id === "notes" || tab.id === "comms" || tab.columns.length
  );
}

function currentRow() {
  return (state.sheet?.rows || []).find((r) => r.id === state.openRowId) || null;
}

function renderSheetTabs() {
  const wrap = $("sheetTabs");
  if (!wrap) return;
  const planner = state.sheets
    .map(
      (s) =>
        `<button type="button" data-sheet="${s.id}" class="${state.view === "planner" && state.sheet?.id === s.id ? "active" : ""}" role="tab" aria-selected="${
          state.view === "planner" && state.sheet?.id === s.id
        }">${escapeHtml(s.title)}</button>`
    )
    .join("");
  wrap.innerHTML = `${planner}<button type="button" data-view="resources" class="${
    state.view === "resources" ? "active" : ""
  }" role="tab" aria-selected="${state.view === "resources"}">Templates</button>`;
}

function setViewChrome() {
  const resources = state.view === "resources";
  const planner = $("commsPlannerChrome");
  const panel = $("commsResources");
  if (planner) planner.hidden = resources;
  if (panel) panel.hidden = !resources;
  if ($("btnRenameSheet")) $("btnRenameSheet").hidden = resources;
  if ($("btnDeleteSheet")) $("btnDeleteSheet").hidden = resources;
  if ($("btnAddResourceHeading")) $("btnAddResourceHeading").hidden = !resources;
  if ($("commsStatus")) {
    $("commsStatus").textContent = resources
      ? "Build shared headings, notes, and links that the whole comms team can use — nothing here is locked."
      : "Job plus workpack or site number stay on the list. Open a row for the full planner, or click a colour dot to code a group.";
  }
}

function filteredResourceSections() {
  const q = state.resourceSearch.trim().toLowerCase();
  if (!q) return state.resources;
  return state.resources
    .map((section) => {
      const headingHit = [section.title, section.body].some((v) => String(v || "").toLowerCase().includes(q));
      const links = (section.links || []).filter((link) =>
        [link.title, link.url, link.note].some((v) => String(v || "").toLowerCase().includes(q))
      );
      if (headingHit) return section;
      return links.length ? { ...section, links } : null;
    })
    .filter(Boolean);
}

function renderResources() {
  const host = $("commsResourceList");
  if (!host) return;
  const sections = filteredResourceSections();
  if (!state.resources.length) {
    host.innerHTML = `<p class="hint">Nothing here yet. Add a heading, then drop in notes and SharePoint (or other https) links. It is shared with every comms user.</p>`;
    return;
  }
  if (!sections.length) {
    host.innerHTML = `<p class="hint">No headings or links match that search.</p>`;
    return;
  }
  host.innerHTML = sections
    .map((section) => {
      const links = section.links || [];
      return `<article class="comms-resource-card" data-section="${section.id}">
        <header class="comms-resource-head">
          <h2>${escapeHtml(section.title)}</h2>
          <div class="toolbar">
            <button type="button" class="btn btn-sm" data-add-link="${section.id}">Add link</button>
            <button type="button" class="btn btn-sm" data-rename-section="${section.id}">Rename</button>
            <button type="button" class="btn btn-sm btn-danger" data-del-section="${section.id}">Remove</button>
          </div>
        </header>
        <label class="full comms-template-body">Notes / template text
          <textarea data-section-body="${section.id}" rows="4" placeholder="Letter wording, distribution steps, who to call…">${escapeHtml(
            section.body || ""
          )}</textarea>
        </label>
        ${
          links.length
            ? `<ul class="comms-resource-links">${links
                .map(
                  (link) => `<li>
                    <div>
                      <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.title)}</a>
                      <span class="comms-resource-url">${escapeHtml(link.url)}</span>
                      ${link.note ? `<span class="hint">${escapeHtml(link.note)}</span>` : ""}
                    </div>
                    <div class="toolbar">
                      <button type="button" class="btn btn-sm" data-edit-link="${link.id}">Edit</button>
                      <button type="button" class="btn btn-sm btn-danger" data-del-link="${link.id}">Remove</button>
                    </div>
                  </li>`
                )
                .join("")}</ul>`
            : `<p class="hint">No links under this heading yet.</p>`
        }
      </article>`;
    })
    .join("");
}

function renderFormBuilder() {
  const host = $("commsFormBuilder");
  if (!host) return;
  host.innerHTML = `<article class="comms-form-builder">
    <header class="comms-resource-head">
      <div>
        <h2>Comms form</h2>
        <p class="hint">Fields added here show on the Comms tab of every planner row — Yes/No, dropdowns, comments, and file uploads.</p>
      </div>
      <button type="button" class="btn btn-sm" id="btnAddFormField">Add field</button>
    </header>
    ${
      state.formFields.length
        ? `<ul class="comms-form-fields">${state.formFields
            .map(
              (field) => `<li>
                <div>
                  <strong>${escapeHtml(field.name)}</strong>
                  <div class="meta">${escapeHtml(field.field_type === "yesno" ? "Yes / No" : field.field_type)}${
                    field.options?.length ? ` · ${escapeHtml(field.options.join(", "))}` : ""
                  }</div>
                </div>
                <button type="button" class="btn btn-sm btn-danger" data-del-form-field="${field.id}">Remove</button>
              </li>`
            )
            .join("")}</ul>`
        : `<p class="hint">No extra Comms fields yet. Add the breakdown the team needs.</p>`
    }
  </article>`;
}

async function loadFormFields() {
  state.formFields = await api("/api/comms/form-fields");
}

async function loadResources() {
  const data = await api("/api/comms/resources");
  state.resources = data.sections || [];
  await loadFormFields();
  renderSheetTabs();
  setViewChrome();
  renderFormBuilder();
  renderResources();
}

function findResourceLink(id) {
  for (const section of state.resources) {
    const hit = (section.links || []).find((link) => link.id === id);
    if (hit) return { section, link: hit };
  }
  return null;
}

function openResourceLinkDialog({ sectionId, link } = {}) {
  $("resourceLinkDialogTitle").textContent = link ? "Edit link" : "Add link";
  $("resourceLinkSectionId").value = String(sectionId || link?.section_id || "");
  $("resourceLinkId").value = link ? String(link.id) : "";
  $("resourceLinkTitle").value = link?.title || "";
  $("resourceLinkUrl").value = link?.url || "";
  $("resourceLinkNote").value = link?.note || "";
  $("resourceLinkDialog").showModal();
  $("resourceLinkTitle").focus();
}

async function showResourcesView() {
  closeDrawer();
  state.view = "resources";
  setResourcesUrl();
  await loadResources();
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
            ${
              row.site
                ? `<span class="comms-list-sub">${escapeHtml(jobLabel(row.site))}</span>`
                : `<span class="comms-list-sub">Not linked</span>`
            }
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
          <p class="hint">Choose a category, then the job. User-visible files appear on the job’s Documents tab once linked.</p>
          <p id="jobLinked"></p>
          <div class="form-grid">
            <label>Category
              <select id="jobCategory">
                <option value="">Select a category…</option>
              </select>
            </label>
            <label>Job
              <select id="jobPick" disabled>
                <option value="">Select a job…</option>
              </select>
            </label>
            <label class="full">Or search
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
    loadJobCategories().catch(() => {});
  } else if (active.id === "notes") {
    $("commsDrawerBody").innerHTML = `
      <section class="tab-panel active">
        <div class="form-section">
          <h3>Notes log</h3>
          <ul class="comms-note-log" id="commsNoteLog"></ul>
          <label class="full comms-note-compose">Add a note
            <textarea id="commsNoteText" rows="3" placeholder="What happened, who was told, next step…"></textarea>
          </label>
          <div class="toolbar">
            <button type="button" class="btn btn-primary" id="btnAddNote">Add note</button>
          </div>
        </div>
        <div class="form-section">
          <h3>Scoping document</h3>
          ${active.columns
            .filter((col) => !/scoping/i.test(col.field_key + col.name))
            .map((col) => `<label class="full">${escapeHtml(col.name)}${cellInput(col, (row.values || {})[col.field_key])}</label>`)
            .join("")}
          <p class="hint">Upload the scoping file for this activity. It stays on this row.</p>
          <div class="form-grid">
            <label class="full">File<input id="commsScopeFile" type="file" multiple /></label>
          </div>
          <div class="toolbar" style="margin-top:0.75rem">
            <button type="button" class="btn btn-primary" id="btnUploadScope">Upload scoping doc</button>
            <span class="hint" id="commsScopeStatus"></span>
          </div>
          <ul class="event-list" id="commsScopeList"></ul>
        </div>
      </section>
    `;
    refreshNotes().catch(() => {});
    refreshDocsList({ target: "commsScopeList", category: "scoping" }).catch(() => {});
  } else if (active.id === "comms") {
    $("commsDrawerBody").innerHTML = `
      <section class="tab-panel active">
        <div class="form-section">
          <h3>Comms</h3>
          <div class="form-grid" id="commsFieldGrid">
            ${active.columns
              .map((col) => `<label class="full">${escapeHtml(col.name)}${cellInput(col, (row.values || {})[col.field_key])}</label>`)
              .join("")}
            ${state.formFields.map((field) => renderFormField(field, row)).join("")}
          </div>
          ${
            state.formFields.length
              ? ""
              : `<p class="hint">Add Yes/No, comment, or file fields on the Templates tab — they show here on every row.</p>`
          }
        </div>
      </section>
    `;
    refreshFormFileLists().catch(() => {});
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

function formatStamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function renderFormField(field, row) {
  const value = (row.form_values || {})[field.field_key] ?? "";
  if (field.field_type === "file") {
    return `<div class="full">
      <strong>${escapeHtml(field.name)}</strong>
      <div class="form-grid" style="margin-top:0.45rem">
        <label class="full">File<input type="file" multiple data-form-file="${escapeHtml(field.field_key)}" /></label>
      </div>
      <div class="toolbar" style="margin-top:0.5rem">
        <button type="button" class="btn btn-sm btn-primary" data-upload-form-file="${escapeHtml(field.field_key)}">Upload</button>
        <span class="hint" data-form-file-status="${escapeHtml(field.field_key)}"></span>
      </div>
      <ul class="event-list" data-form-file-list="${escapeHtml(field.field_key)}"></ul>
    </div>`;
  }
  if (field.field_type === "textarea") {
    return `<label class="full">${escapeHtml(field.name)}<textarea data-form-field="${escapeHtml(
      field.field_key
    )}" rows="3">${escapeHtml(String(value))}</textarea></label>`;
  }
  if (field.field_type === "select" || field.field_type === "yesno") {
    const opts = field.field_type === "yesno" ? ["", "Yes", "No"] : ["", ...(field.options || [])];
    return `<label class="full">${escapeHtml(field.name)}<select data-form-field="${escapeHtml(field.field_key)}">${opts
      .map((o) => `<option value="${escapeHtml(o)}" ${String(o) === String(value) ? "selected" : ""}>${escapeHtml(o || "—")}</option>`)
      .join("")}</select></label>`;
  }
  return `<label class="full">${escapeHtml(field.name)}<input type="text" data-form-field="${escapeHtml(
    field.field_key
  )}" value="${escapeHtml(String(value))}" /></label>`;
}

async function refreshNotes() {
  const row = currentRow();
  const host = $("commsNoteLog");
  if (!row || !host) return;
  state.notes = await api(`/api/comms/rows/${row.id}/notes`);
  host.innerHTML = state.notes.length
    ? state.notes
        .map(
          (note) => `<li>
            <div class="top">
              <span>${escapeHtml(formatStamp(note.created_at))}${note.created_by ? ` · ${escapeHtml(note.created_by)}` : ""}</span>
              <button type="button" class="btn btn-sm btn-danger" data-del-note="${note.id}">Remove</button>
            </div>
            <p>${escapeHtml(note.message)}</p>
          </li>`
        )
        .join("")
    : `<li><p class="meta">No notes yet. Add the first one below.</p></li>`;
}

async function loadJobCategories() {
  const sel = $("jobCategory");
  if (!sel) return;
  state.jobCategories = await api("/api/comms/site-categories");
  const current = currentRow()?.site?.program || "";
  const currentLower = current.trim().toLowerCase();
  sel.innerHTML = `<option value="">Select a category…</option>${state.jobCategories
    .map(
      (c) =>
        `<option value="${escapeHtml(c.name)}" ${c.name.toLowerCase() === currentLower ? "selected" : ""}>${escapeHtml(
          c.name
        )}</option>`
    )
    .join("")}`;
  if (current) await fillJobPick(current, currentRow()?.site_id);
}

async function fillJobPick(program, selectedId) {
  const sel = $("jobPick");
  if (!sel) return;
  if (!program) {
    sel.innerHTML = `<option value="">Select a job…</option>`;
    sel.disabled = true;
    return;
  }
  const jobs = await api(`/api/comms/sites?program=${encodeURIComponent(program)}`);
  sel.disabled = false;
  sel.innerHTML = `<option value="">Select a job…</option>${jobs
    .map(
      (s) =>
        `<option value="${s.id}" ${Number(selectedId) === s.id ? "selected" : ""}>${escapeHtml(s.road_name || "Site")}${
          s.site_number ? ` · ${escapeHtml(s.site_number)}` : ""
        }</option>`
    )
    .join("")}`;
}

async function refreshFormFileLists() {
  const row = currentRow();
  if (!row) return;
  const docs = await api(`/api/comms/rows/${row.id}/documents`);
  for (const field of state.formFields.filter((f) => f.field_type === "file")) {
    const host = document.querySelector(`[data-form-file-list="${cssKey(field.field_key)}"]`);
    if (!host) continue;
    const ids = formFileIds(row, field.field_key);
    const mine = docs.filter((d) => ids.includes(d.id) || (d.description || "").startsWith(`form:${field.field_key}`));
    host.innerHTML = mine.length
      ? mine
          .map(
            (d) => `<li>
              <p><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a></p>
              <button type="button" class="btn btn-sm btn-danger" data-del-doc="${d.id}">Delete</button>
            </li>`
          )
          .join("")
      : `<li><p class="meta">No files uploaded for this item yet.</p></li>`;
  }
}

function formFileIds(row, key) {
  const raw = (row.form_values || {})[key];
  if (Array.isArray(raw)) return raw.map(Number).filter(Boolean);
  return String(raw || "")
    .split(",")
    .map((s) => Number(s.trim()))
    .filter(Boolean);
}

async function uploadCommsRowFile(row, file, { category = "correspondence", description = null, visibility = "comms", onProgress } = {}) {
  return uploadFileChunked(file, {
    beginUrl: `/api/comms/rows/${row.id}/documents/session`,
    chunkUrl: (id, idx) =>
      `/api/comms/rows/${row.id}/documents/session/${encodeURIComponent(id)}/chunk/${idx}`,
    commitUrl: (id) => `/api/comms/rows/${row.id}/documents/session/${encodeURIComponent(id)}/commit`,
    beginBody: { category, description, uploaded_by: userName(), visibility },
    onProgress,
  });
}

async function refreshActiveDocs() {
  if (state.drawerTab === "notes") {
    await refreshDocsList({ target: "commsScopeList", category: "scoping" });
    return;
  }
  if (state.drawerTab === "comms") {
    await refreshFormFileLists();
    return;
  }
  await refreshDocsList();
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

async function refreshDocsList({ target = "commsDocList", category = null } = {}) {
  const row = currentRow();
  const host = $(target);
  if (!row || !host) return;
  const docs = await api(`/api/comms/rows/${row.id}/documents`);
  const list = category ? docs.filter((d) => d.category === category) : docs.filter((d) => d.category !== "scoping");
  host.innerHTML = list.length
    ? list
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
    : `<li><p class="meta">${category === "scoping" ? "No scoping document uploaded yet." : "No files on this row yet."}</p></li>`;
}

function bindDrawerJobHandlers() {
  on("jobCategory", "change", () => {
    fillJobPick($("jobCategory").value).catch((e) => alertDialog(errorMessage(e, "Could not load jobs")));
  });
  on("jobPick", "change", async () => {
    const id = Number($("jobPick").value);
    if (!id || !state.openRowId) return;
    await api(`/api/comms/rows/${state.openRowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id: id }),
    });
    await loadSheet(state.sheet.id, { keepRow: state.openRowId });
  });
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
  if (!preferredId && viewFromUrl() === "resources") {
    await showResourcesView();
    return;
  }
  const want = preferredId || sheetIdFromUrl() || state.sheet?.id;
  const pick = state.sheets.find((s) => s.id === want) || state.sheets[0] || null;
  if (pick) await loadSheet(pick.id, { keepRow: rowIdFromUrl() });
  else {
    state.sheet = null;
    state.view = "planner";
    renderSheetTabs();
    setViewChrome();
    renderTable({ refreshFilters: true });
  }
}

async function loadSheet(id, { keepRow } = {}) {
  state.view = "planner";
  state.sheet = await api(`/api/comms/sheets/${id}`);
  const keep = keepRow || state.openRowId;
  if (keep && !(state.sheet.rows || []).some((r) => r.id === keep)) state.openRowId = null;
  else if (keep) state.openRowId = keep;
  setSheetUrl(id, state.openRowId);
  renderSheetTabs();
  setViewChrome();
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

function exportColumnChoices() {
  const extras = [
    { key: "_job", name: "Job" },
    { key: "_linked_site", name: "Linked job" },
    { key: "_files", name: "Files" },
  ];
  const seen = new Map(extras.map((col) => [col.key, col]));
  for (const sheet of state.sheets) {
    const cols = state.sheet?.id === sheet.id ? state.sheet.columns || [] : sheet.columns || [];
    for (const col of cols) seen.set(col.field_key, { key: col.field_key, name: col.name });
  }
  if (state.sheet?.columns) {
    for (const col of state.sheet.columns) seen.set(col.field_key, { key: col.field_key, name: col.name });
  }
  return [...seen.values()];
}

function fillExportDialog() {
  const scope = $("exportSheetScope");
  if (scope) {
    scope.innerHTML = `<option value="current">This tab (${escapeHtml(state.sheet?.title || "current")})</option>
      <option value="all">All planner tabs</option>
      ${state.sheets
        .map((sheet) => `<option value="${sheet.id}">${escapeHtml(sheet.title)}</option>`)
        .join("")}`;
    scope.value = "current";
  }
  const cols = $("exportColumns");
  if (cols) {
    cols.innerHTML = exportColumnChoices()
      .map(
        (col) => `<label class="lists-check">
          <input type="checkbox" data-export-col="${escapeHtml(col.key)}" checked />
          <span>${escapeHtml(col.name)}</span>
        </label>`
      )
      .join("");
    cols.hidden = true;
  }
  if ($("exportRows")) $("exportRows").value = "visible";
  if ($("exportColScope")) $("exportColScope").value = "list";
}

function selectedExportSheetIds() {
  const scope = $("exportSheetScope")?.value || "current";
  if (scope === "all") return state.sheets.map((s) => s.id);
  if (scope === "current") return state.sheet?.id ? [state.sheet.id] : [];
  const id = Number(scope);
  return id ? [id] : [];
}

function selectedExportColumns() {
  const mode = $("exportColScope")?.value || "list";
  const all = exportColumnChoices();
  if (mode === "all") return all.map((c) => c.key);
  if (mode === "custom") {
    return [...document.querySelectorAll("[data-export-col]:checked")].map((box) => box.dataset.exportCol);
  }
  const keep = new Set(["_job", "_files"]);
  const secondary = secondaryColumn();
  const status = statusColumn();
  if (secondary) keep.add(secondary.field_key);
  if (status) keep.add(status.field_key);
  return all.map((c) => c.key).filter((key) => keep.has(key));
}

async function runCommsExport(format) {
  const sheetIds = selectedExportSheetIds();
  const columnKeys = selectedExportColumns();
  if (!sheetIds.length) {
    await alertDialog("Select a planner tab");
    return;
  }
  if (!columnKeys.length) {
    await alertDialog("Select at least one column");
    return;
  }
  const onlyVisible = $("exportRows")?.value === "visible";
  let rowIds = null;
  if (onlyVisible) {
    if (sheetIds.length === 1 && state.sheet && sheetIds[0] === state.sheet.id) {
      rowIds = filteredRows().map((row) => row.id);
    } else {
      await alertDialog("Visible rows only works when you export this tab. Choose every row, or switch to This tab.");
      return;
    }
  }
  const res = await api("/api/comms/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      format,
      sheet_ids: sheetIds,
      column_keys: columnKeys.filter((key) => key !== "_job"),
      row_ids: rowIds,
      include_job: columnKeys.includes("_job"),
    }),
    timeoutMs: 120000,
  });
  const blob = res instanceof Response ? await res.blob() : res;
  const cd = res instanceof Response ? res.headers.get("Content-Disposition") || "" : "";
  const match = cd.match(/filename="([^"]+)"/);
  const filename = match?.[1] || `comms-planner.${format === "pdf" ? "pdf" : "xlsx"}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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
  await loadFormFields().catch(() => {});
  await loadSheets();

  $("sheetTabs")?.addEventListener("click", async (ev) => {
    const resourcesBtn = ev.target.closest("[data-view=resources]");
    if (resourcesBtn) {
      await showResourcesView();
      return;
    }
    const btn = ev.target.closest("[data-sheet]");
    if (!btn) return;
    closeDrawer();
    await loadSheet(Number(btn.dataset.sheet));
  });

  on("resourceSearch", "input", () => {
    state.resourceSearch = $("resourceSearch").value;
    renderResources();
  });

  on("btnAddResourceHeading", "click", async () => {
    const title = await promptDialog("New heading name:", "SharePoint");
    if (!title) return;
    await api("/api/comms/resources/sections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, created_by: userName() }),
    });
    await loadResources();
  });

  $("commsResources")?.addEventListener("change", async (ev) => {
    const area = ev.target.closest("[data-section-body]");
    if (!area) return;
    try {
      await api(`/api/comms/resources/sections/${area.dataset.sectionBody}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: area.value }),
      });
      const section = state.resources.find((item) => item.id === Number(area.dataset.sectionBody));
      if (section) section.body = area.value;
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not save notes"));
    }
  });

  document.body.addEventListener("click", (ev) => {
    if (ev.target.id !== "btnAddFormField") return;
    $("formFieldName").value = "";
    $("formFieldType").value = "yesno";
    $("formFieldOptions").value = "";
    $("formFieldOptionsWrap").hidden = true;
    $("formFieldDialog").showModal();
  });

  on("formFieldType", "change", () => {
    $("formFieldOptionsWrap").hidden = $("formFieldType").value !== "select";
  });

  on("btnSaveFormField", "click", async () => {
    const name = $("formFieldName").value.trim();
    const field_type = $("formFieldType").value;
    const options = $("formFieldOptions").value.split(",").map((s) => s.trim()).filter(Boolean);
    if (!name) {
      await alertDialog("Field name is required");
      return;
    }
    try {
      await api("/api/comms/form-fields", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, field_type, options, created_by: userName() }),
      });
      $("formFieldDialog").close();
      await loadResources();
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not add field"));
    }
  });

  $("commsResources")?.addEventListener("click", async (ev) => {
    const delField = ev.target.closest("[data-del-form-field]");
    if (delField) {
      if (!await confirmDialog("Remove this field from every planner row?")) return;
      await api(`/api/comms/form-fields/${delField.dataset.delFormField}`, { method: "DELETE" });
      await loadResources();
      return;
    }
    const add = ev.target.closest("[data-add-link]");
    if (add) {
      openResourceLinkDialog({ sectionId: Number(add.dataset.addLink) });
      return;
    }
    const rename = ev.target.closest("[data-rename-section]");
    if (rename) {
      const section = state.resources.find((item) => item.id === Number(rename.dataset.renameSection));
      const title = await promptDialog("Rename this heading:", section?.title || "");
      if (!title) return;
      await api(`/api/comms/resources/sections/${rename.dataset.renameSection}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      await loadResources();
      return;
    }
    const delSection = ev.target.closest("[data-del-section]");
    if (delSection) {
      if (!await confirmDialog("Remove this heading and all of its links?")) return;
      await api(`/api/comms/resources/sections/${delSection.dataset.delSection}`, { method: "DELETE" });
      await loadResources();
      return;
    }
    const edit = ev.target.closest("[data-edit-link]");
    if (edit) {
      const found = findResourceLink(Number(edit.dataset.editLink));
      if (found) openResourceLinkDialog({ sectionId: found.section.id, link: found.link });
      return;
    }
    const delLink = ev.target.closest("[data-del-link]");
    if (delLink) {
      if (!await confirmDialog("Remove this link?")) return;
      await api(`/api/comms/resources/links/${delLink.dataset.delLink}`, { method: "DELETE" });
      await loadResources();
    }
  });

  on("btnSaveResourceLink", "click", async () => {
    const sectionId = Number($("resourceLinkSectionId").value);
    const linkId = Number($("resourceLinkId").value);
    const title = $("resourceLinkTitle").value.trim();
    const url = $("resourceLinkUrl").value.trim();
    const note = $("resourceLinkNote").value.trim();
    if (!title || !url) {
      await alertDialog("Link name and URL are required");
      return;
    }
    try {
      if (linkId) {
        await api(`/api/comms/resources/links/${linkId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, url, note }),
        });
      } else {
        await api(`/api/comms/resources/sections/${sectionId}/links`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, url, note, created_by: userName() }),
        });
      }
      $("resourceLinkDialog").close();
      await loadResources();
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not save link"));
    }
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

  on("btnExport", "click", () => {
    fillExportDialog();
    $("exportDialog").showModal();
  });

  on("exportColScope", "change", () => {
    if ($("exportColumns")) $("exportColumns").hidden = $("exportColScope").value !== "custom";
  });

  on("btnExportXlsx", "click", async () => {
    try {
      await runCommsExport("xlsx");
      $("exportDialog").close();
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not export Excel"));
    }
  });

  on("btnExportPdf", "click", async () => {
    try {
      await runCommsExport("pdf");
      $("exportDialog").close();
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not export PDF"));
    }
  });

  on("btnColumns", "click", () => {
    renderColumnList();
    $("colName").value = "";
    $("colOptions").value = "";
    $("colType").value = "text";
    $("colOptionsWrap").hidden = true;
    if ($("colApplyAll")) $("colApplyAll").checked = false;
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
      body: JSON.stringify({
        name,
        field_type,
        options,
        created_by: userName(),
        apply_all: Boolean($("colApplyAll")?.checked),
      }),
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
    if (ev.target.id === "btnAddNote") {
      const row = currentRow();
      const message = ($("commsNoteText")?.value || "").trim();
      if (!row) return;
      if (!message) {
        await alertDialog("Write a note first");
        return;
      }
      try {
        await api(`/api/comms/rows/${row.id}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, created_by: userName() }),
        });
        $("commsNoteText").value = "";
        await refreshNotes();
      } catch (err) {
        await alertDialog(errorMessage(err, "Could not add note"));
      }
      return;
    }
    if (ev.target.id === "btnUploadScope") {
      const row = currentRow();
      const files = [...($("commsScopeFile")?.files || [])].filter((f) => f && f.size);
      if (!row) return;
      if (!files.length) {
        await alertDialog("Choose a scoping document first");
        return;
      }
      const status = $("commsScopeStatus");
      const errors = [];
      for (let i = 0; i < files.length; i += 1) {
        const file = files[i];
        if (status) status.textContent = `${i + 1}/${files.length} · ${file.name}`;
        try {
          await uploadCommsRowFile(row, file, {
            category: "scoping",
            description: "Scoping document",
            onProgress: (msg) => {
              if (status) status.textContent = msg;
            },
          });
        } catch (err) {
          errors.push(`${file.name}: ${errorMessage(err, "Upload failed")}`);
        }
      }
      if ($("commsScopeFile")) $("commsScopeFile").value = "";
      if (state.sheet) await loadSheet(state.sheet.id, { keepRow: row.id });
      const after = $("commsScopeStatus");
      if (errors.length) {
        if (after) after.textContent = `${files.length - errors.length} uploaded · ${errors.length} failed`;
        await alertDialog(errors.join("\n"));
        return;
      }
      if (after) after.textContent = files.length === 1 ? "Uploaded." : `Uploaded ${files.length} files.`;
      return;
    }
    const uploadForm = ev.target.closest("[data-upload-form-file]");
    if (uploadForm) {
      const row = currentRow();
      const key = uploadForm.dataset.uploadFormFile;
      const inp = document.querySelector(`[data-form-file="${cssKey(key)}"]`);
      const files = [...(inp?.files || [])].filter((f) => f && f.size);
      if (!row) return;
      if (!files.length) {
        await alertDialog("Choose a file first");
        return;
      }
      const status = document.querySelector(`[data-form-file-status="${cssKey(key)}"]`);
      const errors = [];
      const ids = formFileIds(row, key);
      for (let i = 0; i < files.length; i += 1) {
        const file = files[i];
        if (status) status.textContent = `${i + 1}/${files.length} · ${file.name}`;
        try {
          const doc = await uploadCommsRowFile(row, file, {
            category: "correspondence",
            description: `form:${key}`,
            onProgress: (msg) => {
              if (status) status.textContent = msg;
            },
          });
          if (doc?.id) ids.push(doc.id);
        } catch (err) {
          errors.push(`${file.name}: ${errorMessage(err, "Upload failed")}`);
        }
      }
      if (inp) inp.value = "";
      try {
        const next = await api(`/api/comms/rows/${row.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ form_values: { [key]: ids } }),
        });
        row.form_values = next.form_values || { ...(row.form_values || {}), [key]: ids };
      } catch (err) {
        await alertDialog(errorMessage(err, "Could not save file list"));
      }
      if (state.sheet) await loadSheet(state.sheet.id, { keepRow: row.id });
      const after = document.querySelector(`[data-form-file-status="${cssKey(key)}"]`);
      if (errors.length) {
        if (after) after.textContent = `${files.length - errors.length} uploaded · ${errors.length} failed`;
        await alertDialog(errors.join("\n"));
        return;
      }
      if (after) after.textContent = files.length === 1 ? "Uploaded." : `Uploaded ${files.length} files.`;
      return;
    }
    const delNote = ev.target.closest("[data-del-note]");
    if (delNote) {
      if (!await confirmDialog("Delete this note?")) return;
      try {
        await api(`/api/comms/notes/${delNote.dataset.delNote}`, { method: "DELETE" });
        await refreshNotes();
      } catch (err) {
        await alertDialog(errorMessage(err, "Could not delete note"));
      }
      return;
    }
    const vis = ev.target.closest("[data-vis]");
    if (vis) {
      await api(`/api/documents/${vis.dataset.vis}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visibility: vis.dataset.next }),
      });
      await refreshActiveDocs();
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
    if (ev.target.dataset.formField && state.openRowId) {
      const key = ev.target.dataset.formField;
      const value = ev.target.value;
      try {
        const next = await api(`/api/comms/rows/${state.openRowId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ form_values: { [key]: value } }),
        });
        const row = (state.sheet?.rows || []).find((r) => r.id === state.openRowId);
        if (row) row.form_values = next.form_values || { ...(row.form_values || {}), [key]: value };
      } catch (err) {
        await alertDialog(errorMessage(err, "Could not save field"));
      }
      return;
    }
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
        await uploadCommsRowFile(row, file, { category: "correspondence", description, visibility });
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
