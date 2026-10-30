// Streams page: sidebar, live transcript, add/edit, listen-along player.
const streams = new Map();
let selected = null;        // stream id
let oldestId = null;        // for "load earlier"
let lastShown = null;       // last rendered segment (for day / gap separators)
let query = "";
let editingId = null;
let hls = null;

const $ = id => document.getElementById(id);
const current = () => streams.get(selected);
const transcriptEl = $("transcript");

// ---------------------------------------------------------------- boot
(async function init() {
  await mountTopbar("app");
  $("toggle-sidebar")?.addEventListener("click", () => $("sidebar").classList.toggle("open"));
  const list = await api("GET", "/api/streams");
  list.forEach(s => streams.set(s.id, s));
  const fromHash = Number(new URLSearchParams(location.hash.slice(1)).get("s"));
  const remembered = Number(safeGet("selected"));
  const pick = [fromHash, remembered].find(id => streams.has(id)) ?? list[0]?.id;
  renderSidebar();
  if (pick) select(pick); else showEmpty();
  connectEvents();
  setInterval(renderSidebar, 30000); // keep "2m ago" fresh
})();

function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { localStorage.setItem(k, v); } catch {} }

// ---------------------------------------------------------------- sidebar
function subline(s) {
  if (!s.enabled) return "Stopped";
  if (s.status === "error") return s.error || "Error";
  if (s.status === "connecting") return "Connecting…";
  if (s.status === "reconnecting") return "Reconnecting…";
  if (s.last_text) return s.last_text;
  return "Listening for speech…";
}

function renderSidebar() {
  const ul = $("stream-list");
  const sorted = [...streams.values()].sort((a, b) => a.name.localeCompare(b.name));
  ul.innerHTML = sorted.map(s => `
    <li class="stream-item ${s.id === selected ? "active" : ""}" data-id="${s.id}" title="${esc(s.name)}">
      <span class="dot ${s.enabled ? s.status : ""}"></span>
      <span class="name">${esc(s.name)}</span>
      <span class="sub">${esc(subline(s))}</span>
    </li>`).join("");
  ul.querySelectorAll(".stream-item").forEach(li =>
    li.addEventListener("click", () => { select(Number(li.dataset.id)); $("sidebar").classList.remove("open"); }));
}

function showEmpty() {
  selected = null;
  $("view").hidden = true;
  $("empty").hidden = false;
  stopListening();
}

// ---------------------------------------------------------------- header
function renderHeader() {
  const s = current();
  if (!s) return;
  $("s-name").textContent = s.name;
  const status = s.enabled ? s.status : "stopped";
  const pill = $("s-pill");
  pill.className = "pill " + status;
  pill.querySelector(".dot").className = "dot " + status;
  pill.lastElementChild.textContent = STATUS_LABEL[status] || status;
  let host = s.url;
  try { host = new URL(s.url).host; } catch {}
  $("s-meta").innerHTML = [
    `<span>${esc(host)}</span>`,
    `<span>${s.language ? "Language: " + esc(s.language.toUpperCase()) : "Default language"}</span>`,
    s.last_text_at ? `<span>Last speech ${timeAgo(s.last_text_at)}</span>` : "",
  ].join("");
  const alert = $("s-alert");
  alert.hidden = !(s.enabled && s.error);
  alert.textContent = s.error || "";
  $("btn-toggle").innerHTML = s.enabled
    ? `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg><span>Stop</span>`
    : `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5.5v13a1 1 0 0 0 1.5.86l11-6.5a1 1 0 0 0 0-1.72l-11-6.5A1 1 0 0 0 7 5.5Z"/></svg><span>Start</span>`;
  $("btn-toggle").className = "btn" + (s.enabled ? "" : " primary");
  updateListeningHint();
}

// ---------------------------------------------------------------- transcript
async function select(id) {
  if (selected !== id) stopListening();
  selected = id;
  safeSet("selected", id);
  history.replaceState(null, "", "#s=" + id);
  $("empty").hidden = true;
  $("view").hidden = false;
  $("q").value = query = "";
  renderSidebar();
  renderHeader();
  await loadTranscript();
}

