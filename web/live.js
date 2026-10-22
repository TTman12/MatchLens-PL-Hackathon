// Swing "Generate match": asks the server for a brand-new match (swing/live/server.py) and
// plays it on the screen as its minutes arrive. The server generates the match, sends it through
// the agents one minute at a time as an unseen match, and rebuilds the screen's bundle after each
// minute; this file polls for that bundle and hands it to the screen (app.js, window.swingScreen).
//
// URL options: ?live=<id> reopens a generated match while the server still has it.
//              ?drill=<agent>[&drill_mode=flaky] arms the fault drill (admin screen): the next
//              generated match has that agent knocked out, to show the others recover
//              (swing/live/failover.py). Agents: team_play players substitutions match_events
//              explainer interpreter analyst.

(() => {
  "use strict";

  const POLL_MS = 1500;
  const $ = (id) => document.getElementById(id);
  const screen = () => window.swingScreen;
  const params = new URLSearchParams(location.search);

  const WORDS = {
    en: {
      generate: "Generate match", generating: "Generating…", unseen: "Unseen match", seed: "seed",
      no_truth: "fed minute by minute · no truth data used", starting: "Generating a brand-new match…",
      feed_at: (m) => `Feed at ${m}`, foundry: "agents on Foundry", rules: "rules-written cards",
      waiting: (m) => `Agents working on ${m}…`, full_time: "Full time",
      cards: (f, r) => [f ? `${f} by Foundry agents` : "", r ? `${r} rules-written` : ""].filter(Boolean).join(", ") || "no cards",
      offline: "Generating needs the live server. The demo matches still play.", option: (h, a) => `New: ${h} v ${a} (unseen)`,
      drill_off: "Fault drill: off", knock: (a) => `Knock out: ${a}`, flaky: (a) => `Flaky: ${a}`,
      drill: (a, m, n) => `Fault drill: ${a} ${m === "flaky" ? "flaky" : "down"} · ${n} recovered`,
    },
    es: {
      generate: "Generar partido", generating: "Generando…", unseen: "Partido inédito", seed: "semilla",
      no_truth: "minuto a minuto · sin datos de la verdad", starting: "Generando un partido nuevo…",
      feed_at: (m) => `Datos hasta el ${m}`, foundry: "agentes en Foundry", rules: "tarjetas por reglas",
      waiting: (m) => `Los agentes trabajan en el ${m}…`, full_time: "Final",
      cards: (f, r) => [f ? `${f} por agentes de Foundry` : "", r ? `${r} por reglas` : ""].filter(Boolean).join(", ") || "sin tarjetas",
      offline: "Generar necesita el servidor en vivo. Los partidos de demostración siguen disponibles.", option: (h, a) => `Nuevo: ${h} v ${a} (inédito)`,
      drill_off: "Simulacro de fallo: no", knock: (a) => `Tumbar: ${a}`, flaky: (a) => `Intermitente: ${a}`,
      drill: (a, m, n) => `Simulacro: ${a} ${m === "flaky" ? "intermitente" : "caído"} · ${n} recuperados`,
    },
  };
  const w = (k, ...a) => {
    const lang = (screen() && screen().lang) || "en";
    const v = (WORDS[lang] || WORDS.en)[k] ?? WORDS.en[k];
    return typeof v === "function" ? v(...a) : v;
  };

  let job = null; // {id, seed, home, away}
  let timer = 0;
  let shown = false; // the job's bundle is on screen
  let flash = ""; // a message that wins over the status line for a few seconds
  let flashUntil = 0;

  // ---------- the button, the badge and the not-yet-arrived part of the timeline ----------
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "genBtn";
  btn.className = "gen-btn";
  btn.textContent = w("generate");
  // the fault drill: knock one agent out of the next generated match. Admin only: it sits with the
  // controls, which the user screen hides.
  const DRILL_AGENTS = {
    team_play: "Team play", players: "Players", substitutions: "Substitutions", match_events: "Match events",
    explainer: "Explainer", interpreter: "Interpreter", analyst: "Analyst",
  };
  const drillSel = document.createElement("select");
  drillSel.id = "drillSel";
  drillSel.className = "drill-sel";
  drillSel.title = "Fault drill: the next generated match runs with this agent failing, to show the recovery";
  function drillOptions() {
    const keep = drillSel.value;
    const opts = [new Option(w("drill_off"), "")];
    for (const [k, name] of Object.entries(DRILL_AGENTS)) opts.push(new Option(w("knock", name), k));
    for (const k of ["players", "interpreter"]) opts.push(new Option(w("flaky", DRILL_AGENTS[k]), `${k}:flaky`));
    drillSel.replaceChildren(...opts);
    drillSel.value = keep;
  }
  drillOptions();
  {
    const want = params.get("drill");
    if (want && DRILL_AGENTS[want]) drillSel.value = params.get("drill_mode") === "flaky" ? `${want}:flaky` : want;
    if (drillSel.selectedIndex < 0) drillSel.value = "";
  }
  const armed = () => drillSel.classList.toggle("armed", Boolean(drillSel.value));
  drillSel.addEventListener("change", armed);
  armed();

  // the button sits just before the match list, which moves between the user and admin screens
  const place = () => {
    const sel = $("matchSelect");
    if (btn.nextElementSibling !== sel) sel.before(btn);
    if (drillSel.nextElementSibling !== btn) btn.before(drillSel);
  };
  place();

  const badge = document.createElement("div");
  badge.className = "live-badge";
  badge.hidden = true;
  badge.setAttribute("aria-live", "polite");
  document.querySelector(".video").append(badge);

  const pending = document.createElement("div");
  pending.className = "tl-pending";
  pending.hidden = true;
  $("tlTrack").append(pending);

  const say = (msg, secs = 8) => {
    flash = msg;
    flashUntil = performance.now() + secs * 1000;
    draw();
  };

  function liveOf() {
    const b = screen() && screen().bundle;
    return b && b.live && job && b.live.id === job.id ? b.live : null;
  }

  let drillLang = "";
  function draw() {
    place();
    const lang = (screen() && screen().lang) || "en";
    if (lang !== drillLang) {
      drillLang = lang;
      drillOptions();
    }
    btn.textContent = job && !shown ? w("generating") : w("generate");
    btn.disabled = Boolean(job && !shown);
    const live = liveOf();
    const s = screen();
    if (!live && !(job && !shown) && !(flash && performance.now() < flashUntil)) {
      badge.hidden = true;
      pending.hidden = true;
      return;
    }
    let status;
    if (flash && performance.now() < flashUntil) status = flash;
    else if (!live) status = w("starting");
    else if (live.done) status = `${w("full_time")} · ${w("cards", live.by.foundry, live.by.rules)}`;
    else {
      const b = s.bundle;
      const at = b.clock[b.clock.length - 1] || "0'";
      const waiting = s.playing && s.t >= live.ready - 0.05;
      const who = live.note || (live.agents === "foundry" ? w("foundry") : w("rules"));
      status = `${waiting ? w("waiting", at) : w("feed_at", at)} · ${who}`;
    }
    const head = live || job
      ? `<span class="lb-tag">${w("unseen")}</span><span>${w("seed")} ${(live || job).seed}</span><span>${w("no_truth")}</span>`
      : "";
    const drill = live && live.drill ? `<div class="lb-status lb-drill">${esc(w("drill", DRILL_AGENTS[live.drill.agent] || live.drill.agent, live.drill.mode, live.incidents || 0))}</div>` : "";
    badge.innerHTML = `${head ? `<div class="lb-head">${head}</div>` : ""}<div class="lb-status">${esc(status)}</div>${drill}`;
    badge.hidden = false;
    document.querySelector(".feed-note").hidden = Boolean(live || job);
    if (live && !live.done) {
      const b = s.bundle;
      pending.style.left = `${(100 * live.ready) / b.minutes}%`;
      pending.hidden = false;
    } else pending.hidden = true;
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  // ---------- talking to the server ----------
  async function generate() {
    if (job && !shown) return;
    stop();
    btn.disabled = true;
    let res;
    try {
      const [agent, mode] = drillSel.value.split(":");
      const q = agent ? `?${new URLSearchParams(mode ? { drill: agent, drill_mode: mode } : { drill: agent })}` : "";
      res = await fetch(`api/generate${q}`, { method: "POST" });
    } catch {
      btn.disabled = false;
      say(w("offline"));
      return;
    }
    let body = {};
    try {
      body = await res.json();
    } catch {
      body = {};
    }
    if (res.status !== 202) {
      btn.disabled = false;
      say(res.status === 404 || res.status === 501 ? w("offline") : body.error || `${res.status}`);
      return;
    }
    start(body);
  }

  function start(j) {
    job = j;
    shown = false;
    const sel = $("matchSelect");
    const value = `live:${j.id}`;
    let opt = [...sel.options].find((o) => o.value === value);
    if (!opt) {
      opt = new Option(w("option", (j.home || "").toUpperCase(), (j.away || "").toUpperCase()), value);
      sel.prepend(opt);
    }
    sel.value = value;
    const url = new URL(location.href);
    url.searchParams.set("live", j.id);
    url.searchParams.delete("match");
    history.replaceState(null, "", url);
    draw();
    poll();
  }

  function stop() {
    clearTimeout(timer);
    timer = 0;
  }

  async function poll() {
    stop();
    if (!job) return;
    const id = job.id;
    try {
      const res = await fetch(`api/live/${encodeURIComponent(id)}`, { cache: "no-cache" });
      if (!job || job.id !== id) return;
      if (res.status === 404) {
        const body = await res.json().catch(() => ({}));
        drop(body.error || w("offline"));
        return;
      }
      const b = await res.json();
      if (!job || job.id !== id) return;
      const live = b.live || {};
      if (live.status === "failed" && !(b.clock && b.clock.length)) {
        drop(live.note);
        return;
      }
      if (b.clock && b.clock.length && b.teams) {
        if (!job.seed) Object.assign(job, { seed: live.seed });
        if (!shown) {
          shown = true;
          // a reopened ?live= link only knew the id: name the match list's entry from the bundle
          const opt = [...$("matchSelect").options].find((o) => o.value === `live:${id}`);
          if (opt) opt.textContent = w("option", b.teams[0].code, b.teams[1].code);
          screen().use(b);
          screen().play(true);
        } else screen().update(b);
      }
      if (live.status === "done" || live.status === "failed") {
        if (live.note && live.status === "failed") say(live.note);
        draw();
        return;
      }
    } catch {
      // a dropped poll: try again
    }
    draw();
    timer = setTimeout(poll, POLL_MS);
  }

  // the match is gone (cleared away, or it failed before kick-off): back to a demo match
  function drop(msg) {
    const sel = $("matchSelect");
    const opt = job && [...sel.options].find((o) => o.value === `live:${job.id}`);
    if (opt) opt.remove();
    const wasShown = shown;
    job = null;
    shown = false;
    const url = new URL(location.href);
    url.searchParams.delete("live");
    history.replaceState(null, "", url);
    if (wasShown && sel.options.length) sel.dispatchEvent(new Event("change"));
    say(msg || w("offline"));
  }

  btn.addEventListener("click", generate);
  $("matchSelect").addEventListener("change", (e) => {
    const v = e.target.value;
    if (v.startsWith("live:")) {
      if (!job || `live:${job.id}` !== v) start({ id: v.slice(5) });
      else if (shown) {
        shown = false; // put it back on screen from the next poll
        poll();
      }
    } else {
      stop();
      job = null;
      shown = false;
      const url = new URL(location.href);
      url.searchParams.delete("live");
      history.replaceState(null, "", url);
      draw();
    }
  });
  document.addEventListener("keydown", (e) => {
    // Generate match is the admin screen's: the user screen plays the match it opened on
    const admin = $("stage").classList.contains("mode-admin");
    if (admin && (e.key === "g" || e.key === "G") && e.target.tagName !== "SELECT" && !e.ctrlKey && !e.metaKey) generate();
  });
  setInterval(draw, 500);

  // hide the button where there is no server to ask (a plain static copy of web/), and the drill
  // where the server has it switched off
  fetch("api/live")
    .then((r) => {
      if (!r.ok) throw new Error();
      return r.json();
    })
    .then((s) => {
      if (!s.drills) drillSel.hidden = true;
    })
    .catch(() => {
      btn.hidden = true;
      drillSel.hidden = true;
    });

  // a shared ?live= link: once the screen has its match list, put the generated match on it
  const want = params.get("live");
  if (want) {
    const wait = setInterval(() => {
      if (screen() && screen().bundle) {
        clearInterval(wait);
        start({ id: want });
      }
    }, 100);
  }
})();
