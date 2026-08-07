import {
  $,
  api,
  errorMessage,
  escapeHtml,
  fmtDate,
  injectChrome,
  mustBandClass,
  on,
  showPageError,
  stageLabel,
  userName,
} from "./common.js";

const state = {
  sites: [],
  columns: [],
  meta: { workflow_stages: [], priority_threshold_days: 14, councils: [], programs: [], roads: [] },
  detailSiteId: null,
  genericMoas: [],
  autosaveTimer: null,
  suppressAutosave: false,
  highlightId: null,
  highlightHandled: false,
  activeTab: "overview",
  selectedIds: new Set(),
  dragSiteIds: [],
  suppressRowOpen: false,
};

const GANTT_DEFAULT_PROGRAM = "Lifecycle pavements";

function setStatus(msg) {
  const el = $("statusLine");
  if (el) el.textContent = msg;
}

function workflowMap(site) {
  const map = {};
  for (const step of site.workflow || []) map[step.stage] = step.completed;
  return map;
}

function currentStageLabel(site) {
  const key = site.metrics?.current_stage;
  return stageLabel(state.meta, key);
}

function currentStageKey(site) {
  return site?.metrics?.current_stage || "";
}

/** Spreadsheet-style master status: complete all stages up to (and including) target. */
function workflowAdvanceTo(targetKey) {
  const stages = state.meta.workflow_stages || [];
  const linear = stages.filter((s) => s.key !== "revision_needed");
  const workflow = {};
  if (targetKey === "revision_needed") {
    for (const s of stages) {
      workflow[s.key] = s.key === "revision_needed";
    }
    return workflow;
  }
  const idx = linear.findIndex((s) => s.key === targetKey);
  for (const s of stages) {
    if (s.key === "revision_needed") {
      workflow[s.key] = false;
      continue;
    }
    const i = linear.findIndex((x) => x.key === s.key);
    workflow[s.key] = idx >= 0 && i >= 0 && i <= idx;
  }
  return workflow;
}

function statusSelectHtml(site) {
  const current = currentStageKey(site);
  const opts = (state.meta.workflow_stages || [])
    .map(
      (s) =>
        `<option value="${escapeHtml(s.key)}" ${s.key === current ? "selected" : ""}>${escapeHtml(
          s.label
        )}</option>`
    )
    .join("");
  return `<label class="sr-only" for="status-${site.id}">Status for ${escapeHtml(
    site.road_name
  )}</label>
    <select class="status-select" id="status-${site.id}" data-status-select="${site.id}" aria-label="Set status">
      ${opts || `<option value="">No stages</option>`}
    </select>`;
}