async function loadTranscript() {
  const id = selected;
  transcriptEl.innerHTML = "";
  lastShown = null;
  const params = new URLSearchParams({ limit: 150 });
  if (query) params.set("q", query);
  const data = await api("GET", `/api/streams/${id}/segments?${params}`);
  if (id !== selected) return;
  oldestId = data.segments[0]?.id ?? null;
  if (data.more) transcriptEl.insertAdjacentHTML("afterbegin",
    `<div class="load-older"><button class="btn sm" onclick="loadOlder()">Load earlier</button></div>`);
  if (!data.segments.length) {
    transcriptEl.insertAdjacentHTML("beforeend", `<div class="empty" id="none" style="height:auto;padding-top:60px">
      <div><p>${query ? "No lines match your search." : "No speech yet. Lines will appear here as they're transcribed."}</p></div></div>`);
  }
  data.segments.forEach(seg => appendLine(seg, false));
  updateListeningHint();
  scrollToLive();
}

async function loadOlder() {
  if (!oldestId) return;
  const params = new URLSearchParams({ limit: 150, before: oldestId });
  if (query) params.set("q", query);
  const data = await api("GET", `/api/streams/${selected}/segments?${params}`);
  const prevHeight = transcriptEl.scrollHeight;
  transcriptEl.querySelector(".load-older")?.remove();
  // Render the older block into a fragment, then put it on top.
  const savedLast = lastShown;
  lastShown = null;
  const holder = document.createElement("div");
  data.segments.forEach(seg => holder.appendChild(buildLine(seg, false)));
  lastShown = savedLast;
  if (data.more) holder.insertAdjacentHTML("afterbegin",
    `<div class="load-older"><button class="btn sm" onclick="loadOlder()">Load earlier</button></div>`);
  transcriptEl.prepend(...holder.childNodes);
  oldestId = data.segments[0]?.id ?? oldestId;
  transcriptEl.scrollTop += transcriptEl.scrollHeight - prevHeight;
}

const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const fmtDay = ts => new Date(ts * 1000).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });

function highlight(text) {
  const safe = esc(text);
  if (!query) return safe;
  const re = new RegExp(esc(query).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return safe.replace(re, m => `<mark>${m}</mark>`);
}

function buildLine(seg, isNew) {
  const frag = document.createDocumentFragment();
  if (!lastShown || fmtDay(lastShown.ts) !== fmtDay(seg.ts)) {
    const d = document.createElement("div");
    d.className = "day-sep";
    d.textContent = fmtDay(seg.ts);
    frag.appendChild(d);
  } else if (!query && seg.ts - (lastShown.ts + lastShown.duration) > 180) {
    const g = document.createElement("div");
    g.className = "gap-sep";
    frag.appendChild(g);
  }
  const line = document.createElement("div");
  line.className = "line" + (isNew ? " new" : "");
  line.dataset.id = seg.id;
  line.innerHTML = `<time>${fmtTime(seg.ts)}</time><p>${highlight(seg.text)}</p>`;
  frag.appendChild(line);
  lastShown = seg;
  return frag;
}

function appendLine(seg, isNew) {
  $("none")?.remove();
  const hint = transcriptEl.querySelector(".listening");
  const node = buildLine(seg, isNew);
  hint ? transcriptEl.insertBefore(node, hint) : transcriptEl.appendChild(node);
}

function updateListeningHint() {
  const s = current();
  let hint = transcriptEl.querySelector(".listening");
  const show = s && s.enabled && s.status === "live" && !query;
  if (show && !hint) {
    transcriptEl.insertAdjacentHTML("beforeend",
      `<div class="listening"><span class="wave"><i></i><i></i><i></i><i></i></span>Listening</div>`);
  } else if (!show && hint) hint.remove();
}

function nearBottom() { return transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 120; }
function scrollToLive() { transcriptEl.scrollTop = transcriptEl.scrollHeight; $("jump").hidden = true; }
transcriptEl.addEventListener("scroll", () => { if (nearBottom()) $("jump").hidden = true; });

let qTimer;
$("q").addEventListener("input", e => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { query = e.target.value.trim(); loadTranscript(); }, 300);
});

// ---------------------------------------------------------------- live events
function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = e => {
    const ev = JSON.parse(e.data);
    const s = streams.get(ev.stream_id);
    if (ev.type === "deleted") {
      streams.delete(ev.stream_id);
      renderSidebar();
      if (ev.stream_id === selected) { const next = streams.keys().next().value; next ? select(next) : showEmpty(); }
      return;
    }
    if (!s) { // a stream someone else just added
      if (ev.type === "status") api("GET", `/api/streams/${ev.stream_id}`).then(n => { streams.set(n.id, n); renderSidebar(); }).catch(() => {});
      return;
    }
    if (ev.type === "status") {
      Object.assign(s, { status: ev.status, error: ev.error, last_text_at: ev.last_text_at ?? s.last_text_at });
      renderSidebar();
      if (ev.stream_id === selected) renderHeader();
    } else if (ev.type === "segment") {
      s.last_text = ev.text;
      s.last_text_at = ev.ts + ev.duration;
      renderSidebar();
      if (ev.stream_id !== selected) return;
      if (query && !ev.text.toLowerCase().includes(query.toLowerCase())) return;
      const stick = nearBottom();
      appendLine(ev, true);
      if (stick) scrollToLive(); else $("jump").hidden = false;
    }
  };
  es.onerror = () => { /* EventSource reconnects by itself */ };
}

