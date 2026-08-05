import { $, on } from "./common.js";

function qs(name) {
  return new URLSearchParams(location.search).get(name) || "";
}

function showError(id, msg) {
  const el = $(id);
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
  const n = qs("next");
  if (!n || !n.startsWith("/") || n.startsWith("//") || n.startsWith("/login")) return "/";
  return n;
}

function showChangeForm(prefillCurrent = "") {
  $("loginForm").hidden = true;
  $("changeForm").hidden = false;
  if (prefillCurrent) $("currentPassword").value = prefillCurrent;
  $("newPassword").focus();
}

async function tryResumeSession() {
  try {
    const res = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function init() {
  const existing = await tryResumeSession();
  if (existing) {
    if (existing.must_change_password || qs("change") === "1") {
      showChangeForm();
      return;
    }
    location.replace(nextUrl());
    return;
  }
  if (qs("change") === "1") {
    showError("loginError", "Sign in again, then set a new password.");
  }
}

on("loginForm", "submit", async (e) => {
  e.preventDefault();
  showError("loginError", "");
  const btn = $("loginBtn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("username").value.trim(),
        password: $("password").value,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText || "Login failed");
    }
    const user = body.user || {};
    try {
      localStorage.setItem("wru_user", user.display_name || user.username || "");
      localStorage.setItem("wru_role", user.role || "user");
    } catch {
      /* ignore */
    }
    if (user.must_change_password) {
      showChangeForm($("password").value);
      return;
    }
    location.replace(nextUrl());
  } catch (err) {
    showError("loginError", err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

on("changeForm", "submit", async (e) => {
  e.preventDefault();
  showError("changeError", "");
  const next = $("newPassword").value;
  const confirm = $("confirmPassword").value;
  if (next.length < 8) {
    showError("changeError", "New password must be at least 8 characters.");
    return;
  }
  if (next !== confirm) {
    showError("changeError", "New passwords do not match.");
    return;
  }
  const btn = $("changeBtn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/auth/change-password", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: $("currentPassword").value,
        new_password: next,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText || "Could not change password");
    }
    const user = body.user || {};
    try {
      localStorage.setItem("wru_user", user.display_name || user.username || "");
      localStorage.setItem("wru_role", user.role || "user");
    } catch {
      /* ignore */
    }
    location.replace(nextUrl());
  } catch (err) {
    showError("changeError", err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init();
