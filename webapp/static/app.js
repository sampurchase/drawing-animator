"use strict";

// ------------------------------------------------------------------ helpers
const view = document.getElementById("view");
const toastBox = document.getElementById("toast");

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, options) {
  let res;
  try { res = await fetch(path, options); }
  catch (e) { throw new Error("I can't reach the server. Is it still running?"); }
  let body = null;
  try { body = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) throw new Error((body && body.error) || "Something went wrong. Please try again.");
  return body;
}

const json = (method, data) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

let toastTimer = null;
function toast(text) {
  toastBox.textContent = text;
  toastBox.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastBox.hidden = true; }, 3500);
}

function setMsg(el, kind, text) {
  el.className = "msg " + kind;
  el.textContent = text;
}

function seconds(n) {
  n = Math.round(n);
  return n < 60 ? n + " s" : Math.floor(n / 60) + " min " + (n % 60 ? (n % 60) + " s" : "");
}

// ------------------------------------------------------------------ state
const DEFAULTS = { mode: "unison", background: null, music: "builtin", seconds: 16, walk: true, bpm: "", hd: false };
const state = { drawings: [], backgrounds: [], music: [], renders: [], selection: [], opts: { ...DEFAULTS }, tab: "dance" };

try { Object.assign(state.opts, JSON.parse(localStorage.getItem("dance-options") || "{}")); } catch (e) { /* private mode */ }
function saveOpts() { try { localStorage.setItem("dance-options", JSON.stringify(state.opts)); } catch (e) { /* ignore */ } }

const MODES = [
  { id: "unison", title: "Chorus line", text: "Everyone dances the same moves together.", min: 1 },
  { id: "mirror", title: "Mirror pairs", text: "Pairs walk towards each other as mirror images.", min: 2 },
  { id: "conga", title: "Conga line", text: "Follow the leader, a couple of beats behind.", min: 2 },
];
const MODE_NAME = Object.fromEntries(MODES.map((m) => [m.id, m.title]));
const QUALITY_NAME = { preview: "Quick preview", full: "Full video", hd: "HD video" };

function fixOptions() {
  const o = state.opts;
  const bgIds = state.backgrounds.map((b) => b.id);
  if (o.background !== "none" && !bgIds.includes(o.background)) o.background = bgIds[0] || "none";
  if (!["builtin", "none"].includes(o.music) && !state.music.some((m) => m.id === o.music)) o.music = "builtin";
  const need = (MODES.find((m) => m.id === o.mode) || MODES[0]).min;
  if (state.selection.length < need) o.mode = "unison";
}

async function loadAll() {
  const [drawings, backgrounds, music, renders] = await Promise.all(
    ["/api/drawings", "/api/backgrounds", "/api/music", "/api/renders"].map((p) => api(p)));
  Object.assign(state, { drawings, backgrounds, music, renders });
  state.selection = state.selection.filter((id) => drawings.some((d) => d.id === id));
  fixOptions();
  updateBadge();
}

function updateBadge() {
  const active = state.renders.filter((r) => r.status === "queued" || r.status === "running").length;
  const badge = document.getElementById("videoBadge");
  badge.hidden = !active;
  badge.textContent = active;
}

// ------------------------------------------------------------------ tabs
const TABS = { dance: renderDance, drawings: renderDrawings, videos: renderVideos, library: renderLibrary };

function show(tab) {
  if (!TABS[tab]) tab = "dance";
  state.tab = tab;
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  for (const b of document.querySelectorAll(".tab")) {
    if (b.dataset.tab === tab) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
  const y = window.scrollY;
  TABS[tab]();
  window.scrollTo(0, y);
}
for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => { window.scrollTo(0, 0); show(b.dataset.tab); });

