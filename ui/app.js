// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Huntsman for Mac contributors
"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];

const TITLES = { actuation: "Actuation", rapid: "Rapid Trigger", snap: "Snap Tap", lighting: "Lighting", studio: "Studio", device: "Keyboard" };
const NOTES = {
  actuation: "Click a key to select it, or drag across several. The number on each key is the depth it types at, in mm.",
  rapid: "Select keys to limit Rapid Trigger to them, or leave nothing selected for all keys.",
  snap: "The two outlined keys are the pair. Choose them in the panel on the left.",
  lighting: "Each key shows the colour its LED is set to.",
  studio: "",
  testing: "Keys sink as you press them. The trace shows the last key's travel.",
  device: "",
};
const EFFECT_NAMES = { static: "Static", breathing_one: "Breathing, one colour", breathing_two: "Breathing, two colours", breathing_random: "Breathing, random", spectrum: "Spectrum", wave: "Wave", reactive_key_one: "Reactive", reactive_key_random: "Reactive, random", reactive_ripple_one: "Ripple", reactive_ripple_random: "Ripple, random", starlight_one: "Starlight, one colour", starlight_two: "Starlight, two colours", starlight_random: "Starlight, random", fire: "Fire", off: "Off" };
const WELLS = [["#ffffff", "White"], ["#ff3b30", "Red"], ["#ff9500", "Orange"], ["#ffcc00", "Yellow"], ["#34c759", "Green"], ["#00c7be", "Teal"], ["#007aff", "Blue"], ["#af52de", "Purple"], ["#ff2d55", "Pink"], ["#000000", "Off"]];
const LETTERS = "QWERTYUIOPASDFGHJKLZXCVBNM".split("");
const U = 46, GAP = 5;
const UNLIT = "#3a3a40";                 // an unlit doubleshot legend
const RAINBOW = "#ff3b30";              // starting hue for spectrum and wave previews

let api, layout = [], effects = {}, view = "actuation";
let model = null;           // the connected model: {pid, name, status, matrix, features, experimental_on, locked}
let devInfo = null;         // the last info(): firmware, version, ...
let points = {};            // id -> [actuation mm, reset mm]
let selected = new Set();
let state = {};
let custom = null;          // {base:[r,g,b], keys:{id:[r,g,b]}}, as last confirmed by the keyboard
let fxShown = null;         // the built-in effect the keyboard runs: {name, c1, c2, speed, dir}
let testing = false;
let focusId = null;         // roving tabindex on the board
let zoom = 1;

/* ---------- helpers ---------- */
const hex2rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const rgb2hex = a => "#" + a.map(v => (+v).toString(16).padStart(2, "0")).join("");
const mm = v => (+v).toFixed(1) + " mm";
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const keyIds = () => layout.filter(k => k.name !== "RIGHT_GUI").map(k => k.id);
const byName = n => layout.find(k => k.name === n)?.id;
const keyOf = id => layout.find(k => k.id == id);
const label = id => { const k = keyOf(id); return k ? (k.label || "Space") : "?"; };
const cloneCustom = c => ({ base: [...c.base], keys: Object.fromEntries(Object.entries(c.keys).map(([k, v]) => [k, [...v]])) });

// WCAG relative luminance and contrast, so text on a colour is always the more readable of black or white
function luminance(hex) {
  return hex2rgb(hex).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
}
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const inkFor = hex => contrast(hex, "#000000") >= contrast(hex, "#ffffff") ? "#050506" : "#ffffff";

// A plain colour name for screen readers
function colourName(hex) {
  const named = WELLS.find(w => w[0] === hex.toLowerCase()); if (named) return named[1].toLowerCase() === "off" ? "unlit" : named[1].toLowerCase();
  const [r, g, b] = hex2rgb(hex).map(v => v / 255), max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (max < 0.08) return "unlit";
  if (d < 0.12) return max > 0.8 ? "white" : "grey";
  let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4; h = (h * 60 + 360) % 360;
  const name = [[15, "red"], [45, "orange"], [70, "yellow"], [160, "green"], [195, "teal"], [250, "blue"], [290, "purple"], [335, "pink"], [360, "red"]].find(([e]) => h < e)[1];
  return (max < 0.45 ? "dark " : "") + name;
}

function toast(msg, err) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.className = "toast" + (err ? " err" : ""), err ? 6000 : 2400);
}
function setConn(ok, text) { $("#led").className = "led " + (ok ? "on" : "err"); if (text) $("#conn").textContent = text; }
async function call(name, ...args) {
  const r = await api[name](...args);
  // r.reason: the model refused it before anything was sent (experimental or missing feature), still connected
  if (!r.ok) { toast(r.error, true); if (!r.reason) setConn(false, "Not connected"); throw new Error(r.error); }
  setConn(true); return r.data;
}
async function busy(btn, fn) { btn.disabled = true; try { await fn(); } catch (e) { /* toast shown */ } finally { btn.disabled = false; refreshButtons(); } }

/* ---------- keyboard ---------- */
// pseudo-random but stable per key, for starlight and fire timing
const rand = (id, salt) => { const x = Math.sin(id * 12.9898 + salt * 78.233) * 43758.5453; return x - Math.floor(x); };

function drawBoard() {
  const b = $("#board"); b.innerHTML = "";
  const w = Math.max(...layout.map(k => k.x + k.w)), h = Math.max(...layout.map(k => k.y + k.h));
  b.style.width = w * U + "px"; b.style.height = h * U + "px";
  $(".kb-extras").hidden = w < 16;   // media keys and dial: not on 60 % boards
  const rows = [...new Set(layout.map(k => k.y))].sort((a, c) => a - c);
  for (const y of rows) {
    const row = document.createElement("div"); row.className = "kb-row"; row.setAttribute("role", "row");
    for (const k of layout.filter(k => k.y === y).sort((a, c) => a.x - c.x)) {
      const c = document.createElement("div");
      c.className = "cap"; c.dataset.id = k.id; c.setAttribute("role", "gridcell"); c.tabIndex = -1;
      Object.assign(c.style, { left: k.x * U + "px", top: k.y * U + "px", width: k.w * U - GAP + "px", height: k.h * U - GAP + "px" });
      c.style.setProperty("--kx", ((k.x + k.w / 2) / w).toFixed(3));
      c.style.setProperty("--r1", rand(k.id, 1).toFixed(3));
      c.style.setProperty("--r2", rand(k.id, 2).toFixed(3));
      c.innerHTML = '<div class="top"><span class="legend"></span><div class="fill"></div></div><div class="front"></div>';
      c.querySelector(".legend").textContent = k.label;
      if (k.label.length > 3 && k.w < 1.5) c.classList.add("long");
      if (k.name === "RIGHT_GUI") { c.classList.add("off"); c.title = "Fn can't be adjusted"; c.setAttribute("aria-disabled", "true"); }
      row.appendChild(c);
    }
    b.appendChild(row);
  }
  focusId = byName("ESC") ?? layout[0].id;
  fit();
  paint();
}
function fit() {
  const kb = $("#kb"), stage = $("#stage");
  const nw = parseFloat($("#board").style.width) + 44, nh = parseFloat($("#board").style.height) + 68;
  const cs = getComputedStyle(stage);
  const reserved = (traceShown() ? 280 : 0) + $("#dock").offsetHeight + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + 64;
  zoom = Math.max(0.5, Math.min(1.6, stage.clientWidth * 0.9 / nw, (stage.clientHeight - reserved) / nh));
  kb.style.zoom = zoom;
  // keep small type at or above ~9.5 px on screen whatever the zoom
  kb.style.setProperty("--legend-fs", Math.max(11, 10.5 / zoom).toFixed(2) + "px");
  kb.style.setProperty("--legend-long", Math.max(8.5, 8.5 / zoom).toFixed(2) + "px");
  kb.style.setProperty("--front-fs", (9.5 / zoom).toFixed(2) + "px");
  // the skirt is 10 px tall; when the number would not fit there, it moves onto the keycap
  kb.classList.toggle("num-on-top", 9.5 / zoom > 10.5);
}

