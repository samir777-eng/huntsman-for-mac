// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Huntsman for Mac contributors
// Lighting Studio: presets, the layer stack, the effect gallery, parameter forms, sound, typing and smart
// lighting. Shares app.js's globals ($, layout, selected, paint, toast, ...). Python pushes live frames to
// window.onStudioFrame (colours before gamma, so they match the pickers), about 15 times a second.
"use strict";

const ST = { data: null, working: null, sel: null, frame: null, fx: {}, apps: [], tab: "layers" };
const CATEGORIES = [["basic", "Basic"], ["ambient", "Ambient"], ["audio", "Sound"], ["reactive", "Typing"]];
const BLEND_NAMES = { normal: "Normal", add: "Add", screen: "Screen", multiply: "Multiply", max: "Brightest" };
const clone = o => JSON.parse(JSON.stringify(o));
const layers = () => ST.working.layers;
const curLayer = () => layers().find(l => l.id === ST.sel) || null;
const isBuiltin = name => !!ST.data.presets.find(p => p.name === name && p.builtin);

async function scall(name, ...args) {   // like call(), but a refused value isn't a lost connection
  const r = await api[name](...args);
  if (!r.ok) { toast(r.error, true); throw new Error(r.error); }
  return r.data;
}
const quiet = p => p.catch(() => {});
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

/* ---------- live frames on the board ---------- */
function studioLive() { return !!(ST.data && ST.data.enabled && ST.frame); }
// Studio off, its tab open: the board previews the working preset (frames composed by the service, nothing sent to the
// keys), asked for every few seconds while the tab shows so a closed window doesn't keep it running.
function studioPreviewing() { return !!(ST.data && !ST.data.enabled && ST.frame); }
const PREVIEW_ASK_S = 10, PREVIEW_EVERY_MS = 4000;
let previewTimer = null;
const askPreview = s => { try { api.studio_preview(s).catch(() => {}); } catch (e) { /* an older app without it */ } };
function previewUi() {
  const want = view === "studio" && !!ST.data && !ST.data.enabled;
  $("#stPreview").hidden = !want;
  if (want && !previewTimer) { askPreview(PREVIEW_ASK_S); previewTimer = setInterval(() => askPreview(PREVIEW_ASK_S), PREVIEW_EVERY_MS); }
  else if (!want && previewTimer) { clearInterval(previewTimer); previewTimer = null; if (!ST.data?.enabled) askPreview(0); }
}
$("#stPreviewOn").onclick = () => { $("#stOn").click(); $("#stOn").focus(); };
function studioColour(id) { const c = ST.frame && ST.frame[id]; return c ? rgb2hex(c) : "#000000"; }
let capEls = null;
window.onStudioFrame = frame => {
  ST.frame = frame;
  if (!studioLive() && !(view === "studio" && studioPreviewing())) return;
  if (!capEls || !capEls.length || !capEls[0].isConnected) capEls = $$(".cap").map(c => [c, c.dataset.id]);
  let r = 0, g = 0, b = 0, n = 0;
  for (const [c, id] of capEls) {
    const v = frame[id] || [0, 0, 0], dark = v[0] + v[1] + v[2] < 24;
    c.style.setProperty("--legend", dark ? UNLIT : rgb2hex(v));
    c.classList.toggle("unlit", dark);
    r += v[0]; g += v[1]; b += v[2]; n++;
  }
  const kb = $("#kb");
  kb.dataset.fx = "";
  if (n) kb.style.setProperty("--spill", rgb2hex([r, g, b].map(x => Math.min(255, Math.round(x / n * 1.6)))));
};

/* ---------- loading and rendering ---------- */
async function studioRefresh() {
  try { ST.data = await scall("studio_state"); } catch (e) { return; }
  ST.fx = Object.fromEntries(ST.data.effects.map(e => [e.name, e]));
  ST.working = clone(ST.data.working);
  if (!curLayer()) ST.sel = layers().length ? layers()[layers().length - 1].id : null;
  renderStudio();
}
window.studioRefresh = studioRefresh;
window.onStudioChanged = () => studioRefresh();
window.onStudioStatus = s => {
  if (!ST.data) return;
  if (s.errors) ST.data.errors = s.errors;
  ST.engineError = s.engine || null;
  noticesUi();
};
window.onStudioAction = a => { if (ST.data) { ST.data.action = a; smartNowUi(); } };
window.onStudioLevel = level => {
  const pct = Math.round(Math.min(1, Math.max(0, level)) * 100), m = $("#stLevel");
  m.style.setProperty("--p", pct + "%"); m.setAttribute("aria-valuenow", pct);
};

