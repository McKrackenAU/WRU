import { $, api, escapeHtml, injectChrome } from "./common.js";

function renderStatus(s) {
  $("sysMeta").innerHTML = `
    <label>App version<input readonly value="${escapeHtml(s.app_version)}" /></label>
    <label>Branch<input readonly value="${escapeHtml(s.branch)}" /></label>
    <label>Commit<input readonly value="${escapeHtml(s.commit || "—")}" /></label>
    <label>Last updated<input readonly value="${escapeHtml(s.updated_at || "—")}" /></label>
    <label class="full">Repository<input readonly value="${escapeHtml(s.repo)}" /></label>
    <label class="full">Update helper<input readonly value="${escapeHtml(s.can_update ? s.update_available_via : s.detail || "Unavailable")}" /></label>
  `;
  $("updBranch").value = s.branch || "main";
  $("updRepo").value = s.repo || "https://github.com/McKrackenAU/WRU.git";
  $("btnUpdate").disabled = !s.can_update;
}

async function loadStatus() {
  const s = await api("/api/system");
  renderStatus(s);
  return s;
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
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const s = await loadStatus();
        if (s.updated_at && s.updated_at !== before) {
          $("updStatus").textContent = `Update complete · ${s.app_version} (${s.commit || s.branch})`;
          return;
        }
      } catch (_) {
        /* service restarting */
      }
    }
    $("updStatus").textContent = "Update may still be running — refresh in a minute.";
  } catch (err) {
    $("updStatus").textContent = "";
    $("updLog").hidden = false;
    $("updLog").textContent = String(err.message || err);
    await loadStatus().catch(() => {});
  } finally {
    $("btnUpdate").disabled = false;
  }
}

async function init() {
  injectChrome({ active: "/system" });
  $("btnRefresh").addEventListener("click", () =>
    loadStatus().catch((e) => alert(e.message))
  );
  $("btnUpdate").addEventListener("click", () =>
    runUpdate().catch((e) => alert(e.message))
  );
  await loadStatus();
}

init().catch((e) => alert(e.message));