async function quickSetStatus(siteId, stageKey, selectEl) {
  const site = state.sites.find((s) => s.id === Number(siteId));
  if (!site || !stageKey) return;
  const prev = currentStageKey(site);
  if (prev === stageKey) return;
  if (selectEl) {
    selectEl.disabled = true;
    selectEl.classList.add("saving");
  }
  try {
    const updated = await api(`/api/sites/${siteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow: workflowAdvanceTo(stageKey) }),
    });
    const idx = state.sites.findIndex((s) => s.id === Number(siteId));
    if (idx >= 0) state.sites[idx] = updated;
    else await loadAll();
    renderRegister();
    setStatus(`Updated status → ${stageLabel(state.meta, stageKey)}`);
  } catch (err) {
    if (selectEl) selectEl.value = prev;
    alert(errorMessage(err, "Could not update status"));
  } finally {
    if (selectEl) {
      selectEl.disabled = false;
      selectEl.classList.remove("saving");
    }
  }
}

function fillFilterOptions() {
  const stageSel = $("stageFilter");
  const councilSel = $("councilFilter");
  const programSel = $("programFilter");
  if (stageSel) {
    const cur = stageSel.value;
    stageSel.innerHTML =
      `<option value="">All stages</option>` +
      state.meta.workflow_stages
        .map((s) => `<option value="${s.key}">${escapeHtml(s.label)}</option>`)
        .join("");
    stageSel.value = cur;
  }
  if (programSel) {
    const cur = programSel.value;
    programSel.innerHTML =
      `<option value="">All programs</option>` +
      (state.meta.programs || [])
        .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
        .join("");
    programSel.value = cur;
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

function listBadge(list) {
  if (list === "permits") return `<span class="badge badge-permits">Permits</span>`;
  if (list === "trims") return `<span class="badge badge-trims">TRIMS</span>`;
  return `<span class="badge badge-muted">—</span>`;
}

function syncBulkBar() {
  const bar = $("bulkBar");
  const count = state.selectedIds.size;
  if (bar) bar.hidden = count === 0;
  const label = $("bulkCount");
  if (label) label.textContent = `${count} selected`;
  const all = $("selectAllVisible");
  if (all) {
    const visibleIds = state.sites.map((s) => s.id);
    all.checked = visibleIds.length > 0 && visibleIds.every((id) => state.selectedIds.has(id));
    all.indeterminate =
      count > 0 && visibleIds.some((id) => state.selectedIds.has(id)) && !all.checked;
  }
}

function siteRowHtml(site) {
  const m = site.metrics || {};
  const must = m.must_have_status || {};
  const mustDate = must.date || site.moa_must_have_received_date;
  const mustDisplay =
    must.band === "received"
      ? "Received"
      : `${fmtDate(mustDate)}${must.label && must.label !== "—" ? ` · ${escapeHtml(must.label)}` : ""}`;
  const pct = m.workflow_progress_pct ?? 0;
  const highlight = state.highlightId === site.id ? "row-highlight" : "";
  const councils = (site.councils || []).slice(0, 2).join(", ");
  const more = (site.councils || []).length > 2 ? ` +${site.councils.length - 2}` : "";
  const checked = state.selectedIds.has(site.id) ? "checked" : "";
  return `<tr class="register-row ${highlight}" draggable="true" data-site-id="${site.id}" data-action="open" data-id="${site.id}" data-program="${escapeHtml(site.program || "Unassigned")}">
    <td class="select-col" onclick="event.stopPropagation()">
      <input type="checkbox" class="site-select" data-select-id="${site.id}" ${checked} aria-label="Select ${escapeHtml(site.road_name)}" />
    </td>
    <td>
      <div class="site-title"><span class="drag-grip" title="Drag to another program" aria-hidden="true">⋮⋮</span>${escapeHtml(site.road_name)}</div>
      <div class="site-meta">
        <span class="mono">${escapeHtml(site.site_number)}</span>
        ${councils ? ` · ${escapeHtml(councils)}${escapeHtml(more)}` : ""}
      </div>
    </td>
    <td class="status-col" onclick="event.stopPropagation()">
      <div class="status-cell">
        ${statusSelectHtml(site)}
        <div class="progress-bar thin" title="${pct}% complete" aria-hidden="true"><span style="width:${pct}%"></span></div>
      </div>
    </td>
    <td><span class="priority p${site.today_priority}">${site.today_priority}</span></td>
    <td class="mono">${fmtDate(site.indicative_site_start_date) || "—"}</td>
    <td class="mono"><span class="${mustBandClass(must.band)}">${mustDisplay || "—"}</span></td>
    <td>${listBadge(m.client_list)}</td>
    <td class="mono">${escapeHtml(site.moa_number || "—")}</td>
    <td class="actions-col" onclick="event.stopPropagation()">
      <div class="register-actions">
        <button type="button" class="btn btn-primary btn-sm" data-action="open" data-id="${site.id}">Open</button>
        <a class="btn btn-sm" href="/costs?site_id=${site.id}">Traffic</a>
        <a class="btn btn-sm" href="/asphalt?site_id=${site.id}">Asphalt</a>
      </div>
    </td>
  </tr>`;
}

async function moveSitesToProgram(siteIds, program) {
  const target = (program || "").trim();
  if (!target || target === "Unassigned") {
    // Allow explicit Unassigned only when dropping on that bucket
  }
  const ids = [...new Set(siteIds.map(Number).filter((id) => id > 0))];
  if (!ids.length) return;

  const toMove = ids.filter((id) => {
    const site = state.sites.find((s) => s.id === id);
    const current = (site?.program || "").trim() || "Unassigned";
    return site && current !== target;
  });
  if (!toMove.length) return;

  setStatus(
    toMove.length === 1
      ? `Moving site to ${target}…`
      : `Moving ${toMove.length} sites to ${target}…`
  );
  await Promise.all(
    toMove.map((id) =>
      api(`/api/sites/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ program: target === "Unassigned" ? null : target }),
      })
    )
  );
  await loadAll();
  setStatus(
    toMove.length === 1
      ? `Moved to ${target}`
      : `Moved ${toMove.length} sites to ${target}`
  );
}

