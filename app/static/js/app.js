const state = {
  sites: [],
  columns: [],
  meta: { workflow_stages: [], priority_threshold_days: 21 },
  detailSiteId: null,
};

const $ = (id) => document.getElementById(id);

function userName() {
  return ($("userName").value || "").trim() || null;
}

function saveUserName() {
  localStorage.setItem("wru_user", $("userName").value || "");
}

const THEME_KEY = "wru-tgs-theme";

function currentTheme() {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
  root.style.colorScheme = mode;
  const btn = $("themeToggle");
  if (btn) {
    btn.textContent = mode === "dark" ? "Light" : "Dark";
    btn.setAttribute(
      "aria-label",
      mode === "dark" ? "Switch to light mode" : "Switch to dark mode"
    );
  }
}

function initThemeToggle() {
  applyTheme(currentTheme());
  $("themeToggle")?.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch (_) {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

function fmtDate(value) {
  if (!value) return "";
  const [y, m, d] = value.split("-");
  return `${d}/${m}/${y}`;
}

function daysUntil(iso) {
  if (!iso) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(`${iso}T00:00:00`);
  return Math.round((target - today) / 86400000);
}

function mustHaveClass(iso) {
  const d = daysUntil(iso);
  if (d === null) return "";
  if (d < 0 || d >= 14) return "must-have late";
  return "must-have soon";
}

function setStatus(msg) {
  $("statusLine").textContent = msg;
}

function renderHead() {
  const stages = state.meta.workflow_stages;
  const customTh = state.columns
    .map((c) => `<th title="${c.field_key}">${escapeHtml(c.name)}</th>`)
    .join("");
  $("tableHead").innerHTML = `
    <tr>
      <th>Road Name</th>
      <th>Site</th>
      <th>Start</th>
      <th>MoA must-have</th>
      <th>Pri</th>
      ${stages.map((s) => `<th class="stage" title="${escapeHtml(s.label)}">${escapeHtml(s.label)}</th>`).join("")}
      <th>Comments</th>
      <th>MoA #</th>
      <th>Submitted</th>
      ${customTh}
      <th>Docs</th>
      <th></th>
    </tr>
  `;
}

function workflowMap(site) {
  const map = {};
  for (const step of site.workflow || []) map[step.stage] = step.completed;
  return map;
}

function renderBody() {
  const tbody = $("tableBody");
  if (!state.sites.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="30">No sites match. Add a site to get started.</td></tr>`;
    return;
  }

  const stages = state.meta.workflow_stages;
  tbody.innerHTML = state.sites
    .map((site, idx) => {
      const wf = workflowMap(site);
      const stageCells = stages
        .map((s) => {
          const on = !!wf[s.key];
          return `<td class="stage-cell ${on ? "on" : ""}" data-action="toggle-stage" data-id="${site.id}" data-stage="${s.key}" title="${escapeHtml(s.label)}"><span class="dot"></span></td>`;
        })
        .join("");
      const customCells = state.columns
        .map((c) => {
          const val = (site.custom_fields || {})[c.field_key];
          let display = val ?? "";
          if (c.field_type === "checkbox") display = val ? "Yes" : "";
          return `<td>${escapeHtml(String(display))}</td>`;
        })
        .join("");
      return `
        <tr style="animation-delay:${Math.min(idx, 12) * 20}ms">
          <td><strong>${escapeHtml(site.road_name)}</strong></td>
          <td class="mono">${escapeHtml(site.site_number)}</td>
          <td class="mono">${fmtDate(site.indicative_site_start_date)}</td>
          <td class="mono"><span class="${mustHaveClass(site.moa_must_have_received_date)}">${fmtDate(site.moa_must_have_received_date)}</span></td>
          <td><span class="priority p${site.today_priority}">${site.today_priority}</span></td>
          ${stageCells}
          <td class="comments">${escapeHtml(site.comments || "")}</td>
          <td class="mono">${escapeHtml(site.moa_number || "")}</td>
          <td class="mono">${fmtDate(site.moa_submission_date)}</td>
          ${customCells}
          <td class="mono">${site.document_count || 0}</td>
          <td>
            <div class="row-actions">
              <button type="button" class="btn" data-action="edit" data-id="${site.id}">Edit</button>
              <button type="button" class="btn" data-action="detail" data-id="${site.id}">Track / Docs</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadAll() {
  const q = $("search").value.trim();
  const priority = $("priorityFilter").value;
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (priority) params.set("priority", priority);
  const qs = params.toString() ? `?${params}` : "";

  const [meta, columns, sites] = await Promise.all([
    api("/api/meta"),
    api("/api/columns"),
    api(`/api/sites${qs}`),
  ]);
  state.meta = meta;
  state.columns = columns;
  state.sites = sites;
  renderHead();
  renderBody();
  setStatus(`${sites.length} site${sites.length === 1 ? "" : "s"} · ${columns.length} custom column${columns.length === 1 ? "" : "s"}`);
}

function buildWorkflowChecks(selected = {}) {
  $("workflowChecks").innerHTML = state.meta.workflow_stages
    .map(
      (s) => `
      <label>
        <input type="checkbox" name="wf_${s.key}" ${selected[s.key] ? "checked" : ""} />
        ${escapeHtml(s.label)}
      </label>`
    )
    .join("");
}

function buildCustomFields(values = {}) {
  const grid = $("customFieldsGrid");
  const wrap = $("customFieldsEdit");
  if (!state.columns.length) {
    wrap.hidden = true;
    grid.innerHTML = "";
    return;
  }
  wrap.hidden = false;
  grid.innerHTML = state.columns
    .map((c) => {
      const val = values[c.field_key] ?? "";
      if (c.field_type === "checkbox") {
        return `<label class="full"><span><input type="checkbox" data-cf="${c.field_key}" ${val ? "checked" : ""} /> ${escapeHtml(c.name)}</span></label>`;
      }
      if (c.field_type === "select") {
        const opts = (c.options || [])
          .map((o) => `<option value="${escapeHtml(o)}" ${val === o ? "selected" : ""}>${escapeHtml(o)}</option>`)
          .join("");
        return `<label>${escapeHtml(c.name)}<select data-cf="${c.field_key}"><option value=""></option>${opts}</select></label>`;
      }
      const type = c.field_type === "number" || c.field_type === "date" ? c.field_type : "text";
      return `<label>${escapeHtml(c.name)}<input data-cf="${c.field_key}" type="${type}" value="${escapeHtml(val)}" /></label>`;
    })
    .join("");
}

function openSiteDialog(site = null) {
  $("siteDialogTitle").textContent = site ? "Edit site" : "Add site";
  $("siteId").value = site ? site.id : "";
  $("fRoad").value = site?.road_name || "";
  $("fSiteNo").value = site?.site_number || "";
  $("fStart").value = site?.indicative_site_start_date || "";
  $("fMustHave").value = site?.moa_must_have_received_date || "";
  $("fMoaNo").value = site?.moa_number || "";
  $("fMoaSub").value = site?.moa_submission_date || "";
  $("fComments").value = site?.comments || "";
  buildWorkflowChecks(site ? workflowMap(site) : {});
  buildCustomFields(site?.custom_fields || {});
  $("btnDeleteSite").hidden = !site;
  $("siteDialog").showModal();
}

function collectSitePayload() {
  const workflow = {};
  for (const s of state.meta.workflow_stages) {
    const el = document.querySelector(`input[name="wf_${s.key}"]`);
    workflow[s.key] = !!(el && el.checked);
  }
  const custom_fields = {};
  for (const el of document.querySelectorAll("[data-cf]")) {
    const key = el.dataset.cf;
    if (el.type === "checkbox") custom_fields[key] = el.checked;
    else if (el.type === "number") custom_fields[key] = el.value === "" ? null : Number(el.value);
    else custom_fields[key] = el.value;
  }
  return {
    road_name: $("fRoad").value.trim(),
    site_number: $("fSiteNo").value.trim(),
    indicative_site_start_date: $("fStart").value || null,
    moa_must_have_received_date: $("fMustHave").value || null,
    moa_number: $("fMoaNo").value.trim() || null,
    moa_submission_date: $("fMoaSub").value || null,
    comments: $("fComments").value.trim() || null,
    custom_fields,
    workflow,
  };
}

async function saveSite(ev) {
  if (ev.submitter?.value === "cancel") return;
  ev.preventDefault();
  const id = $("siteId").value;
  const payload = collectSitePayload();
  try {
    if (id) {
      await api(`/api/sites/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    $("siteDialog").close();
    await loadAll();
  } catch (err) {
    alert(err.message);
  }
}

async function deleteSite() {
  const id = $("siteId").value;
  if (!id || !confirm("Delete this site and its documents/tracking?")) return;
  await api(`/api/sites/${id}`, { method: "DELETE" });
  $("siteDialog").close();
  await loadAll();
}

function renderColumnList() {
  $("columnList").innerHTML = state.columns.length
    ? state.columns
        .map(
          (c) => `
      <li>
        <div>
          <strong>${escapeHtml(c.name)}</strong>
          <div class="meta">${escapeHtml(c.field_type)} · ${escapeHtml(c.field_key)}</div>
        </div>
        <button type="button" class="btn btn-danger" data-del-col="${c.id}">Remove</button>
      </li>`
        )
        .join("")
    : `<li><div class="meta">No custom columns yet.</div></li>`;
}

async function openColumns() {
  renderColumnList();
  $("colName").value = "";
  $("colOptions").value = "";
  $("colType").value = "text";
  $("colOptionsWrap").hidden = true;
  $("columnsDialog").showModal();
}

async function addColumn() {
  const name = $("colName").value.trim();
  if (!name) {
    alert("Column name is required");
    return;
  }
  const field_type = $("colType").value;
  const options =
    field_type === "select"
      ? $("colOptions")
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : null;
  try {
    await api("/api/columns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, field_type, options, created_by: userName() }),
    });
    await loadAll();
    renderColumnList();
    $("colName").value = "";
    $("colOptions").value = "";
  } catch (err) {
    alert(err.message);
  }
}

async function removeColumn(id) {
  if (!confirm("Remove this column and clear its values from all sites?")) return;
  await api(`/api/columns/${id}`, { method: "DELETE" });
  await loadAll();
  renderColumnList();
}

async function openDetail(siteId) {
  state.detailSiteId = siteId;
  const site = state.sites.find((s) => s.id === siteId) || (await api(`/api/sites/${siteId}`));
  $("detailTitle").textContent = site.road_name;
  $("detailSub").textContent = `${site.site_number} · tracking & documents`;
  await Promise.all([refreshTracking(), refreshDocuments()]);
  $("detailDialog").showModal();
}

async function refreshTracking() {
  const events = await api(`/api/sites/${state.detailSiteId}/tracking`);
  $("trackList").innerHTML = events.length
    ? events
        .map(
          (e) => `
      <li>
        <div class="top">
          <span>${escapeHtml(e.event_type)} · ${escapeHtml(e.created_by || "anon")} · ${new Date(e.created_at).toLocaleString()}</span>
          <button type="button" class="btn" data-del-track="${e.id}">Delete</button>
        </div>
        <p>${escapeHtml(e.message)}</p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No tracking yet.</p></li>`;
}

async function refreshDocuments() {
  const docs = await api(`/api/sites/${state.detailSiteId}/documents`);
  $("docList").innerHTML = docs.length
    ? docs
        .map(
          (d) => `
      <li>
        <div class="top">
          <span>${escapeHtml(d.uploaded_by || "anon")} · ${(d.size_bytes / 1024).toFixed(1)} KB · ${new Date(d.uploaded_at).toLocaleString()}</span>
          <button type="button" class="btn" data-del-doc="${d.id}">Delete</button>
        </div>
        <p><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a></p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No documents attached.</p></li>`;
}

async function addTracking() {
  const message = $("trackMessage").value.trim();
  if (!message) return;
  await api(`/api/sites/${state.detailSiteId}/tracking`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: $("trackType").value,
      message,
      created_by: userName(),
    }),
  });
  $("trackMessage").value = "";
  await refreshTracking();
  await loadAll();
}

async function uploadDoc() {
  const fileInput = $("docFile");
  if (!fileInput.files?.length) {
    alert("Choose a file first");
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  if (userName()) fd.append("uploaded_by", userName());
  const res = await fetch(`/api/sites/${state.detailSiteId}/documents`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert(body.detail || "Upload failed");
    return;
  }
  fileInput.value = "";
  await refreshDocuments();
  await loadAll();
}

async function toggleStage(siteId, stage) {
  const site = state.sites.find((s) => s.id === siteId);
  if (!site) return;
  const wf = workflowMap(site);
  wf[stage] = !wf[stage];
  await api(`/api/sites/${siteId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow: wf }),
  });
  await loadAll();
}

function bindEvents() {
  $("btnAddSite").addEventListener("click", () => openSiteDialog());
  $("btnColumns").addEventListener("click", openColumns);
  $("btnAddColumn").addEventListener("click", addColumn);
  $("btnDeleteSite").addEventListener("click", deleteSite);
  $("btnAddTrack").addEventListener("click", addTracking);
  $("btnUploadDoc").addEventListener("click", uploadDoc);
  $("siteForm").addEventListener("submit", saveSite);
  $("colType").addEventListener("change", () => {
    $("colOptionsWrap").hidden = $("colType").value !== "select";
  });
  $("userName").addEventListener("change", saveUserName);
  $("search").addEventListener("input", debounce(loadAll, 250));
  $("priorityFilter").addEventListener("change", loadAll);

  $("tableBody").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (btn.dataset.action === "edit") {
      const site = state.sites.find((s) => s.id === id);
      openSiteDialog(site);
    } else if (btn.dataset.action === "detail") {
      openDetail(id);
    } else if (btn.dataset.action === "toggle-stage") {
      await toggleStage(id, btn.dataset.stage);
    }
  });

  $("columnList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-col]");
    if (!btn) return;
    await removeColumn(Number(btn.dataset.delCol));
  });

  $("trackList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-track]");
    if (!btn) return;
    await api(`/api/sites/${state.detailSiteId}/tracking/${btn.dataset.delTrack}`, {
      method: "DELETE",
    });
    await refreshTracking();
    await loadAll();
  });

  $("docList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-doc]");
    if (!btn) return;
    if (!confirm("Delete this document?")) return;
    await api(`/api/documents/${btn.dataset.delDoc}`, { method: "DELETE" });
    await refreshDocuments();
    await loadAll();
  });
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function init() {
  $("userName").value = localStorage.getItem("wru_user") || "";
  initThemeToggle();
  bindEvents();
  try {
    await loadAll();
  } catch (err) {
    setStatus(`Failed to load: ${err.message}`);
  }
}

init();
