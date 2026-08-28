import {
  $,
  api,
  on,
  escapeHtml,
  fmtDate,
  injectChrome,
  alertDialog,
  confirmDialog,
  showPageError,
  onLiveSitesChanged,
  syncLiveRevision,
} from "./common.js";

const DEFAULT_PROGRAM = "Lifecycle pavements";
const state = {
  meta: null,
  board: null,
  sites: [],
  dragId: null,
};

function program() {
  return $("programSelect")?.value || DEFAULT_PROGRAM;
}

function parseDates(raw) {
  return String(raw || "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function fillPrograms(selected) {
  const sel = $("programSelect");
  const programs = state.meta?.programs?.length ? state.meta.programs : [DEFAULT_PROGRAM];
  const set = new Set(programs);
  if (selected) set.add(selected);
  sel.innerHTML = [...set]
    .map((p) => `<option value="${escapeHtml(p)}" ${p === selected ? "selected" : ""}>${escapeHtml(p)}</option>`)
    .join("");
}

function fillAddControls() {
  const onBoard = new Set((state.board?.items || []).map((i) => i.site_id));
  const prog = program();
  const candidates = state.sites.filter(
    (s) => !onBoard.has(s.id) && (!prog || (s.program || "") === prog)
  );
  $("addSite").innerHTML = candidates.length
    ? candidates
        .map(
          (s) =>
            `<option value="${s.id}">${escapeHtml(s.road_name)} · ${escapeHtml(s.site_number)}</option>`
        )
        .join("")
    : `<option value="">No sites left to add</option>`;
  syncAddShiftsFromSite();
}

function siteIndicativeShifts(site) {
  const n = Number(site?.indicative_shifts_count);
  if (!Number.isFinite(n) || n < 1) return null;
  return Math.min(365, Math.round(n));
}

function syncAddShiftsFromSite() {
  const id = Number($("addSite")?.value || 0);
  const site = state.sites.find((s) => s.id === id);
  const n = siteIndicativeShifts(site);
  if ($("addShifts")) $("addShifts").value = String(n || 1);
  const night = site?.indicative_shift_type === "night";
  if ($("addShiftDay")) $("addShiftDay").checked = !night;
  if ($("addShiftNight")) $("addShiftNight").checked = night;
}

function addShiftType() {
  if ($("addShiftNight")?.checked && !$("addShiftDay")?.checked) return "night";
  return "day";
}

function wireShiftPair(dayEl, nightEl) {
  if (!dayEl || !nightEl) return;
  const sync = (from) => {
    if (from === "day" && dayEl.checked) nightEl.checked = false;
    if (from === "night" && nightEl.checked) dayEl.checked = false;
    if (!dayEl.checked && !nightEl.checked) dayEl.checked = true;
  };
  dayEl.addEventListener("change", () => sync("day"));
  nightEl.addEventListener("change", () => sync("night"));
}

function pdfExportHref() {
  return `/api/gantt/board/export.pdf?${new URLSearchParams({ program: program() })}`;
}

function syncPdfLink() {
  const btn = $("btnExportPdf");
  if (btn) btn.href = pdfExportHref();
}

function applyBoardForm() {
  const b = state.board;
  if (!b) return;
  $("anchorStart").value = b.anchor_start || "";
  $("skipPh").value = b.skip_public_holidays ? "1" : "0";
  $("skipSun").value = b.skip_sunday_before_monday_ph ? "1" : "0";
  $("boardRdos").value = (b.rdo_dates || []).join(", ");
  if ($("boardExclude")) $("boardExclude").value = (b.exclude_dates || []).join(", ");
}

function wireReorderList(root) {
  if (!root) return;
  root.querySelectorAll("[data-item-id]").forEach((el) => {
    el.addEventListener("dragstart", () => {
      state.dragId = Number(el.dataset.itemId);
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("dragging");
      state.dragId = null;
    });
    el.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      const over = ev.currentTarget;
      if (!state.dragId || Number(over.dataset.itemId) === state.dragId) return;
      const items = [...root.querySelectorAll("[data-item-id]")];
      const dragEl = items.find((i) => Number(i.dataset.itemId) === state.dragId);
      if (!dragEl || dragEl === over) return;
      const dragIndex = items.indexOf(dragEl);
      const overIndex = items.indexOf(over);
      if (dragIndex < overIndex) over.after(dragEl);
      else over.before(dragEl);
    });
    el.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      const ids = [...root.querySelectorAll("[data-item-id]")].map((i) => Number(i.dataset.itemId));
      await reorder(ids);
    });
  });
}

