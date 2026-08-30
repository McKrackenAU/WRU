import { $, api, escapeHtml, injectChrome, isCommsUser, showPageError } from "./common.js";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

let cursor = new Date();
cursor.setDate(1);
let items = [];

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
            const href = isCommsUser() ? item.link || "/comms" : "#";
            return `<a class="comms-cal-item is-${escapeHtml(item.color)}" href="${escapeHtml(href)}" title="${escapeHtml(item.title)}">${escapeHtml(item.field_name)}</a>`;
          })
          .join("")}
      </div>
    </div>`);
  }
  $("calGrid").innerHTML = `<div class="comms-cal-weekdays">${WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>
    <div class="comms-cal-days">${cells.join("")}</div>`;
}

async function load() {
  const data = await api("/api/calendar/comms");
  items = data.items || [];
  const c = data.counts || {};
  $("calCounts").textContent = `${c.overdue || 0} overdue · ${c.open || 0} open · ${c.completed || 0} done`;
  render();
}

async function init() {
  await injectChrome({ active: "/calendar" });
  onNav();
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