function wireProgramDragDrop() {
  const root = $("registerList");
  if (!root || root.dataset.programDndWired) return;
  root.dataset.programDndWired = "1";

  root.addEventListener("dragstart", (ev) => {
    const row = ev.target.closest("tr.register-row");
    if (!row || !root.contains(row)) return;
    if (ev.target.closest("input, select, button, a, .actions-col, .status-col, .select-col")) {
      ev.preventDefault();
      return;
    }
    const id = Number(row.dataset.siteId);
    if (!id) {
      ev.preventDefault();
      return;
    }
    const ids =
      state.selectedIds.has(id) && state.selectedIds.size > 1
        ? [...state.selectedIds]
        : [id];
    state.dragSiteIds = ids;
    state.suppressRowOpen = true;
    row.classList.add("is-dragging");
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", ids.join(","));
    try {
      ev.dataTransfer.setData("application/x-wru-site-ids", JSON.stringify(ids));
    } catch {
      /* some browsers are picky about custom types */
    }
  });

  root.addEventListener("dragend", () => {
    state.dragSiteIds = [];
    root.querySelectorAll(".is-dragging, .drag-over").forEach((el) => {
      el.classList.remove("is-dragging", "drag-over");
    });
    window.setTimeout(() => {
      state.suppressRowOpen = false;
    }, 120);
  });

  root.addEventListener("dragover", (ev) => {
    const section = ev.target.closest("section.register-program[data-program]");
    if (!section || !root.contains(section)) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    root.querySelectorAll(".register-program.drag-over").forEach((el) => {
      if (el !== section) el.classList.remove("drag-over");
    });
    section.classList.add("drag-over");
  });

  root.addEventListener("dragleave", (ev) => {
    const section = ev.target.closest("section.register-program");
    if (!section) return;
    if (section.contains(ev.relatedTarget)) return;
    section.classList.remove("drag-over");
  });

  root.addEventListener("drop", (ev) => {
    const section = ev.target.closest("section.register-program[data-program]");
    if (!section || !root.contains(section)) return;
    ev.preventDefault();
    section.classList.remove("drag-over");
    let ids = state.dragSiteIds;
    if (!ids?.length) {
      try {
        ids = JSON.parse(ev.dataTransfer.getData("application/x-wru-site-ids") || "[]");
      } catch {
        ids = [];
      }
    }
    if (!ids?.length) {
      ids = (ev.dataTransfer.getData("text/plain") || "")
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => n > 0);
    }
    const program = section.getAttribute("data-program") || "";
    moveSitesToProgram(ids, program).catch((err) => {
      alert(errorMessage(err, "Could not move site(s)"));
      loadAll().catch(() => {});
    });
  });
}

function renderRegister() {
  const root = $("registerList");
  if (!root) return;
  if (!state.sites.length && !(state.meta.programs || []).length) {
    root.innerHTML = `<div class="register-empty">No active sites match these filters.</div>`;
    return;
  }

  // Spreadsheet-style: group by program section (keep empty programs as drop targets)
  const groups = new Map();
  for (const site of state.sites) {
    const key = (site.program || "").trim() || "Unassigned";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(site);
  }
  const order = [];
  for (const p of state.meta.programs || []) {
    if (!order.includes(p)) order.push(p);
    if (!groups.has(p)) groups.set(p, []);
  }
  for (const k of groups.keys()) {
    if (!order.includes(k)) order.push(k);
  }
  if (!state.sites.length) {
    // Still show program buckets so filtered-empty isn't a dead page when programs exist
  }

  const head = `
    <thead>
      <tr>
        <th class="select-col"></th>
        <th>Site</th>
        <th>Status</th>
        <th>Pri</th>
        <th>Start</th>
        <th>Must-have</th>
        <th>List</th>
        <th>MoA</th>
        <th class="actions-col"></th>
      </tr>
    </thead>`;

  root.innerHTML = order
    .map((program) => {
      const rows = groups.get(program) || [];
      const ganttLink =
        program === GANTT_DEFAULT_PROGRAM || program.toLowerCase().includes("lifecycle")
          ? `<a class="btn btn-sm" href="/gantt?program=${encodeURIComponent(program)}">Gantt</a>`
          : `<a class="btn btn-sm btn-quiet" href="/gantt?program=${encodeURIComponent(program)}">Enable Gantt</a>`;
      const body = rows.length
        ? rows.map(siteRowHtml).join("")
        : `<tr class="register-empty-row"><td colspan="9"><span class="hint">Drop sites here</span></td></tr>`;
      return `<section class="register-program" data-program="${escapeHtml(program)}">
        <div class="register-program-head">
          <h2 class="register-program-title">${escapeHtml(program)} <span class="hint">${rows.length}</span></h2>
          <div class="register-program-actions">${ganttLink}</div>
        </div>
        <div class="register-table-wrap">
          <table class="register-table">
            ${head}
            <tbody>${body}</tbody>
          </table>
        </div>
      </section>`;
    })
    .join("");
  syncBulkBar();
  wireProgramDragDrop();
}

