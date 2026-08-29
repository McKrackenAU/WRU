import { $, api, escapeHtml, injectChrome, alertDialog, showPageError } from "./common.js";

function card(row) {
  return `
    <section class="panel-card" style="margin-bottom:1rem" data-kind="${escapeHtml(row.key)}">
      <h2>${escapeHtml(row.label)}</h2>
      <p class="hint">${escapeHtml(row.hint)}</p>
      <form class="form-grid" data-storage-form>
        <label class="full">Custom path
          <input name="path" value="${escapeHtml(row.path || "")}" placeholder="${escapeHtml(row.default_path)}" spellcheck="false" />
        </label>
        <p class="hint full">Default: <code>${escapeHtml(row.default_path)}</code></p>
        <p class="hint full">In use: <code>${escapeHtml(row.resolved_path)}</code>
          ${row.writable ? " · writable" : " · <strong>not writable</strong>"}</p>
        <div class="full toolbar">
          <button type="submit" class="btn btn-primary">Save location</button>
          <button type="button" class="btn" data-reset>Use default</button>
          <span class="hint" data-status></span>
        </div>
      </form>
    </section>
  `;
}

async function load() {
  const rows = await api("/api/admin/storage");
  $("storageList").innerHTML = rows.map(card).join("");
  $("storageList").querySelectorAll("[data-kind]").forEach((section) => {
    const kind = section.dataset.kind;
    const form = section.querySelector("[data-storage-form]");
    const status = section.querySelector("[data-status]");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      status.textContent = "";
      try {
        const path = form.querySelector("[name=path]").value.trim();
        await api(`/api/admin/storage/${encodeURIComponent(kind)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        status.textContent = `Saved ${new Date().toLocaleTimeString()}`;
        await load();
      } catch (err) {
        await alertDialog(err.message || String(err));
      }
    });
    section.querySelector("[data-reset]")?.addEventListener("click", async () => {
      try {
        await api(`/api/admin/storage/${encodeURIComponent(kind)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: "" }),
        });
        await load();
      } catch (err) {
        await alertDialog(err.message || String(err));
      }
    });
  });
}

async function init() {
  await injectChrome({ active: "/admin/storage", mode: "admin" });
  await load();
}

init().catch((e) => {
  showPageError("storageList", e, "Could not load storage locations");
});