// ------------------------------------------------------------------ Dance
function renderDance() {
  const o = state.opts;
  const n = state.selection.length;
  const page = h("div", null);

  // 1. who
  page.append(h("h2", null, h("span", { class: "step" }, "1"), "Who is dancing?"));
  if (!state.drawings.length) {
    page.append(h("div", { class: "empty" }, h("p", null, "There are no drawings yet."),
      h("button", { class: "btn", onclick: () => show("drawings") }, "Add a drawing")));
  } else {
    page.append(h("p", { class: "hint" }, n ? n + " chosen. Tap again to take someone out. The first one is on the left." : "Tap the drawings you want in the dance."));
    page.append(h("div", { class: "grid" }, state.drawings.map((d) => {
      const idx = state.selection.indexOf(d.id);
      return h("button", {
        class: "card pick", "aria-pressed": idx >= 0 ? "true" : "false",
        onclick: () => {
          if (idx >= 0) state.selection.splice(idx, 1); else state.selection.push(d.id);
          fixOptions(); show("dance");
        },
      },
        idx >= 0 ? h("div", { class: "num" }, idx + 1) : null,
        h("div", { class: "thumb" }, h("img", { src: d.thumb_url, alt: "" })),
        h("div", { class: "name" }, d.name || "Untitled"));
    })));
    if (n) page.append(h("p", { style: "margin-top:10px" }, h("button", { class: "btn plain", onclick: () => { state.selection = []; fixOptions(); show("dance"); } }, "Clear")));
  }

  // 2. style
  page.append(h("h2", null, h("span", { class: "step" }, "2"), "How do they dance together?"));
  page.append(h("div", { class: "choices" }, MODES.map((m) =>
    h("button", {
      class: "choice", "aria-pressed": o.mode === m.id ? "true" : "false", disabled: n < m.min,
      onclick: () => { o.mode = m.id; saveOpts(); show("dance"); },
    }, h("b", null, m.title), h("span", null, n < m.min ? "Needs 2 or more dancers." : m.text)))));

  // 3. background
  page.append(h("h2", null, h("span", { class: "step" }, "3"), "Where do they dance?"));
  const chip = (id, title, thumb) => h("button", {
    class: "chip", "aria-pressed": o.background === id ? "true" : "false",
    onclick: () => { o.background = id; saveOpts(); show("dance"); },
  }, thumb, h("div", { class: "cap" }, title));
  page.append(h("div", { class: "chips" },
    chip("none", "Plain white", h("div", { class: "swatch" })),
    state.backgrounds.map((b) => chip(b.id, b.name, h("img", { src: b.thumb_url, alt: "" })))));
  page.append(h("p", { class: "hint" }, "Add more places in the Library tab."));

  // 4. music
  page.append(h("h2", null, h("span", { class: "step" }, "4"), "Music"));
  const musicSelect = h("select", {
    "aria-label": "Music", onchange: (e) => { o.music = e.target.value; saveOpts(); },
  },
    h("option", { value: "builtin", selected: o.music === "builtin" }, "Built-in disco beat"),
    state.music.map((m) => h("option", { value: m.id, selected: o.music === m.id }, m.name + " (" + Math.round(m.bpm) + " bpm)")),
    h("option", { value: "none", selected: o.music === "none" }, "No music"));
  page.append(musicSelect);

  // 5. make
  page.append(h("h2", null, h("span", { class: "step" }, "5"), "Make the video"));
  const panel = h("div", { class: "panel stack" });
  panel.append(h("div", null,
    h("div", { class: "hint", style: "margin-bottom:6px" }, "How long?"),
    h("div", { class: "seg" }, [8, 16, 32].map((s) =>
      h("button", { "aria-pressed": o.seconds === s ? "true" : "false", onclick: () => { o.seconds = s; saveOpts(); show("dance"); } }, s + " s")))));
  panel.append(h("label", { class: "check" },
    h("input", { type: "checkbox", checked: o.walk, onchange: (e) => { o.walk = e.target.checked; saveOpts(); } }),
    "Walk across the floor and back"));
  panel.append(h("details", null,
    h("summary", null, "More options"),
    h("label", { class: "field" }, "Tempo in beats per minute (leave empty to use the music's tempo)",
      h("input", { type: "number", min: "40", max: "220", step: "1", inputmode: "numeric", value: o.bpm, placeholder: "e.g. 120",
        onchange: (e) => { o.bpm = e.target.value; saveOpts(); } })),
    h("label", { class: "check" },
      h("input", { type: "checkbox", checked: o.hd, onchange: (e) => { o.hd = e.target.checked; saveOpts(); } }),
      "HD video (1920 x 1080, takes longer)")));
  const msg = h("div", { class: "msg", "aria-live": "polite" });
  const quick = h("button", { class: "btn plain", onclick: () => make("preview") }, "Quick preview");
  const full = h("button", { class: "btn", onclick: () => make(o.hd ? "hd" : "full") }, "Make video");
  panel.append(h("div", { class: "buttons" }, full, quick), msg,
    h("p", { class: "hint" }, "A quick preview is small and only 8 seconds, so you can check it first."));
  page.append(panel);

  async function make(quality) {
    if (!state.selection.length) { setMsg(msg, "err", "Pick at least one drawing first."); return; }
    full.setAttribute("disabled", ""); quick.setAttribute("disabled", "");
    const body = { drawings: state.selection, mode: o.mode, background: o.background || "none", music: o.music,
                   seconds: o.seconds, walk: o.walk, quality };
    if (o.bpm) body.bpm = Number(o.bpm);
    try {
      const job = await api("/api/renders", json("POST", body));
      state.renders.unshift(job);
      updateBadge();
      toast(QUALITY_NAME[quality] + " added to the queue");
      show("videos");
      schedulePoll();
    } catch (e) {
      setMsg(msg, "err", e.message);
      full.removeAttribute("disabled"); quick.removeAttribute("disabled");
    }
  }

  view.replaceChildren(page);
}