function renderStudio() {
  const d = ST.data;
  $("#stOn").checked = d.enabled; $("#stOnLabel").textContent = d.enabled ? "On" : "Off";
  $("#studioOnNote").hidden = !d.enabled; $("#stCloseHint").hidden = !d.enabled;
  $("#stBright").value = Math.round(d.brightness * 100); $("#stFps").value = d.fps;
  sliderOuts();
  presetsUi(); stackUi(); editorUi(); soundUi(); typingUi(); smartUi(); noticesUi();
  if (view === "studio") $("#stageNote").textContent = studioNote();
  if (!d.enabled && view !== "studio") ST.frame = null;   // on its tab the last frame stays until the preview's next one
  if (!d.enabled) paint();
  previewUi();
  fillAll();
}
function studioNote() {
  return ST.data && ST.data.enabled ? "Live: what the keys show now. Select keys on the board to limit a layer to them."
    : "Studio is off, so this is a preview: the keys don't show it until you turn Studio on. Select keys on the board to limit a layer to them.";
}
function sliderOuts() {
  const b = $("#stBright").value + "%", f = $("#stFps").value + " fps";
  $("#stBrightOut").textContent = b; valueText("stBright", b);
  $("#stFpsOut").textContent = f; valueText("stFps", `${f}, higher is smoother`);
}
function stDirtyUi() { $("#stDirty").hidden = !ST.data.dirty; }

function presetsUi() {
  const s = $("#stPreset"); s.innerHTML = "";
  for (const [label, built] of [["Built in", true], ["Yours", false]]) {
    const list = ST.data.presets.filter(p => p.builtin === built); if (!list.length) continue;
    const g = document.createElement("optgroup"); g.label = label;
    list.forEach(p => { const o = document.createElement("option"); o.value = o.textContent = p.name; g.appendChild(o); });
    s.appendChild(g);
  }
  s.value = ST.data.active;
  // A built-in preset can't be changed: no dead Save, Save as… is the way to keep edits
  const built = isBuiltin(ST.data.active);
  if (built && document.activeElement === $("#stSave")) $("#stSaveAs").focus();
  $("#stSave").hidden = built; $("#stSave").disabled = !ST.data.dirty;
  $("#stSaveAs").classList.toggle("primary", built);
  $("#stBuiltinHint").hidden = !built;
  $$("#stMenu [data-act='rename'], #stMenu [data-act='delete']").forEach(b => b.disabled = built);
  stDirtyUi();
}

/* ---------- layer stack (shown top layer first) ---------- */
const ICONS = {
  eye: '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.6" d="M1.8 10S5 4.5 10 4.5 18.2 10 18.2 10 15 15.5 10 15.5 1.8 10 1.8 10z"/><circle cx="10" cy="10" r="2.6" fill="currentColor"/></svg>',
  up: '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M8 4l5 6H3z" fill="currentColor"/></svg>',
  down: '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M8 12L3 6h10z" fill="currentColor"/></svg>',
  del: '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
};
function paletteOf(effect, params) {
  const spec = ST.fx[effect]; if (!spec) return ["#888888"];
  const val = n => (params && params[n] !== undefined ? params[n] : spec.params.find(p => p.name === n)?.default);
  const pc = spec.params.find(p => p.kind === "colors"), c = spec.params.find(p => p.kind === "color");
  const cols = pc ? val(pc.name) : c ? [val(c.name)] : [[255, 255, 255]];
  return cols.map(rgb2hex);
}
const swatch = cols => cols.length > 1 ? `linear-gradient(90deg, ${cols.join(", ")})` : cols[0];
function keysText(l) {
  if (l.keys === "all") return "all keys";
  return l.keys.length === 1 ? `key ${label(l.keys[0])}` : plural(l.keys.length, "key");
}
function stackUi() {
  const ol = $("#stStack"); ol.innerHTML = "";
  const ls = layers();
  if (!ls.length) {
    const li = document.createElement("li"); li.className = "stack-empty";
    li.textContent = "No layers yet. Add one to start."; ol.appendChild(li); return;
  }
  [...ls].reverse().forEach((l, i) => {
    const spec = ST.fx[l.effect] || { label: l.effect }, name = spec.label;
    const li = document.createElement("li");
    li.className = "layer" + (l.id === ST.sel ? " sel" : "") + (l.enabled ? "" : " hidden-layer");
    li.innerHTML = `<button class="eye" aria-pressed="${l.enabled}">${ICONS.eye}</button>
      <button class="layer-main"><span class="swatch"></span><span class="lname"></span><span class="lmeta"></span></button>
      <span class="layer-tools"><button class="mini up">${ICONS.up}</button><button class="mini down">${ICONS.down}</button><button class="mini del">${ICONS.del}</button></span>`;
    const [eye, main] = li.querySelectorAll("button");
    eye.setAttribute("aria-label", `Show ${name}`); eye.title = l.enabled ? "Hide layer" : "Show layer";
    main.setAttribute("aria-current", l.id === ST.sel ? "true" : "false");
    main.querySelector(".swatch").style.background = swatch(paletteOf(l.effect, l.params));
    main.querySelector(".lname").textContent = name;
    main.querySelector(".lmeta").textContent = `${BLEND_NAMES[l.blend]}, ${Math.round(l.opacity * 100)}%, ${keysText(l)}`;
    const up = li.querySelector(".up"), down = li.querySelector(".down"), del = li.querySelector(".del");
    up.setAttribute("aria-label", `Move ${name} up`); down.setAttribute("aria-label", `Move ${name} down`);
    del.setAttribute("aria-label", `Delete ${name}`); up.title = "Move up"; down.title = "Move down"; del.title = "Delete layer";
    up.disabled = i === 0; down.disabled = i === ls.length - 1;
    eye.onclick = () => { l.enabled = !l.enabled; changed(true); focusLayerButton(l.id, ".eye"); };
    main.onclick = () => { ST.sel = l.id; stackUi(); editorUi(); };
    up.onclick = () => move(l, +1, up); down.onclick = () => move(l, -1, down);
    del.onclick = () => removeLayer(l);
    ol.appendChild(li);
  });
}
function focusLayerButton(id, cls) {
  const i = [...layers()].reverse().findIndex(l => l.id === id);
  const b = $$("#stStack li")[i]?.querySelector(cls);
  if (b && !b.disabled) b.focus(); else $$("#stStack li")[i]?.querySelector(".layer-main")?.focus();
}
function move(l, dir, btn) {   // dir +1 = up the stack (later in the array)
  const ls = layers(), i = ls.indexOf(l), j = i + dir; if (j < 0 || j >= ls.length) return;
  [ls[i], ls[j]] = [ls[j], ls[i]];
  changed(true); focusLayerButton(l.id, btn.classList.contains("up") ? ".up" : ".down");
}
function removeLayer(l) {
  const ls = layers(), i = ls.indexOf(l); ls.splice(i, 1);
  if (ST.sel === l.id) ST.sel = ls.length ? ls[Math.min(i, ls.length - 1)].id : null;
  changed(true); toast(`${ST.fx[l.effect]?.label || "Layer"} deleted`);
  if (ST.sel) focusLayerButton(ST.sel, ".layer-main"); else $("#stAdd").focus();
}

