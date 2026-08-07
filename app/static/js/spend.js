import { $, api, escapeHtml, fmtDate, injectChrome, on, showPageError, userName } from "./common.js";

const state = {
  sites: [],
  traffic: [],
  asphalt: [],
  rows: [],
};

function money(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function kindLabel(kind) {
  return kind === "asphalt" ? "Pavements" : "Traffic";
}

function filterParams() {
  const params = new URLSearchParams();
  const kind = $("filterKind")?.value || "";
  const site = $("filterSite")?.value || "";
  const traffic = $("filterTraffic")?.value || "";
  const asphalt = $("filterAsphalt")?.value || "";
  const from = $("filterFrom")?.value || "";
  const to = $("filterTo")?.value || "";
  if (kind) params.set("kind", kind);
  if (site) params.set("site_id", site);
  if (traffic) params.set("traffic_contractor_id", traffic);
  if (asphalt) params.set("asphalt_subcontractor_id", asphalt);
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  return params;
}

function syncKindFields() {
  const kind = $("spendKind")?.value || "traffic";
  const trafficWrap = $("spendTrafficWrap");
  const asphaltWrap = $("spendAsphaltWrap");
  if (trafficWrap) trafficWrap.hidden = kind !== "traffic";
  if (asphaltWrap) asphaltWrap.hidden = kind !== "asphalt";
}

function fillSelects() {
  const siteOpts =
    `<option value="">Select site…</option>` +
    state.sites
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.road_name)} · ${escapeHtml(s.site_number)}</option>`
      )
      .join("");
  $("spendSite").innerHTML = siteOpts;
  $("filterSite").innerHTML =
    `<option value="">All sites</option>` +
    state.sites
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.road_name)} · ${escapeHtml(s.site_number)}</option>`
      )
      .join("");

  const trafficOpts = state.traffic
    .filter((t) => t.active)
    .map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`)
    .join("");
  $("spendTraffic").innerHTML = `<option value="">None</option>${trafficOpts}`;
  $("filterTraffic").innerHTML = `<option value="">Any</option>${trafficOpts}`;

  const asphaltOpts = state.asphalt
    .filter((a) => a.active)
    .map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`)
    .join("");
  $("spendAsphalt").innerHTML = `<option value="">None</option>${asphaltOpts}`;
  $("filterAsphalt").innerHTML = `<option value="">Any</option>${asphaltOpts}`;
}

function renderRows() {
  const body = $("spendBody");
  const total = state.rows.reduce((sum, r) => sum + Number(r.amount || 0), 0);
  $("spendTotal").textContent = money(total);
  $("spendStatus").textContent = `${state.rows.length} row(s)`;
  if (!state.rows.length) {
    body.innerHTML = `<tr><td colspan="8"><span class="hint">No spend rows match these filters.</span></td></tr>`;
    return;
  }
  body.innerHTML = state.rows
    .map(
      (r) => `<tr data-id="${r.id}">
      <td>${escapeHtml(kindLabel(r.kind))}</td>
      <td class="mono">${fmtDate(r.work_date) || "—"}</td>
      <td>
        <div class="site-title">${escapeHtml(r.road_name || "Site")}</div>
        <div class="site-meta mono">${escapeHtml(r.site_number || "")}${r.program ? ` · ${escapeHtml(r.program)}` : ""}</div>
      </td>
      <td>${escapeHtml(r.contractor_name || "—")}</td>
      <td>${escapeHtml(r.category || "—")}</td>
      <td class="mono">${escapeHtml(r.invoice_ref || "—")}</td>
      <td class="mono">${money(r.amount)}</td>
      <td><button type="button" class="btn btn-danger btn-sm" data-del="${r.id}">Delete</button></td>
    </tr>`
    )
    .join("");
}

function syncExportLinks() {
  const q = filterParams().toString();
  const suffix = q ? `?${q}` : "";
  $("btnExportXlsx").href = `/api/spend/export.xlsx${suffix}`;
  $("btnExportPdf").href = `/api/spend/export.pdf${suffix}`;
}

async function loadRows() {
  const q = filterParams().toString();
  state.rows = await api(`/api/spend${q ? `?${q}` : ""}`);
  renderRows();
  syncExportLinks();
}

async function init() {
  await injectChrome({ active: "/spend", mode: "ops" });
  const [sites, traffic, asphalt] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/traffic-contractors?active_only=true"),
    api("/api/asphalt/subcontractors?active_only=true"),
  ]);
  state.sites = Array.isArray(sites) ? sites : [];
  state.traffic = Array.isArray(traffic) ? traffic : [];
  state.asphalt = Array.isArray(asphalt) ? asphalt : [];
  fillSelects();
  syncKindFields();
  await loadRows();

  on("spendKind", "change", syncKindFields);
  on("btnApplyFilters", "click", () => loadRows().catch((e) => alert(e.message)));
  on("spendForm", "submit", async (ev) => {
    ev.preventDefault();
    const kind = $("spendKind").value;
    const siteId = Number($("spendSite").value || 0);
    if (!siteId) {
      alert("Select a site");
      return;
    }
    await api("/api/spend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        site_id: siteId,
        work_date: $("spendDate").value || null,
        amount: Number($("spendAmount").value || 0),
        category: $("spendCategory").value.trim() || null,
        traffic_contractor_id: kind === "traffic" ? Number($("spendTraffic").value || 0) || null : null,
        asphalt_subcontractor_id: kind === "asphalt" ? Number($("spendAsphalt").value || 0) || null : null,
        invoice_ref: $("spendInvoice").value.trim() || null,
        notes: $("spendNotes").value.trim() || null,
        created_by: userName(),
      }),
    });
    $("spendAmount").value = "";
    $("spendNotes").value = "";
    $("spendInvoice").value = "";
    $("spendCategory").value = "";
    await loadRows();
  });
  on("spendBody", "click", async (ev) => {
    const btn = ev.target.closest("[data-del]");
    if (!btn) return;
    if (!confirm("Delete this spend row?")) return;
    await api(`/api/spend/${btn.dataset.del}`, { method: "DELETE" });
    await loadRows();
  });
}

init().catch((e) => showPageError("spendBody", e, "Could not load spend"));