// ------------------------------------------------------------------ Drawings
function renderDrawings() {
  const page = h("div", null);
  const nameBox = h("input", { type: "text", maxlength: "60", placeholder: "Sparkle Robot", autocomplete: "off" });
  const msg = h("div", { class: "msg", "aria-live": "polite" });
  const camera = h("input", { type: "file", id: "camera", accept: "image/*", capture: "environment" });
  const library = h("input", { type: "file", id: "library", accept: "image/*" });
  const labels = [h("label", { class: "btn", for: "camera" }, "Take a photo"), h("label", { class: "btn alt", for: "library" }, "Choose a photo")];

  async function upload(file) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("name", nameBox.value);
    labels.forEach((l) => l.setAttribute("aria-disabled", "true"));
    setMsg(msg, "busy", "Reading your drawing... this takes a few seconds.");
    try {
      const d = await api("/api/drawings", { method: "POST", body: form });
      state.drawings.unshift(d);
      setMsg(msg, "ok", "Added! It looks like the " + d.template + " sheet.");
      nameBox.value = "";
      renderGallery();
    } catch (e) {
      setMsg(msg, "err", e.message);
    } finally {
      labels.forEach((l) => l.removeAttribute("aria-disabled"));
      camera.value = ""; library.value = "";
    }
  }
  camera.addEventListener("change", (e) => upload(e.target.files[0]));
  library.addEventListener("change", (e) => upload(e.target.files[0]));

  page.append(h("h2", null, "Add a drawing"));
  page.append(h("div", { class: "panel" },
    h("label", { class: "field" }, "Name your character (you can skip this)", nameBox),
    h("div", { class: "buttons" }, labels), camera, library, msg));

  page.append(h("h2", null, "All drawings"));
  const gallery = h("div", null);
  page.append(gallery);

  function renderGallery() {
    if (!state.drawings.length) {
      gallery.replaceChildren(h("div", { class: "empty" }, "No drawings yet. Add the first one above!"));
      return;
    }
    gallery.replaceChildren(h("div", { class: "grid big" }, state.drawings.map((d) => h("div", { class: "card" },
      h("div", { class: "thumb" }, h("img", { src: d.thumb_url, alt: "" })),
      h("div", { class: "name" }, d.name || "Untitled"),
      h("div", { class: "meta" }, d.template),
      h("div", { class: "row" },
        h("button", { class: "btn plain", onclick: async () => {
          const next = prompt("New name?", d.name);
          if (next === null) return;
          try { Object.assign(d, await api("/api/drawings/" + d.id, json("PATCH", { name: next }))); renderGallery(); }
          catch (e) { setMsg(msg, "err", e.message); }
        } }, "Rename"),
        h("button", { class: "btn danger", onclick: async () => {
          if (!confirm("Delete " + (d.name || "this drawing") + "? This can't be undone.")) return;
          try {
            await api("/api/drawings/" + d.id, { method: "DELETE" });
            state.drawings = state.drawings.filter((x) => x.id !== d.id);
            state.selection = state.selection.filter((id) => id !== d.id);
            fixOptions(); renderGallery();
          } catch (e) { setMsg(msg, "err", e.message); }
        } }, "Delete"))))));
  }
  renderGallery();
  view.replaceChildren(page);
}

