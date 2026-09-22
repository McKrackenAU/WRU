import {
  $,
  api,
  alertDialog,
  escapeHtml,
  fetchLiveWeather,
  injectChrome,
  on,
  weatherLine,
} from "./common.js";

const state = {
  sites: [],
  reports: [],
  weather: null,
  lat: null,
  lng: null,
};

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function siteLabel(site) {
  if (!site) return "";
  return `${site.site_number} · ${site.road_name}${site.archived ? " (archived)" : ""}`;
}

function fillSites(selected) {
  const sel = $("shiftSite");
  if (!sel) return;
  const includeArchived = $("shiftIncludeArchived")?.checked !== false;
  const rows = state.sites.filter((s) => includeArchived || !s.archived);
  sel.innerHTML =
    `<option value="">Select a site…</option>` +
    rows
      .map(
        (s) =>
          `<option value="${s.id}" ${Number(selected) === s.id ? "selected" : ""}>${escapeHtml(siteLabel(s))}</option>`
      )
      .join("");
}

function renderList() {
  const host = $("shiftList");
  if (!host) return;
  const siteId = Number($("shiftSite")?.value || 0);
  const rows = siteId ? state.reports.filter((r) => r.site_id === siteId) : state.reports;
  host.innerHTML = rows.length
    ? rows
        .map((r) => {
          const weather = weatherLine(r.weather);
          const log = (r.weather_log || [])
            .map((w) => weatherLine(w))
            .filter(Boolean)
            .join(" → ");
          return `<li>
            <div class="top">
              <span>${escapeHtml(r.work_date || "")} · ${escapeHtml(r.shift_type || "day")}${
                r.archived ? " · archived site" : ""
              }</span>
              <a class="btn btn-sm btn-primary" href="/api/shifts/${r.id}/export.pdf">PDF</a>
            </div>
            <p><strong>${escapeHtml(r.site_number || "")}</strong> ${escapeHtml(r.road_name || "")}</p>
            ${r.works_done ? `<p>${escapeHtml(r.works_done)}</p>` : ""}
            ${r.issues ? `<p class="meta">Issues: ${escapeHtml(r.issues)}</p>` : ""}
            ${weather ? `<p class="meta">${escapeHtml(weather)}</p>` : ""}
            ${log && log !== weather ? `<p class="hint">Weather log: ${escapeHtml(log)}</p>` : ""}
          </li>`;
        })
        .join("")
    : `<li><p class="meta">No shift reports yet for this view.</p></li>`;
  $("shiftHint").textContent = siteId
    ? "History for the selected site, including after it is archived."
    : "Latest reports across sites. History stays when a site is archived.";
}

function showWeather(snap) {
  state.weather = snap;
  if ($("shiftWeather")) {
    $("shiftWeather").textContent = snap
      ? `Weather: ${weatherLine(snap)}`
      : "Weather will fill from your location when you save or tap Refresh weather.";
  }
}

function locate() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        state.lat = pos.coords.latitude;
        state.lng = pos.coords.longitude;
        resolve({ lat: state.lat, lng: state.lng });
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  });
}

async function refreshWeather() {
  const pos = (await locate()) || (state.lat != null ? { lat: state.lat, lng: state.lng } : null);
  if (!pos) {
    await alertDialog("Allow location so the shift report can log live weather.");
    return;
  }
  const snap = await fetchLiveWeather(pos.lat, pos.lng);
  showWeather(snap);
}

async function loadReports() {
  const siteId = Number($("shiftSite")?.value || 0);
  const include = $("shiftIncludeArchived")?.checked !== false;
  const params = new URLSearchParams({ include_archived: include ? "true" : "false" });
  if (siteId) params.set("site_id", String(siteId));
  state.reports = await api(`/api/shifts?${params}`);
  renderList();
}

async function saveShift(ev) {
  ev.preventDefault();
  const siteId = Number($("shiftSite").value || 0);
  if (!siteId) {
    await alertDialog("Choose a site.");
    return;
  }
  if (!state.weather) {
    try {
      await refreshWeather();
    } catch {
      /* optional */
    }
  }
  await api("/api/shifts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      site_id: siteId,
      work_date: $("shiftDate").value || todayISO(),
      shift_type: $("shiftType").value || "day",
      crew: $("shiftCrew").value.trim() || null,
      works_done: $("shiftWorks").value.trim() || null,
      issues: $("shiftIssues").value.trim() || null,
      notes: $("shiftNotes").value.trim() || null,
      lat: state.lat,
      lng: state.lng,
      weather: state.weather,
    }),
  });
  $("shiftWorks").value = "";
  $("shiftIssues").value = "";
  $("shiftNotes").value = "";
  await loadReports();
}

async function init() {
  await injectChrome({ active: "/shifts" });
  const preselect = Number(new URLSearchParams(location.search).get("site_id") || 0);
  const [active, archived] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/sites?archived=true").catch(() => []),
  ]);
  state.sites = [...(active || []), ...(archived || [])];
  if ($("shiftDate")) $("shiftDate").value = todayISO();
  fillSites(preselect || "");
  on("shiftSite", "change", () => loadReports().catch((e) => alertDialog(e.message)));
  on("shiftIncludeArchived", "change", () => {
    fillSites(Number($("shiftSite")?.value || 0));
    loadReports().catch((e) => alertDialog(e.message));
  });
  on("btnWeather", "click", () => refreshWeather().catch((e) => alertDialog(e.message)));
  on("shiftForm", "submit", (ev) => saveShift(ev).catch((e) => alertDialog(e.message)));
  await loadReports();
  locate().then((pos) => {
    if (!pos) return;
    fetchLiveWeather(pos.lat, pos.lng).then(showWeather).catch(() => {});
  });
}

init().catch((err) => {
  if ($("shiftList")) $("shiftList").innerHTML = `<li><p class="meta">${escapeHtml(err.message)}</p></li>`;
});
