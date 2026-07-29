import {
  $,
  api,
  escapeHtml,
  fmtDate,
  injectChrome,
  mustBandClass,
  stageLabel,
  userName,
} from "./common.js";

const state = {
  sites: [],
  columns: [],
  meta: { workflow_stages: [], priority_threshold_days: 21, councils: [] },
  detailSiteId: null,
};

function setStatus(msg) {
  $("statusLine").textContent = msg;
}

function workflowMap(site) {
  const map = {};
  for (const step of site.workflow || []) map[step.stage] = step.completed;
  return map;
}

function fillFilterOptions() {
  const stageSel = $("stageFilter");
  const councilSel = $("councilFilter");
  if (stageSel) {
    const cur = stageSel.value;
    stageSel.innerHTML =
      `<option value="">All stages</option>` +
      state.meta.workflow_stages
        .map((s) => `<option value="${s.key}">${escapeHtml(s.label)}</option>`)
        .join("");
    stageSel.value = cur;
  }
  if (councilSel) {
    const cur = councilSel.value;
    const councils = new Set([...(state.meta.councils || [])]);
    for (const s of state.sites) for (const c of s.councils || []) councils.add(c);
    councilSel.innerHTML =
      `<option value="">All councils</option>` +
      [...councils]
        .sort()
        .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
        .join("");
    councilSel.value = cur;
  }
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
      <th>Program</th>
      <th>Councils</th>
      <th>Start</th>
      <th>MoA must-have</th>
      <th>Pri</th>
      <th>%</th>
      ${stages.map((s) => `<th class="stage" title="${escapeHtml(s.label)}">${escapeHtml(s.label)}</th>`).join("")}
      <th>Comments</th>
      <th>MoA #</th>
      <th>TGS</th>
      ${customTh}
      <th>Docs</th>
      <th></th>
    </tr>
  `;
}

function renderBody() {
  const tbody = $("tableBody");
  if (!state.sites.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="40">No active sites match.</td></tr>`;
    return;
  }
  const stages = state.meta.workflow_stages;
  tbody.innerHTML = state.sites
    .map((site) => {
      const wf = workflowMap(site);
      const m = site.metrics || {};
      const must = m.must_have_status || {};
      const stageCells = stages
        .map(
          (s) =>
            `<td class="stage-cell ${wf[s.key] ? "on" : ""}" data-action="toggle-stage" data-id="${site.id}" data-stage="${s.key}" title="${escapeHtml(s.label)}"><span class="dot"></span></td>`
        )
        .join("");
      const customCells = state.columns
        .map((c) => {
          const val = (site.custom_fields || {})[c.field_key];
          let display = val ?? "";
          if (c.field_type === "checkbox") display = val ? "Yes" : "";
          return `<td>${escapeHtml(String(display))}</td>`;
        })
        .join("");
      const councils = (site.councils || [])
        .map((c) => `<span class="chip">${escapeHtml(c)}</span>`)
        .join(" ");
      return `
        <tr>
          <td><strong>${escapeHtml(site.road_name)}</strong></td>
          <td class="mono">${escapeHtml(site.site_number)}</td>
          <td>${escapeHtml(site.program || "")}</td>
          <td>${councils || "—"}</td>
          <td class="mono">${fmtDate(site.indicative_site_start_date)}</td>
          <td class="mono"><span class="${mustBandClass(must.band)}">${fmtDate(site.moa_must_have_received_date)} ${must.label && must.label !== "—" ? `(${escapeHtml(must.label)})` : ""}</span></td>
          <td><span class="priority p${site.today_priority}">${site.today_priority}</span></td>
          <td class="progress-mini">${m.workflow_progress_pct ?? 0}%</td>
          ${stageCells}
          <td class="comments">${escapeHtml(site.comments || "")}</td>
          <td class="mono">${escapeHtml(site.moa_number || "")}</td>
          <td class="mono">${escapeHtml(site.tgs_reference || "")}</td>
          ${customCells}
          <td class="mono">${site.document_count || 0}</td>
          <td>
            <div class="row-actions">
              <button type="button" class="btn" data-action="edit" data-id="${site.id}">Edit</button>
              <button type="button" class="btn" data-action="detail" data-id="${site.id}">Track / Docs</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");
}

async function loadAll() {
  const params = new URLSearchParams({ archived: "false" });
  const q = $("search").value.trim();
  const priority = $("priorityFilter").value;
  const stage = $("stageFilter")?.value;
  const council = $("councilFilter")?.value;
  if (q) params.set("q", q);
  if (priority) params.set("priority", priority);
  if (stage) params.set("stage", stage);
  if (council) params.set("council", council);

  const [meta, columns, sites] = await Promise.all([
    api("/api/meta"),
    api("/api/columns"),
    api(`/api/sites?${params}`),
  ]);
  state.meta = meta;
  state.columns = columns;
  state.sites = sites;
  fillFilterOptions();
  renderHead();
  renderBody();
  const pri = sites.filter((s) => s.metrics?.on_permits_priority_list).length;
  setStatus(
    `${sites.length} active site${sites.length === 1 ? "" : "s"} · ${pri} on permits priority list`
  );
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
  $("fProgram").value = site?.program || "";
  $("fTgs").value = site?.tgs_reference || "";
  $("fStart").value = site?.indicative_site_start_date || "";
  $("fMustHave").value = site?.moa_must_have_received_date || "";
  $("fMoaNo").value = site?.moa_number || "";
  $("fMoaSub").value = site?.moa_submission_date || "";
  $("fCouncils").value = (site?.councils || []).join(", ");
  $("fComments").value = site?.comments || "";
  buildWorkflowChecks(site ? workflowMap(site) : {});
  buildCustomFields(site?.custom_fields || {});
  $("btnArchiveSite").hidden = !site;
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
  const councils = $("fCouncils")
    .value.split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return {
    road_name: $("fRoad").value.trim(),
    site_number: $("fSiteNo").value.trim(),
    program: $("fProgram").value.trim() || null,
    tgs_reference: $("fTgs").value.trim() || null,
    indicative_site_start_date: $("fStart").value || null,
    moa_must_have_received_date: $("fMustHave").value || null,
    moa_number: $("fMoaNo").value.trim() || null,
    moa_submission_date: $("fMoaSub").value || null,
    comments: $("fComments").value.trim() || null,
    councils,
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

async function archiveSite() {
  const id = $("siteId").value;
  if (!id) return;
  const fy = prompt("Archive to financial year (e.g. 2025-26). Leave blank to auto-detect:");
  if (fy === null) return;
  await api(`/api/sites/${id}/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ financial_year: fy.trim() || null }),
  });
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
  if (!name) return alert("Column name is required");
  const field_type = $("colType").value;
  const options =
    field_type === "select"
      ? $("colOptions")
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : null;
  await api("/api/columns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, field_type, options, created_by: userName() }),
  });
  await loadAll();
  renderColumnList();
  $("colName").value = "";
}

