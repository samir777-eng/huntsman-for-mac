"use strict";
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];

const TITLES = { actuation: "Actuation", rapid: "Rapid Trigger", snap: "Snap Tap", lighting: "Lighting", tester: "Key tester", device: "Keyboard" };
const NOTES = {
  actuation: "Click a key to select it, or drag across several. The number on each keycap's front is its actuation point in mm.",
  rapid: "Select keys to limit Rapid Trigger to them, or leave nothing selected for all keys.",
  snap: "Choose the pair in the panel on the left.",
  lighting: "Each key shows the colour its LED is set to.",
  tester: "Keys sink as you press them. The trace shows the last key's travel.",
  device: "",
};
const EFFECT_NAMES = { static: "Static", breathing_one: "Breathing, one colour", breathing_two: "Breathing, two colours", breathing_random: "Breathing, random", spectrum: "Spectrum", wave: "Wave", reactive_key_one: "Reactive", reactive_key_random: "Reactive, random", reactive_ripple_one: "Ripple", reactive_ripple_random: "Ripple, random", starlight_one: "Starlight, one colour", starlight_two: "Starlight, two colours", starlight_random: "Starlight, random", fire: "Fire", off: "Off" };
const WELLS = ["#ffffff", "#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#007aff", "#af52de", "#ff2d55", "#000000"];
const LETTERS = "QWERTYUIOPASDFGHJKLZXCVBNM".split("");
const U = 46, GAP = 4;

let api, layout = [], effects = {}, view = "actuation";
let points = {};            // id -> [actuation mm, reset mm]
let selected = new Set();
let state = {};
let custom = null;          // {base:[r,g,b], keys:{id:[r,g,b]}}
let effectColour = null;    // what the map shows for a built-in effect
let testing = false;

/* ---------- helpers ---------- */
const hex2rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const rgb2hex = a => "#" + a.map(v => (+v).toString(16).padStart(2, "0")).join("");
const mm = v => (+v).toFixed(1) + " mm";
const keyIds = () => layout.filter(k => k.name !== "RIGHT_GUI").map(k => k.id);
const byName = n => layout.find(k => k.name === n)?.id;
const label = id => { const k = layout.find(k => k.id == id); return k ? (k.label || "Space") : "?"; };

function toast(msg, err) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.className = "toast" + (err ? " err" : ""), err ? 6000 : 2400);
}
function setConn(ok, text) { $("#led").className = "led " + (ok ? "on" : "err"); if (text) $("#conn").textContent = text; }
async function call(name, ...args) {
  const r = await api[name](...args);
  if (!r.ok) { toast(r.error, true); setConn(false, "Not connected"); throw new Error(r.error); }
  setConn(true); return r.data;
}
async function busy(btn, fn) { btn.disabled = true; try { await fn(); } catch (e) { /* toast shown */ } finally { btn.disabled = false; } }
function inkFor(hex) { const [r, g, b] = hex2rgb(hex); return (r * 299 + g * 587 + b * 114) / 1000 > 140 ? "#1d1d1f" : "#ffffff"; }

