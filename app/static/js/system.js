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
  const mark = el.querySelector(".mark");
  if (mark) {
    mark.textContent = state === "ok" ? "✓" : state === "bad" ? "!" : "·";
  }
}

function renderSteps(s) {
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
}

function renderStatus(s) {
  const tag = s.version_tag || (s.app_version ? `v${String(s.app_version).replace(/^v/i, "")}` : "—");
  const commit = s.commit || "—";
  const when = s.updated_at || "—";

  if ($("nowVersion")) $("nowVersion").textContent = tag;
  if ($("nowMeta")) {
    $("nowMeta").textContent = [s.branch || "main", commit !== "—" ? commit : null, when !== "—" ? when : null]
      .filter(Boolean)
      .join(" · ");
  }

  $("sysMeta").innerHTML = `
    <div class="version-chip accent"><span class="k">Version</span><span class="v">${escapeHtml(tag)}</span></div>
    <div class="version-chip"><span class="k">Branch</span><span class="v">${escapeHtml(s.branch || "—")}</span></div>
    <div class="version-chip"><span class="k">Commit</span><span class="v">${escapeHtml(commit)}</span></div>
    <div class="version-chip"><span class="k">Updated</span><span class="v">${escapeHtml(when)}</span></div>
    <div class="version-chip" style="grid-column:1/-1"><span class="k">Repository</span><span class="v">${escapeHtml(s.repo || "—")}</span></div>
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
      "Almost there — open “Need a first-time shell setup?” below, run the command once, then hit Refresh.";
    setAlert(
      "warn",
      `<strong>One quick setup step left.</strong> ${escapeHtml(
        s.detail || "Run the shell update once as root, then refresh this page."
      )}`
    );
  } else {
    $("updHint").textContent =
      s.detail || "All set. Hit the green button whenever you want the latest from GitHub.";
    setAlert(
      "ok",
      `<strong>Ready when you are.</strong> Currently on ${escapeHtml(tag)}${
        s.commit ? ` (${escapeHtml(s.commit)})` : ""
      }. Database and uploads are kept.`
    );
  }
}

function renderHistory(payload) {
  const history = payload.history || [];
  const can = payload.current?.can_update;
  const max = payload.max_history || 5;
  $("histHint").textContent = history.length
    ? `${history.length} of ${max} earlier installs ready if you need to roll back.`
    : `After your next update we’ll keep up to ${max} earlier installs here for rollback.`;

  const body = $("histBody");
  if (!history.length) {
    body.innerHTML = `<tr><td class="empty" colspan="4">Nothing to roll back to yet — that’s normal on a fresh install.</td></tr>`;
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
        $("updStatus").textContent = `${successLabel} · ${s.version_tag || s.app_version}`;
        setAlert(
          "ok",
          `<strong>${escapeHtml(successLabel)}.</strong> You’re now on ${escapeHtml(
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
  $("updStatus").textContent = "Still working — check the log, or refresh in a minute.";
  setAlert("warn", "<strong>Still updating.</strong> Give it another minute, or peek at the log below.");
  await refreshLog();
}

async function checkForUpdate() {
  const btn = $("btnCheckUpdate");
  if (btn) btn.disabled = true;
  $("updStatus").textContent = "Checking GitHub…";
  setAlert("pending", "<strong>Checking for updates…</strong> Asking GitHub for the latest VERSION.");
  try {
    const result = await api("/api/system/check-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        branch: $("updBranch")?.value.trim() || "main",
        repo: $("updRepo")?.value.trim(),
      }),
      timeoutMs: 20000,
    });
    const detail = result.detail || "Check finished.";
    $("updStatus").textContent = detail;
    if (result.update_available) {
      const remote = result.remote_tag || result.remote_version || "a newer build";
      setAlert(
        "warn",
        `<strong>Update available — ${escapeHtml(remote)}.</strong> ${escapeHtml(detail)} ` +
          `Use <em>Pull &amp; install update</em> when you’re ready.`
      );
    } else {
      setAlert("ok", `<strong>You’re up to date.</strong> ${escapeHtml(detail)}`);
    }
  } catch (err) {
    $("updStatus").textContent = "";
    setAlert("bad", `<strong>Couldn’t check for updates.</strong> ${escapeHtml(err.message || err)}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runUpdate() {
  if (
    !confirm(
      "Update WRU from GitHub now?\n\nYour data and uploads stay. The app will restart briefly."
    )
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  if ($("btnCheckUpdate")) $("btnCheckUpdate").disabled = true;
  $("updStatus").textContent = "Starting…";
  setAlert("pending", "<strong>Update underway.</strong> Hang tight — the page will refresh when it’s back.");
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
    $("updStatus").textContent = "Installing — waiting for the app to come back…";
    await waitForChange(before, "All done");
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    setAlert("bad", `<strong>Couldn’t start the update.</strong> ${escapeHtml(err.message || err)}`);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
    if ($("btnCheckUpdate")) $("btnCheckUpdate").disabled = false;
  }
}

async function runRollback(version) {
  if (
    !confirm(
      `Roll back to ${version}?\n\nYour data and uploads stay. The app will restart briefly.`
    )
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  $("updStatus").textContent = `Rolling back to ${version}…`;
  setAlert("pending", `<strong>Rolling back to ${escapeHtml(version)}.</strong>`);
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
    await waitForChange(before, `Back on ${version}`);
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    setAlert("bad", `<strong>Rollback didn’t start.</strong> ${escapeHtml(err.message || err)}`);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
  }
}

async function loadNearmapConfig() {
  const cfg = await api("/api/map/config", { timeoutMs: 10000 });
  const hint = $("nearmapHint");
  const input = $("nearmapKey");
  if (cfg.nearmap_configured) {
    const src = cfg.nearmap_key_source === "env" ? "from server environment" : "saved in this install";
    if (hint) hint.textContent = `Configured ${src}. Nearmap is available on the Works map.`;
    if (input) {
      input.placeholder = "••••••••  (enter a new key to replace)";
      input.value = "";
      input.disabled = cfg.nearmap_key_source === "env";
    }
    if ($("btnSaveNearmap")) $("btnSaveNearmap").disabled = cfg.nearmap_key_source === "env";
    if ($("btnClearNearmap")) $("btnClearNearmap").disabled = cfg.nearmap_key_source === "env";
  } else {
    if (hint) hint.textContent = "Not configured — map will use OpenStreetMap only.";
    if (input) {
      input.placeholder = "Paste API key";
      input.disabled = false;
    }
    if ($("btnSaveNearmap")) $("btnSaveNearmap").disabled = false;
    if ($("btnClearNearmap")) $("btnClearNearmap").disabled = false;
  }
  return cfg;
}

async function saveNearmapKey(clear = false) {
  const status = $("nearmapStatus");
  const key = clear ? null : ($("nearmapKey")?.value || "").trim();
  if (!clear && !key) {
    if (status) status.textContent = "Paste a key first, or use Clear.";
    return;
  }
  if (status) status.textContent = clear ? "Clearing…" : "Saving…";
  try {
    const result = await api("/api/map/nearmap-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key }),
      timeoutMs: 15000,
    });
    if (status) {
      status.textContent = result.nearmap_configured
        ? `Saved${result.masked_key ? ` (${result.masked_key})` : ""}.`
        : "Cleared.";
    }
    await loadNearmapConfig();
  } catch (err) {
    if (status) status.textContent = "";
    alert(err.message || err);
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
    loadNearmapConfig().catch(() => {});
  });
  on("btnCheckUpdate", "click", () => checkForUpdate().catch((e) => alert(e.message)));
  on("btnUpdate", "click", () => runUpdate().catch((e) => alert(e.message)));
  on("btnSaveNearmap", "click", () => saveNearmapKey(false).catch((e) => alert(e.message)));
  on("btnClearNearmap", "click", () => {
    if (confirm("Remove the saved Nearmap API key?")) {
      saveNearmapKey(true).catch((e) => alert(e.message));
    }
  });
  try {
    await loadVersions();
  } catch (err) {
    showPageError("sysMeta", err, "Could not load system status");
    if ($("nowVersion")) $("nowVersion").textContent = "—";
    if ($("nowMeta")) $("nowMeta").textContent = err.message;
    $("histBody").innerHTML = `<tr><td class="empty" colspan="4">${escapeHtml(err.message)}</td></tr>`;
    setAlert("bad", `<strong>Couldn’t load status.</strong> ${escapeHtml(err.message)}`);
  }
  try {
    await loadNearmapConfig();
  } catch (err) {
    if ($("nearmapHint")) $("nearmapHint").textContent = err.message || "Could not load Nearmap settings.";
  }
}

init().catch((e) => {
  showPageError("sysMeta", e, "System page failed to start");
  alert(e.message);
});