/* every edit: redraw what depends on it, then send the whole stack (Python validates and debounces) */
const sendLayers = debounce(() => quiet(scall("update_layers", clone(layers())).then(() => { ST.data.dirty = true; presetsUi(); })), 80);
function changed(restack) {
  ST.data.dirty = true; presetsUi(); stackUi();
  if (restack) editorUi();
  sendLayers();
}

/* ---------- parameter editor, generated from the effect's ParamSpecs ---------- */
function stepOf(p) { if (p.kind === "int") return 1; const span = p.max - p.min; return span <= 1 ? 0.01 : span <= 10 ? 0.05 : 0.5; }
function fmt(p, v) {
  if (p.kind === "int") return String(v);
  const unit = p.label.includes("(") || /speed/.test(p.name) ? "" : /angle/.test(p.name) ? "°" : /(fade|period)/.test(p.name) ? " s" : "";
  return (Math.abs(v) >= 10 ? (+v).toFixed(0) : (+v).toFixed(2).replace(/0$/, "")) + unit;
}
function paramRow(l, p) {
  const v = l.params[p.name] !== undefined ? l.params[p.name] : p.default, id = `stp-${p.name}`;
  const set = val => { l.params[p.name] = val; changed(false); };
  const row = document.createElement("div"); row.className = "row";
  const lab = document.createElement("label"); lab.textContent = p.label; lab.htmlFor = id;
  if (p.kind === "color") {
    const i = document.createElement("input"); i.type = "color"; i.id = id; i.value = rgb2hex(v);
    i.oninput = () => set(hex2rgb(i.value)); row.append(lab, i);
  } else if (p.kind === "colors") {
    row.classList.add("stops-row"); lab.removeAttribute("for"); lab.id = id;
    const box = document.createElement("div"); box.className = "stops"; box.setAttribute("role", "group"); box.setAttribute("aria-labelledby", id);
    const cols = v.map(c => [...c]), lo = p.min ?? 1, hi = p.max ?? 8;
    const draw = () => {
      box.innerHTML = "";
      cols.forEach((c, k) => {
        const w = document.createElement("span"); w.className = "stop";
        const i = document.createElement("input"); i.type = "color"; i.value = rgb2hex(c); i.setAttribute("aria-label", `${p.label}, colour ${k + 1} of ${cols.length}`);
        i.oninput = () => { cols[k] = hex2rgb(i.value); set(cols.map(x => [...x])); };
        w.appendChild(i);
        if (cols.length > lo) {
          const x = document.createElement("button"); x.className = "stop-x"; x.innerHTML = ICONS.del; x.setAttribute("aria-label", `Remove colour ${k + 1}`);
          x.onclick = () => { cols.splice(k, 1); set(cols.map(y => [...y])); draw(); box.querySelector("input")?.focus(); };
          w.appendChild(x);
        }
        box.appendChild(w);
      });
      if (cols.length < hi) {
        const add = document.createElement("button"); add.className = "stop-add"; add.textContent = "+"; add.setAttribute("aria-label", `Add a colour to ${p.label}`);
        add.onclick = () => { cols.push([...cols[cols.length - 1]]); set(cols.map(y => [...y])); draw(); box.querySelector(".stop-add")?.focus(); };
        box.appendChild(add);
      }
    };
    draw(); row.append(lab, box);
  } else if (p.kind === "choice") {
    const s = document.createElement("select"); s.id = id;
    p.choices.forEach(c => { const o = document.createElement("option"); o.value = c; o.textContent = c[0].toUpperCase() + c.slice(1); s.appendChild(o); });
    s.value = v; s.onchange = () => set(s.value); row.append(lab, s);
  } else if (p.kind === "bool") {
    const i = document.createElement("input"); i.type = "checkbox"; i.className = "switch"; i.id = id; i.checked = !!v;
    i.onchange = () => set(i.checked); row.append(lab, i);
  } else if (p.kind === "int" && p.max - p.min > 1000) {   // a random seed: a number, and a button for a new one
    const ctl = document.createElement("span"); ctl.className = "row-ctl";
    const i = document.createElement("input"); i.type = "number"; i.className = "num-input"; i.id = id; i.min = p.min; i.max = p.max; i.value = v;
    i.onchange = () => { const n = Math.round(+i.value); if (Number.isFinite(n) && n >= p.min && n <= p.max) set(n); else i.value = l.params[p.name] ?? p.default; };
    const b = document.createElement("button"); b.className = "mini-text"; b.textContent = "New pattern";
    b.onclick = () => { i.value = Math.floor(Math.random() * 100000); set(+i.value); };
    ctl.append(i, b); row.append(lab, ctl);
  } else {
    const ctl = document.createElement("span"); ctl.className = "row-ctl";
    const i = document.createElement("input"); i.type = "range"; i.id = id; i.min = p.min; i.max = p.max; i.step = stepOf(p); i.value = v;
    const out = document.createElement("output"); out.setAttribute("aria-hidden", "true");
    const show = () => { out.textContent = fmt(p, +i.value); i.setAttribute("aria-valuetext", fmt(p, +i.value)); };
    i.oninput = () => { show(); set(p.kind === "int" ? Math.round(+i.value) : +i.value); };
    show(); ctl.append(i, out); row.append(lab, ctl);
  }
  return row;
}
function editorUi() {
  const l = curLayer(), ed = $("#stEditor");
  ed.hidden = !l; if (!l) return;
  const spec = ST.fx[l.effect];
  $("#stEdTitle").textContent = spec.label; $("#stEdDesc").textContent = spec.description;
  const box = $("#stParams"); box.innerHTML = "";
  spec.params.forEach(p => box.appendChild(paramRow(l, p)));
  box.hidden = !spec.params.length;
  $("#stOpacity").value = Math.round(l.opacity * 100); opacityOut();
  $("#stBlend").value = l.blend;
  keysUi(); fillAll();
}
function opacityOut() { const t = $("#stOpacity").value + "%"; $("#stOpacityOut").textContent = t; valueText("stOpacity", t); }
$("#stOpacity").oninput = () => { const l = curLayer(); if (!l) return; l.opacity = +$("#stOpacity").value / 100; opacityOut(); changed(false); };
$("#stBlend").onchange = () => { const l = curLayer(); if (!l) return; l.blend = $("#stBlend").value; changed(false); };