/* What each key's LED shows, so legends glow like the real keyboard */
function fxColour(id) {
  const f = fxShown; if (!f) return "#e9e9ee";
  const n = f.name;
  if (n === "off") return UNLIT;
  if (n === "spectrum" || n === "wave") return RAINBOW;
  if (n === "fire") return "#ff6a1a";
  if (n.endsWith("random")) return `hsl(${Math.round(rand(id, 3) * 360)} 95% 60%)`;
  if (n === "starlight_two" || n === "breathing_two") return n === "starlight_two" && rand(id, 4) > 0.5 ? f.c2 : f.c1;
  return f.c1 || "#e9e9ee";
}
const studioOn = () => typeof studioLive === "function" && studioLive();
function ledColour(id) {
  if (studioOn()) return studioColour(id);   // Studio streams frames: show what the keys really show
  if (custom) return rgb2hex(custom.keys[id] || custom.base);
  return fxColour(id);
}
const unlit = c => c === "#000000" || c === UNLIT;

function capName(id) {
  const k = keyOf(id), name = label(id), p = points[id];
  if (k?.name === "RIGHT_GUI") return `${name}, can't be adjusted`;
  if (view === "actuation") return p ? `${name}, types at ${mm(p[0])}` : name;
  if (view === "rapid") return `${name}, Rapid Trigger ${rtCovers(id) ? "on" : "off"}`;
  if (view === "snap") { const [a, b] = snapPair(); return id === a ? `${name}, Snap Tap first key` : id === b ? `${name}, Snap Tap second key` : name; }
  if (view === "lighting") {
    if (!custom && fxShown && !["static", "off"].includes(fxShown.name) && !fxShown.name.startsWith("reactive")) return `${name}, ${EFFECT_NAMES[fxShown.name]} effect`;
    return `${name}, ${colourName(ledColour(id).startsWith("#") ? ledColour(id) : "#ffffff")}`;
  }
  return name;
}
const selecting = () => ["actuation", "rapid", "lighting", "studio"].includes(view);
function rtCovers(id) { const r = state.rapid; return !!(r && r.enabled && (r.keys === "all" || (r.keys || []).map(Number).includes(id))); }
const snapPair = () => [+$("#snapA").value, +$("#snapB").value];

function paint() {
  const showSel = selecting(), [sa, sb] = snapPair(), kb = $("#kb");
  kb.dataset.view = view;
  kb.dataset.fx = !custom && fxShown && !studioOn() ? fxShown.name : "";
  for (const c of $$(".cap")) {
    const id = +c.dataset.id, p = points[id], front = c.querySelector(".front");
    const led = ledColour(id), dark = unlit(led);
    const isSel = selected.has(id) && showSel;
    c.classList.toggle("sel", isSel);
    if (showSel && !c.classList.contains("off")) c.setAttribute("aria-selected", isSel); else c.removeAttribute("aria-selected");
    c.classList.toggle("rt", view === "rapid" && rtCovers(id));
    c.classList.toggle("pair", view === "snap" && (id === sa || id === sb));
    c.style.setProperty("--legend", dark ? UNLIT : led);
    c.classList.toggle("unlit", dark);
    c.tabIndex = id === focusId ? 0 : -1;
    if (view === "actuation") {
      if (!(testing && c.classList.contains("pressed"))) front.textContent = p ? p[0].toFixed(1) : "";   // a pressed key shows its travel
      c.title = p ? `Types at ${mm(p[0])}, resets at ${mm(p[1])}` : "";
    } else { front.textContent = ""; if (!c.classList.contains("off")) c.title = ""; }
    c.setAttribute("aria-label", capName(id));
  }
  // the glow the keyboard throws on the desk: the most common LED colour
  const counts = {}; keyIds().forEach(id => { const l = ledColour(id); counts[l] = (counts[l] || 0) + 1; });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  kb.style.setProperty("--spill", top && !unlit(top[0]) && !fxAnimated() ? top[0] : (fxAnimated() ? (fxShown.name === "fire" ? "#ff6a1a" : "#7a8cff") : "transparent"));
  if (fxShown) {
    kb.style.setProperty("--c1", fxShown.c1 || "#ffffff"); kb.style.setProperty("--c2", fxShown.c2 || "#00b4ff");
    kb.style.setProperty("--fx-dur", fxDuration(fxShown) + "s");
    kb.dataset.dir = fxShown.dir || "right";
  }
  refreshButtons();
}
const fxAnimated = () => !custom && !studioOn() && fxShown && /spectrum|wave|random|fire/.test(fxShown.name);
function fxDuration(f) {
  if (f.name === "wave") return (1.5 + (f.speed ?? 40) / 255 * 9).toFixed(2);   // lower value = faster
  if (f.name.startsWith("starlight")) return [0, 1.4, 2.4, 3.6][f.speed ?? 2];
  if (f.name === "spectrum") return 8;
  return 4;
}