// ------------------------------------------------------------------ Videos
let videoList = null;

function renderVideos() {
  const page = h("div", null, h("h2", null, "Videos"));
  videoList = h("div", { class: "list" });
  page.append(videoList);
  view.replaceChildren(page);
  syncVideos();
}

function describe(r) {
  const q = r.request;
  const bits = [r.drawing_names.join(", "), MODE_NAME[q.mode] || q.mode, seconds(q.quality === "preview" ? Math.min(q.seconds, 8) : q.seconds), QUALITY_NAME[q.quality]];
  return bits.join(" · ");
}

function useSettings(r) {
  const q = r.request;
  state.selection = q.drawings.filter((id) => state.drawings.some((d) => d.id === id));
  Object.assign(state.opts, { mode: q.mode, background: q.background, music: q.music, seconds: [8, 16, 32].includes(q.seconds) ? q.seconds : 16,
                              walk: q.walk, bpm: "", hd: q.quality === "hd" });
  fixOptions(); saveOpts();
  toast(state.selection.length < q.drawings.length ? "Settings loaded (some drawings are gone)" : "Settings loaded");
  show("dance");
}

function videoCard(r) {
  const el = h("div", { class: "panel video", "data-id": r.id, "data-status": r.status });
  const screen = h("div", { class: "screen" });
  const info = h("div", { class: "stack" });
  info.append(h("div", { class: "name" }, r.name));
  info.append(h("div", { class: "hint" }, describe(r)));
  const buttons = h("div", { class: "buttons" });
  const del = (label) => h("button", { class: "btn danger", onclick: async () => {
    if (label === "Delete" && !confirm("Delete this video? This can't be undone.")) return;
    try { await api("/api/renders/" + r.id, { method: "DELETE" }); await refreshRenders(); }
    catch (e) { toast(e.message); }
  } }, label);

  if (r.status === "done") {
    screen.append(h("img", { src: r.poster_url, alt: "" }),
      h("button", { class: "play", "aria-label": "Play video", onclick: () => {
        screen.replaceChildren(h("video", { src: r.video_url, controls: true, autoplay: true, playsinline: true, poster: r.poster_url }));
      } }, "▶"));
    info.append(h("div", { class: "status ok" }, "Ready" + (r.seconds_taken ? " (made in " + seconds(r.seconds_taken) + ")" : "")));
    buttons.append(h("a", { class: "btn", href: r.download_url }, "Download"),
      h("button", { class: "btn plain", onclick: () => useSettings(r) }, "Use these settings"), del("Delete"));
  } else if (r.status === "failed" || r.status === "cancelled") {
    screen.append(h("div", { class: "label" }, r.status === "failed" ? "Something went wrong" : "Cancelled"));
    info.append(h("div", { class: "status bad" }, r.status === "failed" ? r.error : "You cancelled this one."));
    buttons.append(h("button", { class: "btn plain", onclick: () => useSettings(r) }, "Try again with these settings"), del("Delete"));
  } else {
    screen.append(h("div", { class: "label", "data-role": "label" }));
    info.append(h("div", { class: "status", "data-role": "status" }), h("div", { class: "bar" }, h("i", { "data-role": "bar" })));
    buttons.append(del("Cancel"));
  }
  info.append(buttons);
  el.append(screen, info);
  updateActive(el, r);
  return el;
}