async function openDetail(siteId) {
  state.detailSiteId = siteId;
  const site = state.sites.find((s) => s.id === siteId) || (await api(`/api/sites/${siteId}`));
  $("detailTitle").textContent = site.road_name;
  $("detailSub").textContent = `${site.site_number} · MoA ${site.moa_number || "—"} · docs & tracking`;
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
          <span><span class="doc-cat">${escapeHtml(d.category)}</span> · ${escapeHtml(d.uploaded_by || "anon")} · ${(d.size_bytes / 1024).toFixed(1)} KB</span>
          <button type="button" class="btn" data-del-doc="${d.id}">Delete</button>
        </div>
        <p><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a>${d.description ? ` — ${escapeHtml(d.description)}` : ""}</p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No documents attached to this MoA/site.</p></li>`;
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
  if (!fileInput.files?.length) return alert("Choose a file first");
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("category", $("docCategory").value);
  if ($("docDesc").value.trim()) fd.append("description", $("docDesc").value.trim());
  if (userName()) fd.append("uploaded_by", userName());
  const res = await fetch(`/api/sites/${state.detailSiteId}/documents`, { method: "POST", body: fd });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert(body.detail || "Upload failed");
    return;
  }
  fileInput.value = "";
  $("docDesc").value = "";
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

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function bindEvents() {
  $("btnAddSite").addEventListener("click", () => openSiteDialog());
  $("btnColumns").addEventListener("click", openColumns);
  $("btnAddColumn").addEventListener("click", addColumn);
  $("btnArchiveSite").addEventListener("click", archiveSite);
  $("btnAddTrack").addEventListener("click", addTracking);
  $("btnUploadDoc").addEventListener("click", uploadDoc);
  $("siteForm").addEventListener("submit", saveSite);
  $("colType").addEventListener("change", () => {
    $("colOptionsWrap").hidden = $("colType").value !== "select";
  });
  $("search").addEventListener("input", debounce(loadAll, 250));
  $("priorityFilter").addEventListener("change", loadAll);
  $("stageFilter")?.addEventListener("change", loadAll);
  $("councilFilter")?.addEventListener("change", loadAll);

  $("tableBody").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (btn.dataset.action === "edit") openSiteDialog(state.sites.find((s) => s.id === id));
    else if (btn.dataset.action === "detail") openDetail(id);
    else if (btn.dataset.action === "toggle-stage") await toggleStage(id, btn.dataset.stage);
  });

  $("columnList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-col]");
    if (!btn) return;
    if (!confirm("Remove this column and clear its values from all sites?")) return;
    await api(`/api/columns/${btn.dataset.delCol}`, { method: "DELETE" });
    await loadAll();
    renderColumnList();
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

async function init() {
  injectChrome({ active: "/" });
  bindEvents();
  try {
    await loadAll();
  } catch (err) {
    setStatus(`Failed to load: ${err.message}`);
  }
}

init();
