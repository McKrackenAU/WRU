import { $, api, escapeHtml, injectChrome, on, showPageError } from "./common.js";

let logPollTimer = null;

function setAlert(kind, html) {
  const el = $("sysAlert");
  if (!el) return;
  if (!html) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.className = `sys-alert sys-alert-${kind}`;
  el.innerHTML = html;
}

function setStep(name, state) {
  const el = document.querySelector(`[data-step="${name}"]`);
  if (!el) return;
  el.classList.remove("ok", "bad", "pending");
  el.classList.add(state);
}

function renderSteps(s) {
  const helperOk = Boolean(s.can_update) || !(s.detail || "").toLowerCase().includes("not installed");
  // Heuristic from status fields
  if (!s.can_update && (s.detail || "").toLowerCase().includes("not installed")) {
    setStep("helper", "bad");
    setStep("sudo", "pending");
    setStep("ready", "bad");
  } else if (!s.can_update) {
    setStep("helper", "ok");
    setStep("sudo", "bad");
    setStep("ready", "bad");
  } else {
    setStep("helper", "ok");
    setStep("sudo", "ok");
    setStep("ready", "ok");
  }
  void helperOk;
}

function renderStatus(s) {
  const tag = s.version_tag || (s.app_version ? `v${String(s.app_version).replace(/^v/i, "")}` : "—");
  $("sysMeta").innerHTML = `
    <label>App version<input readonly value="${escapeHtml(tag)}" /></label>
    <label>Branch / ref<input readonly value="${escapeHtml(s.branch || "—")}" /></label>
    <label>Commit<input readonly value="${escapeHtml(s.commit || "—")}" /></label>
    <label>Last updated<input readonly value="${escapeHtml(s.updated_at || "—")}" /></label>
    <label class="full">Repository<input readonly value="${escapeHtml(s.repo || "—")}" /></label>
  `;

  if ($("updBranch") && !$("updBranch").dataset.touched) {
    $("updBranch").value = s.branch || "main";
  }
  if ($("updRepo") && !$("updRepo").dataset.touched) {
    $("updRepo").value = s.repo || "https://github.com/McKrackenAU/WRU.git";
  }

  const btn = $("btnUpdate");
  if (btn) btn.disabled = !s.can_update;

  if ($("shellCt")) $("shellCt").textContent = s.shell_ct || "";
  if ($("shellPve")) $("shellPve").textContent = s.shell_proxmox || "";

  renderSteps(s);

  if (!s.can_update) {
    $("updHint").textContent =
      s.detail ||
      "In-app updates are not ready yet. Open “Advanced: update from the shell” and run the command once as root.";
    setAlert(
      "warn",
      `<strong>Updater not ready.</strong> ${escapeHtml(s.detail || "Run the shell update once, then refresh.")}`
    );
  } else {
    $("updHint").textContent =
      s.detail ||
      "Ready. Click Pull & install — the service restarts itself when the update finishes.";
    setAlert(
      "ok",
      `<strong>Ready to update.</strong> Current install: ${escapeHtml(tag)}${
        s.commit ? ` · ${escapeHtml(s.commit)}` : ""
      }.`
    );
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

async function loadVersions() {
  const payload = await api("/api/system/versions", { timeoutMs: 15000 });
  renderStatus(payload.current);
  renderHistory(payload);
  return payload;
}

async function refreshLog() {
  try {
    const payload = await api("/api/system/update-log", { timeoutMs: 10000 });
    if (payload.log) {
      $("updLog").hidden = false;
      $("updLog").textContent = payload.log;
      $("updLog").scrollTop = $("updLog").scrollHeight;
    }
  } catch (_) {
    /* ignore while service restarts */
  }
}

function startLogPoll() {
  stopLogPoll();
  logPollTimer = setInterval(() => {
    refreshLog().catch(() => {});
  }, 2500);
}

function stopLogPoll() {
  if (logPollTimer) {
    clearInterval(logPollTimer);
    logPollTimer = null;
  }
}

async function waitForChange(beforeUpdatedAt, successLabel) {
  startLogPoll();
  for (let i = 0; i < 80; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    try {
      const payload = await loadVersions();
      const s = payload.current;
      if (s.updated_at && s.updated_at !== beforeUpdatedAt) {
        $("updStatus").textContent = `${successLabel} · ${s.version_tag || s.app_version} (${s.commit || s.branch})`;
        setAlert(
          "ok",
          `<strong>${escapeHtml(successLabel)}.</strong> Now running ${escapeHtml(
            s.version_tag || s.app_version
          )}.`
        );
        await refreshLog();
        stopLogPoll();
        return;
      }
    } catch (_) {
      /* service restarting */
    }
  }
  stopLogPoll();
  $("updStatus").textContent = "Still running — check the log below, or refresh in a minute.";
  setAlert("warn", "<strong>Update may still be running.</strong> Check the log or refresh shortly.");
  await refreshLog();
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
  setAlert("pending", "<strong>Update started.</strong> Waiting for the service to come back…");
  $("updLog").hidden = false;
  $("updLog").textContent = "Starting…";
  startLogPoll();
  try {
    const result = await api("/api/system/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        branch: $("updBranch").value.trim() || "main",
        repo: $("updRepo").value.trim(),
      }),
      timeoutMs: 30000,
    });
    $("updStatus").textContent = result.message || "Update started.";
    if (result.log_tail) $("updLog").textContent = result.log_tail;
    const before = result.status?.updated_at || "";
    $("updStatus").textContent = "Update running — waiting for service…";
    await waitForChange(before, "Update complete");
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    setAlert("bad", `<strong>Update failed to start.</strong> ${escapeHtml(err.message || err)}`);
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
  setAlert("pending", `<strong>Rollback to ${escapeHtml(version)} started.</strong>`);
  $("updLog").hidden = false;
  $("updLog").textContent = "Starting…";
  startLogPoll();
  try {
    const result = await api("/api/system/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
      timeoutMs: 30000,
    });
    $("updStatus").textContent = result.message || "Rollback started.";
    if (result.log_tail) $("updLog").textContent = result.log_tail;
    const before = result.status?.updated_at || "";
    await waitForChange(before, `Rolled back to ${version}`);
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    setAlert("bad", `<strong>Rollback failed.</strong> ${escapeHtml(err.message || err)}`);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
  }
}

async function init() {
  injectChrome({ active: "/admin/system", mode: "admin" });
  on("updBranch", "input", () => {
    if ($("updBranch")) $("updBranch").dataset.touched = "1";
  });
  on("updRepo", "input", () => {
    if ($("updRepo")) $("updRepo").dataset.touched = "1";
  });
  on("btnRefresh", "click", () => {
    loadVersions()
      .then(() => refreshLog())
      .catch((e) => showPageError("sysMeta", e, "Could not load system status"));
  });
  on("btnUpdate", "click", () => runUpdate().catch((e) => alert(e.message)));
  try {
    await loadVersions();
  } catch (err) {
    showPageError("sysMeta", err, "Could not load system status");
    $("histBody").innerHTML = `<tr><td class="empty" colspan="4">${escapeHtml(err.message)}</td></tr>`;
    setAlert("bad", `<strong>System status failed.</strong> ${escapeHtml(err.message)}`);
  }
}

init().catch((e) => {
  showPageError("sysMeta", e, "System page failed to start");
  alert(e.message);
});
