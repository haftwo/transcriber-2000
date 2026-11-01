let me = null, resetUserId = null;
const $ = id => document.getElementById(id);

(async function init() {
  me = await mountTopbar("admin");
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => showTab(t.dataset.tab)));
  showTab(location.hash.slice(1) || "overview");
  setInterval(() => { if (!document.querySelector('[data-panel="overview"]').hidden) loadOverview(); }, 10000);
})();

function showTab(name) {
  if (!document.querySelector(`[data-panel="${name}"]`)) name = "overview";
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll("[data-panel]").forEach(p => p.hidden = p.dataset.panel !== name);
  history.replaceState(null, "", "#" + name);
  ({ overview: loadOverview, users: loadUsers, settings: loadSettings, logs: loadLogs })[name]();
}

const fmtDate = ts => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const fmtDateTime = ts => new Date(ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });

// ---------------------------------------------------------------- overview
async function loadOverview() {
  const [stats, streams] = await Promise.all([api("GET", "/api/admin/stats"), api("GET", "/api/streams")]);
  $("storage-warning").hidden = stats.storage_ok;
  $("storage-warning").innerHTML = `<b>Settings won't survive an update.</b> ${esc(stats.storage_warning)}`;
  $("stats").innerHTML = [
    [stats.running + " / " + stats.streams, "Streams running"],
    [stats.segments_24h.toLocaleString(), "Lines in last 24h"],
    [stats.segments.toLocaleString(), "Lines stored"],
    [stats.users, stats.users === 1 ? "User" : "Users"],
    [stats.db_mb + " MB", "Database size"],
    [stats.audio_gb + " GB", "Recorded audio"],
  ].map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
  $("stream-rows").innerHTML = streams.length ? streams.map(s => {
    const st = s.enabled ? s.status : "stopped";
    return `<tr>
      <td><a href="/#s=${s.id}">${esc(s.name)}</a></td>
      <td><span class="pill ${st}"><span class="dot ${st}"></span>${STATUS_LABEL[st]}</span>
        ${s.enabled && s.error ? `<div class="muted" style="font-size:12.5px;margin-top:4px;max-width:320px">${esc(s.error)}</div>` : ""}</td>
      <td>${s.chunks}</td><td>${s.backlog}</td>
      <td class="muted">${s.last_text_at ? timeAgo(s.last_text_at) : "—"}</td>
      <td class="muted">${esc(s.created_by || "")}</td></tr>`;
  }).join("") : `<tr><td colspan="6" class="muted">No streams yet.</td></tr>`;
}

// ---------------------------------------------------------------- users
async function loadUsers() {
  const users = await api("GET", "/api/admin/users");
  $("user-rows").innerHTML = users.map(u => `<tr>
    <td><b>${esc(u.username)}</b>${u.id === me.id ? ' <span class="muted">(you)</span>' : ""}</td>
    <td>${u.is_admin ? '<span class="badge">Admin</span>' : '<span class="muted">User</span>'}${u.sso ? ' <span class="muted" title="Linked to a Microsoft account">· Microsoft</span>' : ""}</td>
    <td class="muted">${fmtDate(u.created)}</td>
    <td class="actions">
      <button class="btn sm ghost" onclick="openUserDialog(${u.id}, '${esc(u.username)}')">Reset password</button>
      ${u.id !== me.id ? `<button class="btn sm ghost" onclick="setAdmin(${u.id}, ${u.is_admin ? 0 : 1})">${u.is_admin ? "Make user" : "Make admin"}</button>
      <button class="btn sm ghost danger" onclick="deleteUser(${u.id}, '${esc(u.username)}')">Delete</button>` : ""}
    </td></tr>`).join("");
}

function openUserDialog(id, username) {
  const f = $("user-form");
  f.reset();
  f.querySelector(".error-msg").hidden = true;
  resetUserId = id ?? null;
  $("ud-title").textContent = id ? `Reset password for ${username}` : "Add user";
  $("ud-lede").textContent = id ? "They'll need the new password next time they sign in." : "They'll be able to view and manage streams.";
  $("ud-submit").textContent = id ? "Set password" : "Add user";
  $("ud-username").hidden = $("ud-admin").hidden = !!id;
  $("user-dialog").showModal();
}

$("user-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (e.submitter?.value === "cancel") return $("user-dialog").close();
  const f = e.target, err = f.querySelector(".error-msg");
  try {
    if (resetUserId) await api("PATCH", `/api/admin/users/${resetUserId}`, { password: f.password.value });
    else await api("POST", "/api/admin/users", { username: f.username.value.trim(), password: f.password.value, is_admin: f.is_admin.checked });
    $("user-dialog").close();
    toast(resetUserId ? "Password updated" : "User added");
    loadUsers();
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
});

