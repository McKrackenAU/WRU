import { $, api, escapeHtml, injectChrome, confirmDialog } from "./common.js";

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function load() {
  const params = new URLSearchParams({ archived: "true" });
  const fy = $("fyFilter").value;
  const q = $("search").value.trim();
  if (fy) params.set("financial_year", fy);
  if (q) params.set("q", q);
  const sites = await api(`/api/sites?${params}`);
  $("tbody").innerHTML = sites.length
    ? sites
        .map(
          (s) => `<tr>
          <td class="mono">${escapeHtml(s.archived_fy || s.financial_year || "")}</td>
          <td><strong>${escapeHtml(s.road_name)}</strong></td>
          <td class="mono">${escapeHtml(s.site_number)}</td>
          <td>${escapeHtml(s.program || "")}</td>
          <td>${(s.councils || []).map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join(" ") || "—"}</td>
          <td class="mono">${escapeHtml(s.moa_number || "")}</td>
          <td class="mono">${escapeHtml(s.tgs_reference || "")}</td>
          <td class="mono">${s.archived_at ? new Date(s.archived_at).toLocaleDateString() : ""}</td>
          <td><button type="button" class="btn" data-restore="${s.id}">Restore</button></td>
        </tr>`
        )
        .join("")
    : `<tr><td class="empty" colspan="9">No archived sites for this filter.</td></tr>`;
  $("statusLine").textContent = `${sites.length} archived site${sites.length === 1 ? "" : "s"}`;
}

async function init() {
  injectChrome({ active: "/archive" });
  const meta = await api("/api/meta");
  $("fyFilter").innerHTML =
    `<option value="">All years</option>` +
    (meta.financial_years || [])
      .map((y) => `<option value="${escapeHtml(y)}">${escapeHtml(y)}</option>`)
      .join("");
  $("fyFilter").addEventListener("change", load);
  $("search").addEventListener("input", debounce(load, 250));
  $("tbody").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-restore]");
    if (!btn) return;
    if (!await confirmDialog("Restore this site to the active register?")) return;
    await api(`/api/sites/${btn.dataset.restore}/restore`, { method: "POST" });
    await load();
  });
  await load();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="9">${escapeHtml(err.message)}</td></tr>`;
});
