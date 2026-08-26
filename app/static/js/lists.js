import {
  $,
  api,
  escapeHtml,
  fmtDate,
  injectChrome,
  alertDialog,
  onLiveSitesChanged,
  syncLiveRevision,
} from "./common.js";

const state = {
  permits: [],
  trims: [],
  programs: new Set(),
  priorities: new Set(["1", "2"]),
  selectedPrograms: new Set(),
  selectedPriorities: new Set(["1", "2"]),
  sortKey: "start",
  sortDir: "asc",
};

function progressBar(pct) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<div class="progress-bar thin" title="${p}%"><span style="width:${p}%;background:hsl(${(p * 1.2).toFixed(0)},65%,40%)"></span></div>`;
}

function councilWait(site) {
  const wait = site.metrics?.max_council_business_days_waiting;
  if (wait != null) return `${wait} bus. days`;
  const rows = site.metrics?.councils || [];
  if (!rows.length) return "—";
  const assumed = rows.find((c) => c.status === "assumed_no_objection");
  if (assumed) return "Assumed OK";
  if (rows.every((c) => c.status === "no_objection" || c.status === "assumed_no_objection")) {
    return "No objection";
  }
  return "—";
}

function councilSortValue(site) {
  const wait = site.metrics?.max_council_business_days_waiting;
  return wait == null ? -1 : Number(wait);
}

function sortValue(site, key) {
  switch (key) {
    case "pri":
      return Number(site.today_priority) || 99;
    case "road":
      return (site.road_name || "").toLowerCase();
    case "site":
      return (site.site_number || "").toLowerCase();
    case "program":
      return (site.program || "").toLowerCase();
    case "start":
      return site.indicative_site_start_date || "9999-99-99";
    case "council":
      return councilSortValue(site);
    case "moa":
      return (site.moa_number || "").toLowerCase();
    default:
      return "";
  }
}

function compareSites(a, b) {
  const av = sortValue(a, state.sortKey);
  const bv = sortValue(b, state.sortKey);
  let cmp = 0;
  if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
  else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
  if (cmp === 0) {
    cmp = String(a.road_name || "").localeCompare(String(b.road_name || ""), undefined, {
      sensitivity: "base",
    });
  }
  return state.sortDir === "desc" ? -cmp : cmp;
}

function passesFilters(site) {
  const pri = String(site.today_priority || "");
  if (state.selectedPriorities.size && !state.selectedPriorities.has(pri)) return false;
  const program = (site.program || "").trim() || "Unassigned";
  if (state.selectedPrograms.size && !state.selectedPrograms.has(program)) return false;
  return true;
}

function visibleSites(all) {
  return [...all].filter(passesFilters).sort(compareSites);
}

function renderRows(tbodyId, sites) {
  const tbody = $(tbodyId);
  const rows = visibleSites(sites);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td class="empty" colspan="8">No applications match these filters.</td></tr>`;
    return rows;
  }
  tbody.innerHTML = rows
    .map(
      (s) => `<tr class="lists-row" data-open-id="${s.id}">
      <td class="col-pri"><span class="priority p${s.today_priority}">${s.today_priority}</span></td>
      <td class="col-road"><strong>${escapeHtml(s.road_name)}</strong>${progressBar(s.metrics?.workflow_progress_pct)}</td>
      <td class="col-site mono">${escapeHtml(s.site_number)}</td>
      <td class="col-program">${escapeHtml(s.program || "")}</td>
      <td class="col-start mono">${fmtDate(s.indicative_site_start_date) || "—"}</td>
      <td class="col-council">${escapeHtml(councilWait(s))}</td>
      <td class="col-moa mono">${escapeHtml(s.moa_number || "")}</td>
      <td class="col-open">
        <a class="btn btn-primary btn-sm" href="/?highlight=${s.id}">Open</a>
      </td>
    </tr>`
    )
    .join("");
  return rows;
}

