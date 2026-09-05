import { $, api, escapeHtml, fmtDate, injectChrome } from "./common.js";

async function load() {
  const rows = await api("/api/sites/generic-moas");
  $("tbody").innerHTML = rows.length
    ? rows
        .map(
          (s) => `<tr>
          <td class="mono">${escapeHtml(s.moa_number || "—")}</td>
          <td>${escapeHtml(s.road_name || "")} <span class="mono">${escapeHtml(s.site_number || "")}</span></td>
          <td>${escapeHtml(s.program || "")}</td>
          <td class="mono">${fmtDate(s.moa_start_date) || "—"} – ${fmtDate(s.moa_expiry_date) || "—"}</td>
          <td><a class="btn btn-sm btn-primary" href="/?highlight=${s.id}">Open</a>
              <a class="btn btn-sm" href="/documents?moa_number=${encodeURIComponent(s.moa_number || "")}">Files</a></td>
        </tr>`
        )
        .join("")
    : `<tr><td class="empty" colspan="5">No generic MoAs yet. Tick Generic MoA / TGS on a site to list it here.</td></tr>`;
}

async function init() {
  await injectChrome({ active: "/generics" });
  await load();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="5">${escapeHtml(err.message)}</td></tr>`;
});
