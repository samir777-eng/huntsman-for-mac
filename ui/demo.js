// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Huntsman for Mac contributors
// Demo mode: a simulated keyboard so the interface can be previewed in a browser without hardware.
// Studio is simulated too: a small JavaScript renderer draws the layers (approximations of the Python effects)
// and simulated key presses and sound feed the typing and sound effects.
(function () {
  const load = src => new Promise(res => { const s = document.createElement("script"); s.src = src; s.onload = res; document.body.appendChild(s); });
  Promise.all([load("demo-layout.js"), load("demo-studio.js")]).then(() => {
    // ?demo&model=02B0 previews another model (default: the V3 Pro); a picker in the header switches.
    // ?demo&model=none starts with no keyboard; Reconnect then finds &plug=<PID> (default: the V3 Pro).
    const q = new URLSearchParams(location.search);
    const want = (q.get("model") || "").toUpperCase();
    const find = pid => window.DEMO_MODELS.find(m => m.pid === pid) || window.DEMO_MODELS[0];
    let connected = want !== "NONE";
    let M = find(want);   // with no keyboard: the V3 Pro's layout and effects, as the app falls back to
    let layout = M.layout;
    const id = n => layout.find(k => k.name === n).id;
    const ok = d => Promise.resolve({ ok: true, data: d });
    const NOT_FOUND = { ok: false, error: "No supported Razer Huntsman found. Is it plugged in by USB?" };
    const plugged = fn => (...a) => connected ? fn(...a) : Promise.resolve(NOT_FOUND);
    // ?demo&windows=synapse,dynamic previews the Windows build: every model experimental, Razer Synapse running
    // (writes refused, re-checked) and/or Dynamic Lighting on.
    const win = q.has("windows") ? (q.get("windows") || "").split(",") : null;
    const SYNAPSE = "Razer Synapse is running, so Huntsman for Mac only reads the keyboard (Synapse would overwrite any change). Quit Synapse, including its icon in the taskbar's notification area, and the controls come back within a few seconds.";
    const DYNAMIC = "Windows Dynamic Lighting is on, so Windows may control the keyboard's lights and lighting changes here may not show. To give the lights to this app, open Settings, Personalization, Dynamic Lighting, choose the Razer Huntsman and turn off Dynamic Lighting for it (or turn off \"Use Dynamic Lighting on my devices\" for all devices).";
    const platform = () => win ? { platform: "windows", platform_experimental: true, status: "experimental",
      blocked: win.includes("synapse") ? SYNAPSE : null, notices: win.includes("dynamic") ? [DYNAMIC] : [] } : {};
    let experimentalOn = false;
    const locked = () => (M.status === "experimental" || !!win) && !experimentalOn || !!(win && win.includes("synapse"));
    // the same plain refusals as huntsman_core.gate, nothing "sent" while locked
    const refuse = feature => !M.features[feature] ? Promise.resolve({ ok: false, reason: "unavailable", error: `This isn't available on the ${M.name}.` })
      : feature === "key_tester" && M.status === "experimental" ? Promise.resolve({ ok: false, reason: "unavailable", error: `The key tester isn't offered on the ${M.name}: its support is experimental.` })
      : win && win.includes("synapse") ? Promise.resolve({ ok: false, reason: "synapse", error: SYNAPSE })
      : locked() ? Promise.resolve({ ok: false, reason: "experimental", error: `Support for the ${M.name} is experimental. Turn on Keyboard, Experimental support to change its settings.` }) : null;
    const gated = (feature, fn) => (...a) => refuse(feature) || fn(...a);
    let pts, state;
    const use = m => {   // the keyboard the demo simulates (again after Reconnect finds another one)
      M = m; layout = m.layout; pts = {};
      if (M.features.actuation) {
        layout.forEach(k => { if (k.name !== "RIGHT_GUI") pts[k.id] = [2.0, 1.9]; });
        ["W", "A", "S", "D"].forEach(n => { pts[id(n)] = [1.0, 0.9]; });
      }
      state = {
        rapid: { enabled: false, press: 0.3, release: 0.3, keys: "all", continuous: false },
        snap: null, effect: null,
        custom: { base: [255, 255, 255], keys: Object.fromEntries(["W", "A", "S", "D"].map(n => [id(n), [255, 59, 48]])) },
      };
    };
    use(M);
    const fx = {
      off: "", static: "{rgb1}", breathing_one: "{rgb1}", breathing_two: "{rgb1} {rgb2}", breathing_random: "",
      spectrum: "", wave: "{dir} {speed}", reactive_key_one: "{rgb1}", reactive_key_random: "",
      starlight_random: "{speed}", starlight_one: "{speed} {rgb1}", starlight_two: "{speed} {rgb1} {rgb2}",
    };
    const speed = n => n === "wave" ? [1, 255] : n.startsWith("starlight") ? [1, 3] : null;
    let timer = null;
    const studio = demoStudio(layout, ok);
    const info = () => { const { layout: _, ...m } = M; return { ...m, experimental_on: experimentalOn, locked: locked(), ...platform() }; };
    window.pywebview = { api: {
      model: plugged(() => ok(info())),
      experimental: () => ok(experimentalOn),
      set_experimental: on => { experimentalOn = on; return ok(on); },
      led_check: gated("per_key", (r, c) => { studio.studio_enable(false); return ok([r, c]); }),
      end_led_check: () => ok(true),
      layout: () => Promise.resolve(layout),
      effects: () => Promise.resolve(Object.fromEntries(Object.entries(fx).filter(([n]) => M.effects.includes(n)).map(([n, t]) =>
        [n, { speed: speed(n), colors: (t.match(/\{rgb/g) || []).length, dir: t.includes("{dir}") }]))),
      startup: plugged(() => ok([])),
      reconnect: () => { if (!connected) { connected = true; use(find((q.get("plug") || "").toUpperCase())); } return ok([]); },
      info: plugged(() => ok({ version: "0.3.0", model: info(), firmware: "1.03", profile: 1, brightness: 100, effect: "010501000001ffffff000000", state })),
      read_depths: plugged(() => ok(pts)),
      set_depth: gated("actuation", (keys, mm, rel) => {
        const done = {};
        const A = M.actuation;   // the model's scale, as huntsman_core: "Just above" is reset_gap above, never below release_min
        (keys.length ? keys : Object.keys(pts)).forEach(k => { done[k] = pts[k] = [mm, rel ?? +Math.max(A.release_min, mm - A.reset_gap).toFixed(A.decimals)]; });
        return ok({ failed: [], done, count: Object.keys(done).length });
      }),
      set_rapid: gated("rapid", () => ok(true)), set_snap: gated("snap_tap", () => ok(true)), set_prefs: () => ok(true),
      // the keyboard's own lighting replaces Studio, as in app.py
      set_effect: gated("lighting", () => { studio.studio_enable(false); return ok(true); }),
      set_custom: gated("per_key", () => { studio.studio_enable(false); return ok(true); }),
      set_brightness: gated("lighting", () => ok(null)),   // live only
      save_brightness: gated("lighting", () => ok(null)),  // written to the keyboard's memory
      restore_original: gated("actuation", () => M.actuation.factory == null
        ? Promise.resolve({ ok: false, reason: "unavailable", error: `The ${M.name}'s factory depth isn't known, so it can't be restored.` }) : ok(state)),
      start_test: gated("key_tester", () => {
        const seq = ["W", "A", "S", "D"].map(id);
        let t = 0;
        timer = setInterval(() => {
          t += 0.033;
          const i = Math.floor(t / 1.4) % 4, ph = (t % 1.4) / 1.4;
          const d = Math.max(0, Math.sin(Math.min(1, ph * 1.4) * Math.PI)) * (i % 2 ? 3.6 : 1.6);
          window.onDepth(d > 0.01 ? [[seq[i], +d.toFixed(2)]] : []);
        }, 33);
        return ok(true);
      }),
      stop_test: () => { clearInterval(timer); return ok([]); },
      ...studio,
      studio_enable: on => (on && refuse("studio")) || studio.studio_enable(on),
    } };
    document.title += " (demo)";
    // model picker, demo only
    const pick = document.createElement("select");
    pick.id = "demoModel"; pick.setAttribute("aria-label", "Demo model");
    window.DEMO_MODELS.forEach(m => { const o = document.createElement("option"); o.value = m.pid; o.textContent = m.name; pick.appendChild(o); });
    pick.value = connected ? M.pid : "";
    pick.onchange = () => { const q = new URLSearchParams(location.search); q.set("model", pick.value); location.search = q.toString().replace("demo=&", "demo&").replace(/demo=$/, "demo"); };
    document.querySelector(".device-state").appendChild(pick);
    window.dispatchEvent(new Event("pywebviewready"));
  });

  /* ---------- Studio simulation ---------- */
  function demoStudio(layout, ok) {
    const D = window.DEMO_STUDIO, fail = e => Promise.resolve({ ok: false, error: e });
    const copy = o => JSON.parse(JSON.stringify(o));
    const builtins = D.presets.map(p => ({ ...p, builtin: true }));
    let user = [];
    const st = { enabled: new URLSearchParams(location.search).has("studio"), active: "Gaming WASD", fps: 30, brightness: 1, audio: { device: null, sensitivity: 1 }, heat: false };
    let working = copy(builtins.find(p => p.name === st.active)), dirty = false;
    let smart = { idle: { enabled: false, minutes: 10, action: "dim", dim_to: 0.2 }, sleep_off: true, lock_off: true, app_rules: [] };
    const all = () => [...builtins, ...user.map(p => ({ ...p, builtin: false }))];
    const find = n => all().find(p => p.name === n);
    const fx = Object.fromEntries(D.effects.map(e => [e.name, e]));
    const needs = p => [...new Set(p.layers.filter(l => l.enabled).flatMap(l => fx[l.effect].needs))].sort();
    const check = p => { for (const l of p.layers) if (!fx[l.effect]) return `unknown effect '${l.effect}'`; return null; };
    const activate = p => { working = copy(p); dirty = false; st.active = p.name; };
    const unique = b => { let n = 2, name = b; while (find(name)) name = `${b} ${n++}`; return name; };
    const api = {
      studio_state: () => ok({ effects: D.effects, presets: copy(all()), active: st.active, working: copy(working), dirty,
        enabled: st.enabled, fps: st.fps, brightness: st.brightness, needs: needs(working),
        audio: { ...st.audio, devices: [{ index: 0, name: "MacBook Pro Microphone", loopback: false }, { index: 2, name: "BlackHole 2ch", loopback: true }], error: null },
        heat: { enabled: st.heat, keys: st.heat ? 42 : 0 }, smart: copy(smart), action: { brightness: 1, off: false, preset: null },
        errors: { keys: null, audio: null, presets: null } }),
      studio_enable: on => { st.enabled = on; return ok(null); },
      set_active_preset: n => { const p = find(n); if (!p) return fail(`there's no preset called '${n}'`); activate(p); return ok(null); },
      update_layers: ls => { const p = { ...working, layers: copy(ls) }, e = check(p); if (e) return fail(e); working = p; dirty = true; return ok(needs(p)); },
      save_preset: p => {
        if (builtins.some(b => b.name === p.name)) return fail(`'${p.name}' is built in. Use Save as with a new name.`);
        const e = check(p); if (e) return fail(e);
        const i = user.findIndex(u => u.name === p.name); if (i >= 0) user[i] = copy(p); else user.push(copy(p));
        activate(p); return ok(null);
      },
      delete_preset: n => { if (!user.some(u => u.name === n)) return fail("built-in presets can't be deleted"); user = user.filter(u => u.name !== n); if (st.active === n) activate(builtins[0]); return ok(null); },
      rename_preset: (o, n) => { const u = user.find(x => x.name === o); if (!u) return fail("built-in presets can't be renamed. Duplicate it first."); u.name = n; if (st.active === o) { st.active = n; working.name = n; } return ok(null); },
      duplicate_preset: n => { const src = n === st.active ? working : find(n), name = unique(`${n} copy`); user.push({ ...copy(src), name, builtin: undefined }); activate(find(name)); return ok(name); },
      import_preset: text => { try { let d = JSON.parse(text); if (d.format) d = d.preset; d.name = unique(d.name); const e = check(d); if (e) return fail(e); user.push(d); activate(d); return ok(d.name); } catch (e) { return fail("that isn't a preset file"); } },
      export_preset: n => ok({ json: JSON.stringify({ format: "huntsman-for-mac-preset", version: 1, preset: n === st.active ? working : find(n) }, null, 1) }),
      set_studio_brightness: v => { st.brightness = v; return ok(null); },
      set_fps: v => { st.fps = v; return ok(null); },
      set_audio_device: d => { st.audio.device = d; return ok(null); },
      set_audio_sensitivity: v => { st.audio.sensitivity = v; return ok(null); },
      set_heat: on => { st.heat = on; return ok(null); },
      reset_heat: () => ok(null),
      set_smart: c => { if (!(c.idle.minutes > 0)) return fail("idle.minutes must be more than 0"); smart = copy(c); return ok(null); },
      running_apps: () => ok([{ name: "Safari", bundle_id: "com.apple.Safari" }, { name: "Steam", bundle_id: "com.valvesoftware.steam" }, { name: "Visual Studio Code", bundle_id: "com.microsoft.VSCode" }]),
    };
    startRenderer(layout, () => st, () => (window.__demoShown || working));
    return api;
  }

  // A light imitation of lighting/: enough to make each effect recognisable in the preview.
  function startRenderer(layout, settings, preset) {
    const keys = layout.map(k => ({ id: k.id, name: k.name, cx: k.x + k.w / 2, cy: k.y + k.h / 2, row: k.led[0] }));
    const W = Math.max(...layout.map(k => k.x + k.w)), H = Math.max(...layout.map(k => k.y + k.h));
    const clamp = v => Math.max(0, Math.min(255, Math.round(v)));
    const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
    const sample = (cols, t, loop) => {
      if (cols.length === 1) return cols[0];
      if (loop) { const p = ((t % 1) + 1) % 1 * cols.length, i = Math.floor(p); return mix(cols[i % cols.length], cols[(i + 1) % cols.length], p - i); }
      const p = Math.max(0, Math.min(1, t)) * (cols.length - 1), i = Math.min(Math.floor(p), cols.length - 2); return mix(cols[i], cols[i + 1], p - i);
    };
    const hash = (a, b) => { const x = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return x - Math.floor(x); };
    const presses = [], seq = ["W", "A", "S", "D", "E", "R", "SPACE", "Q", "F"];
    let pi = 0;
    const byName = n => keys.find(k => k.name === n);
    const heat = {}; ["W", "A", "S", "D"].forEach(n => heat[byName(n)?.id] = 40); ["E", "R", "Q", "SPACE"].forEach(n => heat[byName(n)?.id] = 15);
    const P = (l, n) => { const v = l.params[n]; if (v !== undefined) return v; const p = window.DEMO_STUDIO.effects.find(e => e.name === l.effect).params.find(q => q.name === n); return p ? p.default : undefined; };
    function render(l, k, t, audio) {
      const e = l.effect, cols = P(l, "colors"), col = P(l, "color");
      const x = k.cx / W, y = k.cy / H;
      switch (e) {
        case "solid": return col;
        case "gradient": return sample(cols, P(l, "mode") === "radial" ? Math.hypot(x - .5, y - .5) * 1.6 : x, false);
        case "rainbow": return sample(cols, x * P(l, "scale") - t * P(l, "speed") * 0.5, true);
        case "colour_cycle": return sample(cols, t * P(l, "speed"), true);
        case "breathing": { const per = P(l, "period"), n = Math.floor(t / per); return cols[n % cols.length].map(v => v * (0.5 - 0.5 * Math.cos(t / per * 2 * Math.PI))); }
        case "aurora": { const s = P(l, "speed"), v = 0.5 + 0.5 * Math.sin(x * 6 / P(l, "scale") + t * s * 1.3 + Math.sin(y * 3 - t * s)); return sample(cols, v * 0.9 + 0.1 * Math.sin(t * s), true).map(c => c * (0.35 + 0.65 * v)); }
        case "plasma": { const s = P(l, "speed"); const v = Math.sin(x * 9 + t * s) + Math.sin(y * 7 - t * s * 1.3) + Math.sin((x + y) * 6 + t * s * .7); return sample(cols, v / 6 + .5, true); }
        case "fire": { const h = 1 - y, n = hash(k.id, Math.floor(t * 8 * P(l, "speed"))); const heatv = Math.max(0, 1 - h * 1.25 + (n - .5) * .5) * P(l, "intensity"); return sample(cols, heatv, false).map(c => c * Math.min(1, heatv * 1.6)); }
        case "starfield": { const ph = (t * P(l, "speed") * 0.6 + hash(k.id, 1)) % 1, on = hash(k.id, Math.floor(t * P(l, "speed") * 0.6 + hash(k.id, 1))) < P(l, "density"); return on ? col.map(c => c * Math.sin(ph * Math.PI)) : [0, 0, 0]; }
        case "matrix": { const col_ = Math.floor(k.cx), sp = P(l, "speed") / 8, head = ((t * sp * 2 + hash(col_, 3) * 6) % 8) - 1.5, d = head - k.row; return d >= 0 && d < 3 && hash(col_, 9) < P(l, "density") + .3 ? col.map(c => c * (1 - d / 3)) : [0, 0, 0]; }
        case "audio_spectrum": { const band = Math.min(15, Math.floor(x * 16)), lvl = audio.bands[band], rowLvl = (5 - k.row + 1) / 6; return lvl >= rowLvl ? sample(cols, rowLvl, false) : [0, 0, 0]; }
        case "audio_pulse": return sample(cols, audio.level, false).map(c => c * (0.15 + 0.85 * Math.min(1, audio.level * P(l, "sensitivity"))));
        case "heatmap": { const v = (heat[k.id] || 0) / 40; return v ? sample(cols, v, false) : [0, 0, 0]; }
        default: return react(l, k, t);
      }
    }
    function react(l, k, t) {
      let out = [0, 0, 0];
      const fade = P(l, "fade");
      for (const p of presses) {
        const age = t - p.t; if (age < 0 || age > fade + 2) continue;
        let v = 0, c = P(l, "color") || P(l, "colors")[0];
        const d = Math.hypot(k.cx - p.k.cx, k.cy - p.k.cy);
        if (l.effect === "reactive_ripple") { const r = age * P(l, "speed") / 2; v = Math.max(0, 1 - Math.abs(d - r) / P(l, "width")) * Math.max(0, 1 - age / fade); }
        else if (l.effect === "reactive_afterglow") v = k.id === p.k.id ? Math.max(0, 1 - age / fade) : 0;
        else if (l.effect === "reactive_explosion") { const r = P(l, "radius") * Math.min(1, age * 4); v = d <= r ? Math.max(0, 1 - age / fade) * (1 - d / (r + .01) * .6) : 0; c = sample(P(l, "colors"), d / P(l, "radius"), false); }
        else if (l.effect === "reactive_trail") v = k.row === p.k.row && Math.abs(k.cx - p.k.cx) < P(l, "length") * Math.min(1, age * 3) ? Math.max(0, 1 - age / fade) : 0;
        out = out.map((o, i) => Math.max(o, c[i] * v));
      }
      return out;
    }
    const blend = (d, s, m) => m === "add" ? d.map((v, i) => v + s[i]) : m === "screen" ? d.map((v, i) => 255 - (255 - v) * (255 - s[i]) / 255)
      : m === "multiply" ? d.map((v, i) => v * s[i] / 255) : m === "max" ? d.map((v, i) => Math.max(v, s[i])) : s;
    const t0 = performance.now();
    window.__frames = 0;
    setInterval(() => {
      const s = settings(), p = preset(), t = (performance.now() - t0) / 1000;
      if (!s.enabled || typeof window.onStudioFrame !== "function") return;
      if (t - (presses.length ? presses[presses.length - 1].t : -1) > 0.45) { const k = byName(seq[pi++ % seq.length]); if (k) presses.push({ k, t }); if (presses.length > 12) presses.shift(); }
      const audio = { level: 0.5 + 0.45 * Math.sin(t * 3.1) * Math.sin(t * 1.3), bands: Array.from({ length: 16 }, (_, i) => Math.max(0, 0.75 - i * 0.035 + 0.25 * Math.sin(t * (3 + i * .4) + i))) };
      const hears = p.layers.some(l => l.enabled && window.DEMO_STUDIO.effects.find(e => e.name === l.effect).needs.includes("audio"));
      if (hears && typeof window.onStudioLevel === "function") window.onStudioLevel(audio.level);
      const frame = {};
      for (const k of keys) {
        let c = [0, 0, 0];
        for (const l of p.layers) {
          if (!l.enabled || (l.keys !== "all" && !l.keys.includes(k.id))) continue;
          const b = blend(c, render(l, k, t, audio), l.blend);
          c = c.map((v, i) => v + (b[i] - v) * l.opacity);
        }
        frame[k.id] = c.map(v => clamp(v * s.brightness * (p.brightness ?? 1)));
      }
      window.__frames++;
      window.onStudioFrame(frame);
    }, 1000 / 15);
  }
})();
