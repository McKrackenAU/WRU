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

const CAP_KEY = "wru-lists-cap";

const state = {
  permits: [],
  trims: [],
  programs: new Set(),
  priorities: new Set(["1", "2"]),
  selectedPrograms: new Set(),
  selectedPriorities: new Set(["1", "2"]),
  sortKey: "start",
  sortDir: "asc",
  cap: null,
  _programsInitialized: false,
  _knownPrograms: new Set(),
};

function parseCap(raw) {
  const n = Number.parseInt(String(raw ?? "").trim(), 10);
  if (!Number.isFinite(n) || n < 1) return null;
  return Math.min(500, n);
}

function loadCapPref() {
  try {
    state.cap = parseCap(localStorage.getItem(CAP_KEY));
  } catch {
    state.cap = null;
  }
}

function saveCapPref() {
  try {
    if (state.cap == null) localStorage.removeItem(CAP_KEY);
    else localStorage.setItem(CAP_KEY, String(state.cap));
  } catch {
    /* ignore */
  }
}

function syncCapInput() {
  const el = $("listCap");
  if (el) el.value = state.cap == null ? "" : String(state.cap);
}

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
  return wait == null ? Number.NEGATIVE_INFINITY : Number(wait);
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

function programKey(site) {
  return (site.program || "").trim() || "Unassigned";
}

function passesFilters(site) {
  // Unchecked = hidden. Empty selection = show none.
  const pri = String(site.today_priority ?? "");
  if (!state.selectedPriorities.has(pri)) return false;
  if (!state.selectedPrograms.has(programKey(site))) return false;
  return true;
}

function visibleSites(all) {
  const rows = [...all].filter(passesFilters).sort(compareSites);
  if (state.cap != null) return rows.slice(0, state.cap);
  return rows;
}

function listCountHint(shown, total, team) {
  if (state.cap != null && shown < total) {
    return `${shown} of ${total} with the ${team} (top ${state.cap})`;
  }
  return `${shown} of ${total} with the ${team}`;
}

function renderRows(tbodyId, sites) {
  const tbody = $(tbodyId);
  if (!tbody) return [];
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
      .map((p) => {
        const checked = state.selectedPriorities.has(p) ? "checked" : "";
        return `<label class="lists-check">
          <input type="checkbox" data-filter-pri="${escapeHtml(p)}" ${checked} />
          <span>Pri ${escapeHtml(p)}</span>
        </label>`;
      })
      .join("");
  }
  if (progHost) {
    const programs = [...state.programs].sort((a, b) => a.localeCompare(b));
    progHost.innerHTML = programs.length
      ? programs
          .map((p) => {
            const checked = state.selectedPrograms.has(p) ? "checked" : "";
            return `<label class="lists-check">
              <input type="checkbox" data-filter-program="${escapeHtml(p)}" ${checked} />
              <span>${escapeHtml(p)}</span>
            </label>`;
          })
          .join("")
      : `<span class="hint">No programs yet</span>`;
  }
}

function syncSortHeaders() {
  document.querySelectorAll(".lists-table [data-sort]").forEach((el) => {
    const key = el.getAttribute("data-sort");
    const active = key === state.sortKey;
    el.classList.toggle("is-active", active);
    if (active) {
      el.setAttribute("data-dir", state.sortDir);
      el.setAttribute("aria-sort", state.sortDir === "asc" ? "ascending" : "descending");
    } else {
      el.removeAttribute("data-dir");
      el.removeAttribute("aria-sort");
    }
  });
}

function renderAll() {
  const permitsVisible = renderRows("permitsBody", state.permits);
  const trimsVisible = renderRows("trimsBody", state.trims);
  if ($("permitsHint")) {
    $("permitsHint").textContent = listCountHint(permitsVisible.length, state.permits.length, "Permits team");
  }
  if ($("trimsHint")) {
    $("trimsHint").textContent = listCountHint(trimsVisible.length, state.trims.length, "TRIMS team");
  }
  syncSortHeaders();
  syncExportLinks();
}

function exportQuery() {
  const params = new URLSearchParams();
  if (state.cap != null) params.set("limit", String(state.cap));
  if (state.sortKey) params.set("sort", state.sortKey);
  params.set("dir", state.sortDir === "desc" ? "desc" : "asc");
  if (state.selectedPriorities.size === 0) params.append("priority", "");
  else [...state.selectedPriorities].forEach((p) => params.append("priority", p));
  if (state.selectedPrograms.size === 0) params.append("program", "");
  else [...state.selectedPrograms].forEach((p) => params.append("program", p));
  return params.toString();
}

function syncExportLinks() {
  const q = exportQuery();
  const label = state.cap != null ? `Export top ${state.cap} matching this page` : "Export all matching this page";
  document.querySelectorAll(".js-list-export[data-export]").forEach((a) => {
    const base = a.getAttribute("data-export");
    a.href = q ? `${base}?${q}` : base;
    a.title = label;
    const kind = (a.getAttribute("data-export-kind") || a.textContent.split("·")[0] || "Export").trim();
    if (!a.getAttribute("data-export-kind")) a.setAttribute("data-export-kind", kind);
    a.textContent = state.cap != null ? `${kind} · top ${state.cap}` : kind;
  });
}

function rebuildProgramUniverse() {
  const previous = state.selectedPrograms;
  const known = state._knownPrograms || new Set();
  state.programs = new Set();
  for (const site of [...state.permits, ...state.trims]) {
    state.programs.add(programKey(site));
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

function setSort(key) {
  if (!key) return;
  if (state.sortKey === key) {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = key;
    state.sortDir = "asc";
  }
  renderAll();
}

function bindFilters() {
  document.addEventListener("change", (ev) => {
    const pri = ev.target.closest("input[data-filter-pri]");
    if (pri) {
      const value = pri.getAttribute("data-filter-pri");
      if (pri.checked) state.selectedPriorities.add(value);
      else state.selectedPriorities.delete(value);
      renderAll();
      return;
    }
    const program = ev.target.closest("input[data-filter-program]");
    if (program) {
      const value = program.getAttribute("data-filter-program");
      if (program.checked) state.selectedPrograms.add(value);
      else state.selectedPrograms.delete(value);
      renderAll();
      return;
    }
    if (ev.target.id === "listCap") {
      state.cap = parseCap(ev.target.value);
      saveCapPref();
      renderAll();
    }
  });
  $("listCap")?.addEventListener("input", () => {
    state.cap = parseCap($("listCap").value);
    saveCapPref();
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
    const th = ev.target.closest(".lists-table thead th");
    const sortEl = th?.querySelector("[data-sort]") || ev.target.closest(".lists-table [data-sort]");
    if (sortEl) {
      ev.preventDefault();
      setSort(sortEl.getAttribute("data-sort"));
      return;
    }
    if (ev.target.closest("a, button, input, label, .lists-filters")) return;
    const row = ev.target.closest("[data-open-id]");
    if (row?.dataset.openId) {
      location.href = `/?highlight=${encodeURIComponent(row.dataset.openId)}`;
    }
  });
}

async function init() {
  await injectChrome({ active: "/lists" });
  loadCapPref();
  syncCapInput();
  bindFilters();
  bindSorting();
  onLiveSitesChanged(() => loadLists().catch(() => {}));
  await loadLists();
  await syncLiveRevision();
}

init().catch((e) => {
  alertDialog(e.message);
});
