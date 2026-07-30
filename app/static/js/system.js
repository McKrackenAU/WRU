import { $, api, escapeHtml, injectChrome } from "./common.js";

function renderStatus(s) {
  const tag = s.version_tag || (s.app_version ? `v${String(s.app_version).replace(/^v/i, "")}` : "—");
  $("sysMeta").innerHTML = `
    <label>App version<input readonly value="${escapeHtml(tag)}" /></label>
    <label>Branch / ref<input readonly value="${escapeHtml(s.branch)}" /></label>
    <label>Commit<input readonly value="${escapeHtml(s.commit || "—")}" /></label>
    <label>Last updated<input readonly value="${escapeHtml(s.updated_at || "—")}" /></label>
    <label class="full">Repository<input readonly value="${escapeHtml(s.repo)}" /></label>
    <label class="full">Updater<input readonly value="${escapeHtml(s.can_update ? s.update_available_via : "Not installed yet — use shell command below")}" /></label>
  `;
  $("updBranch").value = s.branch || "main";
  $("updRepo").value = s.repo || "https://github.com/McKrackenAU/WRU.git";
  $("btnUpdate").disabled = !s.can_update;
  $("shellCt").textContent = s.shell_ct || "";
  $("shellPve").textContent = s.shell_proxmox || "";
  if (s.detail && !s.can_update) {
    $("updHint").textContent = s.detail;
  } else {
    $("updHint").innerHTML =
      "Runs <code>sudo /usr/local/sbin/wru-update</code> on this host. The service restarts when finished. " +
      "Each update records the previous version (max 5) for rollback below.";
  }
}

function renderHistory(payload) {
  const history = payload.history || [];
  const can = payload.current?.can_update;
  const max = payload.max_history || 5;
  $("histHint").textContent = history.length
    ? `${history.length} of ${max} prior version(s) available for rollback.`
    : `Up to ${max} prior installs can be restored. Empty until the first update after this release.`;

  const body = $("histBody");
  if (!history.length) {
    body.innerHTML = `<tr><td class="empty" colspan="4">No prior versions recorded yet.</td></tr>`;
    return;
  }
  body.innerHTML = history
    .map((h) => {
      const tag = escapeHtml(h.tag || `v${h.version}`);
      const commit = escapeHtml(h.commit || "—");
      const when = escapeHtml(h.recorded_at || "—");
      const disabled = can ? "" : "disabled";
      return `<tr>
        <td>${tag}</td>
        <td><code>${commit}</code></td>
        <td>${when}</td>
        <td>
          <button type="button" class="btn btn-danger" data-rollback="${tag}" ${disabled}>
            Roll back
          </button>
        </td>
      </tr>`;
    })
    .join("");

  body.querySelectorAll("[data-rollback]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const ver = btn.getAttribute("data-rollback");
      runRollback(ver).catch((e) => alert(e.message));
    });
  });
}

async function loadStatus() {
  const s = await api("/api/system");
  renderStatus(s);
  return s;
}

async function loadVersions() {
  const payload = await api("/api/system/versions");
  renderStatus(payload.current);
  renderHistory(payload);
  return payload;
}

async function waitForChange(beforeUpdatedAt, successLabel) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    try {
      const payload = await loadVersions();
      const s = payload.current;
      if (s.updated_at && s.updated_at !== beforeUpdatedAt) {
        $("updStatus").textContent = `${successLabel} · ${s.version_tag || s.app_version} (${s.commit || s.branch})`;
        return;
      }
    } catch (_) {
      /* service restarting */
    }
  }
  $("updStatus").textContent = "Job may still be running — refresh in a minute.";
}

async function runUpdate() {
  if (
    !confirm(
      "Pull latest code from GitHub and reinstall WRU?\n\nPostgreSQL data and uploads are kept. The service will restart."
    )
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  $("updStatus").textContent = "Starting update…";
  $("updLog").hidden = true;
  try {
    const result = await api("/api/system/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        branch: $("updBranch").value.trim() || "main",
        repo: $("updRepo").value.trim(),
      }),
    });
    $("updStatus").textContent = result.message || "Update started.";
    if (result.log_tail) {
      $("updLog").hidden = false;
      $("updLog").textContent = result.log_tail;
    }
    const before = result.status?.updated_at || "";
    $("updStatus").textContent = "Update running — waiting for service to come back…";
    await waitForChange(before, "Update complete");
  } catch (err) {
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
  }
}

async function runRollback(version) {
  if (
    !confirm(
      `Roll back to ${version}?\n\nPostgreSQL data and uploads are kept. The current version is saved in history (max 5).`
    )
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  $("updStatus").textContent = `Starting rollback to ${version}…`;
  $("updLog").hidden = true;
  try {
    const result = await api("/api/system/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
    $("updStatus").textContent = result.message || "Rollback started.";
    if (result.log_tail) {
      $("updLog").hidden = false;
      $("updLog").textContent = result.log_tail;
    }
    const before = result.status?.updated_at || "";
    $("updStatus").textContent = "Rollback running — waiting for service to come back…";
    await waitForChange(before, `Rolled back to ${version}`);
  } catch (err) {
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
  }
}

async function init() {
  injectChrome({ active: "/system" });
  $("btnRefresh").addEventListener("click", () =>
    loadVersions().catch((e) => alert(e.message))
  );
  $("btnUpdate").addEventListener("click", () =>
    runUpdate().catch((e) => alert(e.message))
  );
  await loadVersions();
}

init().catch((e) => alert(e.message));
