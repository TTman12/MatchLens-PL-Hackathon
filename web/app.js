// MatchLens broadcast screen. Plays one match bundle (see matchlens/broadcast/bundle.py) on a
// condensed clock. The page does no analysis: everything it shows is in the bundle.
//
// URL options: ?match=<id>  &speed=1|2|4  &autoplay=1  &hide=1 (no operator controls, for capture)
//              &tab=clubs|players|agents  &fan=<team id> (whose fans the card text speaks to)
//              &view=casual|analyst  &lang=en|es  &follow=<player id>
// Keys: space play/pause, H hide controls, N jump to the next card, R restart, U under the hood,
//       F full time (the recap), V casual/analyst, L English/Spanish.

(() => {
  "use strict";

  const SECONDS_PER_MINUTE = 1.6; // at 1x a 95-minute match plays in about 2.5 minutes
  const CARD_SECONDS = 9; // how long a card stays up
  const ANALYSIS_SECONDS = 8; // how long the MatchLens analysis that follows it stays up
  const CARD_SLOWDOWN = 0.12; // the clock creeps while a card is up
  const SPEEDS = [1, 2, 4];

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  let bundle = null;
  let t = 0; // match minute, fractional
  let playing = false;
  let speedIx = Math.max(0, SPEEDS.indexOf(Number(params.get("speed")) || 1));
  let nextCard = 0;
  let cardUntil = 0; // performance.now() ms when the current card leaves
  let phase = null; // "stats" while a card is up, "analysis" while its MatchLens analysis is
  let last = 0;
  let hoodCard = null; // the card the agents tab describes
  let tab = ["clubs", "players", "agents"].includes(params.get("tab")) ? params.get("tab") : params.get("hood") === "1" ? "agents" : "clubs";
  let fan = params.get("fan") || store("matchlens.fan") || "neutral"; // a team id, or "neutral"
  let club = null; // the club the players tab lists
  let player = null; // the player the players tab shows
  let panelMinute = -1;
  let view = pick(params.get("view") || store("matchlens.view"), ["casual", "analyst"], "casual");
  let lang = pick(params.get("lang") || store("matchlens.lang"), ["en", "es"], "en");
  let follow = params.get("follow"); // a player id: follow mode pins his match on screen
  let nextMoment = 0;
  let tagUntil = 0;
  let recapOn = false;

  function pick(v, allowed, fallback) {
    return allowed.includes(v) ? v : fallback;
  }

  function store(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      localStorage.setItem(k, v);
    } catch {
      return null; // private windows and blocked storage: the setting just isn't remembered
    }
    return null;
  }

  // ---------- words: the screen's own words, in English and Spanish ----------
  // The lines on the cards come from the bundle (written and checked by the pipeline); these are
  // the labels around them.
  const WORDS = {
    en: {
      your_club: "Your club", neutral: "Neutral", clubs: "Clubs", players: "Players", agents: "Agents",
      casual: "Casual", analyst: "Analyst", play: "Play", pause: "Pause", momentum: "Momentum",
      win_back: (c) => `How ${c} win it back`, keep_going: (c) => `How ${c} keep it going`, analysis: "MatchLens analysis",
      at: "At", last15: "Last 15'", modelled: "* modelled from tracking-style data.", tap_club: "Tap a club for its players.",
      back: "Back", not_on: "Not on the pitch yet.", on: "on", sub: "sub", passes: "passes",
      follow: "Follow", following: "Following", unfollow: "Stop following",
      full_time: "Full time", who_had_it: "Who had the game", turning: "Turning points", standouts: "Standouts",
      halves: "First half · second half", involvement: "Touches every 5 minutes", before: "before", since: "since",
      confidence: "confidence", stat_of: (who, label) => `${who}'s ${lower(label)}`, rank_at: (club) => `at ${club}`,
      no_bundle_stats: "This match bundle has no stats tables.",
    },
    es: {
      your_club: "Tu club", neutral: "Neutral", clubs: "Clubes", players: "Jugadores", agents: "Agentes",
      casual: "Básica", analyst: "Analista", play: "Ver", pause: "Pausa", momentum: "Inercia",
      win_back: (c) => `Cómo recupera ${c} el control`, keep_going: (c) => `Cómo sigue ${c} mandando`, analysis: "Análisis MatchLens",
      at: "Min.", last15: "Últ. 15'", modelled: "* estimado con datos de seguimiento.", tap_club: "Toca un club para ver sus jugadores.",
      back: "Volver", not_on: "Todavía no ha salido al campo.", on: "entra", sub: "suplente", passes: "pases",
      follow: "Seguir", following: "Siguiendo", unfollow: "Dejar de seguir",
      full_time: "Final", who_had_it: "Quién mandó", turning: "Momentos clave", standouts: "Destacados",
      halves: "Primera parte · segunda parte", involvement: "Toques cada 5 minutos", before: "antes", since: "desde",
      confidence: "confianza", stat_of: (who, label) => `${label} de ${who}`, rank_at: (club) => `en ${club}`,
      no_bundle_stats: "Este partido no tiene tablas de estadísticas.",
    },
  };
  const w = (k, ...a) => {
    const v = WORDS[lang][k] ?? WORDS.en[k];
    return typeof v === "function" ? v(...a) : v;
  };
  // a stat label in the viewer's language
  const L = (label) => (lang === "es" && bundle && bundle.i18n ? bundle.i18n.es.labels[label] || label : label);

  // what each cause is called on the analyst's card
  const CAUSES = {
    play_change: ["Play change", "Cambio de juego"],
    recovery: ["Recovery", "Reacción"],
    fatigue: ["Fatigue", "Cansancio"],
    substitution_impact: ["Sub impact", "Impacto del cambio"],
    sub_no_change: ["Sub, no change", "Cambio sin efecto"],
    goal_no_reaction: ["No reaction", "Sin reacción"],
    goal_lift: ["Goal lift", "Impulso del gol"],
    chasing_the_game: ["Chasing the game", "A remolque"],
    half_time_no_change: ["Same as before", "Todo igual"],
    red_card_reshape: ["Ten men reshape", "Reajuste con diez"],
    red_card_holding: ["Ten men holding", "Aguanta con diez"],
  };
  const causeName = (k) => (CAUSES[k] ? CAUSES[k][lang === "es" ? 1 : 0] : k);

  // follow mode: the name tag for each moment, as [big, small]
  const TAGS = {
    en: {
      goal: () => ["Goal", ""], assist: () => ["Assist", ""], shot: (v) => ["Shot", v ? `xG ${v}` : ""],
      yellow: () => ["Booked", "yellow card"], red: () => ["Sent off", "red card"], on: () => ["On", "off the bench"], off: () => ["Off", "substituted"],
      distance: (v) => [v, "covered"], sprints: (v) => [v, "sprints"], passes: (v) => [v, "passes"],
      progressive_passes: (v) => [v, "progressive passes"], duels_won: (v) => [v, "duels won"], defensive_actions: (v) => [v, "defensive actions"],
    },
    es: {
      goal: () => ["Gol", ""], assist: () => ["Asistencia", ""], shot: (v) => ["Tiro", v ? `xG ${v}` : ""],
      yellow: () => ["Amarilla", "amonestado"], red: () => ["Expulsado", "tarjeta roja"], on: () => ["Entra", "desde el banquillo"], off: () => ["Sale", "sustituido"],
      distance: (v) => [v, "recorridos"], sprints: (v) => [v, "sprints"], passes: (v) => [v, "pases"],
      progressive_passes: (v) => [v, "pases progresivos"], duels_won: (v) => [v, "duelos ganados"], defensive_actions: (v) => [v, "acciones defensivas"],
    },
  };

  // ---------- colour: keep the two sides apart ----------
  function hexToRgb(h) {
    const v = (h || "#888888").replace("#", "");
    return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
  }
  function distance(a, b) {
    const [x, y] = [hexToRgb(a), hexToRgb(b)];
    return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
  }
  function luminance(h) {
    const [r, g, b] = hexToRgb(h).map((c) => c / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function teamColours(home, away) {
    let h = home.colours.primary || "#b3202a";
    let a = away.colours.primary || "#1f4e9c";
    if (distance(h, a) < 60) {
      const alt = away.colours.secondary;
      if (alt && distance(h, alt) >= 90 && luminance(alt) < 0.85) a = alt;
      else a = luminance(h) > 0.5 ? "#2a2a72" : "#e8e8e8";
    }
    // a near-white side still needs to read on the white card body
    return [h, a];
  }

  // ---------- icons ----------
  const ICONS = {
    goal: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="8.5" fill="#fff" stroke="#37003c" stroke-width="1.5"/><path d="M10 5.6l3.6 2.6-1.4 4.2H7.8L6.4 8.2z" fill="#37003c"/></svg>',
    red_card: '<svg viewBox="0 0 20 20"><rect x="5.5" y="2.5" width="9" height="15" rx="1.2" fill="#e90052" stroke="#fff" stroke-width="1"/></svg>',
    substitution: '<svg viewBox="0 0 20 20"><path d="M6 15V5M6 5l-3 3M6 5l3 3" stroke="#00ff85" stroke-width="2" fill="none" stroke-linecap="round"/><path d="M14 5v10M14 15l-3-3M14 15l3-3" stroke="#e90052" stroke-width="2" fill="none" stroke-linecap="round"/></svg>',
    half_time: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 2.5v15" stroke="currentColor" stroke-width="2"/></svg>',
    shift: '<svg viewBox="0 0 20 20"><path d="M2 14l5-5 4 3 7-7" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M13 5h5v5" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    recovery: '<svg viewBox="0 0 20 20"><path d="M4 10a6 6 0 1 0 2-4.5" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round"/><path d="M3 3v4h4" stroke="currentColor" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  // ---------- loading ----------
  async function loadIndex() {
    const index = await (await fetch("data/index.json")).json();
    const sel = $("matchSelect");
    sel.innerHTML = index
      .map((m) => `<option value="${m.match_id}">${m.home} ${m.score[0]}-${m.score[1]} ${m.away}</option>`)
      .join("");
    const want = params.get("match");
    if (want && index.some((m) => m.match_id === want)) sel.value = want;
    sel.addEventListener("change", () => loadMatch(sel.value));
    await loadMatch(sel.value);
    if (params.get("autoplay") === "1") setPlaying(true);
  }

  async function loadMatch(id) {
    bundle = await (await fetch(`data/${id}.json`)).json();
    const [home, away] = bundle.teams;
    const [hc, ac] = teamColours(home, away);
    const root = document.documentElement.style;
    root.setProperty("--home", hc);
    root.setProperty("--away", ac);
    $("sbHomeCode").textContent = home.code;
    $("sbAwayCode").textContent = away.code;
    $("moHome").textContent = home.code;
    $("moAway").textContent = away.code;
    club = home.team_id;
    player = null;
    if (follow && !(bundle.follow && bundle.follow[follow])) follow = null;
    drawFan();
    drawPrefs();
    drawTimeline();
    restart();
  }

  function restart() {
    t = 0;
    nextCard = 0;
    nextMoment = 0;
    hideCard(true);
    hideRecap();
    hideTag();
    drawFollow();
    render();
    renderPanel();
  }

  // ---------- timeline ----------
  const xOf = (m) => `${(100 * m) / bundle.minutes}%`;

  function drawTimeline() {
    const n = bundle.minutes;
    const svg = $("tlChart");
    svg.setAttribute("viewBox", `0 0 ${n} 100`);
    // momentum history as a mirrored area: home above the line, away below
    const pts = bundle.momentum.map((v, m) => [m + 0.5, 50 - (v - 50)]);
    const above = pts.map(([x, y]) => `${x},${Math.min(y, 50)}`).join(" ");
    const below = pts.map(([x, y]) => `${x},${Math.max(y, 50)}`).join(" ");
    svg.innerHTML = `
      <defs><clipPath id="played"><rect id="playedRect" x="0" y="0" width="0" height="100"/></clipPath></defs>
      <g clip-path="url(#played)">
        <polygon class="tl-area-home" points="0.5,50 ${above} ${n - 0.5},50"/>
        <polygon class="tl-area-away" points="0.5,50 ${below} ${n - 0.5},50"/>
      </g>
      <line class="tl-zero" x1="0" x2="${n}" y1="50" y2="50" vector-effect="non-scaling-stroke"/>`;
    $("tlHt").style.left = xOf(bundle.half_time_m);
    // ticks sit on the broadcast clock, so the second half starts at the real restart
    const tickM = (c) => (c < 45 ? c : bundle.half_time_m + (c - 45));
    $("tlTicks").innerHTML = [0, 15, 30, 45, 60, 75, 90]
      .map((c) => `<span style="left:${xOf(tickM(c))}">${c}'</span>`)
      .join("");
    const [home] = bundle.teams;
    $("tlEvents").innerHTML = bundle.timeline
      .filter((e) => e.kind !== "half_time")
      .map((e) => {
        const side = e.team === home.team_id ? "home" : "away";
        const who = e.kind === "substitution" ? `${e.player} for ${e.player_off}` : e.player;
        return `<div class="tl-ev ${side}" data-m="${e.m}" style="left:${xOf(e.m + 0.5)}" title="${e.clock} ${who}">${ICONS[e.kind]}</div>`;
      })
      .join("");
    drawMoments();
    $("tlTrack").onclick = (ev) => {
      const r = ev.currentTarget.getBoundingClientRect();
      seek(((ev.clientX - r.left) / r.width) * bundle.minutes);
    };
  }

  function seek(m) {
    t = Math.max(0, Math.min(bundle.minutes, m));
    nextCard = bundle.cards.findIndex((c) => c.at > t);
    if (nextCard < 0) nextCard = bundle.cards.length;
    seekMoments();
    hideCard(true);
    hideTag();
    if (t < bundle.minutes) hideRecap();
    render();
  }

  // ---------- per-frame rendering ----------
  function momentumAt(m) {
    const s = bundle.momentum;
    const i = Math.max(0, Math.min(s.length - 1, Math.floor(m)));
    const j = Math.min(s.length - 1, i + 1);
    const f = Math.max(0, Math.min(1, m - i));
    return s[i] + (s[j] - s[i]) * f;
  }

  function clockAt(m) {
    const i = Math.max(0, Math.min(bundle.clock.length - 1, Math.floor(m)));
    const label = bundle.clock[i].replace("'", "");
    const secs = String(Math.floor((m - Math.floor(m)) * 60)).padStart(2, "0");
    const [base, extra] = label.split("+");
    if (extra) return `${base}:00 +${extra}`;
    return `${Number(base) - 1}:${secs}`;
  }

  function scoreAt(m) {
    const [home] = bundle.teams;
    let h = 0;
    let a = 0;
    for (const e of bundle.timeline) {
      if (e.kind === "goal" && e.m + 0.5 <= m) e.team === home.team_id ? h++ : a++;
    }
    return [h, a];
  }

  function setText(el, v) {
    if (el.textContent !== String(v)) {
      el.textContent = v;
      return true;
    }
    return false;
  }

  function render() {
    if (!bundle) return;
    $("sbClock").textContent = t >= bundle.minutes ? "FT" : clockAt(t);
    const [h, a] = scoreAt(t);
    const hEl = $("sbHomeGoals");
    const aEl = $("sbAwayGoals");
    if (setText(hEl, h) && t > 0) bump(hEl);
    if (setText(aEl, a) && t > 0) bump(aEl);

    $("moTrack").style.setProperty("--m", `${momentumAt(t)}%`);

    const p = (100 * t) / bundle.minutes;
    $("tlProgress").style.width = `${p}%`;
    $("tlHead").style.left = `${p}%`;
    const rect = document.getElementById("playedRect");
    if (rect) rect.setAttribute("width", String(t));
    for (const el of document.querySelectorAll(".tl-ev")) {
      const done = Number(el.dataset.m) + 0.5 <= t;
      el.classList.toggle("done", done);
      el.classList.toggle("fresh", done && t - Number(el.dataset.m) < 1.5);
    }
    const minute = Math.min(bundle.minutes - 1, Math.floor(t));
    if (minute !== panelMinute) {
      if (tab !== "agents") renderPanel();
      else panelMinute = minute;
      drawFollow();
    }
  }

  function bump(el) {
    el.classList.remove("bump");
    void el.offsetWidth;
    el.classList.add("bump");
  }

  // ---------- cards ----------
  function teamById(id) {
    return bundle.teams.find((x) => x.team_id === id);
  }

  // "Progressive passes" -> "progressive passes", but "xG" stays as it is
  const lower = (label) => (/^[A-Z][a-z]/.test(label) ? label[0].toLowerCase() + label.slice(1) : label);

  // A count before the anchor is a rate scaled to the window (6.9 in 6 minutes): shown against a
  // whole number now, it reads as a whole number too, unless it is under 1
  function before(s) {
    const n = Number(s.usual);
    if (!/^\d+$/.test(s.value) || !Number.isFinite(n) || n < 1) return s.usual;
    return String(Math.round(n));
  }

  // One line to read, then one number to the next: "Brackenford's progressive passes  2 -> 5".
  // The colour chip says whose stat it is; the faded number is before, the solid one is now, so
  // the numbers show the direction on their own. A substitute is against the player he replaced.
  function statRow(s) {
    const team = teamById(s.team);
    const side = team === bundle.teams[0] ? "var(--home)" : "var(--away)";
    const vs = s.usual_label && s.usual_label !== "before" ? ` vs ${s.usual_label.replace(/ \(off\)$/, "")}` : "";
    const title = w("stat_of", s.player || team.short_name, L(s.label)) + vs;
    const mine = followed() && s.player && s.player === followed().name ? " mine" : "";
    return `
      <div class="stat${mine}">
        <span class="stat-strip" style="background:${side}"></span>
        <span class="stat-label">${esc(title)}</span>
        <span class="stat-nums" aria-label="${esc(`${s.usual} to ${s.value}`)}">
          <span class="stat-old">${before(s)}</span>
          ${ARROW}
          <span class="stat-value">${s.value}</span>
        </span>
      </div>`;
  }
  const ARROW =
    '<svg class="stat-to" viewBox="0 0 26 12" aria-hidden="true"><path d="M1 6h21M17 1.5 23 6l-6 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // the Spanish version of a card's part when the pipeline wrote one, else the English
  function es(c) {
    return lang === "es" && c.i18n && c.i18n.es ? c.i18n.es : null;
  }

  function cardText(c) {
    const text = (es(c) && es(c).text) || c.text || {};
    return text[fan] ?? text.neutral ?? (c.text || {})[fan] ?? (c.text || {}).neutral ?? "";
  }

  function cardAnchor(c) {
    return (es(c) && es(c).anchor) || c.anchor;
  }

  // The analyst's card: what the agents settled on, and both clubs before the anchor against since
  function detailHtml(c) {
    const d = c.detail;
    if (!d) return "";
    const [home, away] = bundle.teams;
    const cell = (pair) => `<span class="dt-old">${pair[0]}</span>${ARROW}<b>${pair[1]}</b>`;
    const rows = d.rows
      .map(
        (r) => `<tr><td>${esc(L(r.label))}${r.unit ? ` <span class="u">${r.unit}</span>` : ""}</td>
          <td>${cell(r.values[home.team_id])}</td><td>${cell(r.values[away.team_id])}</td></tr>`,
      )
      .join("");
    const mo = c.momentum;
    return `
      <div class="detail">
        <div class="dt-meta">
          <span class="dt-chip">${esc(causeName(d.cause))}</span>
          ${d.confidence != null ? `<span>${Math.round(100 * d.confidence)}% ${w("confidence")}</span>` : ""}
          <span>${w("momentum")} ${home.code} <span class="dt-old">${Math.round(mo.before)}%</span>${ARROW}<b>${Math.round(mo.now)}%</b></span>
        </div>
        <table class="dt"><thead><tr><th>${w("before")} ${ARROW} ${w("since")} · ${d.minutes}'</th>
          <th>${dot(home.team_id)}${home.code}</th><th>${dot(away.team_id)}${away.code}</th></tr></thead><tbody>${rows}</tbody></table>
      </div>`;
  }

  function showCard(c) {
    const el = $("card");
    el.className = `card kind-${c.kind} view-${view}`;
    const stats = view === "analyst" ? c.stats : c.stats.slice(0, 1);
    el.innerHTML = `
      <div class="card-head">
        <div class="card-anchor">${esc(cardAnchor(c))}</div>
      </div>
      <div class="card-text" id="cardText">${esc(cardText(c))}</div>
      <div class="card-body">${stats.map(statRow).join("")}</div>${view === "analyst" ? detailHtml(c) : ""}`;
    el.hidden = false;
    void el.offsetWidth;
    el.classList.add("on");
    phase = "stats";
    cardUntil = performance.now() + (view === "analyst" ? CARD_SECONDS + 4 : CARD_SECONDS) * 1000;
    hoodCard = c;
    if (tab === "agents") renderPanel();
  }

  // ---------- MatchLens analysis: what a club could do about it, after the card ----------
  function analysisFor(c) {
    const a = c && c.analysis;
    return a ? (a[fan] ?? a.neutral ?? null) : null;
  }

  function analysisLine(c, a) {
    const x = es(c) && es(c).analysis;
    const lens = c.analysis[fan] ? fan : "neutral";
    return (x && x[lens]) || a.line;
  }

  function showAnalysis(c) {
    const el = $("card");
    phase = "analysis";
    cardUntil = performance.now() + 450 + ANALYSIS_SECONDS * 1000;
    el.classList.remove("on");
    el.classList.add("off");
    setTimeout(() => {
      if (phase === "analysis" && cardUntil) drawAnalysis(c);
    }, 450);
  }

  function drawAnalysis(c) {
    const a = analysisFor(c);
    if (!a) return;
    const el = $("card");
    const team = teamById(a.team);
    const side = team === bundle.teams[0] ? "var(--home)" : "var(--away)";
    const ask = a.mode === "fix" ? w("win_back", team.short_name) : w("keep_going", team.short_name);
    el.className = `card analysis view-${view}`;
    el.innerHTML = `
      <div class="card-head">
        <div class="card-anchor"><span class="an-chip" style="background:${side}"></span>${esc(ask)}<span class="an-mark">${w("analysis")}</span></div>
      </div>
      <div class="card-text" id="cardText">${esc(analysisLine(c, a))}</div>
      <div class="card-body">${statRow(a.stat)}</div>`;
    el.hidden = false;
    void el.offsetWidth;
    el.classList.add("on");
  }

  // ---------- the full-time recap ----------
  const sideOf = (id) => (id === bundle.teams[0].team_id ? "var(--home)" : "var(--away)");

  const u = (unit) => (unit === "%" ? "%" : unit ? `<small>${unit}</small>` : "");

  function pairBar(label, a, b, unit) {
    const x = Number(a) || 0;
    const y = Number(b) || 0;
    const share = x + y ? (100 * x) / (x + y) : 50;
    const num = (v) => (Number.isInteger(v) ? v : Number(v).toFixed(v < 10 ? 2 : 1).replace(/\.?0+$/, ""));
    return `<div class="pb">
        <div class="pb-row"><b>${num(x)}${u(unit)}</b><span>${esc(label)}</span><b>${num(y)}${u(unit)}</b></div>
        <div class="pb-bar"><span style="width:${share}%;background:var(--home)"></span><span style="width:${100 - share}%;background:var(--away)"></span></div>
      </div>`;
  }

  function spark(values, upto, cls = "") {
    const max = Math.max(1, ...values);
    return `<div class="spark ${cls}">${values
      .map((v, i) => `<span class="${i < upto ? "" : "future"}" style="height:${Math.max(4, (100 * v) / max)}%"></span>`)
      .join("")}</div>`;
  }

  function recapHtml() {
    const r = bundle.recap;
    const [home, away] = bundle.teams;
    const [hg, ag] = bundle.score[bundle.score.length - 1];
    const text = (lang === "es" && r.i18n && r.i18n.es.text) || r.text;
    const headline = text[fan] ?? text.neutral;
    const spells = r.spells
      .map(
        (s) => `<div class="sp"><div class="sp-col"><span style="height:${s.home}%;background:var(--home)"></span><span style="height:${100 - s.home}%;background:var(--away)"></span></div><span class="sp-l">${s.label}</span></div>`,
      )
      .join("");
    const turns = r.turning_points
      .map(
        (tp) => `<li><span class="tp-clock">${esc(tp.clock)}</span><span class="an-chip" style="background:${sideOf(tp.team)}"></span>
          <span>${esc(tp.label[lang] || tp.label.en)}</span>${view === "analyst" ? `<span class="tp-mo">${tp.before}%${ARROW}${tp.now}%</span>` : ""}</li>`,
      )
      .join("");
    const p = followed();
    const keep = p ? ["possession", "shots"] : view === "analyst" ? r.stats.map((s) => s.key) : ["possession", "shots", "shots_on_target"];
    const stats = r.stats
      .filter((s) => keep.includes(s.key))
      .map((s) => pairBar(L(s.label), s.values[0], s.values[1], s.unit))
      .join("");
    const halves =
      view === "analyst"
        ? `<div class="rc-sec">${w("halves")}</div><table class="dt rc-halves"><thead><tr><th></th><th>${dot(home.team_id)}${home.code}</th><th>${dot(away.team_id)}${away.code}</th></tr></thead><tbody>${r.halves
            .slice(0, p ? 3 : 5)
            .map(
              (h) => `<tr><td>${esc(L(h.label))}</td><td>${h.values[home.team_id][0]}${h.unit === "%" ? "%" : ""} · <b>${h.values[home.team_id][1]}${h.unit === "%" ? "%" : ""}</b></td>
                <td>${h.values[away.team_id][0]}${h.unit === "%" ? "%" : ""} · <b>${h.values[away.team_id][1]}${h.unit === "%" ? "%" : ""}</b></td></tr>`,
            )
            .join("")}</tbody></table>`
        : "";
    const right = p ? followRecap(p) : standoutsHtml(r);
    return `
      <div class="rc-head">
        <span class="rc-ft">${w("full_time")}</span>
        <span class="rc-score"><span class="an-chip" style="background:var(--home)"></span>${home.short_name} <b>${hg}-${ag}</b> ${away.short_name}<span class="an-chip" style="background:var(--away)"></span></span>
      </div>
      <div class="rc-line">${esc(headline)}</div>
      <div class="rc-grid">
        <div>
          <div class="rc-sec">${w("who_had_it")}</div>
          <div class="spells">${spells}</div>
          <div class="rc-sec">${w("turning")}</div>
          <ul class="turns">${turns}</ul>${halves}
        </div>
        <div>${stats}${right}</div>
      </div>`;
  }

  function standoutsHtml(r) {
    const rows = bundle.teams
      .map((tm) => {
        const s = r.stars[tm.team_id];
        if (!s) return "";
        return `<div class="star"><span class="an-chip" style="background:${sideOf(tm.team_id)}"></span><b>${esc(s.name)}</b>
          <span class="star-v">${fmt(s.value, s.unit)}</span><span class="star-l">${esc(L(s.label))}</span></div>`;
      })
      .join("");
    return `<div class="rc-sec">${w("standouts")}</div>${rows}`;
  }

  function showRecap() {
    if (!bundle.recap || recapOn) return;
    recapOn = true;
    if (tab === "agents") setTimeout(renderPanel, 0);
    hideTag();
    const el = $("recap");
    el.innerHTML = recapHtml();
    el.hidden = false;
    $("follow").hidden = true;
    void el.offsetWidth;
    el.classList.add("on");
  }

  function hideRecap() {
    recapOn = false;
    const el = $("recap");
    el.hidden = true;
    el.classList.remove("on");
    drawFollow();
  }

  function redrawRecap() {
    if (recapOn) $("recap").innerHTML = recapHtml();
  }

  // ---------- follow a player ----------
  function followed() {
    if (!follow || !bundle || !bundle.stats) return null;
    return bundle.stats.players.find((x) => x.id === follow) || null;
  }

  const FOLLOW_STATS = {
    casual: ["touches", "passes", "distance"],
    analyst: ["touches", "pass_accuracy", "progressive_passes", "duels_won", "distance", "sprints"],
  };

  function drawFollow() {
    const el = $("follow");
    const p = followed();
    if (!p || !bundle.follow || recapOn) {
      el.hidden = true;
      return;
    }
    const m = Math.min(bundle.minutes - 1, Math.floor(t));
    const defs = Object.fromEntries(bundle.stats.player_stats.map((d) => [d.key, d]));
    const on = p.from <= m;
    const nums = FOLLOW_STATS[view]
      .map((k) => `<div class="fs"><b>${on ? fmt(p.stats[k][m], defs[k].unit) : "-"}</b><span>${esc(L(defs[k].label))}</span></div>`)
      .join("");
    const inv = bundle.follow[p.id].involvement;
    el.innerHTML = `
      <div class="fw-name"><span class="an-chip" style="background:${sideOf(p.team)}"></span><span>${esc(p.name)}</span><span class="fw-role">${p.role}</span></div>
      <div class="fw-nums">${nums}</div>
      ${spark(inv, Math.ceil((m + 1) / 5))}`;
    el.hidden = false;
  }

  function seekMoments() {
    const list = follow && bundle.follow && bundle.follow[follow] ? bundle.follow[follow].moments : [];
    nextMoment = list.findIndex((x) => x.m + 0.5 > t);
    if (nextMoment < 0) nextMoment = list.length;
  }

  function drawMoments() {
    const box = $("tlMe");
    const list = follow && bundle.follow && bundle.follow[follow] ? bundle.follow[follow].moments : [];
    box.innerHTML = list.map((x) => `<span class="tl-me ${x.kind}" style="left:${xOf(x.m + 0.5)}"></span>`).join("");
  }

  function showTag(x) {
    const [big, small] = (TAGS[lang][x.kind] || (() => [x.value || x.kind, ""]))(x.value);
    const el = $("tag");
    el.className = `tag kind-${x.kind}`;
    el.innerHTML = `<b>${esc(big)}</b>${small ? `<span>${esc(small)}</span>` : ""}`;
    el.hidden = false;
    void el.offsetWidth;
    el.classList.add("on");
    tagUntil = performance.now() + 4200;
  }

  function hideTag() {
    tagUntil = 0;
    const el = $("tag");
    el.hidden = true;
    el.classList.remove("on");
  }

  function followRecap(p) {
    const f = bundle.follow[p.id];
    const defs = Object.fromEntries(bundle.stats.player_stats.map((d) => [d.key, d]));
    const club = teamById(p.team).short_name;
    const badges = f.ranks
      .slice(0, 3)
      .map(
        (r) => `<div class="badge"><b>#${r.rank}</b><span>${esc(L(defs[r.key].label))} ${w("rank_at", club)}</span><em>${fmt(r.value, defs[r.key].unit)}</em></div>`,
      )
      .join("");
    return `<div class="rc-sec"><span class="an-chip" style="background:${sideOf(p.team)}"></span> ${esc(p.name)}</div>
      ${badges}<div class="rc-sub">${w("involvement")}</div>${spark(f.involvement, f.involvement.length, "wide")}`;
  }

  function setFollow(id) {
    follow = id;
    seekMoments();
    hideTag();
    drawFollow();
    drawMoments();
    renderPanel();
    redrawRecap();
  }

  // ---------- under the hood ----------
  const AGENT_NAMES = {
    team_play: "Team play",
    players: "Players",
    substitutions: "Substitutions",
    match_events: "Match events",
  };
  const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

  function hoodHtml() {
    if (recapOn) return recapHood();
    const h = hoodCard && hoodCard.hood;
    if (!h) {
      return `<p class="hood-empty">${
        hoodCard ? "This match was explained without the agents." : "What the agents found for each card shows here when it comes up."
      }</p>${translatorHtml()}`;
    }
    const runner = h.runner === "foundry" ? "Microsoft Foundry" : "Offline rules";
    const rows = h.specialists
      .map((s) => {
        const state = s.status === "failed" ? "failed" : s.verdict === "not_me" ? "not me" : "relevant";
        return `<li class="hood-row st-${state.replace(" ", "-")}">
          <span class="hood-agent">${esc(AGENT_NAMES[s.agent] || s.agent)}</span>
          <span class="hood-chip">${state}</span>
          <span class="hood-note">${esc(s.note)}</span></li>`;
      })
      .join("");
    const rounds = h.verifier || [];
    const rejected = rounds.filter((r) => r.status === "rejected").length;
    const verdict = h.fallback
      ? "Fell back to the rules"
      : rejected
        ? `Passed after ${rejected} rejection${rejected > 1 ? "s" : ""}`
        : "Passed first time";
    return `
      <div class="hood-head"><span>${esc(hoodCard.clock)} · ${esc(hoodCard.tag)}</span><span>${runner}</span></div>
      <ul class="hood-list">${rows}</ul>
      <div class="hood-step"><span class="hood-agent">Explainer</span>
        <span class="hood-why">${esc(h.fallback ? "No verified draft; the deterministic rules chose." : h.why)}</span></div>
      <div class="hood-step"><span class="hood-agent">Verifier</span>
        <span class="hood-chip ${h.fallback ? "st-failed" : "st-relevant"}">${verdict}</span>
        <span class="hood-note">${h.board} findings on the board · confidence ${Math.round(100 * h.confidence)}%</span></div>${interpreterHtml(h.interpreter)}${analystHtml(h.analyst)}${translatorHtml(hoodCard)}`;
  }

  // the full-time recap's agents: the Recapper's headline and the Translator
  function recapHood() {
    const a = bundle.recap.agents;
    let rows;
    if (!a) rows = `<p class="hood-empty">The recap headline came from the rules; the Recapper agent hasn't run on this match.</p>`;
    else {
      const rejected = a.rounds.filter((r) => r.status === "rejected").length;
      const verdict = a.fallback ? "Fell back to the rules" : rejected ? "Passed after a rewrite" : "Passed first time";
      rows = `<div class="hood-step"><span class="hood-agent">Recapper</span>
        <span class="hood-chip ${a.fallback ? "st-failed" : "st-relevant"}">${verdict}</span>
        <span class="hood-note">Wrote the full-time headline for each lens from the result and the momentum, checked against them</span></div>`;
    }
    return `<div class="hood-head"><span>Full time · recap</span><span>${a && a.runner === "foundry" ? "Microsoft Foundry" : "Offline rules"}</span></div>
      <p class="hood-note">The graphics (spells, turning points, stats, standouts) are counted by code from the match tables.</p>${rows}${translatorHtml()}`;
  }

  // how the Spanish lines were made: translated and checked, or the rules' Spanish
  function translatorHtml(c) {
    const tr = bundle.translator;
    if (!tr) return "";
    const by = { azure: "Azure AI Translator", foundry: "Translator agent on Foundry", offline: "Rules (offline)" }[tr.backend] || tr.backend;
    const src = tr.sources || {};
    const done = (src.azure || 0) + (src.foundry || 0);
    const note = done
      ? `${done} of ${tr.lines} lines translated and checked (names and numbers kept); ${src.rules || 0} fell back to the rules' Spanish`
      : `Spanish lines from the rules for ${src.rules || 0} of ${tr.lines} lines`;
    const mine = c && c.i18n && c.i18n.es && c.i18n.es.sources ? Object.values(c.i18n.es.sources) : [];
    const chip = mine.length && mine.every((x) => x === "azure" || x === "foundry") ? "st-relevant" : "";
    return `<div class="hood-step"><span class="hood-agent">Translator</span>
        <span class="hood-chip ${chip}">${esc(by)}</span>
        <span class="hood-note">${esc(note)}</span></div>`;
  }

  function interpreterHtml(it) {
    if (!it) return "";
    const rejected = it.rounds.filter((r) => r.status === "rejected").length;
    const verdict = it.fallback ? "Fell back to the rules" : rejected ? "Passed after a rewrite" : "Passed first time";
    return `<div class="hood-step"><span class="hood-agent">Interpreter</span>
        <span class="hood-chip ${it.fallback ? "st-failed" : "st-relevant"}">${verdict}</span>
        <span class="hood-note">Wrote the line on the card for each lens, checked against the facts</span></div>`;
  }

  function analystHtml(it) {
    if (!it) return "";
    const rejected = it.rounds.filter((r) => r.status === "rejected").length;
    const verdict = it.fallback ? "Fell back to the rules" : rejected ? "Passed after a rewrite" : "Passed first time";
    return `<div class="hood-step"><span class="hood-agent">Analyst</span>
        <span class="hood-chip ${it.fallback ? "st-failed" : "st-relevant"}">${verdict}</span>
        <span class="hood-note">Picked what each club could do from the options the stats back, checked against them</span></div>`;
  }

  // ---------- the stats panel ----------
  const dot = (id) => `<span class="chip-dot" style="background:${id === bundle.teams[0].team_id ? "var(--home)" : "var(--away)"}"></span>`;

  function fmt(v, unit) {
    const n = Number.isInteger(v) ? v : v.toFixed(v < 10 ? 2 : 1).replace(/\.?0+$/, "");
    return unit ? `${n}<span class="u">${unit}</span>` : `${n}`;
  }

  // the casual view's clubs tab: a few stats as two-sided bars
  const CASUAL_STATS = ["possession", "shots", "shots_on_target", "box_entries", "corners", "distance"];

  function clubsHtml(m) {
    const st = bundle.stats;
    const [home, away] = bundle.teams;
    const head = (tm) => `<th><button type="button" data-club="${tm.team_id}">${dot(tm.team_id)}${tm.code}</button></th>`;
    if (view === "casual") {
      const bars = st.team_stats
        .filter((d) => CASUAL_STATS.includes(d.key))
        .map((d) => pairBar(L(d.label), st.teams[home.team_id][d.key][m], st.teams[away.team_id][d.key][m], d.unit))
        .join("");
      return `<div class="pb-head">${head(home).replace(/<\/?th>/g, "")}<span>${w("at")} ${bundle.clock[m]}</span>${head(away).replace(/<\/?th>/g, "")}</div>
        ${bars}<p class="note">${w("tap_club")}</p>`;
    }
    const l15 = st.last15;
    const rows = st.team_stats
      .map((d) => {
        const a = st.teams[home.team_id][d.key][m];
        const b = st.teams[away.team_id][d.key][m];
        const lead = (x, y) => (x > y && d.key !== "fouls" && d.key !== "yellow_cards" && d.key !== "offsides" ? "lead" : "");
        const recent = l15
          ? `<td class="l15">${fmt(l15[home.team_id][d.key][m], d.unit)}</td><td class="l15">${fmt(l15[away.team_id][d.key][m], d.unit)}</td>`
          : "";
        return `<tr><td>${esc(L(d.label))}${d.modelled ? '<span class="mod">*</span>' : ""}</td>
          <td class="${lead(a, b)}">${fmt(a, d.unit)}</td><td class="${lead(b, a)}">${fmt(b, d.unit)}</td>${recent}</tr>`;
      })
      .join("");
    const recentHead = l15 ? `<th class="l15" colspan="2">${w("last15")}</th>` : "";
    return `<table class="ct"><thead><tr><th>${w("at")} ${bundle.clock[m]}</th>${head(home)}${head(away)}${recentHead}</tr></thead><tbody>${rows}</tbody></table>
      <p class="note">${w("modelled")} ${w("tap_club")}</p>`;
  }

  function playersHtml(m) {
    const st = bundle.stats;
    const switcher = `<div class="club-switch">${bundle.teams
      .map((tm) => `<button type="button" data-club="${tm.team_id}" class="${tm.team_id === club ? "on" : ""}">${dot(tm.team_id)}${tm.short_name}</button>`)
      .join("")}</div>`;
    const p = player && st.players.find((x) => x.id === player);
    if (p) {
      const tm = teamById(p.team);
      const on = p.from <= m;
      const grid = st.player_stats
        .map((d) => `<div><span>${esc(L(d.label))}${d.modelled ? '<span class="mod">*</span>' : ""}</span><b>${fmt(p.stats[d.key][m], d.unit)}</b></div>`)
        .join("");
      const isOn = follow === p.id;
      const followBtn = bundle.follow
        ? `<button type="button" class="follow-btn ${isOn ? "on" : ""}" data-follow="${isOn ? "" : p.id}">${isOn ? w("unfollow") : w("follow")}</button>`
        : "";
      return `${switcher}<div class="pd-head"><button type="button" data-back="1">${w("back")}</button>
        <div><div class="pd-name">${esc(p.name)}</div><div class="pd-sub">${dot(p.team)} ${tm.short_name} · ${p.role}${p.from > 0 ? ` · ${w("on")} ${bundle.clock[p.from]}` : ""} · ${w("at")} ${bundle.clock[m]}</div></div>${followBtn}</div>
        ${on ? `<div class="pd-grid">${grid}</div>` : `<p class="hood-empty">${w("not_on")}</p>`}
        <p class="note">${w("modelled")}</p>`;
    }
    const list = st.players
      .filter((x) => x.team === club)
      .map((x) => {
        const on = x.from <= m;
        const meta = !on ? w("sub") : x.from > 0 ? `${w("on")} ${bundle.clock[x.from]}` : `${fmt(x.stats.passes[m])} ${w("passes")}`;
        const star = x.id === follow ? '<span class="pl-f" aria-label="followed"></span>' : "";
        return `<li class="${on ? "" : "off"}"><button type="button" data-player="${x.id}">
          <span class="role">${x.role}</span><span>${star}${esc(x.name)}</span><span class="meta">${meta}</span></button></li>`;
      })
      .join("");
    return `${switcher}<ul class="pl">${list}</ul>`;
  }

  function renderPanel() {
    if (!bundle) return;
    const m = Math.min(bundle.minutes - 1, Math.floor(t));
    panelMinute = m;
    for (const b of document.querySelectorAll(".tabs button")) {
      b.classList.toggle("on", b.dataset.tab === tab);
      b.textContent = w(b.dataset.tab);
    }
    const body = $("panelBody");
    if (tab === "agents") body.innerHTML = hoodHtml();
    else if (!bundle.stats) body.innerHTML = `<p class="hood-empty">${w("no_bundle_stats")}</p>`;
    else body.innerHTML = tab === "clubs" ? clubsHtml(m) : playersHtml(m);
  }

  function setTab(name) {
    tab = name;
    renderPanel();
  }

  $("panel").addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.dataset.tab) setTab(b.dataset.tab);
    else if (b.dataset.fan) setFan(b.dataset.fan);
    else if (b.dataset.view) setView(b.dataset.view);
    else if (b.dataset.lang) setLang(b.dataset.lang);
    else if (b.dataset.follow !== undefined) setFollow(b.dataset.follow || null);
    else if (b.dataset.club) {
      club = b.dataset.club;
      player = null;
      setTab("players");
    } else if (b.dataset.player) {
      player = b.dataset.player;
      renderPanel();
    } else if (b.dataset.back) {
      player = null;
      renderPanel();
    }
  });

  // ---------- favourite club ----------
  function drawFan() {
    const ids = bundle.teams.map((x) => x.team_id);
    if (fan !== "neutral" && !ids.includes(fan)) fan = "neutral";
    const opt = (id, label) => `<button type="button" data-fan="${id}" class="${id === fan ? "on" : ""}">${label}</button>`;
    $("fanOpts").innerHTML = opt("neutral", w("neutral")) + bundle.teams.map((x) => opt(x.team_id, `${dot(x.team_id)}${x.code}`)).join("");
    $("fanLabel").textContent = w("your_club");
  }

  // casual or analyst, English or Spanish
  function drawPrefs() {
    const opt = (k, v, label, on) => `<button type="button" data-${k}="${v}" class="${on ? "on" : ""}">${label}</button>`;
    $("viewOpts").innerHTML = opt("view", "casual", w("casual"), view === "casual") + opt("view", "analyst", w("analyst"), view === "analyst");
    $("langOpts").innerHTML = opt("lang", "en", "EN", lang === "en") + opt("lang", "es", "ES", lang === "es");
    $("playBtn").textContent = playing ? w("pause") : w("play");
    $("moLabel").textContent = w("momentum");
    document.documentElement.lang = lang;
    $("stage").classList.toggle("analyst", view === "analyst");
  }

  // a change of club, view or language redraws whatever is up
  function redraw() {
    drawFan();
    drawPrefs();
    if (phase === "analysis" && hoodCard) drawAnalysis(hoodCard);
    else if (phase === "stats" && hoodCard) {
      const until = cardUntil;
      showCard(hoodCard);
      cardUntil = until;
    }
    drawFollow();
    redrawRecap();
    renderPanel();
  }

  function setView(v) {
    view = v;
    store("matchlens.view", v);
    redraw();
  }

  function setLang(v) {
    lang = v;
    store("matchlens.lang", v);
    redraw();
  }

  function setFan(id) {
    fan = id;
    store("matchlens.fan", id);
    drawFan();
    if (phase === "analysis" && hoodCard) drawAnalysis(hoodCard);
    else if (phase === "stats" && hoodCard) $("cardText").textContent = cardText(hoodCard);
    redrawRecap();
  }

  function hideCard(now) {
    const el = $("card");
    cardUntil = 0;
    phase = null;
    if (now) {
      el.hidden = true;
      el.className = "card";
      return;
    }
    el.classList.remove("on");
    el.classList.add("off");
    setTimeout(() => {
      if (!cardUntil) {
        el.hidden = true;
        el.className = "card";
      }
    }, 450);
  }

  // ---------- clock ----------
  function frame(now) {
    const dt = last ? (now - last) / 1000 : 0;
    last = now;
    if (playing && bundle) {
      const showing = cardUntil > 0;
      const rate = (SPEEDS[speedIx] / SECONDS_PER_MINUTE) * (showing ? CARD_SLOWDOWN : 1);
      t = Math.min(bundle.minutes, t + dt * rate);
      if (showing && now >= cardUntil) {
        if (phase === "stats" && analysisFor(hoodCard)) showAnalysis(hoodCard);
        else hideCard(false);
      }
      if (!showing && nextCard < bundle.cards.length && t >= bundle.cards[nextCard].at) {
        showCard(bundle.cards[nextCard]);
        nextCard++;
      }
      moments(now);
      if (t >= bundle.minutes && !cardUntil) {
        setPlaying(false);
        showRecap();
      }
      render();
    }
    requestAnimationFrame(frame);
  }

  // follow mode: pop the next tag when the clock reaches it; one at a time
  function moments(now) {
    if (tagUntil && now >= tagUntil) hideTag();
    const list = follow && bundle.follow && bundle.follow[follow] ? bundle.follow[follow].moments : [];
    if (!tagUntil && nextMoment < list.length && t >= list[nextMoment].m + 0.5) {
      // tags that fell behind while another was up are skipped, so the tag on screen is current
      while (nextMoment + 1 < list.length && t >= list[nextMoment + 1].m + 0.5) nextMoment++;
      showTag(list[nextMoment]);
      nextMoment++;
    }
  }

  function setPlaying(on) {
    playing = on;
    if (on && bundle && t >= bundle.minutes) restart();
    $("playBtn").textContent = on ? w("pause") : w("play");
  }

  $("playBtn").addEventListener("click", () => setPlaying(!playing));
  $("speedBtn").textContent = `${SPEEDS[speedIx]}x`;
  $("speedBtn").addEventListener("click", () => {
    speedIx = (speedIx + 1) % SPEEDS.length;
    $("speedBtn").textContent = `${SPEEDS[speedIx]}x`;
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT") return;
    if (e.code === "Space") {
      e.preventDefault();
      setPlaying(!playing);
    } else if (e.key === "h" || e.key === "H") {
      $("controls").classList.toggle("hidden");
    } else if (e.key === "n" || e.key === "N") {
      const c = bundle && bundle.cards.find((x) => x.at > t + 0.1);
      if (c) seek(c.at - 0.05);
    } else if (e.key === "r" || e.key === "R") {
      restart();
    } else if (e.key === "u" || e.key === "U") {
      setTab(tab === "agents" ? "clubs" : "agents");
    } else if ((e.key === "f" || e.key === "F") && bundle) {
      seek(bundle.minutes);
      showRecap();
    } else if (e.key === "v" || e.key === "V") {
      setView(view === "casual" ? "analyst" : "casual");
    } else if (e.key === "l" || e.key === "L") {
      setLang(lang === "en" ? "es" : "en");
    }
  });
  if (params.get("hide") === "1") $("controls").classList.add("hidden");
  requestAnimationFrame(frame);
  loadIndex();
})();