function renderFilterControls() {
  const priHost = $("filterPriority");
  const progHost = $("filterProgram");
  if (priHost) {
    priHost.innerHTML = [...state.priorities]
      .sort()
      .map(
        (p) => `<label class="lists-check">
          <input type="checkbox" data-filter-pri="${escapeHtml(p)}" ${
            state.selectedPriorities.has(p) ? "checked" : ""
          } /> Pri ${escapeHtml(p)}
        </label>`
      )
      .join("");
  }
  if (progHost) {
    const programs = [...state.programs].sort((a, b) => a.localeCompare(b));
    progHost.innerHTML = programs.length
      ? programs
          .map(
            (p) => `<label class="lists-check">
              <input type="checkbox" data-filter-program="${escapeHtml(p)}" ${
                state.selectedPrograms.has(p) ? "checked" : ""
              } /> ${escapeHtml(p)}
            </label>`
          )
          .join("")
      : `<span class="hint">No programs yet</span>`;
  }
}

function syncSortHeaders() {
  document.querySelectorAll(".th-sort").forEach((btn) => {
    const key = btn.dataset.sort;
    const active = key === state.sortKey;
    btn.classList.toggle("is-active", active);
    if (active) {
      btn.dataset.dir = state.sortDir;
      btn.setAttribute("aria-sort", state.sortDir === "asc" ? "ascending" : "descending");
    } else {
      btn.removeAttribute("data-dir");
      btn.removeAttribute("aria-sort");
    }
  });
}

function renderAll() {
  const permitsVisible = renderRows("permitsBody", state.permits);
  const trimsVisible = renderRows("trimsBody", state.trims);
  $("permitsHint").textContent = `${permitsVisible.length} of ${state.permits.length} with the Permits team`;
  $("trimsHint").textContent = `${trimsVisible.length} of ${state.trims.length} with the TRIMS team`;
  syncSortHeaders();
}

function rebuildProgramUniverse() {
  const previous = state.selectedPrograms;
  const known = state._knownPrograms || new Set();
  state.programs = new Set();
  for (const site of [...state.permits, ...state.trims]) {
    state.programs.add((site.program || "").trim() || "Unassigned");
  }
  if (!state._programsInitialized) {
    state.selectedPrograms = new Set(state.programs);
    state._programsInitialized = true;
  } else {
    const next = new Set();
    for (const p of state.programs) {
      if (previous.has(p) || !known.has(p)) next.add(p);
    }
    state.selectedPrograms = next;
  }
  state._knownPrograms = new Set(state.programs);
}

async function loadLists() {
  const [permits, trims] = await Promise.all([
    api("/api/sites?archived=false&client_list=permits"),
    api("/api/sites?archived=false&client_list=trims"),
  ]);
  state.permits = Array.isArray(permits) ? permits : [];
  state.trims = Array.isArray(trims) ? trims : [];
  rebuildProgramUniverse();
  renderFilterControls();
  renderAll();
}

function bindFilters() {
  $("filterPriority")?.addEventListener("change", (ev) => {
    const box = ev.target.closest("[data-filter-pri]");
    if (!box) return;
    const pri = box.getAttribute("data-filter-pri");
    if (box.checked) state.selectedPriorities.add(pri);
    else state.selectedPriorities.delete(pri);
    renderAll();
  });
  $("filterProgram")?.addEventListener("change", (ev) => {
    const box = ev.target.closest("[data-filter-program]");
    if (!box) return;
    const program = box.getAttribute("data-filter-program");
    if (box.checked) state.selectedPrograms.add(program);
    else state.selectedPrograms.delete(program);
    renderAll();
  });
  $("btnFiltersAll")?.addEventListener("click", () => {
    state.selectedPriorities = new Set(state.priorities);
    state.selectedPrograms = new Set(state.programs);
    renderFilterControls();
    renderAll();
  });
  $("btnFiltersClear")?.addEventListener("click", () => {
    state.selectedPriorities = new Set();
    state.selectedPrograms = new Set();
    renderFilterControls();
    renderAll();
  });
}

function bindSorting() {
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".th-sort");
    if (btn) {
      const key = btn.dataset.sort;
      if (!key) return;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      renderAll();
      return;
    }
    if (ev.target.closest("a, button, input, label")) return;
    const row = ev.target.closest("[data-open-id]");
    if (row?.dataset.openId) {
      location.href = `/?highlight=${encodeURIComponent(row.dataset.openId)}`;
    }
  });
}

async function init() {
  await injectChrome({ active: "/lists" });
  bindFilters();
  bindSorting();
  onLiveSitesChanged(() => loadLists().catch(() => {}));
  await loadLists();
  await syncLiveRevision();
}

init().catch((e) => {
  alertDialog(e.message);
});
