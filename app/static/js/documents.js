import {
  $,
  api,
  escapeHtml,
  injectChrome,
  alertDialog,
  errorMessage,
  applyDocCategories,
  docCategorySelectHtml,
  downloadDocumentsZip,
  onLiveSitesChanged,
  syncLiveRevision,
} from "./common.js";

let categories = [];

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function selectedIds() {
  return [...document.querySelectorAll("#tbody input[data-doc-pick]:checked")].map((el) => Number(el.dataset.docPick));
}

function syncSelectAll() {
  const boxes = [...document.querySelectorAll("#tbody input[data-doc-pick]")];
  const all = $("libSelectAll");
  if (!all) return;
  all.checked = boxes.length > 0 && boxes.every((b) => b.checked);
  all.indeterminate = boxes.some((b) => b.checked) && !all.checked;
}

async function load() {
  const params = new URLSearchParams();
  if ($("moaFilter").value.trim()) params.set("moa_number", $("moaFilter").value.trim());
  if ($("search").value.trim()) params.set("q", $("search").value.trim());
  if ($("categoryFilter").value) params.set("category", $("categoryFilter").value);
  const docs = await api(`/api/documents?${params}`);
  $("tbody").innerHTML = docs.length
    ? docs
        .map(
          (d) => `<tr data-doc-id="${d.id}">
          <td class="doc-check-col"><input type="checkbox" data-doc-pick="${d.id}" aria-label="Select ${escapeHtml(d.original_filename)}" /></td>
          <td>${docCategorySelectHtml(d.id, d.category)}</td>
          <td><a href="/api/documents/${d.id}/download">${escapeHtml(d.original_filename)}</a></td>
          <td class="mono">${escapeHtml(d.moa_number || "")}</td>
          <td>${escapeHtml(d.road_name || "")} <span class="mono">${escapeHtml(d.site_number || "")}</span></td>
          <td>${escapeHtml(d.description || "")}</td>
          <td class="mono">${new Date(d.uploaded_at).toLocaleString()}</td>
          <td><a class="btn" href="/api/documents/${d.id}/download">Download</a></td>
        </tr>`
        )
        .join("")
    : `<tr><td class="empty" colspan="8">No documents match.</td></tr>`;
  $("statusLine").textContent = `${docs.length} document${docs.length === 1 ? "" : "s"}`;
  syncSelectAll();
}

async function changeCategory(sel) {
  try {
    await api(`/api/documents/${sel.dataset.docCat}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: sel.value }),
    });
  } catch (err) {
    alertDialog(errorMessage(err, "Could not update category"));
    await load();
  }
}

async function downloadSelected() {
  const ids = selectedIds();
  if (!ids.length) {
    await alertDialog("Tick the documents you want, then Download selected.");
    return;
  }
  const btn = $("btnDownloadSelected");
  if (btn) btn.disabled = true;
  try {
    await downloadDocumentsZip(ids, "WRU-documents.zip");
  } catch (err) {
    await alertDialog(errorMessage(err, "Could not download"));
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function init() {
  injectChrome({ active: "/documents" });
  const meta = await api("/api/meta");
  applyDocCategories(meta.doc_category_defs || meta.doc_categories);
  categories = meta.doc_category_defs?.length ? meta.doc_category_defs : (meta.doc_categories || []).map((c) => ({ key: c, label: c }));
  $("categoryFilter").innerHTML =
    `<option value="">All categories</option>` +
    categories
      .map((c) => {
        const key = typeof c === "string" ? c : c.key;
        const label = typeof c === "string" ? c : c.label;
        return `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`;
      })
      .join("");
  $("categoryFilter").addEventListener("change", load);
  $("moaFilter").addEventListener("input", debounce(load, 250));
  $("search").addEventListener("input", debounce(load, 250));
  $("btnDownloadSelected")?.addEventListener("click", () => downloadSelected());
  $("libSelectAll")?.addEventListener("change", (ev) => {
    const on = ev.target.checked;
    document.querySelectorAll("#tbody input[data-doc-pick]").forEach((box) => {
      box.checked = on;
    });
  });
  document.addEventListener("change", (ev) => {
    if (ev.target.closest("#tbody [data-doc-pick]")) {
      syncSelectAll();
      return;
    }
    const sel = ev.target.closest("tbody [data-doc-cat]");
    if (sel) changeCategory(sel);
  });
  await load();
  onLiveSitesChanged(() => load().catch(() => {}));
  await syncLiveRevision();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="8">${escapeHtml(err.message)}</td></tr>`;
});