function updateActive(el, r) {
  if (r.status !== "queued" && r.status !== "running") return;
  const pct = Math.round(r.progress * 100);
  const text = r.status === "queued" ? (r.queue_position > 1 ? "Waiting in line (number " + r.queue_position + ")" : "Next in line") : "Making the video... " + pct + "%";
  el.querySelector("[data-role=status]").textContent = text;
  el.querySelector("[data-role=label]").textContent = r.status === "queued" ? "Waiting" : pct + "%";
  el.querySelector("[data-role=bar]").style.width = (r.status === "queued" ? 0 : pct) + "%";
}

function syncVideos() {
  if (state.tab !== "videos" || !videoList) return;
  if (!state.renders.length) {
    videoList.replaceChildren(h("div", { class: "empty" }, h("p", null, "No videos yet."),
      h("button", { class: "btn", onclick: () => show("dance") }, "Make one")));
    return;
  }
  const existing = new Map([...videoList.querySelectorAll("[data-id]")].map((e) => [e.dataset.id, e]));
  const wanted = [];
  for (const r of state.renders) {
    let el = existing.get(r.id);
    if (!el || el.dataset.status !== r.status) el = videoCard(r);   // finished cards are left alone so a playing video isn't interrupted
    else updateActive(el, r);
    wanted.push(el);
  }
  if (videoList.querySelector(".empty") || wanted.some((el, i) => videoList.children[i] !== el) || videoList.children.length !== wanted.length) {
    videoList.replaceChildren(...wanted);
  }
}

async function refreshRenders() {
  state.renders = await api("/api/renders");
  updateBadge();
  syncVideos();
}

// keep progress fresh while anything is queued or running
let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  const active = state.renders.some((r) => r.status === "queued" || r.status === "running");
  if (!active) return;
  pollTimer = setTimeout(async () => {
    try { await refreshRenders(); } catch (e) { /* server busy, try again */ }
    schedulePoll();
  }, 1500);
}