async function loadAll() {
  const params = new URLSearchParams({ archived: "false" });
  const q = $("search")?.value?.trim() || "";
  const priority = $("priorityFilter")?.value || "";
  const stage = $("stageFilter")?.value || "";
  const council = $("councilFilter")?.value || "";
  const program = $("programFilter")?.value || "";
  const list = $("listFilter")?.value || "";
  if (q) params.set("q", q);
  if (priority) params.set("priority", priority);
  if (stage) params.set("stage", stage);
  if (council) params.set("council", council);
  if (program) params.set("program", program);
  if (list) params.set("client_list", list);

  setStatus("Loading active TGS / MoA jobs…");
  const [meta, columns, sites, generics] = await Promise.all([
    api("/api/meta"),
    api("/api/columns"),
    api(`/api/sites?${params}`),
    api("/api/sites/generic-moas").catch(() => []),
  ]);
  state.meta = meta;
  state.columns = columns;
  state.sites = Array.isArray(sites) ? sites : [];
  state.genericMoas = Array.isArray(generics) ? generics : [];
  fillFilterOptions();
  fillProgramSelect();
  fillGenericSelect();
  fillRoadList();
  const days = meta.priority_must_have_days ?? meta.priority_threshold_days ?? 14;
  const priOpt = $("priorityFilter")?.querySelector('option[value="1"]');
  if (priOpt) priOpt.textContent = `Priority 1 (≤ ${days}d)`;
  renderRegister();
  maybeScrollHighlight();
  const pri = state.sites.filter((s) => s.metrics?.on_permits_priority_list).length;
  const trims = state.sites.filter((s) => s.metrics?.on_trims_priority_list).length;
  setStatus(`${state.sites.length} active · ${pri} Permits · ${trims} TRIMS`);
}

function fillRoadList() {
  const list = $("roadList");
  if (!list) return;
  list.innerHTML = (state.meta.roads || [])
    .map((r) => `<option value="${escapeHtml(r)}"></option>`)
    .join("");
}

function maybeScrollHighlight() {
  if (!state.highlightId || state.highlightHandled) return;
  const row = document.querySelector(`tr[data-site-id="${state.highlightId}"]`);
  if (!row) return;
  state.highlightHandled = true;
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  const site = state.sites.find((s) => s.id === state.highlightId);
  if (site) setTimeout(() => openSiteDrawer(site), 300);
}

function fillProgramSelect(selected = "") {
  const sel = $("fProgram");
  if (!sel) return;
  const cur = selected || sel.value;
  sel.innerHTML =
    `<option value="">Select…</option>` +
    (state.meta.programs || [])
      .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
      .join("");
  if (cur) sel.value = cur;
}

function fillGenericSelect(selected = "") {
  const sel = $("fLinkedGeneric");
  if (!sel) return;
  const cur = selected != null && selected !== "" ? String(selected) : sel.value;
  const id = $("siteId")?.value;
  sel.innerHTML =
    `<option value="">None</option>` +
    state.genericMoas
      .filter((g) => String(g.id) !== String(id))
      .map(
        (g) =>
          `<option value="${g.id}">${escapeHtml(g.moa_number || g.site_number)} — ${escapeHtml(g.road_name)}</option>`
      )
      .join("");
  if (cur) sel.value = cur;
}