// Labels and enabled states that depend on the selection and on what is applied
function refreshButtons() {
  const n = selected.size, scope = n ? `${plural(n, "key")} selected` : "All keys";
  $("#actScope").textContent = scope; $("#rtScope").textContent = scope;
  $("#applyDepth").textContent = n ? `Apply to ${plural(n, "key")}` : "Apply to all keys";
  $("#paintScope").textContent = n ? `${plural(n, "key")} selected` : "Select keys on the keyboard to paint them";
  const pb = $("#paintSel"), eb = $("#eraseSel");
  pb.disabled = eb.disabled = !n;
  pb.textContent = n ? `Paint ${plural(n, "key")}` : "Paint selected keys";
  eb.textContent = n ? `Clear ${plural(n, "key")}` : "Clear selected keys";
  const on = $("#rtOn").checked;
  const rtWasOn = !!(state.rapid && state.rapid.enabled);
  $("#applyRt").textContent = !on ? (rtWasOn ? "Turn off Rapid Trigger" : "Rapid Trigger is off") : n ? `Apply to ${plural(n, "key")}` : "Apply to all keys";
  $("#applyRt").disabled = !on && !rtWasOn;
  if (view === "rapid") {
    const r = state.rapid || {};
    $("#stageNote").textContent = (!r.enabled ? "Rapid Trigger is off. " + NOTES.rapid : r.keys === "all" ? "Rapid Trigger is on for all keys, marked with a bar."
      : `Rapid Trigger is on for ${plural((r.keys || []).length, "key")}, marked with a bar. Select keys to change which ones it covers.`);
  }
  const [a, b] = snapPair();
  $("#applySnap").textContent = a === b ? "Choose two different keys" : `Turn on for ${label(a)} and ${label(b)}`;
  $("#applySnap").disabled = a === b;
  $("#offSnap").disabled = !state.snap;
  fxScopeUi(); dirtyUi(); lockUi();
}

/* ---------- models: experimental support, features, LED check ---------- */
const FEATURE_TABS = { actuation: "actuation", rapid: "rapid", snap: "snap_tap" };
const experimentalModel = () => !!model && model.status === "experimental";
const writesLocked = () => experimentalModel() && !model.experimental_on;
// No keyboard answered (model null): claim no feature, so only Lighting and Studio show until one connects
const hasFeature = f => !!model && !!model.features[f];
const viewShown = v => !FEATURE_TABS[v] || hasFeature(FEATURE_TABS[v]);
// While an experimental model's switch is off, every control that writes to it is disabled, with a note
// pointing at the switch. Controls with their own enabled state (refreshButtons) only get forced off here.
let lockShown = false;
function lockUi() {
  const lk = writesLocked();
  $$("[data-write]").forEach(e => { if (lk) e.disabled = true; else if (lockShown) e.disabled = false; });
  $$(".lock-note").forEach(n => n.hidden = !lk);
  const was = lockShown; lockShown = lk;
  if (was && !lk) refreshButtons();
}
function applyModel() {
  if (model) $(".device-name").textContent = model.name;
  $("#expBadge").hidden = !experimentalModel();
  Object.keys(FEATURE_TABS).forEach(v => { $(`#sources button[data-view="${v}"]`).hidden = !viewShown(v); });
  $("#actTest").hidden = $("#actReadings").hidden = !hasFeature("key_tester");
  if (testing && !hasFeature("key_tester")) stopTest();
  $("#restore").hidden = $("#restoreHint").hidden = !hasFeature("actuation");
  $("#expBox").hidden = !experimentalModel();
  $("#expOn").checked = !!model?.experimental_on;
  $("#ledBox").hidden = !experimentalModel() || !model.experimental_on;
  if (!model) { lockUi(); return; }
  const [rows, cols] = model.matrix;
  if ($("#ledRow").options.length !== rows || $("#ledCol").options.length !== cols) {
    for (const [sel, n] of [["#ledRow", rows], ["#ledCol", cols]]) {
      const s = $(sel); s.innerHTML = "";
      for (let i = 0; i < n; i++) { const o = document.createElement("option"); o.value = o.textContent = i; s.appendChild(o); }
    }
    ledUi();
  }
  lockUi();
}
$("#expOn").onchange = async () => {
  const on = $("#expOn").checked; $("#expOn").disabled = true;
  try {
    await call("set_experimental", on);
    if (!on) led.running = false;   // the app put the lighting back before switching off
    model = await call("model");
    toast(on ? "Experimental support on" : "Experimental support off");
  } catch (e) { $("#expOn").checked = !on; }
  finally { $("#expOn").disabled = false; applyModel(); ledUi(); paint(); if (window.studioRefresh) studioRefresh(); }
};

// LED check: light one matrix cell at a time; the tester notes which key lit, for an issue
const led = { running: false, notes: {} };
const ledCell = () => [+$("#ledRow").value || 0, +$("#ledCol").value || 0];
function ledReport() {
  const [rows, cols] = model ? model.matrix : [0, 0];
  const head = model ? `${model.name} (1532:${model.pid}), firmware ${devInfo?.firmware ?? "?"}, Huntsman for Mac ${devInfo?.version ?? "?"}` : "";
  const lines = Object.entries(led.notes).filter(([, v]) => v.trim())
    .map(([k, v]) => k.split(",").map(Number).concat(v.trim()))
    .sort((a, b) => a[0] - b[0] || a[1] - b[1])
    .map(([r, c, v]) => `Row ${r}, column ${c}: ${v}`);
  return [head, `LED check, ${rows} x ${cols} matrix:`, ...(lines.length ? lines : ["(nothing noted yet)"])].join("\n");
}
function ledUi() {
  const [r, c] = ledCell();
  $("#ledCell").textContent = `Row ${r}, column ${c}`;
  $("#ledKey").value = led.notes[`${r},${c}`] || "";
  $("#ledStart").hidden = led.running; $("#ledStop").hidden = !led.running;
  $("#ledReport").value = ledReport();
}
async function ledShow() {
  ledUi();
  if (!led.running) return;
  const [r, c] = ledCell();
  try { await call("led_check", r, c); } catch (e) { /* toast shown */ }
}
function ledStep(d) {
  const [rows, cols] = model.matrix, [r, c] = ledCell();
  const i = ((r * cols + c + d) % (rows * cols) + rows * cols) % (rows * cols);
  $("#ledRow").value = Math.floor(i / cols); $("#ledCol").value = i % cols;
  return ledShow();
}
$("#ledKey").oninput = () => { const [r, c] = ledCell(); led.notes[`${r},${c}`] = $("#ledKey").value; $("#ledReport").value = ledReport(); };
$("#ledRow").onchange = $("#ledCol").onchange = () => ledShow();
$("#ledPrev").onclick = () => ledStep(-1);
$("#ledNext").onclick = () => ledStep(1);
$("#ledStart").onclick = e => busy(e.target, async () => { const [r, c] = ledCell(); await call("led_check", r, c); led.running = true; ledUi(); if (window.studioRefresh) studioRefresh(); });
$("#ledStop").onclick = e => busy(e.target, async () => { await call("end_led_check"); led.running = false; ledUi(); $("#ledStart").focus(); });
$("#ledCopy").onclick = async () => {
  $("#ledReport").value = ledReport();
  try { await navigator.clipboard.writeText($("#ledReport").value); toast("Summary copied"); }
  catch (e) { $("#ledReport").select(); document.execCommand("copy"); toast("Summary copied"); }
};

