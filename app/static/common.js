// Shared helpers for every page.
async function api(method, path, body) {
  const opts = { method, headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/me/password")) {
    location.href = "/login";
    throw new Error("Signed out");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(msg, isErr) {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), isErr ? 6000 : 3000);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

const STATUS_LABEL = { live: "Live", connecting: "Connecting", reconnecting: "Reconnecting", error: "Error", stopped: "Stopped" };

// Simple drop-down menus: <div class="menu"><button data-menu>…</button><div class="menu-pop" hidden>…</div></div>
document.addEventListener("click", e => {
  const trigger = e.target.closest("[data-menu]");
  document.querySelectorAll(".menu-pop").forEach(p => {
    if (!trigger || p !== trigger.nextElementSibling) p.hidden = true;
  });
  if (trigger) trigger.nextElementSibling.hidden = !trigger.nextElementSibling.hidden;
});

async function signOut() {
  await api("POST", "/api/logout").catch(() => {});
  location.href = "/login";
}

function openPasswordDialog() {
  const dlg = document.getElementById("pw-dialog");
  dlg.querySelector("form").reset();
  dlg.querySelector(".error-msg").hidden = true;
  dlg.showModal();
}

function wirePasswordDialog() {
  const dlg = document.getElementById("pw-dialog");
  if (!dlg) return;
  dlg.querySelector("form").addEventListener("submit", async e => {
    e.preventDefault();
    if (e.submitter && e.submitter.value === "cancel") return dlg.close();
    const f = e.target, err = f.querySelector(".error-msg");
    if (f.new.value !== f.confirm.value) { err.textContent = "New passwords don't match"; err.hidden = false; return; }
    try {
      await api("POST", "/api/me/password", { current: f.current.value, new: f.new.value });
      dlg.close();
      toast("Password updated");
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  });
}

// ---- Theme: "auto" follows the device, "light"/"dark" override it. Saved per browser.
const THEME_ICONS = {
  auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
  light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>',
};
function getTheme() {
  try { const t = localStorage.getItem("theme"); return t === "light" || t === "dark" ? t : "auto"; } catch (e) { return "auto"; }
}
function setTheme(t) {
  try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch (e) {}
  if (t === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  document.querySelectorAll(".theme-seg button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.theme === t)));
  window.dispatchEvent(new Event("themechange"));
}
function themePickerHTML() {
  const cur = getTheme();
  return `<div class="theme-seg" role="group" aria-label="Theme">` +
    ["auto", "light", "dark"].map(t =>
      `<button type="button" data-theme="${t}" aria-pressed="${t === cur}" title="${t === "auto" ? "Match this device" : t[0].toUpperCase() + t.slice(1) + " mode"}">${THEME_ICONS[t]}${t[0].toUpperCase() + t.slice(1)}</button>`
    ).join("") + `</div>`;
}
function mountThemePicker(el) {
  el.innerHTML = themePickerHTML();
  el.addEventListener("click", e => {
    const b = e.target.closest(".theme-seg button");
    if (!b) return;
    e.stopPropagation();  // keep the user menu open while switching
    setTheme(b.dataset.theme);
  });
}
// Redraw anything colour-dependent when the device switches light/dark in Auto mode.
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => window.dispatchEvent(new Event("themechange"))); } catch (e) {}

const PW_DIALOG = `
<dialog id="pw-dialog"><form method="dialog">
  <h3>Change password</h3><p class="lede">Use at least 8 characters.</p>
  <div class="error-msg" hidden></div>
  <label class="field"><span>Current password</span><input type="password" name="current" autocomplete="current-password" required></label>
  <label class="field"><span>New password</span><input type="password" name="new" autocomplete="new-password" minlength="8" required></label>
  <label class="field"><span>Confirm new password</span><input type="password" name="confirm" autocomplete="new-password" minlength="8" required></label>
  <div class="dialog-actions"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn primary" value="ok">Update password</button></div>
</form></dialog>`;

async function mountTopbar(active) {
  const me = await api("GET", "/api/me");
  const el = document.querySelector(".topbar");
  el.innerHTML = `
    ${active === "app" ? `<button class="btn ghost icon only-mobile" id="toggle-sidebar" aria-label="Streams">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>` : ""}
    <a class="brand" href="/"><img class="brand-mark" src="/static/favicon.svg" alt="">Audio Transcriber - 2000</a>
    <div class="spacer"></div>
    <a class="nav-link hide-mobile ${active === "app" ? "active" : ""}" href="/">Streams</a>
    ${me.is_admin ? `<a class="nav-link hide-mobile ${active === "admin" ? "active" : ""}" href="/admin">Admin</a>` : ""}
    <div class="menu">
      <button class="btn ghost sm" data-menu>${esc(me.username)}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>
      <div class="menu-pop" hidden>
        <div class="label">Signed in as ${esc(me.username)}${me.is_admin ? " · admin" : ""}</div>
        <a class="mobile-item" href="/">Streams</a>
        ${me.is_admin ? `<a class="mobile-item" href="/admin">Admin</a>` : ""}
        <hr><div class="label">Theme</div>
        <div id="menu-theme"></div>
        <hr>
        <button onclick="openPasswordDialog()">Change password</button>
        <hr><button class="danger" onclick="signOut()">Sign out</button>
      </div>
    </div>`;
  mountThemePicker(document.getElementById("menu-theme"));
  document.body.insertAdjacentHTML("beforeend", PW_DIALOG);
  wirePasswordDialog();
  return me;
}
