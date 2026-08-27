import { $, api, currentUser, injectChrome, on, setSessionUser } from "./common.js";

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

async function init() {
  await injectChrome({ active: "/account" });
  const user = currentUser();
  if ($("accountUsername")) $("accountUsername").value = user?.username || "";
  if ($("accountRole")) $("accountRole").value = user?.role || "";
  if ($("accountDisplayName")) $("accountDisplayName").value = user?.display_name || user?.username || "";
  if (user?.username && String(user.username).toLowerCase() === "root") {
    $("accountDisplayName").readOnly = true;
    $("accountSaveBtn").disabled = true;
  }
}

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
    const user = await api("/api/auth/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: name }),
    });
    setSessionUser(user);
    if ($("accountDisplayName")) $("accountDisplayName").value = user.display_name || name;
    const chip = document.querySelector(".session-user");
    if (chip) chip.textContent = user.display_name || user.username || name;
    show($("accountSaved"), "Saved.");
  } catch (err) {
    show($("accountError"), err.message || String(err));
  } finally {
    btn.disabled = false;
  }
});

init().catch((err) => show($("accountError"), err.message || String(err)));
