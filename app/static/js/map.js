import { $, api, escapeHtml, injectChrome, userName } from "./common.js";

let map;
let geoLayer;
let drawLayer;
let drawnGeometry = null;
let sites = [];
let baseTiles;

function popupHtml(props) {
  const site = props.site;
  const featureId = props.feature_id;
  let body = `<strong>${escapeHtml(props.name || "Feature")}</strong><br/>
    <span class="mono">FY ${escapeHtml(props.financial_year || "")}</span>`;
  if (site) {
    body += `<hr style="border:none;border-top:1px solid var(--ventia-border);margin:0.5rem 0"/>
      <div><strong>${escapeHtml(site.road_name)}</strong></div>
      <div class="mono">${escapeHtml(site.site_number)} · MoA ${escapeHtml(site.moa_number || "—")}</div>
      <div class="mono">TGS ${escapeHtml(site.tgs_reference || "—")}</div>
      <div style="margin-top:0.4rem">
        <a href="/?highlight=${site.id}">Open in Sites</a>
        ${site.archived ? " · archived" : ""}
      </div>
      <label style="display:block;margin-top:0.5rem;font-size:0.8rem">Relink / unlink
        <select data-link-feature="${featureId}" style="width:100%;margin-top:0.25rem">
          <option value="">— Unlink —</option>
          ${sites
            .map(
              (s) =>
                `<option value="${s.id}" ${s.id === site.id ? "selected" : ""}>${escapeHtml(s.site_number)} · ${escapeHtml(s.road_name)}</option>`
            )
            .join("")}
        </select>
      </label>`;
  } else {
    body += `<hr style="border:none;border-top:1px solid var(--ventia-border);margin:0.5rem 0"/>
      <div class="hint">Not linked to a site yet.</div>
      <label style="display:block;margin-top:0.4rem;font-size:0.8rem">Link to site
        <select data-link-feature="${featureId}" style="width:100%;margin-top:0.25rem">
          <option value="">—</option>
          ${sites
            .map(
              (s) =>
                `<option value="${s.id}">${escapeHtml(s.site_number)} · ${escapeHtml(s.road_name)} (${escapeHtml(s.moa_number || "no MoA")})</option>`
            )
            .join("")}
        </select>
      </label>`;
  }
  return body;
}

function setDrawnGeometry(geometry) {
  drawnGeometry = geometry;
  const btn = $("btnSaveDrawn");
  if (btn) btn.disabled = !geometry;
}

function clearDrawing() {
  if (drawLayer) drawLayer.clearLayers();
  setDrawnGeometry(null);
}

function fixMapSize() {
  if (!map) return;
  try {
    map.invalidateSize({ animate: false, pan: false });
    if (baseTiles && typeof baseTiles.redraw === "function") {
      baseTiles.redraw();
    }
  } catch (_) {
    /* ignore */
  }
}

function scheduleMapFix() {
  fixMapSize();
  requestAnimationFrame(() => {
    fixMapSize();
    setTimeout(fixMapSize, 50);
    setTimeout(fixMapSize, 200);
    setTimeout(fixMapSize, 600);
    setTimeout(fixMapSize, 1200);
  });
}

async function refreshLayers() {
  const fy = $("fyFilter").value;
  const params = fy ? `?financial_year=${encodeURIComponent(fy)}` : "";
  const layers = await api(`/api/map/layers${params}`);
  $("layerList").innerHTML = layers.length
    ? layers
        .map(
          (l) => `<li>
          <div class="top">
            <span>${escapeHtml(l.financial_year)} · ${l.feature_count} features</span>
            <button type="button" class="btn btn-danger" data-del-layer="${l.id}">Delete</button>
          </div>
          <p><strong>${escapeHtml(l.name)}</strong><br/><span class="meta">${escapeHtml(l.original_filename)}</span></p>
        </li>`
        )
        .join("")
    : `<li><p class="meta">No KML layers yet.</p></li>`;
}

async function refreshMap() {
  const fy = $("fyFilter").value;
  const params = fy ? `?financial_year=${encodeURIComponent(fy)}` : "";
  const geojson = await api(`/api/map/geojson${params}`);
  if (geoLayer) {
    map.removeLayer(geoLayer);
  }
  geoLayer = L.geoJSON(geojson, {
    style: {
      color: "#0a7a45",
      weight: 2,
      fillColor: "#6fa882",
      fillOpacity: 0.28,
    },
    pointToLayer: (feature, latlng) =>
      L.circleMarker(latlng, {
        radius: 6,
        color: "#0a7a45",
        fillColor: "#6fa882",
        fillOpacity: 0.85,
      }),
    onEachFeature: (feature, layer) => {
      layer.bindPopup(popupHtml(feature.properties || {}), { maxWidth: 300 });
    },
  }).addTo(map);

  try {
    const b = geoLayer.getBounds();
    if (b.isValid()) map.fitBounds(b.pad(0.1));
  } catch (_) {
    /* empty layer */
  }
  scheduleMapFix();
}

