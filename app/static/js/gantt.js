import { $, api, escapeHtml, fmtDate, injectChrome, on, showPageError } from "./common.js";

const DEFAULT_PROGRAM = "Lifecycle pavements";
const state = {
  meta: null,
  board: null,
  sites: [],
  subcontractors: [],
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
  const programs = state.meta?.programs?.length
    ? state.meta.programs
    : [DEFAULT_PROGRAM];
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
  $("addSub").innerHTML =
    `<option value="">Board calendar</option>` +
    state.subcontractors
      .filter((s) => s.active)
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
      .join("");
}

function applyBoardForm() {
  const b = state.board;
  if (!b) return;
  $("anchorStart").value = b.anchor_start || "";
  $("skipPh").value = b.skip_public_holidays ? "1" : "0";
  $("skipSun").value = b.skip_sunday_before_monday_ph ? "1" : "0";
  $("boardRdos").value = (b.rdo_dates || []).join(", ");
}

function renderChart(items) {
  const chart = $("ganttChart");
  const dated = items.filter((i) => i.planned_start && i.planned_end);
  if (!dated.length) {
    chart.hidden = true;
    chart.innerHTML = "";
    return;
  }
  const starts = dated.map((i) => new Date(i.planned_start + "T00:00:00"));
  const ends = dated.map((i) => new Date(i.planned_end + "T00:00:00"));
  const min = new Date(Math.min(...starts));
  const max = new Date(Math.max(...ends));
  const span = Math.max(1, Math.round((max - min) / 86400000) + 1);
  chart.hidden = false;
  chart.innerHTML = dated
    .map((item) => {
      const s = new Date(item.planned_start + "T00:00:00");
      const e = new Date(item.planned_end + "T00:00:00");
      const left = Math.round(((s - min) / 86400000 / span) * 1000) / 10;
      const width = Math.max(2, Math.round((((e - s) / 86400000 + 1) / span) * 1000) / 10);
      return `<div class="gantt-row-bar">
        <div class="gantt-row-label">${escapeHtml(item.site_road_name || "Site")}</div>
        <div class="gantt-track">
          <div class="gantt-bar" style="left:${left}%;width:${width}%" title="${fmtDate(item.planned_start)} – ${fmtDate(item.planned_end)} · ${item.shifts_count} shifts"></div>
        </div>
      </div>`;
    })
    .join("");
}

function renderItems() {
  const items = state.board?.items || [];
  const list = $("ganttList");
  if (!items.length) {
    list.innerHTML = `<p class="hint">No sites on this Gantt yet. Sync program sites or add one below.</p>`;
    renderChart([]);
    return;
  }
  list.innerHTML = `<div class="gantt-sequence" id="seqList">
    ${items
      .map(
        (item, idx) => `<div class="gantt-item" draggable="true" data-item-id="${item.id}">
        <div class="gantt-item-handle" title="Drag to reorder" aria-hidden="true">⋮⋮</div>
        <div class="gantt-item-main">
          <div class="site-title">${idx + 1}. ${escapeHtml(item.site_road_name || "Site")}</div>
          <div class="site-meta mono">${escapeHtml(item.site_number || "")}
            · ${fmtDate(item.planned_start) || "—"} → ${fmtDate(item.planned_end) || "—"}
            ${item.subcontractor_name ? ` · ${escapeHtml(item.subcontractor_name)}` : ""}
            ${item.error ? ` · <span class="must-have late">${escapeHtml(item.error)}</span>` : ""}
          </div>
        </div>
        <label class="gantt-shifts">Shifts
          <input type="number" min="1" value="${item.shifts_count}" data-shifts="${item.id}" />
        </label>
        <label class="gantt-sub">Sub
          <select data-sub="${item.id}">
            <option value="">Board</option>
            ${state.subcontractors
              .filter((s) => s.active)
              .map(
                (s) =>
                  `<option value="${s.id}" ${
                    item.subcontractor_id === s.id ? "selected" : ""
                  }>${escapeHtml(s.name)}</option>`
              )
              .join("")}
          </select>
        </label>
        <button type="button" class="btn btn-sm" data-up="${item.id}" ${idx === 0 ? "disabled" : ""}>Up</button>
        <button type="button" class="btn btn-sm" data-down="${item.id}" ${
          idx === items.length - 1 ? "disabled" : ""
        }>Down</button>
        <button type="button" class="btn btn-danger btn-sm" data-rm="${item.id}">Remove</button>
      </div>`
      )
      .join("")}
  </div>`;
  renderChart(items);
  wireDrag();
}