// ---------------------------------------------------------------- actions
function openStreamDialog(s) {
  const dlg = $("stream-dialog"), f = $("stream-form");
  f.reset();
  f.querySelector(".error-msg").hidden = true;
  editingId = s?.id ?? null;
  $("sd-title").textContent = s ? "Edit stream" : "Add a stream";
  $("sd-submit").textContent = s ? "Save changes" : "Add and start";
  if (s) { f.name.value = s.name; f.url.value = s.url; f.language.value = s.language; }
  dlg.showModal();
}

$("stream-form").addEventListener("submit", async e => {
  e.preventDefault();
  const dlg = $("stream-dialog"), f = e.target, err = f.querySelector(".error-msg");
  if (e.submitter?.value === "cancel") return dlg.close();
  const payload = { name: f.name.value.trim(), url: f.url.value.trim(), language: f.language.value };
  try {
    const s = editingId
      ? await api("PATCH", `/api/streams/${editingId}`, payload)
      : await api("POST", "/api/streams", payload);
    s.last_text = streams.get(s.id)?.last_text;
    streams.set(s.id, s);
    dlg.close();
    toast(editingId ? "Stream updated" : `Added ${s.name}`);
    editingId ? (renderSidebar(), renderHeader()) : select(s.id);
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
});

async function toggleEnabled() {
  const s = current();
  try {
    const n = await api("PATCH", `/api/streams/${s.id}`, { enabled: !s.enabled });
    Object.assign(s, n);
    renderSidebar(); renderHeader();
  } catch (ex) { toast(ex.message, true); }
}

async function restartStream() {
  const s = current();
  try {
    Object.assign(s, await api("PATCH", `/api/streams/${s.id}`, { enabled: true, restart: true }));
    renderSidebar(); renderHeader();
    toast("Restarting " + s.name);
  } catch (ex) { toast(ex.message, true); }
}

async function deleteStream() {
  const s = current();
  if (!confirm(`Delete “${s.name}” and all of its transcript? This can't be undone.`)) return;
  try {
    await api("DELETE", `/api/streams/${s.id}`);
    streams.delete(s.id);
    renderSidebar();
    const next = streams.keys().next().value;
    next ? select(next) : showEmpty();
  } catch (ex) { toast(ex.message, true); }
}

function download(format, hours) {
  location.href = `/api/streams/${selected}/export?format=${format}&hours=${hours}`;
}

// ---------------------------------------------------------------- listen along
function loadHlsJs() {
  if (window.Hls) return Promise.resolve();
  return new Promise((res, rej) => {
    const sc = document.createElement("script");
    sc.src = "https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.17/hls.min.js";
    sc.onload = res; sc.onerror = () => rej(new Error("Couldn't load the audio player"));
    document.head.appendChild(sc);
  });
}

async function toggleListen() {
  if (!$("player").hidden) return stopListening();
  const s = current(), audio = $("audio");
  $("player").hidden = false;
  $("btn-listen").classList.add("primary");
  $("btn-listen").lastElementChild.textContent = "Stop listening";
  try {
    const isHls = /\.m3u8(\?|$)/i.test(s.url);
    if (isHls && !audio.canPlayType("application/vnd.apple.mpegurl")) {
      await loadHlsJs();
      hls = new Hls({ liveSyncDurationCount: 3 });
      hls.on(Hls.Events.ERROR, (_, d) => {
        if (d.fatal) { toast("This stream can't be played in the browser (the station may block it). Transcription is unaffected.", true); stopListening(); }
      });
      hls.loadSource(s.url);
      hls.attachMedia(audio);
    } else {
      audio.src = s.url;
    }
    await audio.play();
  } catch (ex) {
    if (ex.name !== "AbortError") { toast(ex.message || "Playback failed", true); stopListening(); }
  }
}

function stopListening() {
  const audio = $("audio");
  if (hls) { hls.destroy(); hls = null; }
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  $("player").hidden = true;
  $("btn-listen").classList.remove("primary");
  $("btn-listen").lastElementChild.textContent = "Listen";
}
