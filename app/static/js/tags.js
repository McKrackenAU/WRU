import {
  $,
  api,
  on,
  escapeHtml,
  injectChrome,
  alertDialog,
  confirmDialog,
  showPageError,
} from "./common.js";

async function loadTags() {
  const rows = await api("/api/admin/tags");
  const wrap = $("tagsTableWrap");
  if (!rows.length) {
    wrap.innerHTML = `<p class="hint">No tags yet. Add one above.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Slug</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (t) => `<tr data-id="${t.id}">
              <td><input data-f="label" value="${escapeHtml(t.label || t.slug)}" maxlength="64" aria-label="Name for ${escapeHtml(t.slug)}" /></td>
              <td class="mono">${escapeHtml(t.slug)}</td>
              <td class="row-actions">
                <button type="button" class="btn" data-save>Save</button>
                <button type="button" class="btn btn-danger" data-delete>Delete</button>
              </td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;

  wrap.querySelectorAll("tr[data-id]").forEach((tr) => {
    const id = Number(tr.dataset.id);
    tr.querySelector("[data-save]")?.addEventListener("click", async () => {
      try {
        await api(`/api/admin/tags/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label: tr.querySelector('[data-f="label"]').value.trim() }),
        });
        await loadTags();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
    tr.querySelector("[data-delete]")?.addEventListener("click", async () => {
      if (
        !(await confirmDialog(
          "Remove this tag from the library? Existing jobs, categories, and users keep the slug until you edit them."
        ))
      ) {
        return;
      }
      try {
        await api(`/api/admin/tags/${id}`, { method: "DELETE" });
        await loadTags();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
  });
}

async function init() {
  await injectChrome({ active: "/admin/tags", mode: "admin" });
  await loadTags();

  on("createTagForm", "submit", async (e) => {
    e.preventDefault();
    const msg = $("createTagMsg");
    msg.textContent = "";
    try {
      const out = await api("/api/admin/tags", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: $("newTagLabel").value.trim() }),
      });
      $("createTagForm").reset();
      msg.textContent = `Created ${out.label || out.slug}.`;
      await loadTags();
    } catch (err) {
      msg.textContent = err.message || String(err);
    }
  });
}

init().catch((e) => {
  showPageError("tagsTableWrap", e, "Could not load tags");
});