function keysUi() {
  const l = curLayer(); if (!l) return;
  const all = l.keys === "all";
  $$("#stKeys button").forEach(b => { const on = (b.dataset.keys === "all") === all; b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1; });
  const n = selected.size;
  $("#stKeysHint").textContent = all ? (n ? `${plural(n, "key")} selected on the board. Choose Selected keys to limit this layer to them.` : "Lights every key. To limit it, select keys on the board, then choose Selected keys.")
    : `Lights ${l.keys.length > 8 ? plural(l.keys.length, "key") : l.keys.map(label).join(", ")}.`;
  $("#stKeysUse").hidden = all; $("#stKeysShow").hidden = all;
  $("#stKeysUse").disabled = !n; $("#stKeysUse").textContent = n ? `Use the ${plural(n, "selected key")}` : "Use selected keys";
  $("#stKeysClear").disabled = !n;
}
function setKeys(mode, focus) {
  const l = curLayer(); if (!l) return;
  if (mode === "all") l.keys = "all";
  else {
    if (!selected.size) { toast("Select keys on the keyboard first, then choose Selected keys."); keysUi(); return; }
    l.keys = [...selected].sort((a, b) => a - b);
  }
  changed(false); keysUi();
  if (focus) $(`#stKeys [data-keys="${mode}"]`).focus();
}
$$("#stKeys button").forEach(b => b.onclick = () => setKeys(b.dataset.keys));
$("#stKeys").addEventListener("keydown", e => {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
  e.preventDefault(); const l = curLayer(); setKeys(l && l.keys === "all" ? "sel" : "all", true);
});
$("#stKeysUse").onclick = () => setKeys("sel");
$("#stKeysShow").onclick = () => { const l = curLayer(); if (l && l.keys !== "all") { selected = new Set(l.keys); paint(); keysUi(); } };
$("#stKeysClear").onclick = () => { selected.clear(); paint(); keysUi(); };
$("#board").addEventListener("mouseup", () => { if (view === "studio") keysUi(); });
$("#board").addEventListener("keyup", () => { if (view === "studio") keysUi(); });
$("#selectTools").addEventListener("click", () => { if (view === "studio") keysUi(); });

