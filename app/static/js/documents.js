import { $, api, escapeHtml, injectChrome, alertDialog, errorMessage, docCategorySelectHtml, onLiveSitesChanged, syncLiveRevision } from "./common.js";

let categories = [];

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
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
          (d) => `<tr>
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
    : `<tr><td class="empty" colspan="7">No documents match.</td></tr>`;
  $("statusLine").textContent = `${docs.length} document${docs.length === 1 ? "" : "s"}`;
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

async function init() {
  injectChrome({ active: "/documents" });
  const meta = await api("/api/meta");
  categories = meta.doc_categories || [];
  $("categoryFilter").innerHTML =
    `<option value="">All categories</option>` +
    categories
      .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
      .join("");
  $("categoryFilter").addEventListener("change", load);
  $("moaFilter").addEventListener("input", debounce(load, 250));
  $("search").addEventListener("input", debounce(load, 250));
  document.addEventListener("change", (ev) => {
    const sel = ev.target.closest("tbody [data-doc-cat]");
    if (sel) changeCategory(sel);
  });
  await load();
  onLiveSitesChanged(() => load().catch(() => {}));
  await syncLiveRevision();
}

init().catch((err) => {
  $("tbody").innerHTML = `<tr><td class="empty" colspan="7">${escapeHtml(err.message)}</td></tr>`;
});
