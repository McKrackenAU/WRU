import {
  $,
  api,
  alertDialog,
  escapeHtml,
  fetchLiveWeather,
  injectChrome,
  on,
  userName,
  weatherLine,
} from "./common.js";

const state = {
  sites: [],
  reports: [],
  features: [],
  weather: null,
  lat: null,
  lng: null,
  map: null,
  drawLayer: null,
  siteLayer: null,
  measuredM2: 0,
};

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function textOrNull(id) {
  const raw = ($(id)?.value || "").trim();
  return raw || null;
}

function numOrNull(id) {
  const raw = ($(id)?.value || "").trim();
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function visibleSites() {
  const includeArchived = $("shiftIncludeArchived")?.checked !== false;
  return state.sites.filter((site) => includeArchived || !site.archived);
}

function roads() {
  return [...new Set(visibleSites().map((site) => site.road_name).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b)
  );
}

function sitesForRoad(road) {
  return visibleSites()
    .filter((site) => site.road_name === road)
    .sort((a, b) => String(a.site_number).localeCompare(String(b.site_number), undefined, { numeric: true }));
}

function fillRoads(selected) {
  const sel = $("shiftRoad");
  if (!sel) return;
  const current = selected ?? sel.value;
  sel.innerHTML =
    `<option value="">Select a road…</option>` +
    roads()
      .map((road) => `<option value="${escapeHtml(road)}" ${road === current ? "selected" : ""}>${escapeHtml(road)}</option>`)
      .join("");
}

function fillSites(selectedId) {
  const sel = $("shiftSite");
  if (!sel) return;
  const road = $("shiftRoad")?.value || "";
  const rows = road ? sitesForRoad(road) : [];
  const selected = Number(selectedId || 0);
  sel.innerHTML =
    `<option value="">${road ? "Select a site…" : "Select a road first"}</option>` +
    rows
      .map(
        (site) =>
          `<option value="${site.id}" ${selected === site.id ? "selected" : ""}>${escapeHtml(site.site_number)}${
            site.archived ? " (archived)" : ""
          }</option>`
      )
      .join("");
}

function selectedSite() {
  const id = Number($("shiftSite")?.value || 0);
  return state.sites.find((site) => site.id === id) || null;
}

function fmrpLabel(site) {
  const fy = (site?.financial_year || "").trim();
  if (!fy) return "";
  return /fmrp/i.test(fy) ? fy : `FMRP ${fy}`;
}

function applySiteDefaults() {
  const site = selectedSite();
  if (!site) return;
  if ($("dFmrp")) $("dFmrp").value = fmrpLabel(site);
  if ($("dMoa")) $("dMoa").value = site.moa_number || "";
  if ($("dTgs")) $("dTgs").value = site.tgs_reference || "";
  if ($("shiftType")) $("shiftType").value = site.indicative_shift_type === "night" ? "night" : "day";
  if ($("dSupervisor") && !$("dSupervisor").value.trim()) $("dSupervisor").value = userName();
  focusSiteOnMap(site.id);
}

function selectSite(siteId) {
  const site = state.sites.find((row) => row.id === Number(siteId));
  fillRoads(site?.road_name || "");
  fillSites(site?.id || 0);
  if (site) applySiteDefaults();
}

function collectDetails() {
  return {
    fmrp_year: textOrNull("dFmrp"),
    lot_number: textOrNull("dLot"),
    supervisor: textOrNull("dSupervisor"),
    high_risk: textOrNull("dRisk"),
    chainage: textOrNull("dChainage"),
    description: textOrNull("dDescription"),
    road_closed: textOrNull("dRoadClosed"),
    road_opened: textOrNull("dRoadOpened"),
    traffic_contractor: textOrNull("dTrafficContractor"),
    tgs_number: textOrNull("dTgs"),
    moa_number: textOrNull("dMoa"),
    total_tc: numOrNull("dTotalTc"),
    vehicles: numOrNull("dVehicles"),
    arrow_boards: numOrNull("dArrows"),
    spotters: numOrNull("dSpotters"),
    traffic_crew_start: textOrNull("dCrewStart"),
    traffic_crew_end: textOrNull("dCrewEnd"),
    moa_start: textOrNull("dMoaStart"),
    moa_end: textOrNull("dMoaEnd"),
    paving_contractor: textOrNull("dPaver"),
    other_contractors: textOrNull("dOthers"),
    asphalt_type: textOrNull("dMix"),
    thickness_mm: numOrNull("dThickness"),
    shift_area_m2: numOrNull("dShiftArea"),
    site_area_m2: numOrNull("dSiteArea"),
    tonnage: numOrNull("dTonnes"),
    pits: numOrNull("dPits"),
    valves: numOrNull("dValves"),
    loops: numOrNull("dLoops"),
    prestart_notes: textOrNull("dPrestart"),
    profiling_notes: textOrNull("dProfiling"),
    asphalting_notes: textOrNull("dAsphaltNotes"),
    observations: textOrNull("dObservations"),
    incidents: textOrNull("dIncidents"),
    comments: textOrNull("dComments"),
    prestart_done: Boolean($("dPrestartDone")?.checked),
    plant_prestart_done: Boolean($("dPlantPrestart")?.checked),
    tm_implementation: Boolean($("dTmOk")?.checked),
    aftercare: Boolean($("dAftercare")?.checked),
    ncr_raised: Boolean($("dNcr")?.checked),
    photos_url: textOrNull("dPhotos"),
  };
}

function ringOf(latlngs) {
  if (!latlngs?.length) return [];
  if (typeof latlngs[0]?.lat === "number") return latlngs;
  return latlngs[0] || [];
}

function ringAreaM2(latlngs) {
  const ring = ringOf(latlngs);
  if (ring.length < 3) return 0;
  const radius = 6378137;
  let area = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const p1 = ring[i];
    const p2 = ring[(i + 1) % ring.length];
    const lat1 = (p1.lat * Math.PI) / 180;
    const lat2 = (p2.lat * Math.PI) / 180;
    const dLng = ((p2.lng - p1.lng) * Math.PI) / 180;
    area += dLng * (2 + Math.sin(lat1) + Math.sin(lat2));
  }
  return Math.abs((area * radius * radius) / 2);
}

