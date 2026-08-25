import { $, api, currentUser, injectChrome, on, safeNextUrl } from "./common.js";

function qs(name) {
  return new URLSearchParams(location.search).get(name) || "";
}

function showError(msg) {
  const el = $("passwordError");
  if (!el) return;
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

function nextUrl() {
  return safeNextUrl(qs("next"), "/");
}

async function init() {
  await injectChrome({ active: "/password" });
  const user = currentUser();
  const forced = Boolean(user?.must_change_password);
  const banner = $("mustChangeBanner");
  const hint = $("passwordHint");
  if (banner) banner.hidden = !forced;
  if (forced && hint) {
    hint.textContent = "Set a new password to continue. It must be at least 8 characters.";
  }
  if (user?.username && String(user.username).toLowerCase() === "root") {
    if (hint) {
      hint.textContent = "The recovery account password is fixed and cannot be changed here.";
    }
    if (banner) banner.hidden = true;
    $("passwordForm")?.querySelectorAll("input, button").forEach((el) => {
      el.disabled = true;
    });
  }
}

on("passwordForm", "submit", async (e) => {
  e.preventDefault();
  showError("");
  const currentPassword = $("currentPassword").value;
  const newPassword = $("newPassword").value;
  const confirmPassword = $("confirmPassword").value;
  if (newPassword !== confirmPassword) {
    showError("New password and confirmation do not match.");
    return;
  }
  if (newPassword.trim().length < 8) {
    showError("New password must be at least 8 characters.");
    return;
  }
  if (newPassword === currentPassword) {
    showError("New password must be different from the current password.");
    return;
  }
  const btn = $("passwordBtn");
  btn.disabled = true;
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    location.replace(nextUrl());
  } catch (err) {
    showError(err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init().catch((err) => {
  showError(err.message || String(err));
});