/* ---------- effect gallery ---------- */
function galleryUi() {
  const body = $("#galBody"); body.innerHTML = "";
  for (const [cat, title] of CATEGORIES) {
    const list = ST.data.effects.filter(e => e.category === cat); if (!list.length) continue;
    const sec = document.createElement("section"); sec.className = "gal-sec";
    const h = document.createElement("h3"); h.textContent = title; h.id = `gal-${cat}`; sec.appendChild(h);
    const grid = document.createElement("div"); grid.className = "gal-grid"; grid.setAttribute("role", "list"); grid.setAttribute("aria-labelledby", h.id);
    list.forEach(e => {
      const b = document.createElement("button"); b.className = "gal-card"; b.dataset.effect = e.name; b.setAttribute("role", "listitem");
      b.innerHTML = '<span class="gal-swatch"></span><b></b><span></span>';
      b.querySelector(".gal-swatch").style.background = swatch(paletteOf(e.name, null));
      b.querySelector("b").textContent = e.label; b.querySelector("span:last-child").textContent = e.description;
      b.onclick = () => { $("#gallery").close(); addLayer(e); };
      grid.appendChild(b);
    });
    sec.appendChild(grid); body.appendChild(sec);
  }
}
let layerSeq = 0;
function addLayer(e) {
  const id = `l${Date.now().toString(36)}${layerSeq++}`;
  // typing reactions are black where nothing was pressed, so they add onto the layers below
  const blend = e.category === "reactive" || (e.category === "audio" && layers().length) ? "add" : "normal";
  layers().push({ id, effect: e.name, params: {}, keys: "all", blend, opacity: 1, enabled: true });
  ST.sel = id; changed(true);
  focusLayerButton(id, ".layer-main");
  toast(`${e.label} added on top`);
}
$("#stAdd").onclick = () => { galleryUi(); $("#gallery").showModal(); $("#gallery .gal-card")?.focus(); };

/* ---------- presets ---------- */
function confirmBox(title, body, okLabel) {
  const d = $("#confirmDelete");
  $("#cdTitle").textContent = title; $("#cdBody").textContent = body;
  d.querySelector('button[value="delete"]').textContent = okLabel;
  d.returnValue = ""; d.showModal();
  return new Promise(res => d.addEventListener("close", () => res(d.returnValue === "delete"), { once: true }));
}
function askName(title, okLabel, initial, check) {
  const d = $("#nameDialog");
  $("#ndTitle").textContent = title; $("#ndOk").textContent = okLabel; $("#ndName").value = initial; $("#ndErr").textContent = "";
  d.returnValue = ""; d.showModal(); $("#ndName").select();
  return new Promise(res => {
    const submit = e => {
      if (e.submitter && e.submitter.value === "cancel") return;
      const v = $("#ndName").value.trim(), problem = !v ? "Give the preset a name." : check(v);
      if (problem) { e.preventDefault(); $("#ndErr").textContent = problem; $("#ndName").focus(); }
    };
    $("#ndForm").addEventListener("submit", submit);
    d.addEventListener("close", () => { $("#ndForm").removeEventListener("submit", submit); res(d.returnValue === "ok" ? $("#ndName").value.trim() : null); }, { once: true });
  });
}
const nameProblem = (v, except) => isBuiltin(v) ? `“${v}” is built in. Choose another name.`
  : v !== except && ST.data.presets.some(p => p.name === v) ? `A preset called “${v}” already exists.` : "";
