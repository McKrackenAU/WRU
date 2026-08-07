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
    location.replace(nextUrl());
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
    location.replace(nextUrl());
  } catch (err) {
    showError("loginError", err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init();