function polygonsGeoJSON() {
  if (!state.drawLayer) return [];
  return state.drawLayer.getLayers().map((layer) => layer.toGeoJSON());
}

function syncPolygons() {
  const layers = state.drawLayer ? state.drawLayer.getLayers() : [];
  const total = layers.reduce((sum, layer) => sum + (layer.getLatLngs ? ringAreaM2(layer.getLatLngs()) : 0), 0);
  const hint = $("polygonHint");
  if (hint) {
    hint.textContent = layers.length
      ? `${layers.length} polygon${layers.length === 1 ? "" : "s"} · about ${Math.round(total).toLocaleString()} m²`
      : "No polygons yet.";
  }
  const areaInput = $("dShiftArea");
  if (areaInput) {
    const current = Number(areaInput.value);
    const stillAuto = !areaInput.value || (Number.isFinite(current) && Math.round(current) === Math.round(state.measuredM2));
    if (stillAuto) areaInput.value = total ? String(Math.round(total)) : "";
  }
  state.measuredM2 = total;
}

function clearPolygons() {
  state.drawLayer?.clearLayers();
  state.measuredM2 = 0;
  syncPolygons();
}

function setupMap() {
  const canvas = $("shiftMap");
  if (!canvas || state.map || typeof L === "undefined") return;
  state.map = L.map(canvas, { zoomControl: true }).setView([-37.8136, 144.9631], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);
  state.siteLayer = L.geoJSON(null, {
    style: { color: "#94a3b8", weight: 2, fillOpacity: 0.08 },
  }).addTo(state.map);
  state.drawLayer = new L.FeatureGroup();
  state.map.addLayer(state.drawLayer);
  canvas._wruShiftMap = state.map;
  canvas._wruDrawLayer = state.drawLayer;
  state.map.addControl(
    new L.Control.Draw({
      edit: { featureGroup: state.drawLayer, remove: true },
      draw: {
        polygon: { allowIntersection: false, showArea: false },
        rectangle: { showArea: false },
        polyline: false,
        circle: false,
        circlemarker: false,
        marker: false,
      },
    })
  );
  state.map.on(L.Draw.Event.CREATED, (event) => {
    state.drawLayer.addLayer(event.layer);
  });
  state.drawLayer.on("layeradd layerremove", () => syncPolygons());
  state.map.on(L.Draw.Event.EDITED, () => syncPolygons());
  state.map.on(L.Draw.Event.DELETED, () => syncPolygons());
  setTimeout(() => state.map?.invalidateSize(), 250);
}