function payload(name) { return { name, brightness: ST.working.brightness, layers: clone(layers()) }; }

$("#stPreset").onchange = async () => {
  const name = $("#stPreset").value;
  if (ST.data.dirty && !(await confirmBox("Discard changes?", `Your changes to “${ST.data.active}” aren't saved. Switching to “${name}” discards them.`, "Discard"))) {
    $("#stPreset").value = ST.data.active; return;
  }
  ST.sel = null;
  try { await scall("set_active_preset", name); } catch (e) { /* toast shown */ }
  await studioRefresh();
};
$("#stSave").onclick = e => busy(e.target, async () => {
  await scall("save_preset", payload(ST.data.active)); toast(`Saved “${ST.data.active}”`); await studioRefresh();
});
$("#stSaveAs").onclick = async () => {
  const base = isBuiltin(ST.data.active) ? `My ${ST.data.active}` : `${ST.data.active} copy`;
  const name = await askName("Save preset as", "Save", base, v => nameProblem(v));
  if (!name) { $("#stSaveAs").focus(); return; }
  try { await scall("save_preset", payload(name)); toast(`Saved “${name}”`); } catch (e) { /* toast shown */ }
  await studioRefresh(); $("#stSaveAs").focus();
};
const ACTIONS = {
  async rename() {
    const old = ST.data.active, name = await askName("Rename preset", "Rename", old, v => v === old ? "" : nameProblem(v, old));
    if (name && name !== old) { await quiet(scall("rename_preset", old, name)); await studioRefresh(); }
  },
  async duplicate() { const n = await scall("duplicate_preset", ST.data.active); toast(`Duplicated as “${n}”`); await studioRefresh(); },
  async export() {
    const r = await scall("export_preset", ST.data.active);
    if (r.json) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([r.json], { type: "application/json" }));
      a.download = ST.data.active.replace(/[^\w\- ]+/g, "").trim() + ".json"; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } else if (r.path) toast(`Exported to ${r.path}`);
  },
  import() { $("#stImportFile").value = ""; $("#stImportFile").click(); },
  async delete() {
    const name = ST.data.active;
    if (await confirmBox("Delete preset?", `“${name}” is removed from this Mac. Built-in presets stay.`, "Delete")) {
      await quiet(scall("delete_preset", name)); toast(`Deleted “${name}”`); await studioRefresh();
    }
  },
};
$("#stImportFile").onchange = async () => {
  const f = $("#stImportFile").files[0]; if (!f) return;
  if (f.size > 256 * 1024) return toast("That file is too large to be a preset.", true);
  try { const n = await scall("import_preset", await f.text()); toast(`Imported “${n}”`); } catch (e) { /* toast shown */ }
  await studioRefresh();
};

// the "more" menu: arrow keys move, Escape closes and returns focus
function menuOpen(open, focusFirst) {
  $("#stMenu").hidden = !open; $("#stMore").setAttribute("aria-expanded", open);
  if (open && focusFirst) $$("#stMenu button:not(:disabled)")[0]?.focus();
}
$("#stMore").onclick = () => menuOpen($("#stMenu").hidden, true);
$("#stMenu").addEventListener("keydown", e => {
  const items = $$("#stMenu button:not(:disabled)"), i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { e.preventDefault(); menuOpen(false); $("#stMore").focus(); }
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus(); }
  else if (e.key === "Home" || e.key === "End") { e.preventDefault(); items[e.key === "Home" ? 0 : items.length - 1].focus(); }
  else if (e.key === "Tab") menuOpen(false);
});
$$("#stMenu button").forEach(b => b.onclick = async () => {
  menuOpen(false); $("#stMore").focus();
  try { await ACTIONS[b.dataset.act](); } catch (e) { /* toast shown */ }
});
document.addEventListener("mousedown", e => { if (!$("#stMenu").hidden && !e.target.closest(".preset-tools")) menuOpen(false); });

/* ---------- master switch, brightness, smoothness ---------- */
$("#stOn").onchange = async () => {
  const on = $("#stOn").checked; $("#stOn").disabled = true;
  try { await scall("studio_enable", on); toast(on ? "Studio is lighting the keyboard" : "Studio off. The keyboard's own lighting is back."); }
  catch (e) { $("#stOn").checked = !on; }
  finally { $("#stOn").disabled = writesLocked(); }
  await studioRefresh();
};
const sendBright = debounce(v => quiet(scall("set_studio_brightness", v)), 100);
$("#stBright").oninput = () => { sliderOuts(); ST.data.brightness = +$("#stBright").value / 100; sendBright(ST.data.brightness); };
$("#stFps").oninput = sliderOuts;
$("#stFps").onchange = () => quiet(scall("set_fps", +$("#stFps").value));