/* ---------- selection: mouse ---------- */
// click toggles; dragging applies the same toggle to every key it crosses
let drag = null;
$("#board").addEventListener("mousedown", e => {
  const c = e.target.closest(".cap"); if (!c) return;
  focusId = +c.dataset.id;
  if (!selecting() || c.classList.contains("off") || testing) { paint(); return; }
  e.preventDefault(); c.focus({ preventScroll: true });
  const id = +c.dataset.id; drag = selected.has(id) ? "remove" : "add"; toggle(id);
});
$("#board").addEventListener("mouseover", e => {
  if (!drag) return; const c = e.target.closest(".cap"); if (!c || c.classList.contains("off")) return; toggle(+c.dataset.id);
});
addEventListener("mouseup", () => drag = null);
function toggle(id) { drag === "remove" ? selected.delete(id) : selected.add(id); paint(); }

/* ---------- selection: keyboard (grid with roving focus; arrows move by key position) ---------- */
function neighbour(id, dir) {
  const k = keyOf(id), cx = k.x + k.w / 2, cy = k.y + k.h / 2;
  let best = null, bestScore = Infinity;
  for (const o of layout) {
    if (o.id === id) continue;
    const ox = o.x + o.w / 2, oy = o.y + o.h / 2;
    const along = { ArrowRight: ox - cx, ArrowLeft: cx - ox, ArrowDown: oy - cy, ArrowUp: cy - oy }[dir];
    const across = dir === "ArrowRight" || dir === "ArrowLeft" ? Math.abs(oy - cy) : Math.abs(ox - cx);
    if (along < 0.3) continue;
    if ((dir === "ArrowRight" || dir === "ArrowLeft") && across > 0.6) continue;
    const score = along + across * 2.5;
    if (score < bestScore) { bestScore = score; best = o.id; }
  }
  return best;
}
$("#board").addEventListener("keydown", e => {
  const c = e.target.closest(".cap"); if (!c) return;
  const id = +c.dataset.id; let next = null;
  if (e.key.startsWith("Arrow")) next = neighbour(id, e.key);
  else if (e.key === "Home" || e.key === "End") {
    const row = c.parentElement.querySelectorAll(".cap"); next = +(e.key === "Home" ? row[0] : row[row.length - 1]).dataset.id;
  } else if (e.key === " " || e.key === "Enter") {
    e.preventDefault();
    if (selecting() && !c.classList.contains("off") && !testing) { selected.has(id) ? selected.delete(id) : selected.add(id); paint(); }
    return;
  } else return;
  e.preventDefault();
  if (next != null) { focusId = next; paint(); $(`.cap[data-id="${next}"]`).focus(); }
});
$("#board").addEventListener("focusin", e => { const c = e.target.closest(".cap"); if (c && +c.dataset.id !== focusId) { focusId = +c.dataset.id; paint(); } });

$$("#selectTools button").forEach(b => b.onclick = () => {
  const s = b.dataset.sel;
  const sets = { all: keyIds(), wasd: ["W", "A", "S", "D"].map(byName), letters: LETTERS.map(byName),
    numbers: "1234567890".split("").map(byName), arrows: ["UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW"].map(byName), none: [] };
  selected = new Set(sets[s].filter(id => id != null)); paint();   // keys this model lacks are skipped
});