function renderCouncilRows(rows) {
  const list = rows?.length ? rows : [{ council_name: "", submitted_to_council_date: null, no_objection_date: null }];
  $("councilRows").innerHTML = list
    .map(
      (c, i) => `<div class="council-row">
        <input data-c="name" list="councilDatalist" placeholder="Council" value="${escapeHtml(c.council_name || "")}" />
        <label>Submitted<input data-c="submitted" type="date" value="${c.submitted_to_council_date || ""}" /></label>
        <label>No objection<input data-c="noobj" type="date" value="${c.no_objection_date || ""}" /></label>
        <button type="button" class="btn" data-rm-council="${i}">Remove</button>
      </div>`
    )
    .join("");
  let dl = $("councilDatalist");
  if (!dl) {
    dl = document.createElement("datalist");
    dl.id = "councilDatalist";
    document.body.appendChild(dl);
  }
  dl.innerHTML = (state.meta.councils || [])
    .map((c) => `<option value="${escapeHtml(c)}"></option>`)
    .join("");
}

function buildWorkflowChecks(wf) {
  $("workflowChecks").innerHTML = state.meta.workflow_stages
    .map(
      (s) => `<label class="wf-check">
        <input type="checkbox" name="wf_${s.key}" ${wf[s.key] ? "checked" : ""} />
        <span>${escapeHtml(s.label)}</span>
        ${s.list_role && s.list_role !== "none" ? `<em class="meta">${escapeHtml(s.list_role)}</em>` : ""}
      </label>`
    )
    .join("");
}

