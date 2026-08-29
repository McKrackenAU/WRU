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

let logPollTimer = null;
let logOpen = false;
let progressValue = 0;
const DEFAULT_BRANCH = "main";
const DEFAULT_REPO = "https://github.com/McKrackenAU/WRU.git";

function updatePayload() {
  return { branch: DEFAULT_BRANCH, repo: DEFAULT_REPO };
}

function setProgress(pct, label, { busy = true } = {}) {
  const wrap = $("updProgress");
  const fill = $("updProgressFill");
  const bar = $("updProgressBar");
  const text = $("updProgressLabel");
  if (!wrap || !fill) return;
  progressValue = Math.max(0, Math.min(100, Math.round(pct)));
  wrap.hidden = false;
  wrap.classList.toggle("is-busy", busy && progressValue < 100);
  fill.style.width = `${progressValue}%`;
  if (bar) bar.setAttribute("aria-valuenow", String(progressValue));
  if (text) text.textContent = label || (progressValue >= 100 ? "Done." : `Installing… ${progressValue}%`);
}

function hideProgress() {
  const wrap = $("updProgress");
  if (wrap) {
    wrap.hidden = true;
    wrap.classList.remove("is-busy");
  }
  progressValue = 0;
  const fill = $("updProgressFill");
  if (fill) fill.style.width = "0%";
}

function progressFromLog(text) {
  const t = (text || "").toLowerCase();
  let n = Math.max(progressValue, 12);
  if (/start|queued|begin/.test(t)) n = Math.max(n, 18);
  if (/git|fetch|pull|clone/.test(t)) n = Math.max(n, 38);
  if (/install|pip|copy|unpack/.test(t)) n = Math.max(n, 58);
  if (/restart|systemd|waiting|coming back/.test(t)) n = Math.max(n, 82);
  return Math.min(n, 90);
}

