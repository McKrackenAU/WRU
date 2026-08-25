import { $, api, escapeHtml, injectChrome, confirmDialog, promptDialog, alertDialog, errorMessage } from "./common.js";

const state = {
  sites: [],
  selectedIds: new Set(),
};

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function syncBulkBar() {
  const bar = $("bulkBar");
  const count = state.selectedIds.size;
  if (bar) bar.hidden = count === 0;
  const label = $("bulkCount");
  if (label) label.textContent = `${count} selected`;
  const all = $("selectAllVisible");
  if (all) {
    const visibleIds = state.sites.map((s) => s.id);
    all.checked = visibleIds.length > 0 && visibleIds.every((id) => state.selectedIds.has(id));
    all.indeterminate =
      count > 0 && visibleIds.some((id) => state.selectedIds.has(id)) && !all.checked;
  }
}

async function confirmPurge(count, label) {
  const n = Number(count) || 0;
  const what = label || `${n} archived site${n === 1 ? "" : "s"}`;
  const typed = await promptDialog(
    `Permanently delete ${what}? This cannot be undone — documents, estimates, and spend records go with it.\n\nType DELETE to confirm.`,
    "",
    {
      title: "Purge from archive",
      danger: true,
      confirmLabel: "Purge",
      inputLabel: "Type DELETE",
    }
  );
  if (typed == null) return false;
  if (typed.trim().toUpperCase() !== "DELETE") {
    await alertDialog("Purge cancelled — you must type DELETE.");
    return false;
  }
  return true;
}

function renderRows(sites) {
  $("tbody").innerHTML = sites.length
    ? sites
        .map((s) => {
          const checked = state.selectedIds.has(s.id) ? "checked" : "";
          return `<tr>
          <td class="select-col">
            <input type="checkbox" class="site-select" data-select-id="${s.id}" ${checked} aria-label="Select ${escapeHtml(s.road_name)}" />
          </td>
          <td class="mono">${escapeHtml(s.archived_fy || s.financial_year || "")}</td>
          <td><strong>${escapeHtml(s.road_name)}</strong></td>
          <td class="mono">${escapeHtml(s.site_number)}</td>
          <td>${escapeHtml(s.program || "")}</td>
          <td>${(s.councils || []).map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join(" ") || "—"}</td>
          <td class="mono">${escapeHtml(s.moa_number || "")}</td>
          <td class="mono">${escapeHtml(s.tgs_reference || "")}</td>
          <td class="mono">${s.archived_at ? new Date(s.archived_at).toLocaleDateString() : ""}</td>
          <td class="row-actions">
            <button type="button" class="btn" data-restore="${s.id}">Restore</button>
            <button type="button" class="btn btn-danger" data-purge="${s.id}" data-purge-name="${escapeHtml(s.road_name)}">Purge</button>
          </td>
        </tr>`;
        })
        .join("")
    : `<tr><td class="empty" colspan="10">No archived sites for this filter.</td></tr>`;
  syncBulkBar();
}

async function load() {
  const params = new URLSearchParams({ archived: "true" });
  const fy = $("fyFilter").value;
  const q = $("search").value.trim();
  if (fy) params.set("financial_year", fy);
  if (q) params.set("q", q);
  const sites = await api(`/api/sites?${params}`);
  state.sites = Array.isArray(sites) ? sites : [];
  const visible = new Set(state.sites.map((s) => s.id));
  state.selectedIds = new Set([...state.selectedIds].filter((id) => visible.has(id)));
  renderRows(state.sites);
  $("statusLine").textContent = `${state.sites.length} archived site${state.sites.length === 1 ? "" : "s"}`;
}

async function restoreSite(id) {
  if (!await confirmDialog("Restore this site to the active register?")) return;
  await api(`/api/sites/${id}/restore`, { method: "POST" });
  state.selectedIds.delete(Number(id));
  await load();
}

async function purgeIds(ids, label) {
  const unique = [...new Set(ids.map(Number).filter((n) => n > 0))];
  if (!unique.length) return;
  if (!await confirmPurge(unique.length, label)) return;
  if (unique.length === 1) {
    await api(`/api/sites/${unique[0]}`, { method: "DELETE" });
  } else {
    await api("/api/sites/bulk-purge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site_ids: unique }),
    });
  }
  for (const id of unique) state.selectedIds.delete(id);
  await load();
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
  $("tbody").addEventListener("change", (ev) => {
    const box = ev.target.closest("[data-select-id]");
    if (!box) return;
    const id = Number(box.getAttribute("data-select-id"));
    if (box.checked) state.selectedIds.add(id);
    else state.selectedIds.delete(id);
    syncBulkBar();
  });
  $("tbody").addEventListener("click", async (ev) => {
    const restore = ev.target.closest("[data-restore]");
    if (restore) {
      try {
        await restoreSite(restore.dataset.restore);
      } catch (err) {
        await alertDialog(errorMessage(err, "Could not restore site"));
      }
      return;
    }
    const purge = ev.target.closest("[data-purge]");
    if (!purge) return;
    const id = Number(purge.dataset.purge);
    const name = purge.dataset.purgeName || "this archived site";
    try {
      await purgeIds([id], name);
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not purge site"));
    }
  });
  $("selectAllVisible")?.addEventListener("change", (ev) => {
    const on = !!ev.target.checked;
    for (const site of state.sites) {
      if (on) state.selectedIds.add(site.id);
      else state.selectedIds.delete(site.id);
    }
    renderRows(state.sites);
  });
  $("btnClearSelection")?.addEventListener("click", () => {
    state.selectedIds.clear();
    renderRows(state.sites);
  });
  $("btnBulkPurge")?.addEventListener("click", async () => {
    try {
      await purgeIds([...state.selectedIds]);
    } catch (err) {
      await alertDialog(errorMessage(err, "Could not purge sites"));
    }
  });
  await load();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="10">${escapeHtml(err.message)}</td></tr>`;
});