/* ---------- keyboard ---------- */
function drawBoard() {
  const b = $("#board"); b.innerHTML = "";
  const w = Math.max(...layout.map(k => k.x + k.w)), h = Math.max(...layout.map(k => k.y + k.h));
  b.style.width = w * U + "px"; b.style.height = h * U + "px";
  for (const k of layout) {
    const c = document.createElement("div");
    c.className = "cap"; c.dataset.id = k.id;
    Object.assign(c.style, { left: k.x * U + "px", top: k.y * U + "px", width: k.w * U - GAP + "px", height: k.h * U - GAP + "px" });
    c.innerHTML = '<div class="top"><div class="tint"></div><div class="fill"></div><span class="legend"></span></div><div class="front"></div>';
    c.querySelector(".legend").textContent = k.label;
    if (k.label.length > 3 && k.w < 1.5) c.classList.add("long");
    if (k.name === "RIGHT_GUI") { c.classList.add("off"); c.title = "Fn can't be adjusted"; }
    b.appendChild(c);
  }
  fit();
  paint();
}
function fit() {
  const kb = $("#kb"), stage = $(".stage");
  const natural = parseFloat($("#board").style.width) + 44;
  kb.style.zoom = Math.min(1.25, (stage.clientWidth - 64) / natural);
}
// The colour a key's LED shows, so legends glow like the real keyboard.
function ledColour(id) {
  if (custom) return rgb2hex(custom.keys[id] || custom.base);
  return effectColour || "#e9e9ee";
}
function paint() {
  const lighting = view === "lighting", tester = view === "tester";
  for (const c of $$(".cap")) {
    const id = +c.dataset.id, p = points[id], front = c.querySelector(".front");
    const led = ledColour(id), dark = led === "#000000";
    c.classList.toggle("sel", selected.has(id) && !tester);
    c.style.setProperty("--legend", dark ? "#3a3a40" : led);
    // the light spill onto the plate is strongest where lighting is being edited
    c.style.setProperty("--glow", dark ? "transparent" : led + (lighting ? "cc" : "55"));
    if (lighting) {
      front.textContent = "";
      c.title = "";
    } else if (!tester) {
      front.textContent = p ? p[0].toFixed(1) : "";
      c.title = p ? `Types at ${mm(p[0])}, resets at ${mm(p[1])}` : "";
    }
  }
  const n = selected.size;
  const scope = n ? `${n} key${n > 1 ? "s" : ""} selected` : "All keys";
  $("#actScope").textContent = scope; $("#rtScope").textContent = scope;
  $("#applyDepth").textContent = n ? `Apply to ${n} key${n > 1 ? "s" : ""}` : "Apply to all keys";
  $("#paintScope").textContent = n ? `${n} key${n > 1 ? "s" : ""} selected` : "Select keys to paint";
  $("#paintSel").disabled = $("#eraseSel").disabled = !n;
}

// selection: click toggles; dragging applies the same toggle to every key it crosses
let drag = null;
$("#board").addEventListener("mousedown", e => {
  const c = e.target.closest(".cap"); if (!c || c.classList.contains("off") || testing) return;
  e.preventDefault(); const id = +c.dataset.id; drag = selected.has(id) ? "remove" : "add"; toggle(id);
});
$("#board").addEventListener("mouseover", e => {
  if (!drag) return; const c = e.target.closest(".cap"); if (!c || c.classList.contains("off")) return; toggle(+c.dataset.id);
});
addEventListener("mouseup", () => drag = null);
function toggle(id) { drag === "remove" ? selected.delete(id) : selected.add(id); paint(); }
$$("#selectTools button").forEach(b => b.onclick = () => {
  const s = b.dataset.sel;
  const sets = { all: keyIds(), wasd: ["W", "A", "S", "D"].map(byName), letters: LETTERS.map(byName),
    numbers: "1234567890".split("").map(byName), arrows: ["UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW"].map(byName), none: [] };
  selected = new Set(sets[s]); paint();
});