/* ---------- navigation ---------- */
// The key tester runs from Actuation: while it runs, the stage shows the travel trace under the keyboard
const traceShown = () => testing && view === "actuation";
const stageNote = v => v === "actuation" && testing ? NOTES.testing : NOTES[v];
async function show(v) {
  if (!viewShown(v)) v = "lighting";   // a tab this model doesn't have
  if (testing && v !== "actuation") await stopTest();   // the key tester lives in Actuation
  view = v;
  $$("button[data-view]").forEach(b => { if (b.dataset.view === v) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  $$(".pane").forEach(p => p.hidden = p.dataset.pane !== v);
  document.title = `${TITLES[v]} · Huntsman for Mac`;
  $("#stageNote").textContent = stageNote(v);
  $("#selectTools").hidden = !selecting();
  $("#board").setAttribute("aria-multiselectable", selecting());
  $("#traceWrap").hidden = !traceShown();
  $("#stage").dataset.view = v;
  $$(".cap").forEach(c => c.classList.remove("pressed", "typed"));
  fit(); paint(); fillAll(); snapUi();
  if (traceShown()) drawTrace();
  if (window.studioShown) studioShown(v);
}
$$("button[data-view]").forEach(b => b.onclick = () => show(b.dataset.view));

// slider tracks fill up to the thumb; screen readers hear the value with its unit
function fillRange(r) { r.style.setProperty("--fill", ((r.value - r.min) / (r.max - r.min) * 100) + "%"); }
document.addEventListener("input", e => { if (e.target.type === "range") fillRange(e.target); });
function fillAll() { $$('input[type="range"]').forEach(fillRange); }
const valueText = (id, t) => { $("#" + id).setAttribute("aria-valuetext", t); };

/* ---------- actuation ---------- */
const depth = () => +(+$("#depth").value).toFixed(1);
const relValue = () => $("#relMode").value === "custom" ? +(+$("#rel").value).toFixed(1) : +Math.max(0, depth() - 0.1).toFixed(1);
function depthUi() {
  $("#depthNum").textContent = depth().toFixed(1);
  valueText("depth", mm(depth()));
  const rel = $("#rel"); rel.max = Math.max(0, depth() - 0.1).toFixed(1);
  if (+rel.value > +rel.max) rel.value = rel.max;
  $("#relOut").textContent = mm(rel.value); valueText("rel", mm(rel.value));
  $$("#presets button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.v === depth()));
  fillAll(); meterLines(); dirtyUi();
}
$("#depth").oninput = depthUi; $("#rel").oninput = depthUi;
$("#relMode").onchange = () => { $("#relRow").hidden = $("#relMode").value !== "custom"; depthUi(); };
[["Light", 0.5], ["Gaming", 1.0], ["Factory", 1.2], ["Balanced", 1.5], ["Typing", 2.0], ["Firm", 3.0]].forEach(([n, v]) => {
  const b = document.createElement("button"); b.dataset.v = v;
  b.innerHTML = "<b></b><span></span>"; b.children[0].textContent = v.toFixed(1); b.children[1].textContent = n;
  b.setAttribute("aria-label", `${n}, ${mm(v)}`);
  b.onclick = () => { $("#depth").value = v; depthUi(); }; $("#presets").appendChild(b);
});
$("#applyDepth").onclick = e => busy(e.target, async () => {
  const rel = $("#relMode").value === "custom" ? relValue() : null;
  const r = await call("set_depth", [...selected], depth(), rel);
  Object.entries(r.done).forEach(([k, p]) => points[k] = p); paint();
  const n = Object.keys(r.done).length;
  if (r.failed.length) toast(`${n} keys set. ${r.failed.length} didn't confirm: ${r.failed.map(label).join(", ")}`, true);
  else toast(`${plural(n, "key")} now type at ${mm(depth())}`);
});

// "Not applied yet" when the controls differ from what the keyboard has
function dirtyUi() {
  if (!layout.length) return;
  const ids = selected.size ? [...selected] : keyIds(), d = depth(), r = relValue();
  const actDirty = Object.keys(points).length > 0 && ids.some(id => { const p = points[id]; return p && (Math.abs(p[0] - d) > 0.001 || Math.abs(p[1] - r) > 0.001); });
  $("#actDirty").hidden = !actDirty;
  const a = state.rapid || {}, want = rtForm();
  const sameKeys = (x, y) => x === "all" || y === "all" ? x === y : x.length === y.length && x.every(v => y.map(Number).includes(+v));
  const rtDirty = !!a.enabled !== want.enabled || (want.enabled && (Math.abs((a.press ?? 0) - want.press) > 0.001 || Math.abs((a.release ?? 0) - want.release) > 0.001
    || !!a.continuous !== want.continuous || !sameKeys(a.keys ?? "all", want.keys)));
  $("#rtDirty").hidden = !rtDirty;
}

/* ---------- rapid trigger ---------- */
const rtForm = () => ({ enabled: $("#rtOn").checked, press: +$("#rtPress").value, release: +$("#rtRelease").value, keys: selected.size ? [...selected] : "all", continuous: $("#rtCont").checked });
function rtUi() {
  const p = (+$("#rtPress").value).toFixed(2) + " mm", r = (+$("#rtRelease").value).toFixed(2) + " mm";
  $("#rtPressOut").textContent = p; $("#rtReleaseOut").textContent = r; valueText("rtPress", p); valueText("rtRelease", r);
  fillAll(); refreshButtons();
}
$("#rtPress").oninput = $("#rtRelease").oninput = rtUi;
$("#rtOn").onchange = $("#rtCont").onchange = rtUi;
$("#applyRt").onclick = e => {
  const cfg = rtForm();
  busy(e.target, async () => {
    await call("set_rapid", cfg); state.rapid = cfg; paint();
    toast(cfg.enabled ? `Rapid Trigger on for ${cfg.keys === "all" ? "all keys" : plural(cfg.keys.length, "key")}` : "Rapid Trigger off");
  });
};

/* ---------- snap tap ---------- */
function fillSnap() {
  for (const sel of ["#snapA", "#snapB"]) {
    const s = $(sel); s.innerHTML = "";
    layout.filter(k => k.name !== "RIGHT_GUI").forEach(k => { const o = document.createElement("option"); o.value = k.id; o.textContent = k.label || "Space"; s.appendChild(o); });
  }
  $("#snapA").value = byName("A"); $("#snapB").value = byName("D");
}
function snapUi() { const p = state.snap; $("#snapState").textContent = p ? `On for ${label(p[0])} and ${label(p[1])}` : "Off"; }
$("#snapA").onchange = $("#snapB").onchange = () => paint();
$("#applySnap").onclick = e => {
  const [a, b] = snapPair();
  if (a === b) return toast("Choose two different keys", true);
  busy(e.target, async () => { await call("set_snap", [a, b]); state.snap = [a, b]; snapUi(); toast(`Snap Tap on for ${label(a)} and ${label(b)}`); });
};
$("#offSnap").onclick = e => busy(e.target, async () => { await call("set_snap", null); state.snap = null; snapUi(); toast("Snap Tap off"); });

/* ---------- lighting ---------- */
function wellsUi() {
  $$(".wells[data-for] button").forEach(b => b.setAttribute("aria-pressed", $("#" + b.parentElement.dataset.for).value.toLowerCase() === b.dataset.c));
}
$$(".wells[data-for]").forEach(w => WELLS.forEach(([c, name]) => {
  const b = document.createElement("button"); b.style.background = c; b.dataset.c = c; b.title = name; b.setAttribute("aria-label", name);
  b.onclick = () => { $("#" + w.dataset.for).value = c; wellsUi(); }; w.appendChild(b);
}));
$("#paint").oninput = $("#bg").oninput = wellsUi;
function lightMode(m, focus) {
  $$("#lightMode button").forEach(b => { const on = b.dataset.mode === m; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
  $("#keysPane").hidden = m !== "keys"; $("#effectPane").hidden = m !== "effect";
  fillAll();
}
$$("#lightMode button").forEach(b => b.onclick = () => lightMode(b.dataset.mode));
$("#lightMode").addEventListener("keydown", e => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const cur = $("#lightMode [aria-selected='true']").dataset.mode;
  lightMode(e.key === "Home" ? "keys" : e.key === "End" ? "effect" : cur === "keys" ? "effect" : "keys", true);
});
// The keyboard can only show per-key colours on all keys at once, so the first paint must give the
// other keys a colour too: keep the colour they show now (a static effect's colour) instead of white.
// Changes go into a copy, which only becomes the shown state once the keyboard accepts it.
function draftCustom() {
  if (custom) return cloneCustom(custom);
  const now = fxShown && fxShown.name === "static" && fxShown.c1 ? fxShown.c1 : $("#bg").value;
  $("#bg").value = now; wellsUi();
  return { base: hex2rgb(now), keys: {} };
}
async function sendCustom(btn, next, msg) {
  await busy(btn, async () => {
    await call("set_custom", next.base, next.keys);
    custom = next; fxShown = null; paint(); applyAccent(); toast(msg);
    if (window.studioRefresh) studioRefresh();   // Python turned Studio off for the keyboard's own colours
  });
}
$("#paintSel").onclick = e => { const n = draftCustom(), c = hex2rgb($("#paint").value); selected.forEach(id => n.keys[id] = [...c]); sendCustom(e.target, n, `Painted ${plural(selected.size, "key")}`); };
$("#eraseSel").onclick = e => { const n = draftCustom(); selected.forEach(id => delete n.keys[id]); sendCustom(e.target, n, `Cleared ${plural(selected.size, "key")}`); };
$("#applyBg").onclick = e => { const n = draftCustom(); n.base = hex2rgb($("#bg").value); sendCustom(e.target, n, "Unpainted keys updated"); };

function effectUi() {
  const fx = effects[$("#effect").value] || {};
  $("#c1Row").hidden = !(fx.colors >= 1); $("#c2Row").hidden = !(fx.colors >= 2);
  $("#dirRow").hidden = !fx.dir; $("#spRow").hidden = !fx.speed;
  if (fx.speed) { const s = $("#speed"); s.min = fx.speed[0]; s.max = fx.speed[1]; if (+s.value < fx.speed[0] || +s.value > fx.speed[1]) s.value = fx.dir ? 40 : 2; speedUi(); }
  fillAll();
}
function speedUi() {
  const fx = effects[$("#effect").value]; if (!fx || !fx.speed) return;
  const v = +$("#speed").value, [lo, hi] = fx.speed;  // lower value = faster
  const t = fx.dir ? Math.round((hi - v) / (hi - lo) * 100) + "%" : ["", "Fast", "Medium", "Slow"][v];
  $("#speedOut").textContent = t; valueText("speed", fx.dir ? `${t} speed` : t);
}
$("#speed").oninput = speedUi; $("#effect").onchange = () => { effectUi(); fxScopeUi(); };
// Effects always cover the whole keyboard. A static colour with keys selected is really a per-key paint.
function fxScopeUi() {
  const n = selected.size, name = $("#effect").value, staticSel = n && name === "static";
  $("#applyFx").textContent = staticSel ? `Apply to ${plural(n, "key")}` : "Apply to whole keyboard";
  $("#fxNote").textContent = staticSel ? "Only the selected keys change; the others keep their colour."
    : n ? "Effects light the whole keyboard. To colour only the selected keys, use Per key or choose Static." : "Effects run on the keyboard and are saved on it. For a real ripple, typing trails and more, use Studio.";
}
$("#applyFx").onclick = e => {
  const name = $("#effect").value, fx = effects[name], o = {};
  if (name === "static" && selected.size) {   // colour just the selected keys
    const n = draftCustom(), c = hex2rgb($("#c1").value); selected.forEach(id => n.keys[id] = [...c]);
    return sendCustom(e.target, n, `Coloured ${plural(selected.size, "key")}`);
  }
  if (fx.colors >= 1) o.rgb1 = hex2rgb($("#c1").value);
  if (fx.colors >= 2) o.rgb2 = hex2rgb($("#c2").value);
  if (fx.speed) o.speed = +$("#speed").value;
  if (fx.dir) o.direction = $("#dir").value;
  busy(e.target, async () => {
    await call("set_effect", name, o);
    custom = null; fxShown = fxFromForm(name); paint(); applyAccent(); toast(`${EFFECT_NAMES[name]} applied`);
    if (window.studioRefresh) studioRefresh();
  });
};
function fxFromForm(name) {
  const fx = effects[name] || {};
  return { name, c1: fx.colors >= 1 ? $("#c1").value : null, c2: fx.colors >= 2 ? $("#c2").value : null,
    speed: fx.speed ? +$("#speed").value : null, dir: fx.dir ? $("#dir").value : null };
}
// Brightness: live while dragging, written to the keyboard's memory when let go
let brightTimer;
function brightUi() { const v = $("#bright").value + "%"; $("#brightOut").textContent = v; valueText("bright", v); }
$("#bright").oninput = () => { brightUi(); clearTimeout(brightTimer); brightTimer = setTimeout(() => call("set_brightness", +$("#bright").value).catch(() => {}), 120); };
$("#bright").onchange = () => { clearTimeout(brightTimer); call("save_brightness", +$("#bright").value).catch(() => {}); };

/* ---------- key tester ---------- */
const trace = { key: null, samples: [], peak: 0, act: null, rel: null };
const WINDOW_MS = 4000;
window.onDepth = batch => {            // batch: [[keyId, mm], ...] from the app
  const now = performance.now();
  const active = new Map(batch);
  for (const c of $$(".cap")) {
    const id = +c.dataset.id, d = active.get(id) || 0, p = points[id];
    c.classList.toggle("pressed", d > 0.05);
    c.querySelector(".fill").style.height = (d / 4 * 100).toFixed(1) + "%";
    c.classList.toggle("typed", !!(p && d >= p[0]));
    if (view === "actuation") c.querySelector(".front").textContent = d > 0 ? d.toFixed(2) : p ? p[0].toFixed(1) : "";
  }
  if (batch.length) {
    const [id] = batch.reduce((a, b) => b[1] > a[1] ? b : a);
    if (trace.key !== id) { trace.key = id; trace.peak = 0; trace.samples = []; }
  }
  const d = trace.key != null ? (active.get(trace.key) || 0) : 0;
  trace.samples.push([now, d]); trace.peak = Math.max(trace.peak, d);
  while (trace.samples.length && now - trace.samples[0][0] > WINDOW_MS) trace.samples.shift();
  if (trace.key != null) {
    const p = points[trace.key] || [];
    $("#tAct").textContent = p[0] != null ? mm(p[0]) : "–";
    $("#tRel").textContent = p[1] != null ? mm(p[1]) : "–";
    $("#tPeak").textContent = trace.peak.toFixed(2) + " mm";
    // actuation meter: the live key against the depth on the slider
    $("#mLive").dataset.idle = "false";
    $("#mKey").textContent = `Key ${label(trace.key)}`;
    $("#mNum").textContent = d.toFixed(2);
    const hit = d >= depth(), applied = p[0] != null && Math.abs(p[0] - depth()) < 0.001;
    $("#mHit").textContent = applied ? `Types at ${mm(depth())}: ${hit ? "reached" : "not reached"}`
      : `With ${mm(depth())} (not applied yet): ${hit ? "reached" : "not reached"}`;
    $("#mHit").classList.toggle("on", hit);
    meterKey(d, hit);
  }
  drawTrace(); traceLabel();
};
window.onTestEnded = (reason, ok) => { testing = false; testerUi(); if (reason) toast(reason, ok === false); };
function meterLines() {
  $("#mAct").style.setProperty("--p", (depth() / 4).toFixed(3));
  $("#mRel").style.setProperty("--p", (relValue() / 4).toFixed(3));
}
// the key in the meter sinks with travel; its top edge sits at the current depth
function meterKey(d, hit) {
  $("#mCap").style.setProperty("--p", (Math.min(4, d) / 4).toFixed(3));
  $("#mCap").classList.toggle("hit", !!hit);
}

let lastLabel = 0;
function traceLabel(force) {
  const now = performance.now(); if (!force && now - lastLabel < 1000) return; lastLabel = now;
  const cv = $("#trace");
  if (trace.key == null) { cv.setAttribute("aria-label", "Travel trace. No key pressed yet."); return; }
  const p = points[trace.key];
  cv.setAttribute("aria-label", `Travel trace for ${label(trace.key)} over the last 4 seconds. Deepest press ${trace.peak.toFixed(2)} mm` +
    (p ? `; it types at ${mm(p[0])} and resets at ${mm(p[1])}.` : "."));
}

function drawTrace() {
  const cv = $("#trace"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 200;
  if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const ink2 = css.getPropertyValue("--ink-2").trim(), line = css.getPropertyValue("--line-2").trim();
  const accent = css.getPropertyValue("--accent").trim() || "#6ad7ff";
  const L = 44, R = w - 12, T = 10, B = h - 22;
  const y = v => T + (v / 4) * (B - T);   // travel goes down, like pressing
  g.font = "11px -apple-system, sans-serif"; g.fillStyle = ink2; g.strokeStyle = line; g.lineWidth = 1;
  for (let v = 0; v <= 4; v++) { g.beginPath(); g.moveTo(L, y(v) + .5); g.lineTo(R, y(v) + .5); g.stroke(); g.fillText(v + " mm", 4, y(v) + 4); }
  g.fillText("4 s ago", L, h - 4); g.textAlign = "right"; g.fillText("now", R, h - 4); g.textAlign = "left";
  const p = trace.key != null ? points[trace.key] : null;
  if (p) {
    g.setLineDash([4, 3]); g.strokeStyle = accent;
    g.beginPath(); g.moveTo(L, y(p[0])); g.lineTo(R, y(p[0])); g.stroke();
    g.globalAlpha = .5; g.beginPath(); g.moveTo(L, y(p[1])); g.lineTo(R, y(p[1])); g.stroke(); g.globalAlpha = 1;
    g.setLineDash([]); g.fillStyle = accent;
    g.fillText(`types at ${p[0].toFixed(1)}`, L + 6, y(p[0]) + 14);
    g.globalAlpha = .7; g.fillText(`resets at ${p[1].toFixed(1)}`, L + 6, y(p[1]) - 5); g.globalAlpha = 1;
  }
  const s = trace.samples; if (s.length < 2) return;
  const now = s[s.length - 1][0], x = t => R - (now - t) / WINDOW_MS * (R - L);
  if (p) {  // shade the stretch where the key was past its actuation point
    g.save(); g.beginPath(); g.rect(L, y(p[0]), R - L, B - y(p[0])); g.clip();
    g.fillStyle = accent; g.globalAlpha = .18; g.beginPath(); g.moveTo(x(s[0][0]), y(p[0]));
    s.forEach(([t, v]) => g.lineTo(x(t), y(Math.max(v, p[0])))); g.lineTo(x(now), y(p[0])); g.closePath(); g.fill(); g.restore();
  }
  g.strokeStyle = getComputedStyle(document.body).color; g.lineWidth = 1.75; g.beginPath();
  s.forEach(([t, v], i) => i ? g.lineTo(x(t), y(v)) : g.moveTo(x(t), y(v))); g.stroke();
}

function testerUi() {
  $("#actTest").textContent = testing ? "Stop testing" : "Test with a key press";
  $("#actTest").classList.toggle("on", testing);
  $("#testBanner").hidden = !testing;
  $("#stage").classList.toggle("testing", testing);
  if (testing) { $("#mLive").dataset.idle = "true"; $("#mKey").textContent = "Press a key on the Huntsman"; $("#mNum").textContent = "0.00"; $("#mHit").textContent = `Types at ${mm(depth())}`; }
  $("#mLive").classList.toggle("active", testing);
  $("#traceWrap").hidden = !traceShown();
  if (view === "actuation") $("#stageNote").textContent = stageNote(view);
  fit(); if (traceShown()) drawTrace();
  if (!testing) { meterKey(0, false); $$(".cap").forEach(c => { c.classList.remove("pressed", "typed"); c.querySelector(".fill").style.height = 0; }); paint(); traceLabel(true); }
}
async function stopTest() { if (!testing) return; testing = false; testerUi(); try { await call("stop_test"); toast("Testing stopped. The keyboard types normally again."); } catch (e) { /* error toast already shown */ } }
async function toggleTest() {
  if (testing) return stopTest();
  await call("start_test"); testing = true; trace.key = null; trace.samples = []; testerUi();
  if (view !== "actuation") return stopTest();   // the tab changed while the test was starting
}
$("#actTest").onclick = e => busy(e.target, toggleTest);
$("#bannerStop").onclick = e => busy(e.target, stopTest);
addEventListener("beforeunload", () => { if (testing) api.stop_test(); });

/* ---------- progress of long reads and writes (app.py calls window.onProgress) ---------- */
let progressTimer;
window.onProgress = (done, total) => {
  const el = $("#progress"), pct = total > 0 ? Math.min(100, Math.round(done / total * 100)) : 100;
  clearTimeout(progressTimer);
  el.hidden = false; el.style.setProperty("--p", pct + "%"); el.setAttribute("aria-valuenow", pct);
  if (pct >= 100) progressTimer = setTimeout(() => { el.hidden = true; }, 250);
};

/* ---------- keyboard info ---------- */
$("#reload").onclick = e => busy(e.target, async () => { const done = await call("reconnect"); if (done.length) toast("Sent again: " + done.join(", ")); await load(); });
$("#restore").onclick = () => { $("#confirmRestore").returnValue = ""; $("#confirmRestore").showModal(); };
$("#confirmRestore").addEventListener("close", () => {
  if ($("#confirmRestore").returnValue !== "restore") { $("#restore").focus(); return; }
  busy($("#restore"), async () => { state = await call("restore_original"); applyState(); await readPoints(); toast("Factory depth restored"); });
  $("#restore").focus();
});

async function readPoints() {
  points = await call("read_depths");
  // start the slider at the depth most keys use now
  const count = {};
  Object.values(points).forEach(p => count[p[0]] = (count[p[0]] || 0) + 1);
  const common = Object.entries(count).sort((a, b) => b[1] - a[1])[0];
  if (common) { $("#depth").value = common[0]; depthUi(); }
  paint();
}
/* ---------- accent colour (the app's own, separate from the LED colours on the keys) ---------- */
const ACCENTS = [["#6ad7ff", "Ice"], ["#00c7be", "Teal"], ["#0a84ff", "Blue"], ["#7a5cff", "Violet"], ["#ff2d55", "Pink"], ["#ff9500", "Orange"], ["#ffd60a", "Yellow"], ["#f2f2f7", "White"]];
const DEFAULT_ACCENT = ACCENTS[0][0];
function setAccent(hex) {
  if (!hex || !hex.startsWith("#") || unlit(hex) || luminance(hex) < 0.04) hex = DEFAULT_ACCENT;
  const root = document.documentElement.style;
  root.setProperty("--accent", hex);
  root.setProperty("--accent-ink", inkFor(hex));
  $$("#accentWells button").forEach(b => b.setAttribute("aria-pressed", b.dataset.c === hex));
  drawTrace();
}
function lightingAccent() {
  if (custom) {  // the most used colour on the keyboard
    const n = {}; keyIds().forEach(id => { const h = rgb2hex(custom.keys[id] || custom.base); n[h] = (n[h] || 0) + 1; });
    return Object.entries(n).sort((a, b) => b[1] - a[1])[0][0];
  }
  return fxShown && fxShown.c1 ? fxShown.c1 : DEFAULT_ACCENT;
}
function applyAccent() {
  const ui = state.ui || {};
  $("#accentMatch").checked = !!ui.accentMatch;
  setAccent(ui.accentMatch ? lightingAccent() : (ui.accent || DEFAULT_ACCENT));
}
async function savePrefs(prefs) { state.ui = { ...(state.ui || {}), ...prefs }; try { await call("set_prefs", prefs); } catch (e) {} }
ACCENTS.forEach(([c, name]) => {
  const b = document.createElement("button"); b.style.background = c; b.dataset.c = c; b.title = name; b.setAttribute("aria-label", name);
  b.onclick = () => { savePrefs({ accent: c, accentMatch: false }); $("#accentMatch").checked = false; setAccent(c); };
  $("#accentWells").appendChild(b);
});
$("#accentMatch").onchange = () => { savePrefs({ accentMatch: $("#accentMatch").checked }); applyAccent(); };

function applyState() {
  const r = state.rapid || {};
  $("#rtOn").checked = !!r.enabled; $("#rtCont").checked = !!r.continuous;
  $("#rtPress").value = r.press ?? 0.3; $("#rtRelease").value = r.release ?? 0.3; rtUi();
  custom = state.custom ? { base: state.custom.base, keys: Object.fromEntries(Object.entries(state.custom.keys).map(([k, v]) => [+k, v])) } : null;
  if (custom) { $("#bg").value = rgb2hex(custom.base); lightMode("keys"); } else lightMode(state.effect ? "effect" : "keys");
  const fx = state.effect;
  if (fx) {
    $("#effect").value = fx.name; effectUi();
    if (fx.rgb1) $("#c1").value = rgb2hex(fx.rgb1);
    if (fx.rgb2) $("#c2").value = rgb2hex(fx.rgb2);
    if (fx.speed) { $("#speed").value = fx.speed; speedUi(); }
    if (fx.direction) $("#dir").value = fx.direction;
    fxShown = custom ? null : fxFromForm(fx.name);
  }
  wellsUi(); snapUi(); paint(); applyAccent();
}
function fromRaw(raw) {  // effect bytes the keyboard reports: store, led, effect id, ...
  const names = { 0: "off", 1: "static", 2: "breathing_one", 3: "spectrum", 4: "wave", 5: "reactive_key_one", 6: "reactive_key_random", 7: "starlight_one", 9: "fire" };
  const name = names[parseInt(raw.slice(4, 6), 16)];
  if (name === "static") $("#c1").value = "#" + raw.slice(12, 18);
  if (name) { $("#effect").value = name; effectUi(); fxShown = fxFromForm(name); }
}
function fillEffects() {
  const sel = $("#effect"), was = sel.value;
  sel.innerHTML = "";
  // only list effects the keyboard code supports (firmware 1.03 refuses some that other models have)
  for (const n of Object.keys(EFFECT_NAMES).filter(n => effects[n])) { const o = document.createElement("option"); o.value = n; o.textContent = EFFECT_NAMES[n]; sel.appendChild(o); }
  if (effects[was]) sel.value = was;
}
// The connected model, again: on Reconnect a keyboard may have appeared, or another model replaced it. A new
// PID (or the first one after none) brings its layout and effects; the same one keeps the board as drawn.
async function followModel() {
  const before = model?.pid ?? null;
  try { model = await call("model"); } catch (e) { model = null; }   // connects, so layout and effects follow it
  if (model && model.pid !== before) {
    layout = await api.layout(); effects = await api.effects();
    selected = new Set([...selected].filter(id => keyOf(id)));
    fillEffects(); fillSnap(); drawBoard(); effectUi();
    if (window.studioRefresh) studioRefresh();
  }
  applyModel(); show(view);
  return !!model;
}
async function load(again = true) {
  if (again && !(await followModel())) { setConn(false, "Not connected"); return; }
  setConn(true, "Reading");
  try {
    const i = await call("info");
    devInfo = i; state = i.state;
    $("#bright").value = i.brightness; brightUi(); fillAll();
    if (!state.effect && !state.custom) fromRaw(i.effect);
    applyState();
    $("#devInfo").innerHTML = "";
    const m = i.model || model || { name: "Huntsman V3 Pro", pid: "02A6" };
    [["Model", m.name], ["USB ID", `1532:${m.pid}`], ["Firmware", i.firmware], ["Stored profile", String(i.profile)], ["Brightness", i.brightness + "%"], ["App version", i.version || "–"]]
      .forEach(([k, v]) => { const r = document.createElement("div"); r.className = "row"; r.innerHTML = '<span></span><span class="val"></span>'; r.children[0].textContent = k; r.children[1].textContent = v; $("#devInfo").appendChild(r); });
    if (hasFeature("actuation")) await readPoints();
    ledUi();
    setConn(true, `Connected, firmware ${i.firmware}`);
  } catch (e) { setConn(false, "Not connected"); }
}

/* ---------- start ---------- */
async function start() {
  api = window.pywebview.api;
  try { model = await call("model"); } catch (e) { model = null; }   // connects, so layout and effects follow it
  layout = await api.layout(); effects = await api.effects();
  fillEffects(); fillSnap(); drawBoard(); effectUi(); depthUi(); rtUi(); testerUi(); wellsUi(); applyModel(); show(view);
  if (model) {
    try { const done = await call("startup"); if (done.length) toast("Sent again: " + done.join(", ")); } catch (e) {}
    await load(false);   // the model was just read
  } else setConn(false, "Not connected");
  if (window.studioStart) await studioStart();
  let fitTimer;
  addEventListener("resize", () => { clearTimeout(fitTimer); fitTimer = setTimeout(() => { fit(); drawTrace(); }, 100); });
}
addEventListener("pywebviewready", start);
// Demo mode (ui/index.html?demo in a browser): a simulated keyboard so the interface can be previewed.
if (new URLSearchParams(location.search).has("demo")) { const s = document.createElement("script"); s.src = "demo.js"; document.body.appendChild(s); }