function renderChart(items) {
  const chart = $("ganttChart");
  const dated = items.filter((i) => i.planned_start && i.planned_end);
  if (!dated.length) {
    chart.innerHTML = `<p class="hint">No dated sites yet — set indicative start dates and shifts on the sites register, then refresh.</p>`;
    return;
  }
  const starts = dated.map((i) => new Date(i.planned_start + "T00:00:00"));
  const ends = dated.map((i) => new Date(i.planned_end + "T00:00:00"));
  const min = new Date(Math.min(...starts));
  const max = new Date(Math.max(...ends));
  const span = Math.max(1, Math.round((max - min) / 86400000) + 1);

  chart.innerHTML = `<div class="gantt-chart-list" id="chartList">
    ${dated
      .map((item, idx) => {
        const s = new Date(item.planned_start + "T00:00:00");
        const e = new Date(item.planned_end + "T00:00:00");
        const left = Math.round(((s - min) / 86400000 / span) * 1000) / 10;
        const width = Math.max(2, Math.round((((e - s) / 86400000 + 1) / span) * 1000) / 10);
        return `<div class="gantt-row-bar" draggable="true" data-item-id="${item.id}">
          <div class="gantt-row-label">
            <span class="gantt-item-handle" aria-hidden="true">⋮⋮</span>
            <span>${idx + 1}. ${escapeHtml(item.site_road_name || "Site")}</span>
            <span class="hint mono">${fmtDate(item.planned_start)} → ${fmtDate(item.planned_end)}</span>
          </div>
          <div class="gantt-track">
            <div class="gantt-bar" style="left:${left}%;width:${width}%" title="${fmtDate(
              item.planned_start
            )} – ${fmtDate(item.planned_end)} · ${item.shifts_count} ${item.shift_type || "day"}"></div>
          </div>
        </div>`;
      })
      .join("")}
  </div>`;
  wireReorderList($("chartList"));
}

function renderItems() {
  const items = state.board?.items || [];
  const list = $("ganttList");
  renderChart(items);
  if (!items.length) {
    list.innerHTML = `<p class="hint">No sites on this Gantt yet. Sites with this program auto-load from the register.</p>`;
    return;
  }
  list.innerHTML = `<div class="gantt-sequence" id="seqList">
    ${items
      .map(
        (item, idx) => `<div class="gantt-item" data-item-id="${item.id}">
        <div class="gantt-item-main">
          <div class="site-title">${idx + 1}. ${escapeHtml(item.site_road_name || "Site")}</div>
          <div class="site-meta mono">${escapeHtml(item.site_number || "")}
            · ${fmtDate(item.planned_start) || "—"} → ${fmtDate(item.planned_end) || "—"}
            · ${escapeHtml(item.shift_type || "day")}
            ${item.link_mode === "fixed_start" ? " · indicative" : " · cascaded"}
            ${item.error ? ` · <span class="must-have late">${escapeHtml(item.error)}</span>` : ""}
          </div>
        </div>
        <label class="gantt-shifts">Shifts
          <input type="number" min="1" value="${item.shifts_count}" data-shifts="${item.id}" />
        </label>
        <div class="gantt-shift-checks">
          <label class="check-row gantt-shift-check">
            <input type="checkbox" data-shift-day="${item.id}" ${item.shift_type === "night" ? "" : "checked"} />
            <span>Day</span>
          </label>
          <label class="check-row gantt-shift-check">
            <input type="checkbox" data-shift-night="${item.id}" ${item.shift_type === "night" ? "checked" : ""} />
            <span>Night</span>
          </label>
        </div>
        <button type="button" class="btn btn-danger btn-sm" data-rm="${item.id}">Remove</button>
      </div>`
      )
      .join("")}
  </div>`;
}

async function loadBoard() {
  const prog = program();
  state.board = await api(`/api/gantt/board?program=${encodeURIComponent(prog)}`);
  applyBoardForm();
  fillAddControls();
  renderItems();
  syncPdfLink();
  updateGanttHint();
}

function updateGanttHint() {
  const cascading = (state.board?.items || []).some((i) => i.link_mode === "after_previous");
  const saved = Boolean(state.board?.schedule_saved);
  if (!$("ganttHint")) return;
  $("ganttHint").textContent = saved
    ? "Saved Gantt — edit Day/Night, weather dates, or order, then Save again. Refresh from sites rebuilds from the register."
    : cascading
      ? "Drag bars to reorder — dates cascade from the top site. Save Gantt to keep this sequence after export."
      : "Bars use each site’s indicative start — Save Gantt to lock the sequence for later edits.";
}

function christmasShutdownRange(year) {
  // Inclusive shutdown covering Christmas Eve through the day after New Year.
  const dates = [];
  const start = new Date(Date.UTC(year, 11, 24));
  const end = new Date(Date.UTC(year + 1, 0, 2));
  for (let t = start.getTime(); t <= end.getTime(); t += 86400000) {
    dates.push(new Date(t).toISOString().slice(0, 10));
  }
  return dates;
}

function mergeIsoDates(...lists) {
  return [...new Set(lists.flat().filter(Boolean))].sort();
}

function addChristmasShutdown() {
  const existing = parseDates($("boardExclude")?.value);
  const year = Number(($("anchorStart")?.value || "").slice(0, 4)) || new Date().getFullYear();
  const range = christmasShutdownRange(year);
  const merged = mergeIsoDates(existing, range);
  $("boardExclude").value = merged.join(", ");
  const hint = $("xmasHint");
  if (hint) {
    hint.textContent = `Added ${range[0]} → ${range[range.length - 1]}. Save Gantt to apply.`;
  }
}

