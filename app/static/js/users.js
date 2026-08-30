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
import { selectedTagsFrom, tagPickerHtml } from "./tag_picker.js";

let tagLibrary = [];

function fmtWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

async function loadUsers() {
  const rows = await api("/api/admin/users");
  const wrap = $("usersTableWrap");
  if (!rows.length) {
    wrap.innerHTML = `<p class="hint">No users yet.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Display name</th>
            <th>Role</th>
            <th>Tags</th>
            <th>Active</th>
            <th>Last login</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (u) => `<tr data-id="${u.id}">
              <td><code>${escapeHtml(u.username)}</code>${
                u.must_change_password ? ' <span class="hint">must change pw</span>' : ""
              }</td>
              <td>${escapeHtml(u.display_name || "")}</td>
              <td>
                <select data-role aria-label="Role for ${escapeHtml(u.username)}">
                  <option value="user" ${u.role === "user" ? "selected" : ""}>User</option>
                  <option value="comms" ${u.role === "comms" ? "selected" : ""}>Comms</option>
                  <option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option>
                </select>
              </td>
              <td>
                <div data-tags>${tagPickerHtml({ library: tagLibrary, selected: u.tags || [], name: `user-${u.id}` })}</div>
              </td>
              <td>
                <label class="inline-check">
                  <input type="checkbox" data-active ${u.active ? "checked" : ""} />
                  Active
                </label>
              </td>
              <td>${escapeHtml(fmtWhen(u.last_login_at))}</td>
              <td class="row-actions">
                <button type="button" class="btn" data-save>Save</button>
                <button type="button" class="btn" data-reset>Reset password</button>
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
        await api(`/api/admin/users/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            role: tr.querySelector("[data-role]").value,
            active: tr.querySelector("[data-active]").checked,
            tags: selectedTagsFrom(tr.querySelector("[data-tags]")),
          }),
        });
        await loadUsers();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
    tr.querySelector("[data-reset]")?.addEventListener("click", async () => {
      if (!await confirmDialog("Reset this user’s password to a temporary value?")) return;
      try {
        const out = await api(`/api/admin/users/${id}/reset-password`, { method: "POST" });
        alertDialog(`Temporary password for ${out.username}:\n\n${out.temporary_password}\n\nThey must change it on next login.`);
        await loadUsers();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
    tr.querySelector("[data-delete]")?.addEventListener("click", async () => {
      if (!await confirmDialog("Delete this user permanently?")) return;
      try {
        await api(`/api/admin/users/${id}`, { method: "DELETE" });
        await loadUsers();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
  });
}

async function init() {
  await injectChrome({ active: "/admin/users", mode: "admin" });
  try {
    const data = await api("/api/tags");
    tagLibrary = data.items || [];
  } catch {
    tagLibrary = [];
  }
  if ($("newTagsPicker")) {
    $("newTagsPicker").innerHTML = tagPickerHtml({ library: tagLibrary, selected: [], name: "new-user" });
  }
  await loadUsers();

  on("createUserForm", "submit", async (e) => {
    e.preventDefault();
    const msg = $("createMsg");
    msg.textContent = "";
    try {
      const password = $("newPassword").value.trim();
      const body = {
        username: $("newUsername").value.trim(),
        display_name: $("newDisplayName").value.trim(),
        role: $("newRole").value,
        tags: selectedTagsFrom($("newTagsPicker")),
      };
      if (password) body.password = password;
      const out = await api("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      $("createUserForm").reset();
      if ($("newTagsPicker")) {
        $("newTagsPicker").innerHTML = tagPickerHtml({ library: tagLibrary, selected: [], name: "new-user" });
      }
      if (out.temporary_password) {
        msg.textContent = `Created ${out.username}. Temporary password: ${out.temporary_password}`;
      } else {
        msg.textContent = `Created ${out.username}.`;
      }
      await loadUsers();
    } catch (err) {
      msg.textContent = err.message || String(err);
    }
  });
}

init().catch((e) => {
  showPageError("usersTableWrap", e, "Could not load users");
});
