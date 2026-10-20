// MatchLens broadcast screen. Plays one match bundle (see matchlens/broadcast/bundle.py) on a
// condensed clock. The page does no analysis: everything it shows is in the bundle.
//
// URL options: ?match=<id>  &speed=1|2|4  &autoplay=1  &hide=1 (no operator controls, for capture)
// Keys: space play/pause, H hide controls, N jump to the next card, R restart.

(() => {
  "use strict";

  const SECONDS_PER_MINUTE = 1.6; // at 1x a 95-minute match plays in about 2.5 minutes
  const CARD_SECONDS = 9; // how long a card stays up
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
  let last = 0;

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
  // icons drawn on the coloured tag of a card, in the tag's own ink
  const TAG_ICONS = {
    red_card: '<svg viewBox="0 0 20 20"><rect x="5.5" y="2.5" width="9" height="15" rx="1.2" fill="currentColor"/></svg>',
    goal: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 5.8l3.4 2.5-1.3 4H7.9l-1.3-4z" fill="currentColor"/></svg>',
    substitution: '<svg viewBox="0 0 20 20"><path d="M6 15V5M6 5l-3 3M6 5l3 3M14 5v10M14 15l-3-3M14 15l3-3" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

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
    drawTimeline();
    restart();
  }

  function restart() {
    t = 0;
    nextCard = 0;
    hideCard(true);
    render();
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
    $("tlTrack").onclick = (ev) => {
      const r = ev.currentTarget.getBoundingClientRect();
      seek(((ev.clientX - r.left) / r.width) * bundle.minutes);
    };
  }

  function seek(m) {
    t = Math.max(0, Math.min(bundle.minutes, m));
    nextCard = bundle.cards.findIndex((c) => c.at > t);
    if (nextCard < 0) nextCard = bundle.cards.length;
    hideCard(true);
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

    const share = momentumAt(t);
    $("moFillHome").style.width = `${share}%`;
    $("moFillAway").style.width = `${100 - share}%`;
    $("moMarker").style.left = `${share}%`;

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

  function statRow(s) {
    const team = teamById(s.team);
    const side = team === bundle.teams[0] ? "var(--home)" : "var(--away)";
    const who = s.player ? s.player : team.short_name;
    const when = s.window ? ` · last ${s.window.replace("in ", "")}` : "";
    const unit = s.unit ? `<span class="stat-unit">${s.unit}</span>` : "";
    return `
      <div class="stat">
        <span class="stat-strip" style="background:${side}"></span>
        <span class="stat-code">${s.code}</span>
        <span class="stat-text">
          <div class="stat-label">${s.label}</div>
          <div class="stat-sub">${who}${when}</div>
        </span>
        <span class="stat-nums">
          <span class="stat-value">${s.value}${unit}</span>
          <span class="stat-usual">${s.usual_label}<b>${s.usual}</b></span>
        </span>
      </div>`;
  }

  function showCard(c) {
    const el = $("card");
    const [home, away] = bundle.teams;
    const tagIcon = TAG_ICONS[c.kind] || ICONS[c.kind] || ICONS.shift;
    el.className = `card kind-${c.kind}`;
    el.innerHTML = `
      <div class="card-head">
        <div class="card-tag">${tagIcon}<span>${c.tag}</span></div>
        <div class="card-anchor">${c.anchor}</div>
      </div>
      <div class="card-body">${c.stats.map(statRow).join("")}</div>
      <div class="card-foot">
        <span class="cf-label">Momentum</span>
        <div class="cf-bar">
          <div class="mo-fill mo-fill-home" style="width:${c.momentum.before}%"></div>
          <div class="mo-fill mo-fill-away" style="width:${100 - c.momentum.before}%"></div>
          <div class="cf-ghost" style="left:${c.momentum.before}%"></div>
          <div class="cf-now" style="left:${c.momentum.before}%"></div>
        </div>
        <span class="cf-codes">${home.code} · ${away.code}</span>
      </div>`;
    el.hidden = false;
    void el.offsetWidth;
    el.classList.add("on");
    // after the entry, slide the bar from before to now
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        el.querySelector(".mo-fill-home").style.width = `${c.momentum.now}%`;
        el.querySelector(".mo-fill-away").style.width = `${100 - c.momentum.now}%`;
        el.querySelector(".cf-now").style.left = `${c.momentum.now}%`;
      }),
    );
    cardUntil = performance.now() + CARD_SECONDS * 1000;
  }

  function hideCard(now) {
    const el = $("card");
    cardUntil = 0;
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
      if (showing && now >= cardUntil) hideCard(false);
      if (!showing && nextCard < bundle.cards.length && t >= bundle.cards[nextCard].at) {
        showCard(bundle.cards[nextCard]);
        nextCard++;
      }
      if (t >= bundle.minutes && !cardUntil) setPlaying(false);
      render();
    }
    requestAnimationFrame(frame);
  }

  function setPlaying(on) {
    playing = on;
    if (on && bundle && t >= bundle.minutes) restart();
    $("playBtn").textContent = on ? "Pause" : "Play";
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
    }
  });
  if (params.get("hide") === "1") $("controls").classList.add("hidden");

  // a still frame dropped in web/assets/stadium.jpg replaces the drawn backdrop
  const still = new Image();
  still.onload = () => {
    const bd = $("backdrop");
    bd.style.setProperty("--still", `url("${still.src}")`);
    bd.classList.add("has-image");
  };
  still.src = "assets/stadium.jpg";

  requestAnimationFrame(frame);
  loadIndex();
})();