async function saveBoard() {
  state.board = await api(`/api/gantt/board?program=${encodeURIComponent(program())}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      anchor_start: $("anchorStart").value || null,
      skip_public_holidays: $("skipPh").value === "1",
      skip_sunday_before_monday_ph: $("skipSun").value === "1",
      rdo_dates: parseDates($("boardRdos").value),
      exclude_dates: parseDates($("boardExclude")?.value),
      schedule_saved: true,
    }),
  });
  applyBoardForm();
  fillAddControls();
  renderItems();
  updateGanttHint();
}

async function reorder(itemIds) {
  state.board = await api(`/api/gantt/board/reorder?program=${encodeURIComponent(program())}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_ids: itemIds }),
  });
  applyBoardForm();
  fillAddControls();
  renderItems();
}

async function init() {
  await injectChrome({ active: "/gantt", mode: "ops" });
  const params = new URLSearchParams(location.search);
  const prog = params.get("program") || DEFAULT_PROGRAM;
  const [meta, sites] = await Promise.all([
    api("/api/meta"),
    api("/api/sites?archived=false"),
  ]);
  state.meta = meta;
  state.sites = sites;
  fillPrograms(prog);
  syncPdfLink();
  wireShiftPair($("addShiftDay"), $("addShiftNight"));
  on("addSite", "change", () => syncAddShiftsFromSite());
  onLiveSitesChanged(() => loadBoard().catch(() => {}));
  await loadBoard();
  await syncLiveRevision();

  on("programSelect", "change", () => {
    const url = new URL(location.href);
    url.searchParams.set("program", program());
    history.replaceState({}, "", url);
    loadBoard().catch((e) => { alertDialog(e.message); });
  });
  on("btnSaveBoard", "click", () => saveBoard().catch((e) => { alertDialog(e.message); }));
  on("btnXmasShutdown", "click", () => addChristmasShutdown());
  on("btnSyncSites", "click", async () => {
    if (state.board?.schedule_saved) {
      if (
        !(await confirmDialog(
          "Rebuild this Gantt from site indicative starts and shifts? Saved order and dates will be replaced. Weather / missed days on the board calendar are kept."
        ))
      ) {
        return;
      }
    }
    state.board = await api(
      `/api/gantt/board/sync-program-sites?program=${encodeURIComponent(program())}&unlock=1`,
      { method: "POST" }
    );
    applyBoardForm();
    fillAddControls();
    renderItems();
    syncPdfLink();
    updateGanttHint();
  });
  on("addItemForm", "submit", async (e) => {
    e.preventDefault();
    const siteId = Number($("addSite").value);
    if (!siteId) return;
    state.board = await api(`/api/gantt/board/items?program=${encodeURIComponent(program())}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site_id: siteId,
        shifts_count: Number($("addShifts").value || 1),
        shift_type: addShiftType(),
      }),
    });
    fillAddControls();
    renderItems();
    syncPdfLink();
  });
  on("ganttList", "click", async (ev) => {
    const rm = ev.target.closest("[data-rm]");
    if (!rm) return;
    if (!await confirmDialog("Remove this site from the Gantt?")) return;
    state.board = await api(
      `/api/gantt/board/items/${rm.dataset.rm}?program=${encodeURIComponent(program())}`,
      { method: "DELETE" }
    );
    fillAddControls();
    renderItems();
    syncPdfLink();
  });
  on("ganttList", "change", async (ev) => {
    const shifts = ev.target.closest("[data-shifts]");
    const shiftDay = ev.target.closest("[data-shift-day]");
    const shiftNight = ev.target.closest("[data-shift-night]");
    if (shifts) {
      state.board = await api(
        `/api/gantt/board/items/${shifts.dataset.shifts}?program=${encodeURIComponent(program())}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ shifts_count: Number(shifts.value || 1) }),
        }
      );
      applyBoardForm();
      renderItems();
    }
    if (shiftDay || shiftNight) {
      const box = shiftDay || shiftNight;
      const itemId = Number(box.dataset.shiftDay || box.dataset.shiftNight);
      const row = box.closest("[data-item-id]");
      const dayBox = row?.querySelector("[data-shift-day]");
      const nightBox = row?.querySelector("[data-shift-night]");
      if (shiftNight && nightBox?.checked && dayBox) dayBox.checked = false;
      if (shiftDay && dayBox?.checked && nightBox) nightBox.checked = false;
      if (dayBox && nightBox && !dayBox.checked && !nightBox.checked) dayBox.checked = true;
      const shiftType = nightBox?.checked && !dayBox?.checked ? "night" : "day";
      state.board = await api(
        `/api/gantt/board/items/${itemId}?program=${encodeURIComponent(program())}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ shift_type: shiftType }),
        }
      );
      applyBoardForm();
      renderItems();
    }
  });
}

init().catch((e) => showPageError("ganttChart", e, "Could not load Gantt"));
