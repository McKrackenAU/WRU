import { $, api, escapeHtml, injectChrome, isCommsUser, showPageError, alertDialog } from "./common.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

let cursor = new Date();
cursor.setDate(1);
let items = [];
let selected = null;

function ymd(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthLabel(d) {
  return d.toLocaleString(undefined, { month: "long", year: "numeric" });
}

function startOfGrid(d) {
  const first = new Date(d.getFullYear(), d.getMonth(), 1);
  const dow = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - dow);
  return start;
}

function findItem(rowId, fieldKey) {
  return items.find((i) => Number(i.row_id) === Number(rowId) && i.field_key === fieldKey) || null;
}

function fmtWhen(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function render() {
  $("calMonthLabel").textContent = monthLabel(cursor);
  const start = startOfGrid(cursor);
  const today = ymd(new Date());
  const byDay = new Map();
  for (const item of items) {
    if (!item.due_date) continue;
    const list = byDay.get(item.due_date) || [];
    list.push(item);
    byDay.set(item.due_date, list);
  }
  const cells = [];
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const key = ymd(day);
    const inMonth = day.getMonth() === cursor.getMonth();
    const dayItems = byDay.get(key) || [];
    cells.push(`<div class="comms-cal-day ${inMonth ? "" : "is-outside"} ${key === today ? "is-today" : ""}">
      <span class="comms-cal-num">${day.getDate()}</span>
      <div class="comms-cal-items">
        ${dayItems
          .map((item) => {
            const open = selected && Number(selected.row_id) === Number(item.row_id) && selected.field_key === item.field_key;
            const notes = item.note_count ? `<span class="comms-cal-note-count">${item.note_count}</span>` : "";
            return `<button type="button" class="comms-cal-item is-${escapeHtml(item.color)}${open ? " is-open" : ""}" data-cal-item data-row="${item.row_id}" data-field="${escapeHtml(item.field_key)}" title="${escapeHtml(item.title)}">${escapeHtml(item.field_name)}${notes}</button>`;
          })
          .join("")}
      </div>
    </div>`);
  }
  $("calGrid").innerHTML = `<div class="comms-cal-weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>
    <div class="comms-cal-days">${cells.join("")}</div>`;
}

function renderNoteTags(item) {
  const wrap = $("calNoteTags");
  if (!wrap) return;
  const tags = item.tags || [];
  wrap.innerHTML = tags.length
    ? tags.map((t) => `<span class="tag-chip is-readonly">${escapeHtml(t)}</span>`).join("")
    : "";
}

function renderNotes(notes) {
  const list = $("calNoteList");
  if (!list) return;
  if (!notes.length) {
    list.innerHTML = `<p class="hint">No notes yet. Add one below — Comms will be notified.</p>`;
    return;
  }
  list.innerHTML = notes
    .map(
      (n) => `<article class="cal-note-item">
        <header><strong>${escapeHtml(n.created_by || "Someone")}</strong><time>${escapeHtml(fmtWhen(n.created_at))}</time></header>
        <p>${escapeHtml(n.body || "")}</p>
      </article>`
    )
    .join("");
}

async function loadNotes(item) {
  const data = await api(
    `/api/calendar/comms/notes?row_id=${encodeURIComponent(item.row_id)}&field_key=${encodeURIComponent(item.field_key)}`
  );
  renderNotes(data.items || []);
}

async function openItem(item) {
  selected = item;
  const panel = $("calNotePanel");
  if (panel) panel.hidden = false;
  $("calNoteTitle").textContent = item.title || item.field_name || "Calendar item";
  const due = item.due_date || "no date";
  $("calNoteMeta").textContent = `${item.status || "open"} · due ${due}`;
  renderNoteTags(item);
  const planner = $("calNotePlanner");
  const plannerLink = $("calNotePlannerLink");
  if (planner && plannerLink) {
    const show = isCommsUser() && item.planner_link;
    planner.hidden = !show;
    plannerLink.href = item.planner_link || "/comms";
  }
  render();
  try {
    await loadNotes(item);
  } catch (err) {
    $("calNoteList").innerHTML = `<p class="hint">${escapeHtml(err.message || "Could not load notes")}</p>`;
  }
  const params = new URLSearchParams(location.search);
  params.set("row", String(item.row_id));
  params.set("field", item.field_key);
  history.replaceState(null, "", `${location.pathname}?${params.toString()}`);
  $("calNoteBody")?.focus();
}

function closePanel() {
  selected = null;
  const panel = $("calNotePanel");
  if (panel) panel.hidden = true;
  const params = new URLSearchParams(location.search);
  params.delete("row");
  params.delete("field");
  const q = params.toString();
  history.replaceState(null, "", q ? `${location.pathname}?${q}` : location.pathname);
  render();
}

function applyDeepLink() {
  const params = new URLSearchParams(location.search);
  const row = params.get("row");
  const field = params.get("field");
  if (!row || !field) return false;
  const item = findItem(row, field);
  if (!item) return false;
  if (item.due_date) {
    cursor = new Date(`${item.due_date}T00:00:00`);
    cursor.setDate(1);
  }
  openItem(item);
  return true;
}

async function load() {
  const data = await api("/api/calendar/comms");
  items = data.items || [];
  const c = data.counts || {};
  $("calCounts").textContent = `${c.overdue || 0} overdue · ${c.open || 0} open · ${c.completed || 0} done`;
  if (!applyDeepLink()) render();
}

async function init() {
  await injectChrome({ active: "/calendar" });
  onNav();
  $("calGrid")?.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-cal-item]");
    if (!btn) return;
    ev.preventDefault();
    const item = findItem(btn.dataset.row, btn.dataset.field);
    if (item) openItem(item);
  });
  $("calNoteClose")?.addEventListener("click", () => closePanel());
  $("calNoteForm")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!selected) return;
    const body = $("calNoteBody")?.value.trim();
    if (!body) return;
    try {
      await api("/api/calendar/comms/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          row_id: selected.row_id,
          field_key: selected.field_key,
          body,
        }),
      });
      $("calNoteBody").value = "";
      selected.note_count = (Number(selected.note_count) || 0) + 1;
      render();
      await loadNotes(selected);
    } catch (err) {
      alertDialog(err.message || String(err));
    }
  });
  await load();
}

function onNav() {
  $("calPrev")?.addEventListener("click", () => {
    cursor.setMonth(cursor.getMonth() - 1);
    render();
  });
  $("calNext")?.addEventListener("click", () => {
    cursor.setMonth(cursor.getMonth() + 1);
    render();
  });
  $("calToday")?.addEventListener("click", () => {
    cursor = new Date();
    cursor.setDate(1);
    render();
  });
}

init().catch((e) => {
  showPageError("calGrid", e, "Could not load the comms calendar");
});
