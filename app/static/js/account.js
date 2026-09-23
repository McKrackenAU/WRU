import {
  $,
  api,
  applyLook,
  currentUser,
  injectChrome,
  on,
  OPS_NAV,
  persistAndApplyLook,
  setSessionUser,
  THEME_KEY,
} from "./common.js";

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

const LIGHT_DEFAULTS = {
  accent: "#004825",
  bg: "#f3f6f2",
  ink: "#1f2933",
  panel: "#ffffff",
  border: "#d5ddd4",
};

const DARK_DEFAULTS = {
  accent: "#3dd68c",
  bg: "#070809",
  ink: "#e6e8eb",
  panel: "#0e1116",
  border: "#252a31",
};

const COLOR_FIELDS = {
  light: {
    accent: "colorLightAccent",
    bg: "colorLightBg",
    ink: "colorLightInk",
    panel: "colorLightPanel",
    border: "colorLightBorder",
  },
  dark: {
    accent: "colorDarkAccent",
    bg: "colorDarkBg",
    ink: "colorDarkInk",
    panel: "colorDarkPanel",
    border: "colorDarkBorder",
  },
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

function fillPalette(mode, colors) {
  const defaults = mode === "dark" ? DARK_DEFAULTS : LIGHT_DEFAULTS;
  const fields = COLOR_FIELDS[mode];
  for (const [key, id] of Object.entries(fields)) {
    if ($(id)) $(id).value = colors?.[key] || defaults[key];
  }
}

function collectedPalette(mode) {
  const fields = COLOR_FIELDS[mode];
  const out = {};
  for (const [key, id] of Object.entries(fields)) {
    out[key] = $(id)?.value || "";
  }
  return out;
}

function previewTheme() {
  const theme = $("accountTheme")?.value || "system";
  const mode = theme === "dark" || theme === "light" ? theme : document.documentElement.classList.contains("dark") ? "dark" : "light";
  applyLook(
    {
      ...prefs(),
      colors_light: collectedPalette("light"),
      colors_dark: collectedPalette("dark"),
    },
    mode
  );
}

async function init() {
  await injectChrome({ active: "/account" });
  const user = currentUser();
  if ($("accountUsername")) $("accountUsername").value = user?.username || "";
  if ($("accountRole")) $("accountRole").value = user?.role || "";
  if ($("accountDisplayName")) $("accountDisplayName").value = user?.display_name || user?.username || "";
  if ($("accountTheme")) $("accountTheme").value = prefs().theme || "system";
  fillPalette("light", prefs().colors_light || prefs().colors || {});
  fillPalette("dark", prefs().colors_dark || {});
  const links = OPS_NAV.filter((l) => !l.commsOnly || user?.role === "comms" || user?.role === "admin").map((l) => ({
    key: l.href,
    label: l.label,
  }));
  renderPills("quickLinkPicker", links, prefs().quick_links || [], "quick");
  renderPills("homeWidgetPicker", WIDGETS, prefs().home_widgets || [], "widget");
  if (user?.username && String(user.username).toLowerCase() === "root") {
    $("accountDisplayName").readOnly = true;
  }
}

on("accountTheme", "change", () => {
  const theme = $("accountTheme").value;
  if (theme === "dark" || theme === "light") {
    try {
      const who = String(currentUser()?.username || "").toLowerCase();
      if (who) localStorage.setItem(`${THEME_KEY}:${who}`, theme);
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }
  previewTheme();
});

Object.values(COLOR_FIELDS.light).forEach((id) => {
  $(id)?.addEventListener("input", () => {
    applyLook({ ...prefs(), colors_light: collectedPalette("light") }, "light");
  });
});

Object.values(COLOR_FIELDS.dark).forEach((id) => {
  $(id)?.addEventListener("input", () => {
    applyLook({ ...prefs(), colors_dark: collectedPalette("dark") }, "dark");
  });
});

on("btnClearLightColors", "click", () => {
  fillPalette("light", {});
  applyLook({ ...prefs(), colors_light: {} }, "light");
});

on("btnClearDarkColors", "click", () => {
  fillPalette("dark", {});
  applyLook({ ...prefs(), colors_dark: {} }, "dark");
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
        colors_light: collectedPalette("light"),
        colors_dark: collectedPalette("dark"),
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
    persistAndApplyLook(user);
    if ($("accountDisplayName")) $("accountDisplayName").value = user.display_name || name;
    const chip = document.querySelector(".session-user");
    if (chip) chip.textContent = user.display_name || user.username || name;
    show($("accountSaved"), "Saved. These colours and shortcuts apply only to this login.");
  } catch (err) {
    show($("accountError"), err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init().catch((err) => show($("accountError"), err.message || String(err)));