function wireDrag() {
  const root = $("seqList");
  if (!root) return;
  root.querySelectorAll(".gantt-item").forEach((el) => {
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
      const items = [...root.querySelectorAll(".gantt-item")];
      const dragEl = items.find((i) => Number(i.dataset.itemId) === state.dragId);
      if (!dragEl || dragEl === over) return;
      const dragIndex = items.indexOf(dragEl);
      const overIndex = items.indexOf(over);
      if (dragIndex < overIndex) over.after(dragEl);
      else over.before(dragEl);
    });
    el.addEventListener("drop", async (ev) => {
      ev.preventDefault();
      const ids = [...root.querySelectorAll(".gantt-item")].map((i) => Number(i.dataset.itemId));
      await reorder(ids);
    });
  });
}

async function loadBoard() {
  const prog = program();
  state.board = await api(`/api/gantt/board?program=${encodeURIComponent(prog)}`);
  applyBoardForm();
  fillAddControls();
  renderItems();
  $("ganttHint").textContent = state.board.anchor_start
    ? "Drag rows to reorder — dates cascade from the anchor"
    : "Set an anchor start date so the sequence can schedule";
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
    }),
  });
  applyBoardForm();
  fillAddControls();
  renderItems();
}

async function reorder(itemIds) {
  state.board = await api(`/api/gantt/board/reorder?program=${encodeURIComponent(program())}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_ids: itemIds }),
  });
  fillAddControls();
  renderItems();
}

async function move(itemId, dir) {
  const ids = (state.board.items || []).map((i) => i.id);
  const idx = ids.indexOf(itemId);
  const swap = idx + dir;
  if (idx < 0 || swap < 0 || swap >= ids.length) return;
  [ids[idx], ids[swap]] = [ids[swap], ids[idx]];
  await reorder(ids);
}

async function init() {
  await injectChrome({ active: "/gantt", mode: "ops" });
  const params = new URLSearchParams(location.search);
  const prog = params.get("program") || DEFAULT_PROGRAM;
  const [meta, sites, subs] = await Promise.all([
    api("/api/meta"),
    api("/api/sites?archived=false"),
    api("/api/asphalt/subcontractors?active_only=true"),
  ]);
  state.meta = meta;
  state.sites = sites;
  state.subcontractors = subs;
  fillPrograms(prog);
  await loadBoard();

  on("programSelect", "change", () => {
    const url = new URL(location.href);
    url.searchParams.set("program", program());
    history.replaceState({}, "", url);
    loadBoard().catch((e) => alert(e.message));
  });
  on("btnSaveBoard", "click", () => saveBoard().catch((e) => alert(e.message)));
  on("btnSyncSites", "click", async () => {
    state.board = await api(
      `/api/gantt/board/sync-program-sites?program=${encodeURIComponent(program())}`,
      { method: "POST" }
    );
    fillAddControls();
    renderItems();
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
        subcontractor_id: Number($("addSub").value || 0) || null,
      }),
    });
    fillAddControls();
    renderItems();
  });
  on("ganttList", "click", async (ev) => {
    const up = ev.target.closest("[data-up]");
    const down = ev.target.closest("[data-down]");
    const rm = ev.target.closest("[data-rm]");
    if (up) return move(Number(up.dataset.up), -1).catch((e) => alert(e.message));
    if (down) return move(Number(down.dataset.down), 1).catch((e) => alert(e.message));
    if (rm) {
      if (!confirm("Remove this site from the Gantt?")) return;
      state.board = await api(
        `/api/gantt/board/items/${rm.dataset.rm}?program=${encodeURIComponent(program())}`,
        { method: "DELETE" }
      );
      fillAddControls();
      renderItems();
    }
  });
  on("ganttList", "change", async (ev) => {
    const shifts = ev.target.closest("[data-shifts]");
    const sub = ev.target.closest("[data-sub]");
    if (shifts) {
      state.board = await api(
        `/api/gantt/board/items/${shifts.dataset.shifts}?program=${encodeURIComponent(program())}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ shifts_count: Number(shifts.value || 1) }),
        }
      );
      renderItems();
    }
    if (sub) {
      state.board = await api(
        `/api/gantt/board/items/${sub.dataset.sub}?program=${encodeURIComponent(program())}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subcontractor_id: Number(sub.value || 0) || null }),
        }
      );
      renderItems();
    }
  });
}

init().catch((e) => showPageError("ganttList", e, "Could not load Gantt"));
