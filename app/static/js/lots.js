import { $, api, alertDialog, escapeHtml, injectChrome, on } from "./common.js";

const state = { lots: [], sites: [] };

function siteLabel(site) {
  return `${site.road_name || ""} · ${site.site_number || ""}`.trim();
}

function fillSites() {
  const sel = $("filterSite");
  if (!sel) return;
  const current = sel.value;
  const preset = new URLSearchParams(location.search).get("site_id") || "";
  const chosen = current || preset;
  sel.innerHTML =
    `<option value="">All sites</option>` +
    state.sites
      .map(
        (site) =>
          `<option value="${site.id}" ${String(site.id) === String(chosen) ? "selected" : ""}>${escapeHtml(siteLabel(site))}</option>`
      )
      .join("");
}

function query() {
  const params = new URLSearchParams();
  const siteId = $("filterSite")?.value || "";
  const kind = $("filterKind")?.value || "";
  const mix = ($("filterMix")?.value || "").trim();
  const qa = $("filterQa")?.value || "";
  if (siteId) params.set("site_id", siteId);
  if (kind) params.set("work_kind", kind);
  if (mix) params.set("mix", mix);
  if (qa) params.set("qa_status", qa);
  const text = params.toString();
  return text ? `?${text}` : "";
}

function render() {
  const body = $("lotsBody");
  if (!body) return;
  body.innerHTML = state.lots.length
    ? state.lots
        .map((row) => {
          const kind = row.work_kind === "pro" ? "PRO" : "HMA";
          const pdf = row.shift_id
            ? `<a class="btn btn-sm btn-primary" href="/api/shifts/${row.shift_id}/export.pdf">PDF</a>`
            : "";
          return `<tr data-lot="${row.id}">
            <td><strong>${escapeHtml(row.lot_number || "")}</strong></td>
            <td>${escapeHtml(row.work_date || "")}</td>
            <td>${escapeHtml(row.road_name || "")}${row.road_number ? ` · ${escapeHtml(row.road_number)}` : ""}</td>
            <td>${escapeHtml(row.site_number || "")}</td>
            <td>${kind}</td>
            <td>${escapeHtml(row.mix || "")}</td>
            <td>${escapeHtml(row.supervisor || "")}</td>
            <td>
              <select data-qa="${row.id}">
                <option value="pending" ${row.qa_status === "pending" ? "selected" : ""}>Pending</option>
                <option value="accepted" ${row.qa_status === "accepted" ? "selected" : ""}>Accepted</option>
                <option value="hold" ${row.qa_status === "hold" ? "selected" : ""}>Hold</option>
              </select>
            </td>
            <td><input data-notes="${row.id}" value="${escapeHtml(row.qa_notes || "")}" placeholder="QA note" /></td>
            <td>${pdf}</td>
          </tr>`;
        })
        .join("")
    : `<tr><td class="empty" colspan="10">No lots yet. Saving a shift report adds one here.</td></tr>`;
  body.querySelectorAll("select[data-qa]").forEach((sel) => {
    sel.addEventListener("change", () => {
      saveLot(Number(sel.dataset.qa), { qa_status: sel.value }).catch((err) => alertDialog(err.message));
    });
  });
  body.querySelectorAll("input[data-notes]").forEach((input) => {
    input.addEventListener("change", () => {
      saveLot(Number(input.dataset.notes), { qa_notes: input.value }).catch((err) => alertDialog(err.message));
    });
  });
  if ($("lotsStatus")) {
    $("lotsStatus").textContent = `${state.lots.length} lot${state.lots.length === 1 ? "" : "s"}`;
  }
}

async function saveLot(id, payload) {
  const updated = await api(`/api/lots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const index = state.lots.findIndex((row) => row.id === id);
  if (index >= 0) state.lots[index] = updated;
}

async function loadLots() {
  state.lots = await api(`/api/lots${query()}`);
  render();
}

async function init() {
  await injectChrome({ active: "/lots" });
  const [active, archived] = await Promise.all([
    api("/api/sites?archived=false"),
    api("/api/sites?archived=true").catch(() => []),
  ]);
  state.sites = [...(active || []), ...(archived || [])].sort((a, b) =>
    siteLabel(a).localeCompare(siteLabel(b))
  );
  fillSites();
  on("btnApplyLots", "click", () => loadLots().catch((err) => alertDialog(err.message)));
  on("filterSite", "change", () => loadLots().catch((err) => alertDialog(err.message)));
  on("filterKind", "change", () => loadLots().catch((err) => alertDialog(err.message)));
  on("filterQa", "change", () => loadLots().catch((err) => alertDialog(err.message)));
  await loadLots();
}

init().catch((err) => {
  if ($("lotsStatus")) $("lotsStatus").textContent = err.message;
});
