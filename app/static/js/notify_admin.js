import { $, api, on, escapeHtml, injectChrome, alertDialog, confirmDialog, showPageError } from "./common.js";

let stages = [];
let programs = [];
let users = [];

function userLabel(id) {
  const u = users.find((row) => row.id === id);
  if (!u) return `#${id}`;
  return u.display_name && u.display_name !== u.username ? `${u.display_name} (${u.username})` : u.username;
}

function selectedUserIds(select) {
  return [...(select?.selectedOptions || [])].map((o) => Number(o.value)).filter((n) => n > 0);
}

function userOptions(selected) {
  const picked = new Set((selected || []).map(Number));
  return users
    .map(
      (u) =>
        `<option value="${u.id}" ${picked.has(u.id) ? "selected" : ""}>${escapeHtml(userLabel(u.id))}</option>`
    )
    .join("");
}

function stageOptions(selected, includeBlank = false) {
  const blank = includeBlank ? `<option value="">Any stage</option>` : "";
  return (
    blank +
    stages
      .map((s) => `<option value="${escapeHtml(s.key)}" ${s.key === selected ? "selected" : ""}>${escapeHtml(s.label)}</option>`)
      .join("")
  );
}

function programOptions(selected) {
  const want = (selected || "").trim();
  return [
    `<option value="">Any program</option>`,
    ...programs.map(
      (p) => `<option value="${escapeHtml(p)}" ${p.toLowerCase() === want.toLowerCase() ? "selected" : ""}>${escapeHtml(p)}</option>`
    ),
  ].join("");
}

async function loadRules() {
  const rows = await api("/api/admin/notification-rules");
  const wrap = $("rulesTableWrap");
  if (!rows.length) {
    wrap.innerHTML = `<p class="hint">No rules yet. Add one below — for example Structures jobs entering Ready for Works, sent to anyone tagged <code>structures</code>.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>When</th>
            <th>Program</th>
            <th>Notify</th>
            <th>On</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map((r) => {
              const tags = (r.target_tags || []).map((t) => `<code>${escapeHtml(t)}</code>`).join(" ") || "—";
              const extras = (r.target_user_ids || []).map((id) => escapeHtml(userLabel(id))).join(", ");
              return `<tr data-id="${r.id}">
                <td><input data-f="name" value="${escapeHtml(r.name)}" /></td>
                <td>
                  <select data-f="stage_key">${stageOptions(r.stage_key)}</select>
                  <p class="hint" style="margin:0.25rem 0 0">Stage entered</p>
                </td>
                <td><select data-f="program">${programOptions(r.program)}</select></td>
                <td>
                  <input data-f="target_tags" value="${escapeHtml((r.target_tags || []).join(", "))}" placeholder="e.g. structures" />
                  <label class="hint" style="margin-top:0.35rem">Also these users <span class="hint">(none selected = tags only)</span>
                    <select data-f="target_user_ids" multiple size="3">${userOptions(r.target_user_ids)}</select>
                  </label>
                  <label class="hint" style="margin-top:0.35rem">Message
                    <textarea data-f="message_template" rows="2" placeholder="Optional. {site} {stage} {program}">${escapeHtml(r.message_template || "")}</textarea>
                  </label>
                </td>
                <td>
                  <label class="inline-check">
                    <input type="checkbox" data-f="enabled" ${r.enabled ? "checked" : ""} />
                    Enabled
                  </label>
                </td>
                <td class="row-actions">
                  <button type="button" class="btn" data-save>Save</button>
                  <button type="button" class="btn btn-danger" data-delete>Delete</button>
                </td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>
  `;

  wrap.querySelectorAll("tr[data-id]").forEach((tr) => {
    const id = Number(tr.dataset.id);
    tr.querySelector("[data-save]")?.addEventListener("click", async () => {
      try {
        await api(`/api/admin/notification-rules/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: tr.querySelector('[data-f="name"]').value.trim(),
            stage_key: tr.querySelector('[data-f="stage_key"]').value,
            program: tr.querySelector('[data-f="program"]').value,
            target_tags: tr.querySelector('[data-f="target_tags"]').value,
            target_user_ids: selectedUserIds(tr.querySelector('[data-f="target_user_ids"]')),
            message_template: tr.querySelector('[data-f="message_template"]').value,
            enabled: tr.querySelector('[data-f="enabled"]').checked,
          }),
        });
        await loadRules();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
    tr.querySelector("[data-delete]")?.addEventListener("click", async () => {
      if (!(await confirmDialog("Delete this notification rule?"))) return;
      try {
        await api(`/api/admin/notification-rules/${id}`, { method: "DELETE" });
        await loadRules();
      } catch (err) {
        alertDialog(err.message || String(err));
      }
    });
  });
}

async function init() {
  await injectChrome({ active: "/admin/notifications", mode: "admin" });
  const [meta, opts] = await Promise.all([api("/api/meta"), api("/api/admin/notification-rules/options")]);
  stages = meta.workflow_stages || [];
  programs = meta.programs || [];
  users = opts.users || [];

  $("newStage").innerHTML = stageOptions("ready_for_works");
  $("newProgram").innerHTML = programOptions("Structures");
  $("newUsers").innerHTML = userOptions([]);

  await loadRules();

  on("createRuleForm", "submit", async (e) => {
    e.preventDefault();
    const msg = $("createRuleMsg");
    msg.textContent = "";
    try {
      await api("/api/admin/notification-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: $("newRuleName").value.trim(),
          trigger: "stage_entered",
          stage_key: $("newStage").value,
          program: $("newProgram").value,
          target_tags: $("newTags").value,
          target_user_ids: selectedUserIds($("newUsers")),
          message_template: $("newMessage").value,
          enabled: $("newEnabled").checked,
        }),
      });
      $("createRuleForm").reset();
      $("newEnabled").checked = true;
      $("newStage").innerHTML = stageOptions("ready_for_works");
      $("newProgram").innerHTML = programOptions("Structures");
      $("newUsers").innerHTML = userOptions([]);
      msg.textContent = "Rule saved.";
      await loadRules();
    } catch (err) {
      msg.textContent = err.message || String(err);
    }
  });
}

init().catch((e) => {
  showPageError("rulesTableWrap", e, "Could not load notification rules");
});
