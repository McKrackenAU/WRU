import {
  $,
  injectChrome,
  alertDialog,
  confirmDialog,
  errorMessage,
  uploadFileChunked,
} from "./common.js";

function setStatus(id, text) {
  const el = $(id);
  if (el) el.textContent = text || "";
}

async function exportBackup() {
  setStatus("exportStatus", "Building backup — the download starts when it is ready…");
  const btn = $("btnExportBackup");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/admin/backup/export", {
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = res.statusText || `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const disp = res.headers.get("content-disposition") || "";
    const match = /filename="?([^"]+)"?/i.exec(disp);
    const name = match?.[1] || "wru-backup.zip";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setStatus("exportStatus", `Downloaded ${name}`);
  } catch (err) {
    setStatus("exportStatus", "");
    await alertDialog(errorMessage(err, "Could not export backup"));
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function importBackup() {
  const file = $("backupFile")?.files?.[0];
  if (!file) {
    await alertDialog("Choose a WRU backup .zip first.");
    return;
  }
  const ok = await confirmDialog(
    "Import this backup? It replaces the live database and uploaded files on this server. This cannot be undone from here."
  );
  if (!ok) return;
  const btn = $("btnImportBackup");
  if (btn) btn.disabled = true;
  try {
    setStatus("importStatus", "Starting…");
    const result = await uploadFileChunked(file, {
      beginUrl: "/api/admin/backup/session",
      chunkUrl: (id, idx) => `/api/admin/backup/session/${encodeURIComponent(id)}/chunk/${idx}`,
      commitUrl: (id) => `/api/admin/backup/session/${encodeURIComponent(id)}/commit`,
      onProgress: (msg) => setStatus("importStatus", msg),
      timeoutMs: 300000,
    });
    setStatus("importStatus", result?.message || "Restored. Reload the tracker.");
    await alertDialog(result?.message || "Backup restored. Reload every open WRU tab.");
  } catch (err) {
    setStatus("importStatus", "");
    await alertDialog(errorMessage(err, "Could not import backup"));
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function init() {
  injectChrome({ active: "/admin/backup", mode: "admin" });
  $("btnExportBackup")?.addEventListener("click", () => exportBackup());
  $("btnImportBackup")?.addEventListener("click", () => importBackup());
}

init().catch((e) => {
  alertDialog(e.message);
});