/* ---------- sub-tabs ---------- */
function stTab(t, focus) {
  ST.tab = t;
  $$("#stTabs button").forEach(b => { const on = b.dataset.tab === t; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
  for (const [k, id] of [["layers", "stLayers"], ["sound", "stSound"], ["typing", "stTyping"], ["smart", "stSmart"]]) $("#" + id).hidden = k !== t;
  if (t === "smart" && !ST.apps.length) loadApps();
  fillAll();
}
$$("#stTabs button").forEach(b => b.onclick = () => stTab(b.dataset.tab));
$("#stTabs").addEventListener("keydown", e => {
  const order = ["layers", "sound", "typing", "smart"], i = order.indexOf(ST.tab);
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: order.length - 1 }[e.key]; if (next === undefined) return;
  e.preventDefault(); stTab(order[(next + order.length) % order.length], true);
});

/* ---------- notices: permissions and connection ---------- */
function notice(el, text) { el.hidden = !text; el.textContent = text || ""; }
function noticesUi() {
  const er = ST.data.errors || {};
  notice($("#stKeysErr"), er.keys); notice($("#stAudioErr"), er.audio);
  const top = [ST.engineError && `Can't reach the keyboard (${ST.engineError}). Trying again shortly.`, er.presets,
    er.keys && ST.tab !== "typing" && "Typing effects are blocked: see Typing.", er.audio && ST.tab !== "sound" && "Sound effects are blocked: see Sound."].filter(Boolean);
  notice($("#stNotice"), top.join(" "));
}

/* ---------- sound ---------- */
function soundUi() {
  const a = ST.data.audio, s = $("#stDevice"); s.innerHTML = "";
  const def = document.createElement("option"); def.value = ""; def.textContent = "Default input"; s.appendChild(def);
  a.devices.forEach(d => { const o = document.createElement("option"); o.value = d.index; o.textContent = d.name + (d.loopback ? " (system audio)" : ""); s.appendChild(o); });
  s.value = a.device == null ? "" : String(a.device);
  $("#stSens").value = a.sensitivity; sensOut();
  const listening = ST.data.enabled && ST.data.needs.includes("audio");
  $("#stLevelHint").textContent = listening ? "Listening now. The bar follows the sound." : "The level moves while Studio is on with a sound effect in the preset.";
  if (!listening) window.onStudioLevel(0);
  if (a.error) notice($("#stAudioErr"), a.error);
}
function sensOut() { const t = (+$("#stSens").value).toFixed(1) + "×"; $("#stSensOut").textContent = t; valueText("stSens", t); }
$("#stDevice").onchange = () => quiet(scall("set_audio_device", $("#stDevice").value === "" ? null : +$("#stDevice").value));
$("#stSens").oninput = sensOut;
$("#stSens").onchange = () => quiet(scall("set_audio_sensitivity", +$("#stSens").value));

/* ---------- typing ---------- */
function typingUi() { $("#stHeat").checked = ST.data.heat.enabled; $("#stHeatCount").textContent = plural(ST.data.heat.keys, "key"); }
$("#stHeat").onchange = async () => {
  try { await scall("set_heat", $("#stHeat").checked); ST.data.heat.enabled = $("#stHeat").checked; }
  catch (e) { $("#stHeat").checked = !$("#stHeat").checked; }
};
$("#stHeatReset").onclick = e => busy(e.target, async () => { await scall("reset_heat"); ST.data.heat.keys = 0; typingUi(); toast("Heatmap reset"); });

/* ---------- smart lighting ---------- */
function smartUi() {
  const c = ST.data.smart, i = c.idle;
  $("#smIdle").checked = i.enabled; $("#smMinutes").value = i.minutes; $("#smAction").value = i.action;
  $("#smDim").value = Math.round(i.dim_to * 100); $("#smSleep").checked = c.sleep_off; $("#smLock").checked = c.lock_off;
  smartRows(); rulesUi(); smartNowUi();
}
function smartRows() {
  $$("#stSmart [data-idle]").forEach(r => r.hidden = !$("#smIdle").checked || (r.hasAttribute("data-dim") && $("#smAction").value !== "dim"));
  const t = $("#smDim").value + "%"; $("#smDimOut").textContent = t; valueText("smDim", t); fillAll();
}
function smartNowUi() {
  const a = ST.data.action || {};
  $("#stSmartNow").textContent = !ST.data.enabled ? "Smart lighting works while Studio is on."
    : a.off ? "The keys are off now (asleep, locked or away)." : a.brightness < 1 ? "Dimmed now, because you're away."
    : a.preset ? `Showing “${a.preset}” for the app in front.` : "";
}
function smartForm() {
  const c = ST.data.smart, mins = Math.round(+$("#smMinutes").value);
  return { idle: { enabled: $("#smIdle").checked, minutes: mins >= 1 && mins <= 240 ? mins : c.idle.minutes, action: $("#smAction").value, dim_to: +$("#smDim").value / 100 },
    sleep_off: $("#smSleep").checked, lock_off: $("#smLock").checked, app_rules: c.app_rules.map(r => ({ ...r })) };
}
const sendSmart = debounce(async () => {
  const cfg = smartForm();
  try { await scall("set_smart", cfg); ST.data.smart = cfg; } catch (e) { smartUi(); }
}, 250);
["#smIdle", "#smAction", "#smSleep", "#smLock"].forEach(s => $(s).addEventListener("change", () => { smartRows(); ST.data.smart = smartForm(); sendSmart(); }));
$("#smMinutes").addEventListener("input", () => { ST.data.smart = smartForm(); sendSmart(); });
$("#smDim").addEventListener("input", () => { smartRows(); ST.data.smart = smartForm(); sendSmart(); });

function appName(bundle) { return ST.apps.find(a => a.bundle_id === bundle)?.name || bundle; }
function rulesUi() {
  const ul = $("#smRules"); ul.innerHTML = "";
  const rules = ST.data.smart.app_rules;
  if (!rules.length) { const li = document.createElement("li"); li.className = "rules-empty"; li.textContent = "No app rules yet."; ul.appendChild(li); return; }
  rules.forEach((r, k) => {
    const li = document.createElement("li"); li.className = "rule";
    li.innerHTML = '<span class="rule-app"><b></b><small></small></span><select></select><button class="mini del"></button>';
    li.querySelector("b").textContent = appName(r.bundle_id); li.querySelector("small").textContent = r.bundle_id;
    const s = li.querySelector("select"); s.setAttribute("aria-label", `Preset for ${appName(r.bundle_id)}`);
    ST.data.presets.forEach(p => { const o = document.createElement("option"); o.value = o.textContent = p.name; s.appendChild(o); });
    if (!ST.data.presets.some(p => p.name === r.preset)) { const o = document.createElement("option"); o.value = r.preset; o.textContent = `${r.preset} (missing)`; s.appendChild(o); }
    s.value = r.preset; s.onchange = () => { r.preset = s.value; sendSmart(); };
    const x = li.querySelector("button"); x.innerHTML = ICONS.del; x.setAttribute("aria-label", `Remove the rule for ${appName(r.bundle_id)}`);
    x.onclick = () => { rules.splice(k, 1); rulesUi(); sendSmart(); $("#smPick").focus(); };
    ul.appendChild(li);
  });
}
// On Windows an app is its program name ("steam.exe"), in place of the Mac's bundle ID; the lighting keeps running
// from the tray icon instead of the menu bar icon.
const onWindows = () => typeof model !== "undefined" && model?.platform === "windows";
function appRuleUi() {
  const w = onWindows();
  $("#smBundle").placeholder = w ? "or program name, e.g. steam.exe" : "or bundle ID, e.g. com.valvesoftware.steam";
  $("label[for=smBundle]").textContent = w ? "App program name" : "App bundle ID";
  $("#stCloseHint").textContent = `While Studio is on, closing the window keeps the lighting running from the ${w ? "tray" : "menu bar"} icon. Quit from there.`;
}
async function loadApps() {
  appRuleUi();
  try { ST.apps = await scall("running_apps"); } catch (e) { ST.apps = []; }
  const s = $("#smPick"); s.length = 1;
  ST.apps.forEach(a => { const o = document.createElement("option"); o.value = a.bundle_id; o.textContent = a.name; s.appendChild(o); });
  rulesUi();
}
$("#smAdd").onclick = () => {
  const typed = $("#smBundle").value.trim(), w = onWindows();
  const bundle = $("#smPick").value || (w ? typed.toLowerCase() : typed);
  const valid = w ? /^[^\\/:*?"<>|]+\.exe$/i.test(bundle) : /^[A-Za-z0-9][\w.-]*$/.test(bundle);
  if (!valid) { toast(w ? "Pick an open app, or type its program name (like steam.exe)." : "Pick an open app, or type its bundle ID (like com.apple.Safari).", true); $("#smBundle").focus(); return; }
  const rules = ST.data.smart.app_rules;
  if (rules.some(r => r.bundle_id === bundle)) { toast(`${appName(bundle)} already has a rule.`, true); return; }
  rules.push({ bundle_id: bundle, preset: ST.data.active });
  $("#smPick").value = ""; $("#smBundle").value = "";
  rulesUi(); sendSmart(); toast(`${appName(bundle)} added`);
};

/* ---------- hooks used by app.js ---------- */
window.studioShown = v => { if (v === "studio") appRuleUi(); if (v === "studio" && ST.data) { $("#stageNote").textContent = studioNote(); keysUi(); } previewUi(); };
window.studioStart = async () => { await studioRefresh(); };
