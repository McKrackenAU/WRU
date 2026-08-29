import { $, api, escapeHtml, injectChrome, alertDialog, showPageError } from "./common.js";

function mountOptions(mounts, selected) {
  const rows = mounts || [];
  const opts = [`<option value="">App default</option>`];
  for (const m of rows) {
    const mark = m.writable ? "" : " · not writable";
    opts.push(
      `<option value="${escapeHtml(m.path)}" ${m.path === selected ? "selected" : ""}>${escapeHtml(
        m.label || m.path
      )}${mark}</option>`
    );
  }
  opts.push(`<option value="__custom__" ${selected === "__custom__" ? "selected" : ""}>Type a path…</option>`);
  return opts.join("");
}

function previewPath(row, mount) {
  if (!mount) return row.default_path;
  const rel = row.default_relative || "";
  return `${mount.replace(/\/$/, "")}/${rel}`;
}

function card(row, mounts) {
  const inferred = row.inferred_mount || "";
  const known = new Set((mounts || []).map((m) => m.path));
  const selected = !row.path ? "" : inferred && known.has(inferred) ? inferred : "__custom__";
  const custom = selected === "__custom__";
  return `
    <section class="panel-card storage-card" data-kind="${escapeHtml(row.key)}">
      <h2>${escapeHtml(row.label)}</h2>
      <p class="hint">${escapeHtml(row.hint)}</p>
      <form class="form-grid" data-storage-form>
        <label>Disk / mount
          <select name="mount">${mountOptions(mounts, selected)}</select>
        </label>
        <p class="hint full" data-preview>Will use: <code>${escapeHtml(
          custom ? row.path || row.default_path : previewPath(row, selected)
        )}</code></p>
        <label class="full" data-custom-wrap ${custom ? "" : "hidden"}>Custom path
          <input name="path" value="${escapeHtml(row.path || "")}" placeholder="${escapeHtml(
            row.default_path
          )}" spellcheck="false" />
        </label>
        <p class="hint full">Default: <code>${escapeHtml(row.default_path)}</code>
          · In use: <code>${escapeHtml(row.resolved_path)}</code>
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

function bindPreview(section, row, mounts) {
  const form = section.querySelector("[data-storage-form]");
  const select = form.querySelector("[name=mount]");
  const customWrap = form.querySelector("[data-custom-wrap]");
  const preview = form.querySelector("[data-preview]");
  const pathInput = form.querySelector("[name=path]");
  const update = () => {
    const mount = select.value;
    customWrap.hidden = mount !== "__custom__";
    if (mount === "__custom__") {
      preview.innerHTML = `Will use: <code>${escapeHtml(pathInput.value.trim() || row.default_path)}</code>`;
    } else if (!mount) {
      preview.innerHTML = `Will use: <code>${escapeHtml(row.default_path)}</code>`;
    } else {
      preview.innerHTML = `Will use: <code>${escapeHtml(previewPath(row, mount))}</code> — folders are created on save.`;
    }
  };
  select.addEventListener("change", update);
  pathInput.addEventListener("input", update);
}

async function load() {
  const payload = await api("/api/admin/storage");
  const locations = payload.locations || payload;
  const mounts = payload.mounts || [];
  $("storageMounts").innerHTML = mountOptions(mounts, "");
  $("storageList").innerHTML = locations.map((row) => card(row, mounts)).join("");
  $("storageList").querySelectorAll("[data-kind]").forEach((section) => {
    const kind = section.dataset.kind;
    const row = locations.find((item) => item.key === kind);
    const form = section.querySelector("[data-storage-form]");
    const status = section.querySelector("[data-status]");
    bindPreview(section, row, mounts);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      status.textContent = "";
      try {
        const mount = form.querySelector("[name=mount]").value;
        const path = form.querySelector("[name=path]").value.trim();
        const body = mount && mount !== "__custom__" ? { mount } : { path: mount === "" ? "" : path };
        await api(`/api/admin/storage/${encodeURIComponent(kind)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
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

async function applyAll() {
  const mount = $("storageMounts").value;
  if (!mount || mount === "__custom__") {
    await alertDialog("Pick a disk / mount first. The app will create uploads, KML, and backups under it.");
    return;
  }
  try {
    await api("/api/admin/storage/documents", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mount, apply_all: true }),
    });
    await load();
  } catch (err) {
    await alertDialog(err.message || String(err));
  }
}

async function init() {
  await injectChrome({ active: "/admin/storage", mode: "admin" });
  $("btnApplyAll")?.addEventListener("click", () => applyAll());
  await load();
}

init().catch((e) => {
  showPageError("storageList", e, "Could not load storage locations");
});