function setLogOpen(open) {
  logOpen = Boolean(open);
  const log = $("updLog");
  const btn = $("btnToggleLog");
  if (log) log.hidden = !logOpen;
  if (btn) {
    btn.setAttribute("aria-expanded", logOpen ? "true" : "false");
    btn.textContent = logOpen ? "Hide logs" : "Logs";
  }
}

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
  const detail = (s.detail || "").toLowerCase();
  const helperMissing = /not installed|isn['’]t installed/.test(detail);
  if (!s.can_update && helperMissing) {
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
  const channel = s.channel_label || "Beta";
  const channelKey = (s.channel || "beta").toLowerCase() === "stable" ? "stable" : "beta";
  const commit = s.commit || "—";
  const when = s.updated_at || "—";

  if ($("nowVersion")) $("nowVersion").textContent = tag;
  if ($("nowMeta")) {
    $("nowMeta").textContent = when !== "—" ? `${channel} · ${when}` : channel;
  }

  $("sysMeta").innerHTML = `
    <div class="version-chip accent"><span class="k">Version</span><span class="v">${escapeHtml(tag)}</span></div>
    <div class="version-chip channel-${channelKey}"><span class="k">Channel</span><span class="v">${escapeHtml(channel)}</span></div>
    <div class="version-chip"><span class="k">Branch</span><span class="v">${escapeHtml(s.branch || "—")}</span></div>
    <div class="version-chip"><span class="k">Commit</span><span class="v">${escapeHtml(commit)}</span></div>
    <div class="version-chip"><span class="k">Updated</span><span class="v">${escapeHtml(when)}</span></div>
    <div class="version-chip" style="grid-column:1/-1"><span class="k">Repository</span><span class="v">${escapeHtml(s.repo || "—")}</span></div>
  `;

  const markStable = $("btnMarkStable");
  const markBeta = $("btnMarkBeta");
  if (markStable) markStable.hidden = channelKey === "stable";
  if (markBeta) markBeta.hidden = channelKey !== "stable";

  const btn = $("btnUpdate");
  if (btn) btn.disabled = !s.can_update;

  renderSteps(s);

  if (!s.can_update) {
    $("updHint").textContent =
      s.detail || "The updater isn't ready on this server yet. Ask whoever installed WRU to finish setup, then hit Refresh.";
    setAlert(
      "warn",
      `<strong>Updater not ready.</strong> ${escapeHtml(
        s.detail || "The update helper isn’t installed on this server yet."
      )}`
    );
  } else {
    $("updHint").textContent =
      s.detail || "All set. Hit the green button whenever you want the latest from GitHub.";
    setAlert(
      "ok",
      `<strong>Ready when you are.</strong> Currently on ${escapeHtml(tag)} (${escapeHtml(channel)}). Database and uploads are kept.`
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
    body.innerHTML = `<tr><td class="empty" colspan="5">Nothing to roll back to yet — that’s normal on a fresh install.</td></tr>`;
    return;
  }
  body.innerHTML = history
    .map((h) => {
      const tag = escapeHtml(h.tag || `v${h.version}`);
      const channel = escapeHtml(h.channel_label || "—");
      const commit = escapeHtml(h.commit || "—");
      const when = escapeHtml(h.recorded_at || "—");
      const disabled = can ? "" : "disabled";
      return `<tr>
        <td>${tag}</td>
        <td>${channel}</td>
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
      runRollback(ver).catch((e) => { alertDialog(e.message); });
    });
  });
}

async function setChannel(channel) {
  const status = $("channelStatus");
  if (status) status.textContent = channel === "stable" ? "Marking Stable…" : "Marking Beta…";
  try {
    const next = await api("/api/system/channel", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel }),
      timeoutMs: 15000,
    });
    renderStatus(next);
    if (status) status.textContent = next.channel_label ? `Now ${next.channel_label}.` : "Saved.";
  } catch (err) {
    if (status) status.textContent = "";
    throw err;
  }
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
      if ($("updLog")) $("updLog").textContent = payload.log;
      if (logOpen) {
        $("updLog").hidden = false;
        $("updLog").scrollTop = $("updLog").scrollHeight;
      }
      if (!$("updProgress")?.hidden) {
        setProgress(progressFromLog(payload.log), $("updProgressLabel")?.textContent, { busy: true });
      }
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
    const bump = Math.min(90, progressValue + 2);
    setProgress(bump, $("updProgressLabel")?.textContent || "Installing…", { busy: true });
    try {
      const payload = await loadVersions();
      const s = payload.current;
      if (s.updated_at && s.updated_at !== beforeUpdatedAt) {
        setProgress(100, `${successLabel} · ${s.version_tag || s.app_version}`, { busy: false });
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
  $("updStatus").textContent = "Still working — open Logs, or refresh in a minute.";
  setAlert("warn", "<strong>Still updating.</strong> Give it another minute, or open Logs.");
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
      body: JSON.stringify(updatePayload()),
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
    !(await confirmDialog(
      "Update WRU from GitHub now?\n\nYour data and uploads stay. The app will restart briefly.",
      { title: "Install update", confirmLabel: "Update", cancelLabel: "Cancel" }
    ))
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  if ($("btnCheckUpdate")) $("btnCheckUpdate").disabled = true;
  $("updStatus").textContent = "Starting…";
  setAlert("pending", "<strong>Update underway.</strong> Hang tight — the page will refresh when it’s back.");
  setProgress(8, "Starting update…");
  if ($("updLog")) $("updLog").textContent = "Starting…";
  startLogPoll();
  try {
    const result = await api("/api/system/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updatePayload()),
      timeoutMs: 30000,
    });
    $("updStatus").textContent = result.message || "Update started.";
    if (result.log_tail && $("updLog")) $("updLog").textContent = result.log_tail;
    setProgress(progressFromLog(result.log_tail || result.message || ""), "Installing — waiting for the app to come back…");
    const before = result.status?.updated_at || "";
    $("updStatus").textContent = "Installing — waiting for the app to come back…";
    await waitForChange(before, "All done");
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    hideProgress();
    if ($("updLog")) $("updLog").textContent = String(err.message || err);
    setLogOpen(true);
    setAlert("bad", `<strong>Couldn’t start the update.</strong> ${escapeHtml(err.message || err)}`);
    await loadVersions().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
    if ($("btnCheckUpdate")) $("btnCheckUpdate").disabled = false;
  }
}

async function runRollback(version) {
  if (
    !(await confirmDialog(
      `Roll back to ${version}?\n\nYour data and uploads stay. The app will restart briefly.`,
      { title: "Roll back", confirmLabel: "Roll back", cancelLabel: "Cancel", danger: true }
    ))
  ) {
    return;
  }
  $("btnUpdate").disabled = true;
  $("updStatus").textContent = `Rolling back to ${version}…`;
  setAlert("pending", `<strong>Rolling back to ${escapeHtml(version)}.</strong>`);
  setProgress(8, `Rolling back to ${version}…`);
  if ($("updLog")) $("updLog").textContent = "Starting…";
  startLogPoll();
  try {
    const result = await api("/api/system/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
      timeoutMs: 30000,
    });
    $("updStatus").textContent = result.message || "Rollback started.";
    if (result.log_tail && $("updLog")) $("updLog").textContent = result.log_tail;
    setProgress(progressFromLog(result.log_tail || ""), `Rolling back to ${version}…`);
    const before = result.status?.updated_at || "";
    await waitForChange(before, `Back on ${version}`);
  } catch (err) {
    stopLogPoll();
    $("updStatus").textContent = "";
    hideProgress();
    if ($("updLog")) $("updLog").textContent = String(err.message || err);
    setLogOpen(true);
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
    alertDialog(err.message || err);
  }
}

async function init() {
  injectChrome({ active: "/admin/system", mode: "admin" });
  on("btnToggleLog", "click", () => {
    setLogOpen(!logOpen);
    if (logOpen) refreshLog().catch(() => {});
  });
  on("btnRefresh", "click", () => {
    loadVersions()
      .then(() => {
        if (logOpen) return refreshLog();
        return null;
      })
      .catch((e) => showPageError("sysMeta", e, "Could not load system status"));
    loadNearmapConfig().catch(() => {});
  });
  on("btnCheckUpdate", "click", () => checkForUpdate().catch((e) => { alertDialog(e.message); }));
  on("btnUpdate", "click", () => runUpdate().catch((e) => { alertDialog(e.message); }));
  on("btnMarkStable", "click", () => setChannel("stable").catch((e) => { alertDialog(e.message); }));
  on("btnMarkBeta", "click", () => setChannel("beta").catch((e) => { alertDialog(e.message); }));
  on("btnSaveNearmap", "click", () => saveNearmapKey(false).catch((e) => { alertDialog(e.message); }));
  on("btnClearNearmap", "click", async () => {
    if (!(await confirmDialog("Remove the saved Nearmap API key?"))) return;
    saveNearmapKey(true).catch((e) => { alertDialog(e.message); });
  });
  try {
    await loadVersions();
  } catch (err) {
    showPageError("sysMeta", err, "Could not load system status");
    if ($("nowVersion")) $("nowVersion").textContent = "—";
    if ($("nowMeta")) $("nowMeta").textContent = err.message;
    $("histBody").innerHTML = `<tr><td class="empty" colspan="5">${escapeHtml(err.message)}</td></tr>`;
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
  alertDialog(e.message);
});