async function uploadKml() {
  const file = $("kmlFile").files?.[0];
  if (!file) return alert("Choose a KML file");
  const fd = new FormData();
  fd.append("file", file);
  if ($("layerName").value.trim()) fd.append("name", $("layerName").value.trim());
  if ($("fyFilter").value) fd.append("financial_year", $("fyFilter").value);
  if (userName()) fd.append("uploaded_by", userName());
  const res = await fetch("/api/map/layers", { method: "POST", body: fd });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert(body.detail || "Upload failed");
    return;
  }
  $("kmlFile").value = "";
  $("layerName").value = "";
  await refreshLayers();
  await refreshMap();
}

async function saveDrawnSite() {
  const road = $("drawRoad").value.trim();
  const siteNo = $("drawSiteNo").value.trim();
  if (!road || !siteNo) return alert("Road name and site number are required");
  if (!drawnGeometry) return alert("Draw a point, line, or polygon first");
  try {
    await api("/api/sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        road_name: road,
        site_number: siteNo,
        program: $("drawProgram").value || null,
        geometry: drawnGeometry,
        geometry_name: road,
      }),
    });
    $("drawRoad").value = "";
    $("drawSiteNo").value = "";
    clearDrawing();
    sites = await api("/api/sites?archived=false");
    const archived = await api("/api/sites?archived=true");
    sites = [...sites, ...archived];
    await refreshLayers();
    await refreshMap();
    alert("Site added to the register and map.");
  } catch (err) {
    alert(err.message);
  }
}

function setupDraw() {
  drawLayer = new L.FeatureGroup();
  map.addLayer(drawLayer);
  const control = new L.Control.Draw({
    edit: { featureGroup: drawLayer, remove: true },
    draw: {
      marker: true,
      polyline: true,
      polygon: true,
      rectangle: true,
      circle: false,
      circlemarker: false,
    },
  });
  map.addControl(control);
  map.on(L.Draw.Event.CREATED, (e) => {
    drawLayer.clearLayers();
    drawLayer.addLayer(e.layer);
    const gj = e.layer.toGeoJSON();
    setDrawnGeometry(gj.geometry);
  });
  map.on(L.Draw.Event.DELETED, () => setDrawnGeometry(null));
  map.on(L.Draw.Event.EDITED, () => {
    const layers = drawLayer.getLayers();
    if (!layers.length) {
      setDrawnGeometry(null);
      return;
    }
    setDrawnGeometry(layers[0].toGeoJSON().geometry);
  });
}

function waitForLayout() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

async function init() {
  if (typeof L === "undefined") {
    throw new Error("Map library failed to load. Hard-refresh the page and try again.");
  }

  injectChrome({ active: "/map" });
  await waitForLayout();

  const canvas = $("mapCanvas");
  const layout = $("mapLayout");
  if (!canvas) throw new Error("Map container missing");

  map = L.map(canvas, {
    preferCanvas: true,
    zoomControl: true,
  }).setView([-37.8136, 144.9631], 11);

  baseTiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
    updateWhenIdle: false,
    updateWhenZooming: false,
  }).addTo(map);

  setupDraw();
  map.whenReady(scheduleMapFix);
  map.on("zoomend moveend", () => fixMapSize());

  window.addEventListener("resize", scheduleMapFix);
  document.getElementById("navToggle")?.addEventListener("click", () => {
    setTimeout(scheduleMapFix, 50);
    setTimeout(scheduleMapFix, 320);
  });

  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => scheduleMapFix());
    ro.observe(canvas);
    if (layout) ro.observe(layout);
    const shellMain = document.querySelector(".shell-main");
    if (shellMain) ro.observe(shellMain);
  }

  const meta = await api("/api/meta");
  $("fyFilter").innerHTML =
    `<option value="">All years</option>` +
    (meta.financial_years || [])
      .map((y) => `<option value="${escapeHtml(y)}">${escapeHtml(y)}</option>`)
      .join("");
  $("drawProgram").innerHTML =
    `<option value="">Program…</option>` +
    (meta.programs || [])
      .map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
      .join("");

  sites = await api("/api/sites?archived=false");
  const archived = await api("/api/sites?archived=true");
  sites = [...sites, ...archived];

  $("fyFilter").addEventListener("change", async () => {
    await refreshLayers();
    await refreshMap();
  });
  $("btnUploadKml").addEventListener("click", uploadKml);
  $("btnSaveDrawn").addEventListener("click", saveDrawnSite);
  $("btnClearDrawn").addEventListener("click", clearDrawing);
  $("layerList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-del-layer]");
    if (!btn) return;
    if (!confirm("Delete this KML layer and its features?")) return;
    await api(`/api/map/layers/${btn.dataset.delLayer}`, { method: "DELETE" });
    await refreshLayers();
    await refreshMap();
  });

  document.body.addEventListener("change", async (ev) => {
    const sel = ev.target.closest("[data-link-feature]");
    if (!sel) return;
    const featureId = sel.dataset.linkFeature;
    const siteId = sel.value ? Number(sel.value) : null;
    await api(`/api/map/features/${featureId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_id: siteId }),
    });
    await refreshMap();
  });

  await refreshLayers();
  await refreshMap();
  scheduleMapFix();
}

init().catch((err) => {
  console.error(err);
  const canvas = document.getElementById("mapCanvas");
  if (canvas) {
    canvas.innerHTML = `<div class="page-error" role="alert"><strong>Map failed to load</strong><p>${escapeHtml(
      err.message || String(err)
    )}</p></div>`;
  } else {
    alert(err.message);
  }
});
