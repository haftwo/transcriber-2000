// Streams page: sidebar, live transcript, add/edit, listen-along player.
const streams = new Map();
let selected = null;        // stream id
let oldestId = null;        // for "load earlier"
let lastShown = null;       // last rendered segment (for day / gap separators)
let query = "";
let editingId = null;
let hls = null;
let pastMode = false;       // showing a past moment (picked with "Go to time") rather than live
let newestId = null;        // for "load later" while in pastMode

const $ = id => document.getElementById(id);
const current = () => streams.get(selected);
const transcriptEl = $("transcript");

// ---------------------------------------------------------------- boot
(async function init() {
  const me = await mountTopbar("app");
  if (me.is_admin) api("GET", "/api/admin/stats").then(st => {
    if (st.storage_ok) return;
    $("main").insertAdjacentHTML("afterbegin", `<div class="storage-warning" style="margin:14px 26px 0">
      <b>Settings won't survive an update.</b> ${esc(st.storage_warning)}</div>`);
  }).catch(() => {});
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

const byPosition = (a, b) => (a.position ?? 0) - (b.position ?? 0) || a.id - b.id;
const GRIP = `<span class="grip" title="Drag to reorder" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor">
  <circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/>
  <circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg></span>`;

function renderSidebar() {
  if (drag) return; // don't redraw the list while someone is dragging it
  const ul = $("stream-list");
  const sorted = [...streams.values()].sort(byPosition);
  ul.innerHTML = sorted.map(s => `
    <li class="stream-item ${s.id === selected ? "active" : ""}" data-id="${s.id}" title="${esc(s.name)}">
      <span class="dot ${s.enabled ? s.status : ""}"></span>
      <span class="name">${esc(s.name)}</span>
      <span class="sub">${esc(subline(s))}</span>
      ${sorted.length > 1 ? GRIP : ""}
    </li>`).join("");
  ul.querySelectorAll(".stream-item").forEach(li => {
    li.addEventListener("click", () => {
      if (justDragged) return;
      select(Number(li.dataset.id)); $("sidebar").classList.remove("open");
    });
    li.addEventListener("pointerdown", e => startDrag(e, li));
  });
}

// ---------------------------------------------------------------- drag to reorder
// Mouse: drag any stream. Touch: drag by the ⋮⋮ handle (so normal swipes still scroll the list).
let drag = null;
let justDragged = false;

function startDrag(e, li) {
  if (e.button !== 0 || streams.size < 2) return;
  if (e.pointerType !== "mouse" && !e.target.closest(".grip")) return;
  const ul = $("stream-list");
  const before = [...ul.children].map(el => Number(el.dataset.id));
  const startY = e.clientY;
  let active = false;

  const move = ev => {
    if (!active) {
      if (Math.abs(ev.clientY - startY) < 5) return; // a click, not a drag (yet)
      active = true;
      drag = li;
      li.classList.add("dragging");
      ul.classList.add("reordering");
    }
    ev.preventDefault();
    // put the dragged item before the first other item whose middle is below the pointer
    const others = [...ul.children].filter(el => el !== li);
    const next = others.find(el => { const r = el.getBoundingClientRect(); return ev.clientY < r.top + r.height / 2; });
    if (next) { if (li.nextElementSibling !== next) ul.insertBefore(li, next); }
    else if (ul.lastElementChild !== li) ul.appendChild(li);
    // auto-scroll when dragging near the top/bottom edge of a long list
    const box = ul.getBoundingClientRect();
    if (ev.clientY < box.top + 30) ul.scrollTop -= 8;
    else if (ev.clientY > box.bottom - 30) ul.scrollTop += 8;
  };

  const end = ev => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    if (!active) return;
    li.classList.remove("dragging");
    ul.classList.remove("reordering");
    drag = null;
    justDragged = true; setTimeout(() => { justDragged = false; }, 0); // swallow the click that follows
    const after = [...ul.children].map(el => Number(el.dataset.id));
    if (ev.type === "pointercancel" || after.join() === before.join()) { renderSidebar(); return; }
    saveOrder(after, before);
  };

  window.addEventListener("pointermove", move, { passive: false });
  window.addEventListener("pointerup", end);
  window.addEventListener("pointercancel", end);
}

function applyOrder(ids) {
  ids.forEach((id, i) => { const s = streams.get(id); if (s) s.position = i; });
}

async function saveOrder(ids, previous) {
  applyOrder(ids);
  renderSidebar();
  try {
    applyOrder((await api("PUT", "/api/streams/order", { ids })).ids);
  } catch (err) {
    applyOrder(previous); // put it back the way it was
    toast(`Couldn't save the new order: ${err.message}`, true);
  }
  renderSidebar();
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
  if (selected !== id) { stopListening(); closeClip(); }
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
  setPastMode(false);
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
  markLines();
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
  markLines();
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
  line.className = "line" + (isNew ? " new" : "") + (seg.rec_id ? " has-audio" : "");
  line.dataset.id = seg.id;
  line.dataset.ts = seg.ts;
  if (seg.rec_id) {
    line.dataset.rec = seg.rec_id;
    line.dataset.off = seg.rec_offset;
    line.dataset.dur = seg.duration;
    line.title = "Click to play · Shift-click to include more lines";
  }
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
  const show = s && s.enabled && s.status === "live" && !query && !pastMode;
  if (show && !hint) {
    transcriptEl.insertAdjacentHTML("beforeend",
      `<div class="listening"><span class="wave"><i></i><i></i><i></i><i></i></span>Listening</div>`);
  } else if (!show && hint) hint.remove();
}

function nearBottom() { return transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 120; }
function scrollToLive() {
  if (pastMode) { loadTranscript(); return; }
  transcriptEl.scrollTop = transcriptEl.scrollHeight; $("jump").hidden = true;
}
transcriptEl.addEventListener("scroll", () => { if (nearBottom() && !pastMode) $("jump").hidden = true; });

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
    if (ev.type === "order") { applyOrder(ev.ids); renderSidebar(); return; } // reordered (maybe in another tab)
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
      if (pastMode) { $("jump").hidden = false; return; } // looking at the past — don't add live lines
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
  closeClip();
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

// ---------------------------------------------------------------- recorded audio player
// Clicking a line loads that line plus 30 s either side from the server's recording,
// draws its waveform at the bottom of the page and plays from the start of the line.
const PAD = 30;            // seconds of context either side of the selected lines
const STEP = 30;           // seconds added by Earlier / Later
const MAX_CLIP = 15 * 60;  // matches the server limit
const clipAudio = $("clip-audio");
let clip = null;           // { streamId, rec, recStarted, recLength, from, to, selFrom, selTo, start, duration, peaks, url, blob }
let clipToken = 0;
let rafId = null;

const fmtClock = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

function lineInfo(el) {
  return el && el.dataset.rec ? { rec: Number(el.dataset.rec), off: Number(el.dataset.off), dur: Number(el.dataset.dur) } : null;
}

// Click a line → play it. Shift-click → stretch the selection to that line.
// Drag-select text across lines → load those lines (paused) so you can review or download.
transcriptEl.addEventListener("click", e => {
  const lineEl = e.target.closest(".line");
  if (!lineEl || (getSelection().toString() && !e.shiftKey)) return;
  const info = lineInfo(lineEl);
  if (!info) return toast("There's no recording for this line (recording was off, or the audio has expired).", true);
  if (e.shiftKey) getSelection().removeAllRanges();
  if (e.shiftKey && clip && clip.rec === info.rec) {
    openClip(info.rec, Math.min(clip.selFrom, info.off), Math.max(clip.selTo, info.off + info.dur), true);
  } else {
    openClip(info.rec, info.off, info.off + info.dur, true);
  }
});

transcriptEl.addEventListener("mouseup", () => {
  setTimeout(() => {
    const sel = getSelection();
    if (!sel.toString().trim() || !transcriptEl.contains(sel.anchorNode)) return;
    const a = lineInfo(sel.anchorNode.parentElement?.closest(".line"));
    const b = lineInfo(sel.focusNode.parentElement?.closest(".line"));
    if (!a || !b || a.rec !== b.rec) return;
    if (a.off === b.off) return; // selecting inside one line is probably for copying
    openClip(a.rec, Math.min(a.off, b.off), Math.max(a.off + a.dur, b.off + b.dur), false);
  }, 0);
});

async function openClip(rec, selFrom, selTo, autoplay) {
  stopListening();
  let from = selFrom - PAD, to = selTo + PAD;
  if (to - from > MAX_CLIP) to = from + MAX_CLIP;
  clip = { streamId: selected, rec, selFrom, selTo, from: Math.max(0, from), to };
  await loadClip(selFrom, autoplay);
}

async function loadClip(playAt, autoplay) {
  const token = ++clipToken, c = clip;
  $("clipbar").hidden = false;
  $("clipbar").classList.add("loading");
  markLines();
  try {
    const res = await fetch(`/api/streams/${c.streamId}/audio?rec=${c.rec}&start=${c.from.toFixed(2)}&end=${c.to.toFixed(2)}`,
      { credentials: "same-origin" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `Couldn't load audio (${res.status})`);
    const blob = await res.blob();
    const start = Number(res.headers.get("X-Clip-Start"));
    const recStarted = Number(res.headers.get("X-Rec-Started"));
    const recLength = Number(res.headers.get("X-Rec-Length"));
    const audioBuf = await decode(blob);
    if (token !== clipToken) return;
    if (c.url) URL.revokeObjectURL(c.url);
    Object.assign(c, { blob, url: URL.createObjectURL(blob), start, recStarted, recLength,
                       duration: audioBuf.duration, peaks: computePeaks(audioBuf, 3000) });
    c.from = start; c.to = start + audioBuf.duration;
    clipAudio.src = c.url;
    await new Promise(r => clipAudio.addEventListener("loadedmetadata", r, { once: true }));
    clipAudio.currentTime = Math.min(Math.max(playAt - c.start, 0), c.duration - 0.05);
    $("clipbar").classList.remove("loading");
    $("clip-earlier").disabled = c.from <= 0.05 || c.to - c.from >= MAX_CLIP - 1;
    $("clip-later").disabled = c.to >= c.recLength - 0.5 || c.to - c.from >= MAX_CLIP - 1;
    renderTicks();
    drawWave();
    if (autoplay) clipAudio.play().catch(() => {});
  } catch (ex) {
    if (token !== clipToken) return;
    toast(ex.message, true);
    if (!c.url) closeClip(); else $("clipbar").classList.remove("loading");
  }
}

let audioCtx;
async function decode(blob) {
  audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx.decodeAudioData(await blob.arrayBuffer());
}

function computePeaks(buf, buckets) {
  const data = buf.getChannelData(0), per = Math.max(1, Math.floor(data.length / buckets));
  const peaks = new Float32Array(Math.ceil(data.length / per));
  for (let i = 0; i < peaks.length; i++) {
    let max = 0;
    const end = Math.min(data.length, (i + 1) * per);
    for (let j = i * per; j < end; j += 4) { const v = Math.abs(data[j]); if (v > max) max = v; }
    peaks[i] = max;
  }
  // normalise so quiet streams still show a useful shape
  let top = 0; peaks.forEach(v => { if (v > top) top = v; });
  if (top > 0) for (let i = 0; i < peaks.length; i++) peaks[i] /= top;
  return peaks;
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function drawWave() {
  const c = clip;
  if (!c || !c.peaks) return;
  const canvas = $("wave"), box = $("wave-box");
  const dpr = window.devicePixelRatio || 1;
  const w = box.clientWidth, h = box.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const x = t => (t - c.start) / c.duration * w;

  // the selected line(s)
  ctx.fillStyle = cssVar("--wave-sel");
  ctx.fillRect(x(c.selFrom), 0, x(c.selTo) - x(c.selFrom), h);

  const played = x(c.start + clipAudio.currentTime);
  const mid = h / 2, amp = h / 2 - 6;
  const playedColor = cssVar("--wave-played"), restColor = cssVar("--wave-rest");
  for (let px = 0; px < w; px++) {
    const a = Math.floor(px / w * c.peaks.length), b = Math.max(a + 1, Math.floor((px + 1) / w * c.peaks.length));
    let v = 0;
    for (let i = a; i < b; i++) if (c.peaks[i] > v) v = c.peaks[i];
    const bar = Math.max(0.5, v * amp);
    ctx.fillStyle = px < played ? playedColor : restColor;
    ctx.fillRect(px, mid - bar, 1, bar * 2);
  }
  // playhead
  ctx.fillStyle = cssVar("--wave-head");
  ctx.fillRect(Math.round(played) - 1, 0, 2, h);

  $("clip-time").textContent = fmtClock(c.recStarted + c.start + clipAudio.currentTime);
}

function renderTicks() {
  const c = clip, box = $("ticks");
  const w = box.clientWidth || 600;
  const steps = [5, 10, 15, 30, 60, 120, 300];
  const major = steps.find(s => c.duration / s <= Math.max(2, Math.floor(w / 110))) || 600;
  const minor = major / (major === 15 ? 3 : 5);
  const abs0 = c.recStarted + c.start;
  let html = "";
  for (let t = Math.ceil(abs0 / minor) * minor; t <= abs0 + c.duration; t += minor) {
    const pct = (t - abs0) / c.duration * 100;
    const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
    html += isMajor
      ? `<span class="tick major" style="left:${pct}%"><b>${fmtClock(t)}</b></span>`
      : `<span class="tick" style="left:${pct}%"></span>`;
  }
  box.innerHTML = html;
}

function tick() {
  drawWave();
  markPlaying();
  rafId = clipAudio.paused ? null : requestAnimationFrame(tick);
}
clipAudio.addEventListener("play", () => { $("clipbar").classList.add("playing"); if (!rafId) tick(); });
clipAudio.addEventListener("pause", () => { $("clipbar").classList.remove("playing"); drawWave(); });
clipAudio.addEventListener("seeked", () => { drawWave(); markPlaying(); });

$("clip-play").addEventListener("click", e => {
  e.stopPropagation();
  if (clipAudio.paused) { if (clipAudio.ended) clipAudio.currentTime = 0; clipAudio.play(); } else clipAudio.pause();
});
$("wave-box").addEventListener("click", e => {
  if (!clip?.duration || e.target.closest(".clip-btn")) return;
  const r = $("wave-box").getBoundingClientRect();
  clipAudio.currentTime = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1) * clip.duration;
  if (clipAudio.paused) clipAudio.play().catch(() => {});
});
$("clip-earlier").addEventListener("click", () => extendClip(-STEP));
$("clip-later").addEventListener("click", () => extendClip(STEP));
$("clip-close").addEventListener("click", closeClip);
$("clip-dl").addEventListener("click", downloadClip);

function extendClip(delta) {
  if (!clip?.duration) return;
  const pos = clip.start + clipAudio.currentTime, wasPlaying = !clipAudio.paused;
  if (delta < 0) clip.from = Math.max(0, clip.from + delta); else clip.to += delta;
  if (clip.to - clip.from > MAX_CLIP) delta < 0 ? (clip.to = clip.from + MAX_CLIP) : (clip.from = clip.to - MAX_CLIP);
  clipAudio.pause();
  loadClip(pos, wasPlaying);
}

function downloadClip() {
  if (!clip?.url) return;
  const s = streams.get(clip.streamId);
  const d = new Date((clip.recStarted + clip.start) * 1000);
  const p = n => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  const safe = (s?.name || "stream").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "") || "stream";
  const a = document.createElement("a");
  a.href = clip.url;
  a.download = `${safe}-${stamp}-${Math.round(clip.duration)}s.mp3`;
  document.body.appendChild(a); a.click(); a.remove();
}

function closeClip() {
  clipToken++;
  clipAudio.pause();
  clipAudio.removeAttribute("src");
  clipAudio.load();
  if (clip?.url) URL.revokeObjectURL(clip.url);
  clip = null;
  $("clipbar").hidden = true;
  $("clipbar").classList.remove("playing", "loading");
  markLines();
}

// highlight the selected lines and the one being played
function markLines() {
  transcriptEl.querySelectorAll(".line.selected").forEach(l => l.classList.remove("selected"));
  if (clip) transcriptEl.querySelectorAll(`.line[data-rec="${clip.rec}"]`).forEach(l => {
    const off = Number(l.dataset.off);
    if (off >= clip.selFrom - 0.01 && off < clip.selTo - 0.01) l.classList.add("selected");
  });
  markPlaying();
}

function markPlaying() {
  const t = clip?.duration ? clip.start + clipAudio.currentTime : null;
  let now = null;
  if (t !== null && !clipAudio.paused) transcriptEl.querySelectorAll(`.line[data-rec="${clip.rec}"]`).forEach(l => {
    const off = Number(l.dataset.off);
    if (t >= off && t < off + Number(l.dataset.dur)) now = l;
  });
  transcriptEl.querySelectorAll(".line.playing").forEach(l => { if (l !== now) l.classList.remove("playing"); });
  if (now && !now.classList.contains("playing")) {
    now.classList.add("playing");
    const r = now.getBoundingClientRect(), box = transcriptEl.getBoundingClientRect();
    if (r.top < box.top || r.bottom > box.bottom) now.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

document.addEventListener("keydown", e => {
  if (!clip || e.target.closest("input, textarea, select, dialog")) return;
  if (e.key === "Escape") closeClip();
  else if (e.key === " " && !e.target.closest("button")) { e.preventDefault(); $("clip-play").click(); }
});
window.addEventListener("resize", () => { if (clip?.duration) { renderTicks(); drawWave(); } });


// ---------------------------------------------------------------- go to a date and time
const pad2 = n => String(n).padStart(2, "0");
const toDateInput = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const toTimeInput = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;

function setPastMode(on) {
  pastMode = on;
  $("jump").hidden = !on;
  $("jump").textContent = "↓ Back to live";
  $("btn-goto").classList.toggle("primary", on);
}

function openGotoDialog() {
  const f = $("goto-form");
  f.querySelector(".error-msg").hidden = true;
  // start from the moment currently in view, or 15 minutes ago
  const firstVisible = [...transcriptEl.querySelectorAll(".line")].find(l => l.getBoundingClientRect().bottom > transcriptEl.getBoundingClientRect().top);
  const ts = clip?.duration ? clip.recStarted + clip.start + clipAudio.currentTime
           : firstVisible && !nearBottom() ? Number(firstVisible.dataset.ts) : Date.now() / 1000 - 900;
  const d = new Date(ts * 1000);
  f.date.value = toDateInput(d);
  f.time.value = toTimeInput(d);
  f.date.max = toDateInput(new Date());
  $("goto-dialog").showModal();
}

$("goto-form").querySelectorAll("[data-ago]").forEach(b => b.addEventListener("click", () => {
  const d = new Date(Date.now() - Number(b.dataset.ago) * 1000), f = $("goto-form");
  f.date.value = toDateInput(d);
  f.time.value = toTimeInput(d);
}));

$("goto-form").addEventListener("submit", async e => {
  e.preventDefault();
  const dlg = $("goto-dialog"), f = e.target, err = f.querySelector(".error-msg");
  if (e.submitter?.value === "cancel") return dlg.close();
  const t = f.time.value.length === 5 ? f.time.value + ":00" : f.time.value;
  const when = new Date(`${f.date.value}T${t}`);   // local time
  if (isNaN(when)) { err.textContent = "Pick a date and a time"; err.hidden = false; return; }
  if (when.getTime() > Date.now() + 1000) { err.textContent = "That's in the future — pick a time that has already happened"; err.hidden = false; return; }
  dlg.close();
  await jumpTo(when.getTime() / 1000);
});

async function jumpTo(ts) {
  const id = selected;
  $("q").value = query = "";
  const data = await api("GET", `/api/streams/${id}/segments?limit=150&at=${ts}`);
  if (id !== selected) return;
  setPastMode(data.newer);
  transcriptEl.innerHTML = "";
  lastShown = null;
  oldestId = data.segments[0]?.id ?? null;
  newestId = data.segments.at(-1)?.id ?? null;
  if (data.more) transcriptEl.insertAdjacentHTML("afterbegin",
    `<div class="load-older"><button class="btn sm" onclick="loadOlder()">Load earlier</button></div>`);
  data.segments.forEach(seg => appendLine(seg, false));
  if (data.newer) transcriptEl.insertAdjacentHTML("beforeend",
    `<div class="load-older load-newer"><button class="btn sm" onclick="loadNewer()">Load later</button></div>`);
  updateListeningHint();

  // mark the chosen moment and scroll to it
  const marker = document.createElement("div");
  marker.className = "time-marker";
  marker.innerHTML = `<span>${fmtDay(ts)} · ${fmtTime(ts)}</span>`;
  const next = [...transcriptEl.querySelectorAll(".line")].find(l => Number(l.dataset.ts) + Number(l.dataset.dur || 0) > ts);
  const nextIsInside = next && Number(next.dataset.ts) <= ts;
  if (next && !nextIsInside) next.before(marker);
  else if (!next) (transcriptEl.querySelector(".load-newer, .listening") ? transcriptEl.querySelector(".load-newer, .listening").before(marker) : transcriptEl.append(marker));
  const target = nextIsInside ? next : marker;
  if (nextIsInside) next.classList.add("flash");
  if (!data.segments.length) marker.insertAdjacentHTML("afterend",
    `<div class="empty" style="height:auto;padding:30px 0"><div><p>No transcript around this time.</p></div></div>`);
  target.scrollIntoView({ block: "center" });

  // open the recording at that moment (paused, so nothing blares out)
  if (data.recording) {
    const r = data.recording;
    const line = nextIsInside && next.dataset.rec == r.id ? next : null;
    const from = line ? Number(line.dataset.off) : r.offset;
    const to = line ? from + Number(line.dataset.dur) : r.offset + 10;
    await openClip(r.id, from, to, false);
    if (clip?.duration) { clipAudio.currentTime = Math.max(0, r.offset - clip.start); drawWave(); }
  } else {
    closeClip();
    toast("There's no recording for that moment (recording was off, the stream was down, or the audio has been deleted).", true);
  }
}

async function loadNewer() {
  if (!newestId) return;
  const data = await api("GET", `/api/streams/${selected}/segments?limit=150&after=${newestId}`);
  transcriptEl.querySelector(".load-newer")?.remove();
  data.segments.forEach(seg => appendLine(seg, false));
  newestId = data.segments.at(-1)?.id ?? newestId;
  markLines();
  if (data.more) transcriptEl.insertAdjacentHTML("beforeend",
    `<div class="load-older load-newer"><button class="btn sm" onclick="loadNewer()">Load later</button></div>`);
  else { setPastMode(false); updateListeningHint(); }  // caught up with live
}

window.addEventListener("themechange", () => { try { drawWave(); } catch (e) {} });