function buildCustomFields(values) {
  const grid = $("customFieldsGrid");
  if (!state.columns.length) {
    grid.innerHTML = `<p class="hint">No custom columns yet.</p>`;
    return;
  }
  grid.innerHTML = state.columns
    .map((c) => {
      const val = values?.[c.field_key] ?? "";
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

function setTab(name) {
  state.activeTab = name;
  document.querySelectorAll(".drawer-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.dataset.panel === name);
  });
}

function openDrawer() {
  const d = $("siteDrawer");
  d.hidden = false;
  d.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
}

function closeDrawer() {
  const d = $("siteDrawer");
  d.hidden = true;
  d.setAttribute("aria-hidden", "true");
  document.body.classList.remove("drawer-open");
  state.suppressAutosave = true;
  state.detailSiteId = null;
}

async function openSiteDrawer(site = null) {
  state.suppressAutosave = true;
  state.detailSiteId = site?.id || null;
  $("siteDialogTitle").textContent = site ? site.road_name : "Add site";
  $("drawerKicker").textContent = site
    ? `${site.site_number}${site.moa_number ? ` · MoA ${site.moa_number}` : ""}`
    : "New register row";
  $("siteId").value = site ? site.id : "";
  $("fRoad").value = site?.road_name || "";
  $("fSiteNo").value = site?.site_number || "";
  fillProgramSelect(site?.program || "");
  $("fTgs").value = site?.tgs_reference || "";
  $("fStart").value = site?.indicative_site_start_date || "";
  $("fMustHave").value = site?.moa_must_have_received_date || "";
  $("fMustManual").checked = !!site?.must_have_manual;
  $("fMoaNo").value = site?.moa_number || "";
  $("fMoaSub").value = site?.moa_submission_date || "";
  $("fMoaRec").value = site?.moa_received_date || "";
  $("fMoaStart").value = site?.moa_start_date || "";
  $("fMoaExp").value = site?.moa_expiry_date || "";
  $("fExtFlag").value = site?.extension_flag || "No";
  $("fExtSub").value = site?.extension_submission_date || "";
  $("fExtRec").value = site?.extension_received_date || "";
  $("fExtStart").value = site?.extension_start_date || "";
  $("fExtExp").value = site?.extension_expiry_date || "";
  $("fJobDone").value = site?.job_completed_date || "";
  $("fInclude").checked = site ? site.include_in_totals !== false : true;
  $("fGenericMoa").checked = !!site?.is_generic_moa;
  fillGenericSelect(site?.linked_generic_moa_id || "");
  renderCouncilRows(site?.council_details || []);
  $("fComments").value = site?.comments || "";
  $("fKml").value = "";
  const days = state.meta.council_no_objection_business_days ?? 10;
  if ($("councilHint")) {
    $("councilHint").textContent = `After ${days} business days without a response we assume no objection (Admin → Rules).`;
  }
  buildWorkflowChecks(site ? workflowMap(site) : {});
  buildCustomFields(site?.custom_fields || {});
  $("btnArchiveSite").hidden = !site;
  $("autosaveStatus").hidden = !site;
  $("autosaveStatus").textContent = site ? "Edits autosave." : "";
  setTab("overview");
  if (site) {
    $("activityHint").hidden = true;
    $("activityBody").hidden = false;
    $("btnOpenCosts").href = `/costs?site_id=${site.id}`;
    await Promise.all([refreshTracking(), refreshDocuments(), refreshCosts()]);
  } else {
    $("activityHint").hidden = false;
    $("activityBody").hidden = true;
  }
  openDrawer();
  queueMicrotask(() => {
    state.suppressAutosave = false;
  });
}

function collectCouncilRows() {
  return [...document.querySelectorAll("#councilRows .council-row")].map((row) => ({
    council_name: row.querySelector('[data-c="name"]').value.trim(),
    submitted_to_council_date: row.querySelector('[data-c="submitted"]').value || null,
    no_objection_date: row.querySelector('[data-c="noobj"]').value || null,
  }));
}

function collectCouncils() {
  return collectCouncilRows().filter((c) => c.council_name);
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
  const linked = $("fLinkedGeneric").value;
  return {
    road_name: $("fRoad").value.trim(),
    site_number: $("fSiteNo").value.trim(),
    program: $("fProgram").value.trim() || null,
    tgs_reference: $("fTgs").value.trim() || null,
    indicative_site_start_date: $("fStart").value || null,
    moa_must_have_received_date: $("fMustHave").value || null,
    must_have_manual: $("fMustManual").checked,
    moa_number: $("fMoaNo").value.trim() || null,
    moa_submission_date: $("fMoaSub").value || null,
    moa_received_date: $("fMoaRec").value || null,
    moa_start_date: $("fMoaStart").value || null,
    moa_expiry_date: $("fMoaExp").value || null,
    extension_flag: $("fExtFlag").value || "No",
    extension_submission_date: $("fExtSub").value || null,
    extension_received_date: $("fExtRec").value || null,
    extension_start_date: $("fExtStart").value || null,
    extension_expiry_date: $("fExtExp").value || null,
    job_completed_date: $("fJobDone").value || null,
    include_in_totals: $("fInclude").checked,
    is_generic_moa: $("fGenericMoa").checked,
    linked_generic_moa_id: linked ? Number(linked) : null,
    comments: $("fComments").value.trim() || null,
    councils: collectCouncils(),
    custom_fields,
    workflow,
  };
}

async function parseKmlFile(file) {
  if (!file) return null;
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/map/parse-kml", { method: "POST", body: fd });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Could not parse KML");
  }
  const data = await res.json();
  return { geometry: data.primary_geometry, name: data.primary_name || null };
}