/* ---------- navigation ---------- */
async function show(v) {
  if (testing && v !== "tester" && v !== "actuation") await stopTest();
  view = v;
  $$("button[data-view]").forEach(b => { if (b.dataset.view === v) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  $$(".pane").forEach(p => p.hidden = p.dataset.pane !== v);
  document.title = `${TITLES[v]} · Huntsman for Mac`;
  $("#stageNote").textContent = NOTES[v];
  $("#selectTools").hidden = v === "tester" || v === "snap" || v === "device";
  $("#traceWrap").hidden = v !== "tester";
  $$(".cap").forEach(c => c.classList.remove("pressed", "typed"));
  paint();
  if (v === "tester") drawTrace();
}
$$("button[data-view]").forEach(b => b.onclick = () => show(b.dataset.view));
// slider tracks fill up to the thumb
function fillRange(r) { r.style.setProperty("--fill", ((r.value - r.min) / (r.max - r.min) * 100) + "%"); }
document.addEventListener("input", e => { if (e.target.type === "range") fillRange(e.target); });
function fillAll() { $$('input[type="range"]').forEach(fillRange); }

/* ---------- actuation ---------- */
const depth = () => +(+$("#depth").value).toFixed(1);
function depthUi() {
  $("#depthNum").textContent = depth().toFixed(1);
  const rel = $("#rel"); rel.max = Math.max(0, depth() - 0.1).toFixed(1);
  if (+rel.value > +rel.max) rel.value = rel.max;
  $("#relOut").textContent = mm(rel.value);
  $$("#presets button").forEach(b => b.setAttribute("aria-pressed", +b.dataset.v === depth()));
  fillAll();
  meterLines();
}
$("#depth").oninput = depthUi; $("#rel").oninput = depthUi;
$("#relMode").onchange = () => { $("#relRow").hidden = $("#relMode").value !== "custom"; depthUi(); };
[["Light", 0.5], ["Gaming", 1.0], ["Factory", 1.2], ["Balanced", 1.5], ["Typing", 2.0], ["Firm", 3.0]].forEach(([n, v]) => {
  const b = document.createElement("button"); b.dataset.v = v;
  b.innerHTML = "<b></b><span></span>"; b.children[0].textContent = v.toFixed(1); b.children[1].textContent = n;
  b.onclick = () => { $("#depth").value = v; depthUi(); }; $("#presets").appendChild(b);
});
$("#applyDepth").onclick = e => busy(e.target, async () => {
  const rel = $("#relMode").value === "custom" ? +(+$("#rel").value).toFixed(1) : null;
  const r = await call("set_depth", [...selected], depth(), rel);
  Object.entries(r.done).forEach(([k, p]) => points[k] = p); paint();
  const n = Object.keys(r.done).length;
  if (r.failed.length) toast(`${n} keys set. ${r.failed.length} didn't confirm: ${r.failed.map(label).join(", ")}`, true);
  else toast(`${n} key${n > 1 ? "s" : ""} now type at ${mm(depth())}`);
});

/* ---------- rapid trigger ---------- */
function rtUi() { $("#rtPressOut").textContent = (+$("#rtPress").value).toFixed(2) + " mm"; $("#rtReleaseOut").textContent = (+$("#rtRelease").value).toFixed(2) + " mm"; }
$("#rtPress").oninput = $("#rtRelease").oninput = rtUi;
$("#applyRt").onclick = e => {
  const on = $("#rtOn").checked;
  const cfg = { enabled: on, press: +$("#rtPress").value, release: +$("#rtRelease").value, keys: selected.size ? [...selected] : "all", continuous: $("#rtCont").checked };
  busy(e.target, async () => { await call("set_rapid", cfg); state.rapid = cfg; toast(on ? `Rapid Trigger on for ${selected.size ? selected.size + " keys" : "all keys"}` : "Rapid Trigger off"); });
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
$("#applySnap").onclick = e => {
  const a = +$("#snapA").value, b = +$("#snapB").value;
  if (a === b) return toast("Choose two different keys", true);
  busy(e.target, async () => { await call("set_snap", [a, b]); state.snap = [a, b]; snapUi(); toast("Snap Tap on"); });
};
$("#offSnap").onclick = e => busy(e.target, async () => { await call("set_snap", null); state.snap = null; snapUi(); toast("Snap Tap off"); });

/* ---------- lighting ---------- */
$$(".wells[data-for]").forEach(w => WELLS.forEach(c => {
  const b = document.createElement("button"); b.style.background = c; b.title = c === "#000000" ? "Off" : c; b.setAttribute("aria-label", b.title);
  b.onclick = () => { $("#" + w.dataset.for).value = c; }; w.appendChild(b);
}));
function lightMode(m) {
  $$("#lightMode button").forEach(b => b.setAttribute("aria-selected", b.dataset.mode === m));
  $("#keysPane").hidden = m !== "keys"; $("#effectPane").hidden = m !== "effect";
}
$$("#lightMode button").forEach(b => b.onclick = () => lightMode(b.dataset.mode));
// The keyboard can only show per-key colours on all keys at once, so the first paint must give the
// other keys a colour too: keep the colour they show now (a static effect's colour) instead of white.
function ensureCustom() {
  if (custom) return;
  const current = effectColour && effectColour !== "#8e8e93" ? effectColour : $("#bg").value;
  $("#bg").value = current;
  custom = { base: hex2rgb(current), keys: {} };
}
async function sendCustom(btn, msg) { await busy(btn, async () => { await call("set_custom", custom.base, custom.keys); effectColour = null; paint(); applyAccent(); toast(msg); }); }
$("#paintSel").onclick = e => { ensureCustom(); const c = hex2rgb($("#paint").value); selected.forEach(id => custom.keys[id] = c); sendCustom(e.target, `Painted ${selected.size} key${selected.size > 1 ? "s" : ""}`); };
$("#eraseSel").onclick = e => { ensureCustom(); selected.forEach(id => delete custom.keys[id]); sendCustom(e.target, "Cleared"); };
$("#applyBg").onclick = e => { ensureCustom(); custom.base = hex2rgb($("#bg").value); sendCustom(e.target, "Other keys updated"); };

function effectUi() {
  const fx = effects[$("#effect").value] || {};
  $("#c1Row").hidden = !(fx.colors >= 1); $("#c2Row").hidden = !(fx.colors >= 2);
  $("#dirRow").hidden = !fx.dir; $("#spRow").hidden = !fx.speed;
  if (fx.speed) { const s = $("#speed"); s.min = fx.speed[0]; s.max = fx.speed[1]; if (+s.value < fx.speed[0] || +s.value > fx.speed[1]) s.value = fx.dir ? 40 : 2; speedUi(); }
}
function speedUi() {
  const fx = effects[$("#effect").value]; if (!fx || !fx.speed) return;
  const v = +$("#speed").value, [lo, hi] = fx.speed;  // lower value = faster
  $("#speedOut").textContent = fx.dir ? Math.round((hi - v) / (hi - lo) * 100) + "%" : ["", "Fast", "Medium", "Slow"][v];
}
$("#speed").oninput = speedUi; $("#effect").onchange = effectUi;
function effectPreview(name) { const fx = effects[name]; return name === "off" ? "#000000" : fx && fx.colors ? $("#c1").value : "#8e8e93"; }
$("#applyFx").onclick = e => {
  const name = $("#effect").value, fx = effects[name], o = {};
  if (fx.colors >= 1) o.rgb1 = hex2rgb($("#c1").value);
  if (fx.colors >= 2) o.rgb2 = hex2rgb($("#c2").value);
  if (fx.speed) o.speed = +$("#speed").value;
  if (fx.dir) o.direction = $("#dir").value;
  busy(e.target, async () => { await call("set_effect", name, o); custom = null; effectColour = effectPreview(name); paint(); applyAccent(); toast(`${EFFECT_NAMES[name]} applied`); });
};
let brightTimer;
$("#bright").oninput = () => { $("#brightOut").textContent = $("#bright").value + "%"; clearTimeout(brightTimer); brightTimer = setTimeout(() => call("set_brightness", +$("#bright").value).catch(() => {}), 180); };

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
    if (view === "tester") c.querySelector(".front").textContent = d > 0 ? d.toFixed(2) : "";
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
    $("#testKey").textContent = `Key ${label(trace.key)}`;
    $("#liveNum").textContent = d.toFixed(2);
    $("#tAct").textContent = p[0] != null ? mm(p[0]) : "–";
    $("#tRel").textContent = p[1] != null ? mm(p[1]) : "–";
    $("#tPeak").textContent = trace.peak.toFixed(2) + " mm";
    // actuation meter: the live key against the depth on the slider (not yet applied)
    $("#mKey").textContent = `Key ${label(trace.key)}`;
    $("#mNum").textContent = d.toFixed(2);
    $("#mFill").style.height = `calc(${(d / 4 * 100).toFixed(1)}% - 6px)`;
    const hit = d >= depth();
    $("#mHit").textContent = hit ? `Types at ${depth().toFixed(1)} mm` : `Types at ${depth().toFixed(1)} mm, not reached`;
    $("#mHit").classList.toggle("on", hit);
  }
  drawTrace();
};
window.onTestEnded = (reason, ok) => { testing = false; testerUi(); if (reason) toast(reason, ok === false); };
function meterLines() {
  const rel = $("#relMode").value === "custom" ? +$("#rel").value : Math.max(0, depth() - 0.1);
  $("#mAct").style.top = `calc(${(depth() / 4 * 100).toFixed(1)}% - 1px)`;
  $("#mRel").style.top = `calc(${(rel / 4 * 100).toFixed(1)}% - 1px)`;
}

function drawTrace() {
  const cv = $("#trace"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 220;
  if (!w) return;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const ink2 = css.getPropertyValue("--ink-2").trim(), line = css.getPropertyValue("--line-strong").trim();
  const accent = getComputedStyle($("button.primary")).backgroundColor;
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
  $("#testToggle").textContent = testing ? "Stop testing" : "Start testing";
  $("#testToggle").classList.toggle("primary", !testing);
  $("#liveSub").textContent = testing ? "Press keys on the Huntsman now." : "Travel of the last key you pressed.";
  $("#actTest").textContent = testing ? "Stop testing (keyboard types again)" : "Test with a key press";
  $("#actTest").classList.toggle("on", testing);
  $("#mLive").hidden = !testing;
  if (!testing) { $("#mFill").style.height = 0; $$(".cap").forEach(c => { c.classList.remove("pressed", "typed"); c.querySelector(".fill").style.height = 0; }); paint(); }
}
async function stopTest() { if (!testing) return; testing = false; testerUi(); try { await call("stop_test"); toast("Testing stopped. The keyboard types normally again."); } catch (e) { /* error toast already shown */ } }
async function toggleTest() {
  if (testing) return stopTest();
  await call("start_test"); testing = true; trace.key = null; trace.samples = []; testerUi();
  toast("Testing: the Huntsman won't type until you stop.");
}
$("#testToggle").onclick = e => busy(e.target, toggleTest);
$("#actTest").onclick = e => busy(e.target, toggleTest);
addEventListener("beforeunload", () => { if (testing) api.stop_test(); });

/* ---------- keyboard info ---------- */
$("#reload").onclick = e => busy(e.target, async () => { const done = await call("reconnect"); if (done.length) toast("Sent again: " + done.join(", ")); await load(); });
$("#restore").onclick = e => busy(e.target, async () => { state = await call("restore_original"); applyState(); await readPoints(); toast("Factory depth restored"); });

async function readPoints() {
  points = await call("read_depths");
  // start the slider at the depth most keys use now
  const count = {};
  Object.values(points).forEach(p => count[p[0]] = (count[p[0]] || 0) + 1);
  const common = Object.entries(count).sort((a, b) => b[1] - a[1])[0];
  if (common) { $("#depth").value = common[0]; depthUi(); }
  paint();
}
/* ---------- accent colour ---------- */
const ACCENTS = ["#3ddc84", "#00c7be", "#0a84ff", "#7a5cff", "#ff2d55", "#ff9500", "#ffd60a", "#f2f2f7"];
function setAccent(hex) {
  if (!hex || hex === "#000000") hex = ACCENTS[0];
  const root = document.documentElement.style;
  root.setProperty("--accent", hex);
  root.setProperty("--accent-ink", inkFor(hex) === "#ffffff" ? "#ffffff" : "#06110a");
  $$("#accentWells button").forEach(b => b.setAttribute("aria-pressed", b.dataset.c === hex));
  drawTrace();
}
function lightingAccent() {
  if (custom) {  // the most used colour on the keyboard
    const n = {}; keyIds().forEach(id => { const h = rgb2hex(custom.keys[id] || custom.base); n[h] = (n[h] || 0) + 1; });
    return Object.entries(n).sort((a, b) => b[1] - a[1])[0][0];
  }
  return effectColour && effectColour !== "#8e8e93" ? effectColour : ACCENTS[0];
}
function applyAccent() {
  const ui = state.ui || {};
  $("#accentMatch").checked = !!ui.accentMatch;
  setAccent(ui.accentMatch ? lightingAccent() : (ui.accent || ACCENTS[0]));
}
async function savePrefs(prefs) { state.ui = { ...(state.ui || {}), ...prefs }; try { await call("set_prefs", prefs); } catch (e) {} }
ACCENTS.forEach(c => {
  const b = document.createElement("button"); b.style.background = c; b.dataset.c = c; b.title = c; b.setAttribute("aria-label", "Accent " + c);
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
    effectColour = custom ? null : effectPreview(fx.name);
  }
  snapUi(); paint(); applyAccent();
}
function fromRaw(raw) {  // effect bytes the keyboard reports: store, led, effect id, ...
  const names = { 0: "off", 1: "static", 2: "breathing_one", 3: "spectrum", 4: "wave", 5: "reactive_key_one", 6: "reactive_ripple_one", 7: "starlight_one", 9: "fire" };
  const name = names[parseInt(raw.slice(4, 6), 16)];
  if (name === "static") $("#c1").value = "#" + raw.slice(12, 18);
  if (name) { $("#effect").value = name; effectUi(); effectColour = effectPreview(name); }
}
async function load() {
  setConn(true, "Reading");
  try {
    const i = await call("info");
    state = i.state;
    $("#bright").value = i.brightness; $("#brightOut").textContent = i.brightness + "%"; fillAll();
    if (!state.effect && !state.custom) fromRaw(i.effect);
    applyState();
    $("#devInfo").innerHTML = "";
    [["Model", "Huntsman V3 Pro"], ["USB ID", "1532:02A6"], ["Firmware", i.firmware], ["Stored profile", String(i.profile)], ["Brightness", i.brightness + "%"]]
      .forEach(([k, v]) => { const r = document.createElement("div"); r.className = "row"; r.innerHTML = "<span></span><output></output>"; r.children[0].textContent = k; r.children[1].textContent = v; $("#devInfo").appendChild(r); });
    await readPoints();
    setConn(true, `Connected, firmware ${i.firmware}`);
  } catch (e) { setConn(false, "Not connected"); }
}

/* ---------- start ---------- */
async function start() {
  api = window.pywebview.api;
  layout = await api.layout(); effects = await api.effects();
  for (const n of Object.keys(EFFECT_NAMES)) { const o = document.createElement("option"); o.value = n; o.textContent = EFFECT_NAMES[n]; $("#effect").appendChild(o); }
  drawBoard(); fillSnap(); effectUi(); depthUi(); rtUi(); testerUi(); show(view);
  try { const done = await call("startup"); if (done.length) toast("Sent again: " + done.join(", ")); } catch (e) {}
  await load();
  let fitTimer;
  addEventListener("resize", () => { clearTimeout(fitTimer); fitTimer = setTimeout(() => { fit(); drawTrace(); }, 100); });
}
addEventListener("pywebviewready", start);
// Demo mode (ui/index.html?demo in a browser): a simulated keyboard so the interface can be previewed.
if (new URLSearchParams(location.search).has("demo")) { const s = document.createElement("script"); s.src = "demo.js"; document.body.appendChild(s); }