function focusSiteOnMap(siteId) {
  if (!state.map || !state.siteLayer) return;
  const feats = state.features.filter((feat) => Number(feat.site_id) === Number(siteId) && feat.geometry);
  state.siteLayer.clearLayers();
  if (!feats.length) {
    state.map.setView([-37.8136, 144.9631], 11);
    return;
  }
  state.siteLayer.addData({
    type: "FeatureCollection",
    features: feats.map((feat) => ({ type: "Feature", geometry: feat.geometry, properties: {} })),
  });
  try {
    state.map.fitBounds(state.siteLayer.getBounds(), { padding: [24, 24], maxZoom: 17 });
  } catch {
    /* empty bounds */
  }
}

function money(amount) {
  return `$${Number(amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function renderList() {
  const host = $("shiftList");
  if (!host) return;
  const siteId = Number($("shiftSite")?.value || 0);
  const rows = siteId ? state.reports.filter((row) => row.site_id === siteId) : state.reports;
  host.innerHTML = rows.length
    ? rows
        .map((row) => {
          const weather = weatherLine(row.weather);
          const details = row.details || {};
          const summary = [
            details.asphalt_type,
            details.shift_area_m2 ? `${details.shift_area_m2} m²` : "",
            details.tonnage ? `${details.tonnage} t` : "",
            (row.polygons || []).length ? `${row.polygons.length} polygon${row.polygons.length === 1 ? "" : "s"}` : "",
          ]
            .filter(Boolean)
            .join(" · ");
          return `<li>
            <div class="top">
              <span>${escapeHtml(row.work_date || "")} · ${escapeHtml(row.shift_type || "day")}${
                row.archived ? " · archived site" : ""
              }</span>
              <a class="btn btn-sm btn-primary" href="/api/shifts/${row.id}/export.pdf">PDF</a>
            </div>
            <p><strong>${escapeHtml(row.site_number || "")}</strong> ${escapeHtml(row.road_name || "")}</p>
            ${summary ? `<p class="meta">${escapeHtml(summary)}</p>` : ""}
            ${details.asphalting_notes ? `<p>${escapeHtml(details.asphalting_notes)}</p>` : ""}
            ${row.issues ? `<p class="meta">Issues: ${escapeHtml(row.issues)}</p>` : ""}
            ${weather ? `<p class="meta">${escapeHtml(weather)}</p>` : ""}
          </li>`;
        })
        .join("")
    : `<li><p class="meta">No shift reports yet for this view.</p></li>`;
  if ($("shiftHint")) {
    $("shiftHint").textContent = siteId
      ? "History for the selected site, including after it is archived."
      : "Latest reports across sites. History stays when a site is archived.";
  }
}

function showWeather(snap) {
  state.weather = snap;
  if ($("shiftWeather")) {
    $("shiftWeather").textContent = snap
      ? `Weather: ${weatherLine(snap)}`
      : "Weather fills from your location when you save or tap Refresh weather.";
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
  showWeather(await fetchLiveWeather(pos.lat, pos.lng));
}

async function loadReports() {
  const siteId = Number($("shiftSite")?.value || 0);
  const include = $("shiftIncludeArchived")?.checked !== false;
  const params = new URLSearchParams({ include_archived: include ? "true" : "false" });
  if (siteId) params.set("site_id", String(siteId));
  state.reports = await api(`/api/shifts?${params}`);
  renderList();
}

function clearShiftNarrative() {
  for (const id of [
    "dChainage",
    "dDescription",
    "dRoadClosed",
    "dRoadOpened",
    "dCrewStart",
    "dCrewEnd",
    "dMoaStart",
    "dMoaEnd",
    "dShiftArea",
    "dTonnes",
    "dPrestart",
    "dProfiling",
    "dAsphaltNotes",
    "dObservations",
    "dIncidents",
    "dComments",
  ]) {
    if ($(id)) $(id).value = "";
  }
  clearPolygons();
}

async function saveShift(ev) {
  ev.preventDefault();
  const siteId = Number($("shiftSite")?.value || 0);
  if (!$("shiftRoad")?.value || !siteId) {
    await alertDialog("Choose a road, then a site number.");
    return;
  }
  if (!state.weather) {
    try {
      const pos = await locate();
      if (pos) showWeather(await fetchLiveWeather(pos.lat, pos.lng));
    } catch {
      /* weather stays blank when location is unavailable */
    }
  }
  const details = collectDetails();
  const created = await api("/api/shifts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      site_id: siteId,
      work_date: $("shiftDate").value || todayISO(),
      shift_type: $("shiftType").value || "day",
      crew: details.supervisor,
      works_done: details.asphalting_notes || details.description,
      issues: details.incidents,
      notes: details.observations || details.comments,
      lat: state.lat,
      lng: state.lng,
      weather: state.weather,
      details,
      polygons: polygonsGeoJSON(),
    }),
  });
  let hint = "Shift saved.";
  if ($("dPostSpend")?.checked && created?.id) {
    const spend = await api(`/api/shifts/${created.id}/actual-spend`, { method: "POST" });
    const posted = [];
    if (spend.posted?.traffic) posted.push(`Traffic ${money(spend.posted.traffic.amount)}`);
    if (spend.posted?.asphalt) {
      const asphalt = spend.posted.asphalt;
      posted.push(
        `Asphalt ${money(asphalt.amount)} · ${asphalt.rate_name || asphalt.unit} · ${asphalt.quantity} ${asphalt.unit}`
      );
    }
    const warnings = (spend.warnings || []).filter(Boolean);
    hint = [posted.join(" · ") || "Shift saved. No actual spend was posted.", ...warnings].join(" ");
  }
  if ($("shiftCostHint")) $("shiftCostHint").textContent = hint;
  clearShiftNarrative();
  await loadReports();
}

async function init() {
  await injectChrome({ active: "/shifts" });
  setupMap();
  const preselect = Number(new URLSearchParams(location.search).get("site_id") || 0);
  const [active, archived, features] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/sites?archived=true").catch(() => []),
    api("/api/map/features").catch(() => []),
  ]);
  state.sites = [...(active || []), ...(archived || [])];
  state.features = features || [];
  if ($("shiftDate")) $("shiftDate").value = todayISO();
  selectSite(preselect);
  on("shiftRoad", "change", () => {
    fillSites(0);
    state.siteLayer?.clearLayers();
    loadReports().catch((err) => alertDialog(err.message));
  });
  on("shiftSite", "change", () => {
    applySiteDefaults();
    loadReports().catch((err) => alertDialog(err.message));
  });
  on("shiftIncludeArchived", "change", () => {
    const current = selectedSite();
    fillRoads(current?.road_name || "");
    fillSites(current?.id || 0);
    loadReports().catch((err) => alertDialog(err.message));
  });
  on("btnClearPolygons", "click", () => clearPolygons());
  on("btnWeather", "click", () => refreshWeather().catch((err) => alertDialog(err.message)));
  on("shiftForm", "submit", (ev) => saveShift(ev).catch((err) => alertDialog(err.message)));
  await loadReports();
  locate().then((pos) => {
    if (!pos) return;
    fetchLiveWeather(pos.lat, pos.lng).then(showWeather).catch(() => {});
  });
}

init().catch((err) => {
  if ($("shiftList")) $("shiftList").innerHTML = `<li><p class="meta">${escapeHtml(err.message)}</p></li>`;
});