async function saveSite(ev) {
  ev.preventDefault();
  const id = $("siteId").value;
  const payload = collectSitePayload();
  if (!payload.road_name || !payload.site_number) {
    alert("Road name and site number are required.");
    return;
  }
  try {
    const parsed = await parseKmlFile($("fKml").files?.[0]);
    if (parsed?.geometry) {
      payload.geometry = parsed.geometry;
      payload.geometry_name = parsed.name || payload.road_name;
    }
    let saved;
    if (id) {
      saved = await api(`/api/sites/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      saved = await api("/api/sites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    await loadAll();
    openSiteDrawer(saved);
    $("autosaveStatus").hidden = false;
    $("autosaveStatus").textContent = `Saved ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    alert(errorMessage(err, "Could not save site"));
  }
}

function scheduleAutosave() {
  if (state.suppressAutosave) return;
  const id = $("siteId")?.value;
  if (!id || $("siteDrawer")?.hidden) return;
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(async () => {
    try {
      const payload = collectSitePayload();
      if (!payload.road_name) delete payload.road_name;
      if (!payload.site_number) delete payload.site_number;
      const updated = await api(`/api/sites/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      $("autosaveStatus").hidden = false;
      $("autosaveStatus").textContent = `Saved ${new Date().toLocaleTimeString()}`;
      const idx = state.sites.findIndex((s) => s.id === Number(id));
      if (idx >= 0) state.sites[idx] = updated;
      else await loadAll();
      renderRegister();
      $("siteDialogTitle").textContent = updated.road_name;
      $("drawerKicker").textContent = `${updated.site_number}${
        updated.moa_number ? ` · MoA ${updated.moa_number}` : ""
      }`;
    } catch (err) {
      $("autosaveStatus").hidden = false;
      $("autosaveStatus").textContent = `Autosave failed: ${errorMessage(err, "unknown error")}`;
    }
  }, 700);
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
  state.selectedIds.delete(Number(id));
  closeDrawer();
  await loadAll();
}

async function bulkArchiveSelected() {
  const ids = [...state.selectedIds];
  if (!ids.length) return;
  if (!confirm(`Archive ${ids.length} selected site${ids.length === 1 ? "" : "s"}?`)) return;
  const fy = prompt("Archive to financial year (e.g. 2025-26). Leave blank to auto-detect:");
  if (fy === null) return;
  await api("/api/sites/bulk-archive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ site_ids: ids, financial_year: fy.trim() || null }),
  });
  state.selectedIds.clear();
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

function moneyFmt(n) {
  if (n == null) return "—";
  return `$${Number(n).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

async function refreshCosts() {
  if (!state.detailSiteId) return;
  const rows = await api(`/api/costs/estimates?site_id=${state.detailSiteId}`);
  $("costList").innerHTML = rows.length
    ? rows
        .map(
          (r) => `<li>
          <div class="top">
            <span>${escapeHtml(r.mode === "closure_24h" ? "24h closure" : "Standard")} · ${new Date(r.created_at).toLocaleString()}</span>
            <a class="btn btn-sm" href="/costs?site_id=${state.detailSiteId}">Open</a>
          </div>
          <p><strong>${escapeHtml(r.name)}</strong> — <span class="money">${moneyFmt(r.summary_total)}</span></p>
        </li>`
        )
        .join("")
    : `<li><p class="meta">No cost estimates yet.</p></li>`;
}

async function refreshTracking() {
  if (!state.detailSiteId) return;
  const events = await api(`/api/sites/${state.detailSiteId}/tracking`);
  $("trackList").innerHTML = events.length
    ? events
        .map(
          (e) => `
      <li>
        <div class="top">
          <span>${escapeHtml(e.event_type)} · ${escapeHtml(e.created_by || "anon")} · ${new Date(e.created_at).toLocaleString()}</span>
          <button type="button" class="btn btn-sm" data-del-track="${e.id}">Delete</button>
        </div>
        <p>${escapeHtml(e.message)}</p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No tracking yet.</p></li>`;
}

async function refreshDocuments() {
  if (!state.detailSiteId) return;
  const docs = await api(`/api/sites/${state.detailSiteId}/documents`);
  $("docList").innerHTML = docs.length
    ? docs
        .map(
          (d) => `
      <li>
        <div class="top">
          <span><span class="doc-cat">${escapeHtml(d.category)}</span> · ${(d.size_bytes / 1024).toFixed(1)} KB</span>
          <button type="button" class="btn btn-sm" data-del-doc="${d.id}">Delete</button>
        </div>
        <p><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a></p>
      </li>`
        )
        .join("")
    : `<li><p class="meta">No documents yet.</p></li>`;
}

async function addTracking() {
  const message = $("trackMessage").value.trim();
  if (!message || !state.detailSiteId) return;
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
  if (!state.detailSiteId) return;
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

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function bindEvents() {
  on("btnAddSite", "click", () => openSiteDrawer());
  on("btnColumns", "click", openColumns);
  on("btnAddColumn", "click", () => addColumn().catch((e) => alert(e.message)));
  on("btnArchiveSite", "click", () => archiveSite().catch((e) => alert(e.message)));
  on("btnAddTrack", "click", () => addTracking().catch((e) => alert(e.message)));
  on("btnUploadDoc", "click", () => uploadDoc().catch((e) => alert(e.message)));
  on("siteForm", "submit", (ev) =>
    saveSite(ev).catch((e) => alert(errorMessage(e, "Could not save site")))
  );
  on("colType", "change", () => {
    if ($("colOptionsWrap")) $("colOptionsWrap").hidden = $("colType").value !== "select";
  });
  on("search", "input", debounce(() => loadAll().catch(showLoadError), 250));
  ["priorityFilter", "stageFilter", "councilFilter", "programFilter", "listFilter"].forEach((id) => {
    on(id, "change", () => loadAll().catch(showLoadError));
  });

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-close-dialog]");
    if (btn) document.getElementById(btn.dataset.closeDialog)?.close();
    if (ev.target.closest("[data-close-drawer]")) closeDrawer();
    const tab = ev.target.closest(".drawer-tab");
    if (tab) setTab(tab.dataset.tab);
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && $("siteDrawer") && !$("siteDrawer").hidden) closeDrawer();
  });

  on("btnAddCouncil", "click", () => {
    const current = collectCouncilRows();
    current.push({ council_name: "", submitted_to_council_date: null, no_objection_date: null });
    renderCouncilRows(current);
  });
  on("councilRows", "click", (ev) => {
    const btn = ev.target.closest("[data-rm-council]");
    if (!btn) return;
    btn.closest(".council-row")?.remove();
    if (!$("councilRows")?.querySelector(".council-row")) renderCouncilRows([]);
    scheduleAutosave();
  });
  on("siteForm", "input", scheduleAutosave);
  on("siteForm", "change", scheduleAutosave);

  on("registerList", "click", (ev) => {
    if (state.suppressRowOpen) return;
    if (ev.target.closest("[data-status-select], .status-col, .select-col, .actions-col, a.btn, .drag-grip"))
      return;
    const btn = ev.target.closest("[data-action='open']");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const site = state.sites.find((s) => s.id === id);
    if (site) openSiteDrawer(site);
  });

  on("registerList", "change", (ev) => {
    const box = ev.target.closest("[data-select-id]");
    if (box) {
      const id = Number(box.getAttribute("data-select-id"));
      if (box.checked) state.selectedIds.add(id);
      else state.selectedIds.delete(id);
      syncBulkBar();
      return;
    }
    const sel = ev.target.closest("[data-status-select]");
    if (!sel) return;
    const id = sel.getAttribute("data-status-select");
    quickSetStatus(id, sel.value, sel).catch((e) => alert(e.message));
  });

  on("selectAllVisible", "change", (ev) => {
    const on = !!ev.target.checked;
    for (const site of state.sites) {
      if (on) state.selectedIds.add(site.id);
      else state.selectedIds.delete(site.id);
    }
    renderRegister();
  });
  on("btnClearSelection", "click", () => {
    state.selectedIds.clear();
    renderRegister();
  });
  on("btnBulkArchive", "click", () => {
    bulkArchiveSelected().catch((e) => alert(e.message || String(e)));
  });

  on("columnList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-col]");
    if (!btn) return;
    if (!confirm("Remove this column and clear its values from all sites?")) return;
    await api(`/api/columns/${btn.dataset.delCol}`, { method: "DELETE" });
    await loadAll();
    renderColumnList();
  });

  on("trackList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-track]");
    if (!btn) return;
    await api(`/api/sites/${state.detailSiteId}/tracking/${btn.dataset.delTrack}`, {
      method: "DELETE",
    });
    await refreshTracking();
  });

  on("docList", "click", async (ev) => {
    const btn = ev.target.closest("[data-del-doc]");
    if (!btn) return;
    if (!confirm("Delete this document?")) return;
    await api(`/api/documents/${btn.dataset.delDoc}`, { method: "DELETE" });
    await refreshDocuments();
  });
}

function showLoadError(err) {
  const msg = err?.message || String(err);
  setStatus(`Failed to load: ${msg}`);
  showPageError("registerList", err, "Could not load sites");
}

async function init() {
  try {
    injectChrome({ active: "/", mode: "ops" });
    const params = new URLSearchParams(location.search);
    const hl = params.get("highlight");
    if (hl && Number(hl)) state.highlightId = Number(hl);
    bindEvents();
    await loadAll();
  } catch (err) {
    showLoadError(err);
  }
}

init().catch((err) => {
  showLoadError(err);
  console.error(err);
});
