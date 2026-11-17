// Demo mode: a simulated keyboard so the interface can be previewed in a browser without hardware.
(function () {
  const s = document.createElement("script");
  s.src = "demo-layout.js";
  s.onload = () => {
    const layout = window.DEMO_LAYOUT;
    const id = n => layout.find(k => k.name === n).id;
    const ok = d => Promise.resolve({ ok: true, data: d });
    const pts = {};
    layout.forEach(k => { if (k.name !== "RIGHT_GUI") pts[k.id] = [2.0, 1.9]; });
    ["W", "A", "S", "D"].forEach(n => { pts[id(n)] = [1.0, 0.9]; });
    const state = {
      rapid: { enabled: false, press: 0.3, release: 0.3, keys: "all", continuous: false },
      snap: null, effect: null,
      custom: { base: [255, 255, 255], keys: Object.fromEntries(["W", "A", "S", "D"].map(n => [id(n), [255, 59, 48]])) },
    };
    const fx = {
      off: "", static: "{rgb1}", breathing_one: "{rgb1}", breathing_two: "{rgb1} {rgb2}", breathing_random: "",
      spectrum: "", wave: "{dir} {speed}", reactive_key_one: "{rgb1}", reactive_key_random: "", reactive_ripple_one: "{rgb1}",
      reactive_ripple_random: "", starlight_random: "{speed}", starlight_one: "{speed} {rgb1}", starlight_two: "{speed} {rgb1} {rgb2}", fire: "",
    };
    const speed = n => n === "wave" ? [1, 255] : n.startsWith("starlight") ? [1, 3] : null;
    let timer = null;
    window.pywebview = { api: {
      layout: () => Promise.resolve(layout),
      effects: () => Promise.resolve(Object.fromEntries(Object.entries(fx).map(([n, t]) =>
        [n, { speed: speed(n), colors: (t.match(/\{rgb/g) || []).length, dir: t.includes("{dir}") }]))),
      startup: () => ok([]),
      reconnect: () => ok([]),
      info: () => ok({ firmware: "1.03", profile: 1, brightness: 100, effect: "010501000001ffffff000000", state }),
      read_depths: () => ok(pts),
      set_depth: (keys, mm, rel) => {
        const done = {};
        (keys.length ? keys : Object.keys(pts)).forEach(k => { done[k] = pts[k] = [mm, rel ?? +(mm - 0.1).toFixed(1)]; });
        return ok({ failed: [], done, count: Object.keys(done).length });
      },
      set_rapid: () => ok(true), set_snap: () => ok(true), set_effect: () => ok(true),
      set_custom: () => ok(true), set_brightness: () => ok(null), set_prefs: () => ok(true),
      restore_original: () => ok(state),
      start_test: () => {
        const seq = ["W", "A", "S", "D"].map(id);
        let t = 0;
        timer = setInterval(() => {
          t += 0.033;
          const i = Math.floor(t / 1.4) % 4, ph = (t % 1.4) / 1.4;
          const d = Math.max(0, Math.sin(Math.min(1, ph * 1.4) * Math.PI)) * (i % 2 ? 3.6 : 1.6);
          window.onDepth(d > 0.01 ? [[seq[i], +d.toFixed(2)]] : []);
        }, 33);
        return ok(true);
      },
      stop_test: () => { clearInterval(timer); return ok([]); },
    } };
    document.title += " (demo)";
    window.dispatchEvent(new Event("pywebviewready"));
  };
  document.body.appendChild(s);
})();
