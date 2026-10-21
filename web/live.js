// MatchLens "Generate match": asks the server for a brand-new match (matchlens/live/server.py) and
// plays it on the screen as its minutes arrive. The server generates the match, sends it through
// the agents one minute at a time as an unseen match, and rebuilds the screen's bundle after each
// minute; this file polls for that bundle and hands it to the screen (app.js, window.matchlensScreen).
//
// URL option: ?live=<id> reopens a generated match while the server still has it.

(() => {
  "use strict";

  const POLL_MS = 1500;
  const $ = (id) => document.getElementById(id);
  const screen = () => window.matchlensScreen;
  const params = new URLSearchParams(location.search);

  const WORDS = {
    en: {
      generate: "Generate match", generating: "Generating…", unseen: "Unseen match", seed: "seed",
      no_truth: "fed minute by minute · no truth data used", starting: "Generating a brand-new match…",
      feed_at: (m) => `Feed at ${m}`, foundry: "agents on Foundry", rules: "rules-written cards",
      waiting: (m) => `Agents working on ${m}…`, full_time: "Full time",
      cards: (f, r) => [f ? `${f} by Foundry agents` : "", r ? `${r} rules-written` : ""].filter(Boolean).join(", ") || "no cards",
      offline: "Generating needs the live server. The demo matches still play.", option: (h, a) => `New: ${h} v ${a} (unseen)`,
    },
    es: {
      generate: "Generar partido", generating: "Generando…", unseen: "Partido inédito", seed: "semilla",
      no_truth: "minuto a minuto · sin datos de la verdad", starting: "Generando un partido nuevo…",
      feed_at: (m) => `Datos hasta el ${m}`, foundry: "agentes en Foundry", rules: "tarjetas por reglas",
      waiting: (m) => `Los agentes trabajan en el ${m}…`, full_time: "Final",
      cards: (f, r) => [f ? `${f} por agentes de Foundry` : "", r ? `${r} por reglas` : ""].filter(Boolean).join(", ") || "sin tarjetas",
      offline: "Generar necesita el servidor en vivo. Los partidos de demostración siguen disponibles.", option: (h, a) => `Nuevo: ${h} v ${a} (inédito)`,
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
  // the button sits just before the match list, which moves between the user and admin screens
  const place = () => {
    const sel = $("matchSelect");
    if (btn.nextElementSibling !== sel) sel.before(btn);
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

  function draw() {
    place();
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
    badge.innerHTML = `${head ? `<div class="lb-head">${head}</div>` : ""}<div class="lb-status">${esc(status)}</div>`;
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
      res = await fetch("api/generate", { method: "POST" });
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
    if ((e.key === "g" || e.key === "G") && e.target.tagName !== "SELECT" && !e.ctrlKey && !e.metaKey) generate();
  });
  setInterval(draw, 500);

  // hide the button where there is no server to ask (a plain static copy of web/)
  fetch("api/live")
    .then((r) => {
      if (!r.ok) throw new Error();
    })
    .catch(() => {
      btn.hidden = true;
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