// ------------------------------------------------------------------ Library
function renderLibrary() {
  const page = h("div", null);

  // backgrounds
  const bgMsg = h("div", { class: "msg", "aria-live": "polite" });
  const bgFile = h("input", { type: "file", id: "bgfile", accept: "image/*" });
  bgFile.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("name", prompt("Name this place?", file.name.replace(/\.[^.]+$/, "")) || "");
    setMsg(bgMsg, "busy", "Adding...");
    try { state.backgrounds.unshift(await api("/api/backgrounds", { method: "POST", body: form })); fixOptions(); setMsg(bgMsg, "ok", "Added!"); renderBackgrounds(); }
    catch (err) { setMsg(bgMsg, "err", err.message); }
    bgFile.value = "";
  });
  const bgList = h("div", null);
  function renderBackgrounds() {
    bgList.replaceChildren(h("div", { class: "grid" }, state.backgrounds.map((b) => h("div", { class: "card" },
      h("img", { src: b.thumb_url, alt: "", style: "width:100%;border-radius:10px;aspect-ratio:16/9;object-fit:cover" }),
      h("div", { class: "name" }, b.name),
      h("button", { class: "btn danger", onclick: async () => {
        if (!confirm("Delete " + b.name + "?")) return;
        try { await api("/api/backgrounds/" + b.id, { method: "DELETE" }); state.backgrounds = state.backgrounds.filter((x) => x.id !== b.id); fixOptions(); renderBackgrounds(); }
        catch (err) { setMsg(bgMsg, "err", err.message); }
      } }, "Delete")))));
  }
  page.append(h("h2", null, "Places to dance"),
    h("p", { class: "hint" }, "A photo or picture to dance in front of, like a dance floor, a stage or a garden."),
    h("div", { class: "buttons" }, h("label", { class: "btn alt", for: "bgfile" }, "Add a picture")), bgFile, bgMsg, bgList);
  renderBackgrounds();

  // music
  const mMsg = h("div", { class: "msg", "aria-live": "polite" });
  const mFile = h("input", { type: "file", id: "mfile", accept: "audio/*,.mp3,.m4a,.wav" });
  const mName = h("input", { type: "text", maxlength: "60", placeholder: "Song name (optional)" });
  const mBpm = h("input", { type: "number", min: "40", max: "220", value: "120", inputmode: "numeric" });
  const chosen = h("span", { class: "hint" }, "No file chosen");
  mFile.addEventListener("change", () => { chosen.textContent = mFile.files[0] ? mFile.files[0].name : "No file chosen"; });
  const mList = h("div", null);
  const addBtn = h("button", { class: "btn", onclick: async () => {
    const file = mFile.files[0];
    if (!file) { setMsg(mMsg, "err", "Choose a music file first."); return; }
    const form = new FormData();
    form.append("file", file); form.append("name", mName.value); form.append("bpm", mBpm.value);
    addBtn.setAttribute("disabled", ""); setMsg(mMsg, "busy", "Adding...");
    try {
      state.music.unshift(await api("/api/music", { method: "POST", body: form }));
      setMsg(mMsg, "ok", "Added!"); mFile.value = ""; mName.value = ""; chosen.textContent = "No file chosen"; renderMusic();
    } catch (err) { setMsg(mMsg, "err", err.message); }
    addBtn.removeAttribute("disabled");
  } }, "Add music");
  function renderMusic() {
    mList.replaceChildren(h("div", { class: "list" }, state.music.map((m) => h("div", { class: "item" },
      h("div", { class: "grow" }, h("div", { class: "name" }, m.name), h("div", { class: "hint" }, Math.round(m.bpm) + " bpm · " + seconds(m.duration))),
      h("button", { class: "btn danger", onclick: async () => {
        if (!confirm("Delete " + m.name + "?")) return;
        try { await api("/api/music/" + m.id, { method: "DELETE" }); state.music = state.music.filter((x) => x.id !== m.id); fixOptions(); renderMusic(); }
        catch (err) { setMsg(mMsg, "err", err.message); }
      } }, "Delete")))));
  }
  page.append(h("h2", null, "Music"),
    h("p", { class: "hint" }, "The built-in disco beat is always there. You can add your own songs too. The dancing follows the tempo, so tell it how fast the song is. Not sure? 120 is a good guess for a happy pop song."),
    h("div", { class: "panel stack" },
      h("div", { class: "buttons" }, h("label", { class: "btn alt", for: "mfile" }, "Choose a music file"), chosen), mFile,
      h("label", { class: "field" }, "Name", mName),
      h("label", { class: "field" }, "Tempo (beats per minute)", mBpm),
      h("div", { class: "buttons" }, addBtn), mMsg),
    h("div", { style: "margin-top:14px" }, mList));
  renderMusic();
  view.replaceChildren(page);
}

// ------------------------------------------------------------------ start
(async function start() {
  const tab = location.hash.slice(1);
  state.tab = TABS[tab] ? tab : "dance";
  try { await loadAll(); }
  catch (e) { view.replaceChildren(h("div", { class: "msg err" }, e.message)); return; }
  show(state.tab);
  schedulePoll();
})();