async function setAdmin(id, val) {
  try { await api("PATCH", `/api/admin/users/${id}`, { is_admin: val }); loadUsers(); }
  catch (ex) { toast(ex.message, true); }
}

async function deleteUser(id, name) {
  if (!confirm(`Delete user “${name}”?`)) return;
  try { await api("DELETE", `/api/admin/users/${id}`); toast("User deleted"); loadUsers(); }
  catch (ex) { toast(ex.message, true); }
}

// ---------------------------------------------------------------- settings
let savedAudioDays = null;

async function loadSettings() {
  const s = await api("GET", "/api/admin/settings");
  savedAudioDays = Number(s.audio_retention_days);
  showAudioUsage();
  const f = $("settings-form");
  for (const [k, v] of Object.entries(s)) {
    const el = f.elements[k];
    if (!el) continue;
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
  }
  $("sso-redirect").value = location.origin + "/auth/microsoft/callback";
  f.sso_client_secret.placeholder = s.sso_client_secret_set ? "•••••••• saved — leave blank to keep" : "";
  $("sso-secret-hint").innerHTML = s.sso_client_secret_set
    ? "A secret is saved. Paste a new <b>Value</b> only to replace it."
    : "The secret's <b>Value</b>, not its ID.";
}

async function copyRedirect() {
  const el = $("sso-redirect");
  try { await navigator.clipboard.writeText(el.value); toast("Redirect URI copied"); }
  catch { el.select(); toast("Press Ctrl+C / ⌘C to copy", true); }
}

async function testSSO() {
  const f = $("settings-form"), el = $("sso-test-result");
  el.className = "test-result"; el.textContent = "Testing…";
  try {
    const r = await api("POST", "/api/admin/test-sso", {
      sso_tenant_id: f.sso_tenant_id.value.trim(),
      sso_client_id: f.sso_client_id.value.trim(),
      sso_client_secret: f.sso_client_secret.value.trim(),
    });
    el.className = "test-result " + (r.ok ? "ok" : "bad");
    el.textContent = (r.ok ? "✓ " : "✕ ") + r.message;
  } catch (ex) { el.className = "test-result bad"; el.textContent = "✕ " + ex.message; }
}

$("settings-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, out = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    out[el.name] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value;
  }
  const newDays = Number(out.audio_retention_days);
  const shorter = newDays > 0 && (savedAudioDays === 0 || newDays < savedAudioDays);
  if (shorter && !confirm(`Recordings older than ${newDays} day${newDays === 1 ? "" : "s"} will be deleted now. This can't be undone. Continue?`)) return;
  try {
    await api("PUT", "/api/admin/settings", out);
    toast("Settings saved");
    if (shorter) await pruneAudio(true);
    loadSettings();
  } catch (ex) { toast(ex.message, true); }
});

async function pruneAudio(confirmed) {
  const days = Number($("settings-form").audio_retention_days.value);
  if (!confirmed) {
    if (days !== savedAudioDays) return toast("Save your settings first, then delete", true);
    if (days <= 0) return toast("Recordings are set to be kept forever — set a number of days first", true);
    if (!confirm(`Delete all recorded audio older than ${days} day${days === 1 ? "" : "s"}? This can't be undone.`)) return;
  }
  try {
    const r = await api("POST", "/api/admin/prune-audio");
    toast(r.message);
    showAudioUsage();
  } catch (ex) { toast(ex.message, true); }
}

async function showAudioUsage() {
  try {
    const st = await api("GET", "/api/admin/stats");
    $("audio-usage").textContent = `Recordings currently use ${st.audio_gb} GB.`;
  } catch { /* not important */ }
}

async function testWhisper() {
  const el = $("test-result");
  el.className = "test-result"; el.textContent = "Testing…";
  try {
    const r = await api("POST", "/api/admin/test-whisper", { whisper_url: $("settings-form").whisper_url.value });
    el.className = "test-result " + (r.ok ? "ok" : "bad");
    el.textContent = (r.ok ? "✓ " : "✕ ") + r.message;
  } catch (ex) { el.className = "test-result bad"; el.textContent = "✕ " + ex.message; }
}

// ---------------------------------------------------------------- logs
async function loadLogs() {
  const rows = await api("GET", "/api/admin/logs?limit=300");
  $("log-rows").innerHTML = rows.length ? rows.map(r => `<tr>
    <td class="muted" style="white-space:nowrap">${fmtDateTime(r.ts)}</td>
    <td><span class="lvl ${r.level}">${r.level}</span></td>
    <td>${r.stream_name ? `<b>${esc(r.stream_name)}</b> · ` : ""}${esc(r.message)}</td></tr>`).join("")
    : `<tr><td class="muted">Nothing logged yet.</td></tr>`;
}
