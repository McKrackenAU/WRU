import { $, api, applyUserColors, currentUser, injectChrome, on, OPS_NAV, setSessionUser } from "./common.js";

const WIDGETS = [
  { key: "approvals", label: "Approved MoAs" },
  { key: "status", label: "Status changes" },
  { key: "comms", label: "Comms" },
  { key: "costs", label: "Traffic estimates" },
  { key: "spend", label: "Actual spend" },
  { key: "stages", label: "Stages" },
  { key: "programs", label: "Programs" },
  { key: "councils", label: "Councils" },
];

const COLOR_DEFAULTS = {
  accent: "#0a7a45",
  bg: "#f4f7f5",
  ink: "#142018",
  panel: "#ffffff",
};

function show(el, msg) {
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

function prefs() {
  return currentUser()?.prefs || {};
}

function renderPills(hostId, items, selected, attr) {
  const host = $(hostId);
  if (!host) return;
  host.innerHTML = items
    .map((item) => {
      const on = selected.includes(item.key);
      return `<label class="prefs-pill ${on ? "is-on" : ""}">
        <input type="checkbox" data-${attr}="${item.key}" ${on ? "checked" : ""} />
        <span>${item.label}</span>
      </label>`;
    })
    .join("");
}

function selectedKeys(attr) {
  return [...document.querySelectorAll(`[data-${attr}]:checked`)].map((el) => el.getAttribute(`data-${attr}`));
}

function fillColors(colors) {
  const map = {
    colorAccent: colors?.accent || COLOR_DEFAULTS.accent,
    colorBg: colors?.bg || COLOR_DEFAULTS.bg,
    colorInk: colors?.ink || COLOR_DEFAULTS.ink,
    colorPanel: colors?.panel || COLOR_DEFAULTS.panel,
  };
  for (const [id, value] of Object.entries(map)) {
    if ($(id)) $(id).value = value;
  }
}

function collectedColors() {
  const raw = {
    accent: $("colorAccent")?.value || "",
    bg: $("colorBg")?.value || "",
    ink: $("colorInk")?.value || "",
    panel: $("colorPanel")?.value || "",
  };
  const out = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value && value !== COLOR_DEFAULTS[key]) out[key] = value;
  }
  return out;
}

async function init() {
  await injectChrome({ active: "/account" });
  const user = currentUser();
  if ($("accountUsername")) $("accountUsername").value = user?.username || "";
  if ($("accountRole")) $("accountRole").value = user?.role || "";
  if ($("accountDisplayName")) $("accountDisplayName").value = user?.display_name || user?.username || "";
  if ($("accountTheme")) $("accountTheme").value = prefs().theme || "system";
  fillColors(prefs().colors || {});
  const links = OPS_NAV.map((l) => ({ key: l.href, label: l.label }));
  renderPills("quickLinkPicker", links, prefs().quick_links || [], "quick");
  renderPills("homeWidgetPicker", WIDGETS, prefs().home_widgets || [], "widget");
  if (user?.username && String(user.username).toLowerCase() === "root") {
    $("accountDisplayName").readOnly = true;
  }
}

on("accountTheme", "change", () => {
  const theme = $("accountTheme").value;
  if (theme === "dark" || theme === "light") {
    localStorage.setItem("wru-tgs-theme", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
  }
});

["colorAccent", "colorBg", "colorInk", "colorPanel"].forEach((id) => {
  $(id)?.addEventListener("input", () => applyUserColors(collectedColors()));
});

on("btnClearColors", "click", () => {
  fillColors({});
  applyUserColors({});
});

on("accountForm", "submit", async (e) => {
  e.preventDefault();
  show($("accountError"), "");
  show($("accountSaved"), "");
  const name = $("accountDisplayName").value.trim();
  if (!name) {
    show($("accountError"), "Display name is required.");
    return;
  }
  const btn = $("accountSaveBtn");
  btn.disabled = true;
  try {
    const isRoot = String(currentUser()?.username || "").toLowerCase() === "root";
    const body = {
      prefs: {
        theme: $("accountTheme").value,
        colors: collectedColors(),
        quick_links: selectedKeys("quick").slice(0, 8),
        home_widgets: selectedKeys("widget"),
      },
    };
    if (!isRoot) body.display_name = name;
    const user = await api("/api/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setSessionUser(user);
    applyUserColors(user?.prefs?.colors);
    if ($("accountDisplayName")) $("accountDisplayName").value = user.display_name || name;
    const chip = document.querySelector(".session-user");
    if (chip) chip.textContent = user.display_name || user.username || name;
    show($("accountSaved"), "Saved. Reload any open tab to refresh shortcuts.");
  } catch (err) {
    show($("accountError"), err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init().catch((err) => show($("accountError"), err.message || String(err)));
