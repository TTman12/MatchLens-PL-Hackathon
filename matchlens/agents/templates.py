"""Deterministic fact-box writers, in English and Spanish.

Three jobs share these templates:

- the **offline provider** writes every lens draft with them, so tests and the demo run
  with no model and no credentials;
- the **Verifier** falls back to them when a model draft cannot be repaired;
- the **Translator** re-renders a template draft in another language exactly, with the
  same numbers.

Every number a template writes is taken from an evidence item and formatted the way
``evidence.fmt`` and ``evidence.pct`` format it, so a template box always verifies.
Templates avoid number words ("one up", "five minutes") for the same reason.
"""

from __future__ import annotations

from matchlens.contracts import Draft, Lens, MomentType

from .evidence import fmt, pct
from .state import MomentContext, TemplateRef

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Player lens headlines
        "h.scorer_speed": "{name}: {speed} km/h, then {shot_speed} km/h",
        "h.scorer": "{name} scores",
        "h.assist_break": "{name} splits the line",
        "h.assist": "{name} sets it up",
        "h.starts": "{name} starts it",
        "h.build_up": "{name} keeps it moving",
        "h.booked": "{name} booked",
        "h.sent_off": "{name} sent off",
        "h.fouled": "{name} brought down",
        "h.keeper": "{name} keeps it out",
        "h.denied": "{name} denied",
        "h.miss": "{name} misses a big one",
        "h.taker": "{name} delivers",
        "h.close": "{name} goes close",
        "h.on_ball": "{name} on the ball",
        "h.involved": "{name} in the thick of it",
        # Club lens headlines
        "h.club_lead_derby": "Derby lead for {team}",
        "h.club_lead": "{team} lead!",
        "h.club_level": "{team} level it!",
        "h.club_pull_back": "{team} hit back",
        "h.club_conceded": "{opponent} score",
        "h.club_ban": "{name} banned for {opponent}",
        "h.club_red_own": "{name} sent off",
        "h.club_red_rival": "{name} sent off for {opponent}",
        # Pundit headlines
        "h.pundit_break": "{passer} breaks the line",
        "h.pundit_finish": "Clinical from {scorer}",
        "h.pundit_save": "Big save from {keeper}",
        "h.pundit_chance": "Big chance missed",
        "h.pundit_swing": "{team} take control",
        "h.pundit_red": "A red card changes it",
        # Timeline rail (global layer)
        "h.tl_goal": "Goal: {scorer}",
        "h.tl_yellow": "Yellow card: {name}",
        "h.tl_red": "Red card: {name}",
        "h.tl_corner": "Corner: {team}",
        "h.tl_save": "Save: {keeper}",
        "h.tl_chance": "Chance: {name}",
        "h.tl_swing": "{team} on top",
        # Body sentences
        "s.run_finish": "{name} hit {speed} km/h on the run and finished at {shot_speed} km/h.",
        "s.finish": "{name} finished a {xg} xG chance.",
        "s.season_goals": "That's {goals} league goals this season.",
        "s.first_goal": "A first league goal of the season.",
        "s.drought": "The first goal in {matches} matches.",
        "s.season_best": "That's {name}'s fastest this season.",
        "s.assist_pass": "A {distance} m {pass_label}, rated {difficulty} difficulty, "
        "put {scorer} through.",
        "s.assist_simple": "The final pass for {scorer}'s goal.",
        "s.share": "{share}% of the move's value.",
        "s.touches_run": "{touches} touches in the move, covering {distance} m.",
        "s.touches": "{touches} touches in the move.",
        "s.ban": "Yellow number {yellows} brings a ban: {name} misses {fixture}.",
        "s.yellow_count": "Yellow number {yellows} this season.",
        "s.red_ban": "Banned for the next match.",
        "s.fouled": "Fouled by {fouler}.",
        "s.save_speed": "Saved a {shot_speed} km/h shot worth {xg} xG.",
        "s.save": "Saved a {xg} xG chance.",
        "s.chance_speed": "A {xg} xG chance, struck at {shot_speed} km/h.",
        "s.chance": "A {xg} xG chance.",
        "s.corner": "Corner for {team}.",
        "s.touches_recent": "{touches} touches as {team} take over.",
        "s.scoreline": "{home} {score_home}-{score_away} {away}.",
        "s.win_up": "Win chance up from {before}% to {after}%.",
        "s.win_down": "Win chance down from {before}% to {after}%.",
        "s.live_top": "Top of the live table.",
        "s.live_position": "{position} on the live table.",
        "s.red_own": "{team} play on a player short.",
        "s.red_rival": "{team} have the extra player now.",
        "s.pundit_break": "A {distance} m {pass_label} at {difficulty} difficulty took the "
        "defence out. {passer} made {share}% of the move's value.",
        "s.pundit_finish": "A {xg} xG chance, finished at {shot_speed} km/h.",
        "s.pundit_finish_plain": "A {xg} xG chance, finished.",
        "s.pundit_swing": "{team}'s win chance moved from {before}% to {after}%.",
        "s.threat": "Threat in the recent spell: {home} {home_threat}, {away} {away_threat}.",
        # Fixtures
        "f.away": "the trip to {opponent}",
        "f.home": "the home match against {opponent}",
        # Pass labels
        "p.through": "through ball",
        "p.cross": "cross",
        "p.lofted": "lofted ball",
        "p.long": "long ball",
        "p.cut_back": "cut-back",
        "p.pass": "pass",
    },
    "es": {
        "h.scorer_speed": "{name}: {speed} km/h y luego {shot_speed} km/h",
        "h.scorer": "Gol de {name}",
        "h.assist_break": "{name} rompe la línea",
        "h.assist": "{name} la prepara",
        "h.starts": "{name} la inicia",
        "h.build_up": "{name} mueve la jugada",
        "h.booked": "Amarilla para {name}",
        "h.sent_off": "Expulsión de {name}",
        "h.fouled": "Falta sobre {name}",
        "h.keeper": "{name} lo evita",
        "h.denied": "{name}, sin premio",
        "h.miss": "{name} perdona una clara",
        "h.taker": "Centro de {name}",
        "h.close": "{name} lo intenta",
        "h.on_ball": "{name} al mando",
        "h.involved": "{name}, en plena jugada",
        "h.club_lead_derby": "Ventaja en el derbi para {team}",
        "h.club_lead": "¡{team} por delante!",
        "h.club_level": "¡{team} empata!",
        "h.club_pull_back": "{team} recorta distancias",
        "h.club_conceded": "Marca {opponent}",
        "h.club_ban": "{name}, sancionado ante {opponent}",
        "h.club_red_own": "Expulsión de {name}",
        "h.club_red_rival": "Expulsión de {name} en {opponent}",
        "h.pundit_break": "{passer} rompe líneas",
        "h.pundit_finish": "Definición letal de {scorer}",
        "h.pundit_save": "Paradón de {keeper}",
        "h.pundit_chance": "Ocasión clarísima fallada",
        "h.pundit_swing": "{team} toma el control",
        "h.pundit_red": "La roja lo cambia todo",
        "h.tl_goal": "Gol: {scorer}",
        "h.tl_yellow": "Amarilla: {name}",
        "h.tl_red": "Roja: {name}",
        "h.tl_corner": "Córner: {team}",
        "h.tl_save": "Parada: {keeper}",
        "h.tl_chance": "Ocasión: {name}",
        "h.tl_swing": "{team} domina",
        "s.run_finish": "{name} alcanzó {speed} km/h en carrera y definió a {shot_speed} km/h.",
        "s.finish": "{name} definió una ocasión de {xg} xG.",
        "s.season_goals": "Ya suma {goals} goles de liga esta temporada.",
        "s.first_goal": "Su primer gol de liga de la temporada.",
        "s.drought": "Es su primer gol en {matches} partidos.",
        "s.season_best": "Es la máxima velocidad de {name} esta temporada.",
        "s.assist_pass": "Un {pass_label} de {distance} m, con dificultad {difficulty}, "
        "dejó solo a {scorer}.",
        "s.assist_simple": "El último pase para el gol de {scorer}.",
        "s.share": "El {share}% del valor de la jugada.",
        "s.touches_run": "{touches} toques en la jugada y {distance} m recorridos.",
        "s.touches": "{touches} toques en la jugada.",
        "s.ban": "La amarilla número {yellows} trae sanción: {name} se pierde {fixture}.",
        "s.yellow_count": "Es su amarilla número {yellows} de la temporada.",
        "s.red_ban": "Sancionado para el próximo partido.",
        "s.fouled": "Falta de {fouler}.",
        "s.save_speed": "Detuvo un disparo a {shot_speed} km/h de {xg} xG.",
        "s.save": "Detuvo una ocasión de {xg} xG.",
        "s.chance_speed": "Una ocasión de {xg} xG, con disparo a {shot_speed} km/h.",
        "s.chance": "Una ocasión de {xg} xG.",
        "s.corner": "Córner para {team}.",
        "s.touches_recent": "{touches} toques mientras {team} toma el control.",
        "s.scoreline": "{home} {score_home}-{score_away} {away}.",
        "s.win_up": "Probabilidad de victoria: del {before}% al {after}%.",
        "s.win_down": "Probabilidad de victoria: baja del {before}% al {after}%.",
        "s.live_top": "Líder en la clasificación en directo.",
        "s.live_position": "{position_es} en la clasificación en directo.",
        "s.red_own": "{team} se queda en inferioridad.",
        "s.red_rival": "{team} juega ahora con superioridad numérica.",
        "s.pundit_break": "Un {pass_label} de {distance} m, con dificultad {difficulty}, "
        "dejó atrás a la defensa. {passer} aportó el {share}% del valor de la jugada.",
        "s.pundit_finish": "Una ocasión de {xg} xG, definida a {shot_speed} km/h.",
        "s.pundit_finish_plain": "Una ocasión de {xg} xG, convertida.",
        "s.pundit_swing": "La probabilidad de victoria de {team} pasó del {before}% al {after}%.",
        "s.threat": "Amenaza en el último tramo: {home} {home_threat}, {away} {away_threat}.",
        "f.away": "la visita a {opponent}",
        "f.home": "el partido en casa ante {opponent}",
        "p.through": "pase al hueco",
        "p.cross": "centro",
        "p.lofted": "balón elevado",
        "p.long": "balón largo",
        "p.cut_back": "pase atrás",
        "p.pass": "pase",
    },
}

LANGUAGES = tuple(STRINGS)


def _ordinal_en(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def render(ref: TemplateRef, lang: str) -> tuple[str, str]:
    """Headline and body for a template draft in ``lang``."""
    strings = STRINGS[lang]
    params = dict(ref.params)
    # Language-dependent pieces are stored as keys and resolved here.
    for key in ("pass_label", "fixture", "what"):
        if f"{key}_key" in params:
            params[key] = strings[params[f"{key}_key"]].format(**params)
    headline = strings[ref.key].format(**params)
    body = " ".join(strings[part].format(**params) for part in ref.parts)
    return headline, body


def to_draft(ref: TemplateRef, lens: Lens, subject: str | None, lang: str = "en") -> Draft:
    headline, body = render(ref, lang)
    return Draft(
        lens=lens,
        subject_id=subject,
        headline=headline,
        body=body,
        evidence_ids=list(ref.evidence_ids),
        author="template",
    )


class _Builder:
    """Collects params, body parts and cited evidence while a template is put together."""

    def __init__(self, ctx: MomentContext) -> None:
        self.ctx = ctx
        self.params: dict[str, str] = {}
        self.parts: list[str] = []
        self.evidence: list[str] = []

    def name(self, key: str, entity: str) -> None:
        self.params[key] = self.ctx.names.get(entity, entity)

    def num(self, ref: str, field: str, param: str, *, percent: bool = False) -> bool:
        item = self.ctx.ledger.get(ref)
        if item is None or field not in item.numbers:
            return False
        value = item.numbers[field]
        self.params[param] = pct(value) if percent else fmt(value)
        if item.id not in self.evidence:
            self.evidence.append(item.id)
        return True

    def has(self, ref: str, *fields: str) -> bool:
        item = self.ctx.ledger.get(ref)
        return item is not None and all(f in item.numbers for f in fields)

    def done(self, headline: str) -> TemplateRef:
        return TemplateRef(headline, self.params, self.parts, self.evidence)


# -- Player lens ------------------------------------------------------------------------

SPRINT_KMH = 19.8
"""A scorer's run speed leads the box only from high-speed running upward; a header from
a standing start at a corner is told by its finish instead."""


def player_template(ctx: MomentContext, player_id: str) -> TemplateRef:
    """A box for one contributor, from the evidence only."""
    c = ctx.contributor(player_id)
    role = c.role if c else "build_up"
    b = _Builder(ctx)
    b.name("name", player_id)
    m = ctx.moment
    scorer = ctx.facts.get("scorer")
    if scorer:
        b.name("scorer", str(scorer))

    if m.type is MomentType.GOAL and role == "scorer":
        run = ctx.ledger.get(f"run:{player_id}")
        sprint = run is not None and run.numbers.get("top_speed_kmh", 0.0) >= SPRINT_KMH
        fast = sprint and b.has("shot", "shot_speed_kmh")
        if fast:
            b.num(f"run:{player_id}", "top_speed_kmh", "speed")
            b.num("shot", "shot_speed_kmh", "shot_speed")
            b.parts.append("s.run_finish")
            headline = "h.scorer_speed"
        else:
            b.num("shot", "xg", "xg")
            b.parts.append("s.finish")
            headline = "h.scorer"
        if b.has("milestone", "goals"):
            b.num("milestone", "goals", "goals")
            b.parts.append("s.first_goal")
        elif b.has("milestone", "matches"):
            b.num("milestone", "matches", "matches")
            b.parts.append("s.drought")
        elif b.num("season_goals", "goals", "goals"):
            b.parts.append("s.season_goals")
        return b.done(headline)

    if m.type is MomentType.GOAL and role == "assist":
        if b.has(f"pass:{player_id}", "distance_m", "difficulty"):
            b.num(f"pass:{player_id}", "distance_m", "distance")
            b.num(f"pass:{player_id}", "difficulty", "difficulty")
            b.params["pass_label_key"] = f"p.{ctx.facts.get(f'pass:{player_id}:pass_type', 'pass')}"
            if b.params["pass_label_key"] not in STRINGS["en"]:
                b.params["pass_label_key"] = "p.pass"
            b.parts.append("s.assist_pass")
            broke = bool(ctx.facts.get(f"pass:{player_id}:line_breaking"))
            headline = "h.assist_break" if broke else "h.assist"
        else:
            b.parts.append("s.assist_simple")
            headline = "h.assist"
        if b.num(f"share:{player_id}", "share", "share", percent=True):
            b.parts.append("s.share")
        return b.done(headline)

    if m.type is MomentType.GOAL:
        first = min(
            (x for x in ctx.contributors if x.events), key=lambda x: x.events[0], default=None
        )
        headline = (
            "h.starts" if first is not None and first.player_id == player_id else "h.build_up"
        )
        if b.has(f"share:{player_id}", "touches"):
            b.num(f"share:{player_id}", "touches", "touches")
            if b.num(f"run:{player_id}", "distance_m", "distance"):
                b.parts.append("s.touches_run")
            else:
                b.parts.append("s.touches")
        share = ctx.ledger.get(f"share:{player_id}")
        if share is not None and share.numbers.get("share", 0.0) >= 0.05:
            b.num(f"share:{player_id}", "share", "share", percent=True)
            b.parts.append("s.share")
        return b.done(headline)

    if m.type is MomentType.CARD and role == "fouler":
        red = bool(ctx.facts.get("red"))
        if red:
            b.parts.append("s.red_ban")
            return b.done("h.sent_off")
        b.num("discipline", "yellows", "yellows")
        if ctx.facts.get("banned") and _fixture(b):
            b.parts.append("s.ban")
        else:
            b.parts.append("s.yellow_count")
        return b.done("h.booked")

    if m.type is MomentType.CARD and role == "fouled":
        b.name("fouler", str(ctx.facts.get("booked", "")))
        b.parts.append("s.fouled")
        return b.done("h.fouled")

    if m.type in (MomentType.BIG_SAVE, MomentType.BIG_CHANCE, MomentType.CORNER) and role in (
        "keeper",
        "shooter",
    ):
        shot_ref = "won_by" if m.type is MomentType.CORNER and _is_cause(ctx, player_id) else "shot"
        speed = b.num(shot_ref, "shot_speed_kmh", "shot_speed")
        b.num(shot_ref, "xg", "xg")
        if role == "keeper":
            b.parts.append("s.save_speed" if speed else "s.save")
            return b.done("h.keeper")
        b.parts.append("s.chance_speed" if speed else "s.chance")
        if m.type is MomentType.CORNER:
            return b.done("h.close")
        return b.done("h.denied" if m.type is MomentType.BIG_SAVE else "h.miss")

    if m.type is MomentType.CORNER and role == "taker":
        b.name("team", str(ctx.facts.get("team", "")))
        b.parts.append("s.corner")
        return b.done("h.taker")

    if m.type is MomentType.SWING and b.has(f"touches:{player_id}", "touches"):
        b.num(f"touches:{player_id}", "touches", "touches")
        b.name("team", str(ctx.facts.get("team", "")))
        b.parts.append("s.touches_recent")
        return b.done("h.on_ball")

    return b.done("h.involved")


def _is_cause(ctx: MomentContext, player_id: str) -> bool:
    item = ctx.ledger.get("won_by")
    c = ctx.contributor(player_id)
    return bool(item and c and item.source in c.events)


def _fixture(b: _Builder) -> bool:
    opponent = b.ctx.facts.get("ban_opponent")
    if not opponent or not b.ctx.ledger.get("fixture"):
        return False
    b.name("opponent", str(opponent))
    b.params["fixture_key"] = "f.home" if b.ctx.facts.get("ban_venue") == "home" else "f.away"
    fixture = b.ctx.ledger.get("fixture")
    if fixture and fixture.id not in b.evidence:
        b.evidence.append(fixture.id)
    return True


# -- Club lens --------------------------------------------------------------------------


def club_template(ctx: MomentContext, team_id: str, home_id: str, away_id: str) -> TemplateRef:
    """A partisan box for ``team_id``'s fans. Call only when the club gate has fired."""
    m = ctx.moment
    b = _Builder(ctx)
    b.name("team", team_id)
    opponent = away_id if team_id == home_id else home_id
    b.name("opponent", opponent)
    win_ref = f"win_prob:{team_id}"

    def win_sentence() -> None:
        item = ctx.ledger.get(win_ref)
        if item and item.numbers.get("before") != item.numbers.get("after"):
            b.num(win_ref, "before", "before", percent=True)
            b.num(win_ref, "after", "after", percent=True)
            up = item.numbers["after"] > item.numbers["before"]
            b.parts.append("s.win_up" if up else "s.win_down")

    def table_sentence() -> None:
        item = ctx.ledger.get(f"live:{team_id}")
        if not item or not ctx.facts.get(f"moved:{team_id}"):
            return
        position = int(item.numbers["position"])
        b.num(f"live:{team_id}", "position", "position_raw")
        b.params["position"] = _ordinal_en(position)
        b.params["position_es"] = f"{position}º"
        b.parts.append("s.live_top" if position == 1 else "s.live_position")

    if m.type is MomentType.GOAL:
        score = ctx.facts.get("score", (0, 0))
        ours, theirs = (score[0], score[1]) if team_id == home_id else (score[1], score[0])
        if m.scoring_team == team_id:
            if ours > theirs:
                headline = "h.club_lead_derby" if ctx.facts.get("derby") else "h.club_lead"
            elif ours == theirs:
                headline = "h.club_level"
            else:
                headline = "h.club_pull_back"
        else:
            headline = "h.club_conceded"
        b.name("home", home_id)
        b.name("away", away_id)
        b.num("score", "score_home", "score_home")
        b.num("score", "score_away", "score_away")
        b.parts.append("s.scoreline")
        win_sentence()
        table_sentence()
        return b.done(headline)

    if m.type is MomentType.CARD:
        booked = str(ctx.facts.get("booked", ""))
        b.name("name", booked)
        own = ctx.facts.get("booked_team") == team_id
        if ctx.facts.get("red"):
            b.parts.append("s.red_own" if own else "s.red_rival")
            if own:
                b.parts.append("s.red_ban")
            win_sentence()
            if own:
                return b.done("h.club_red_own")
            b.name("opponent", str(ctx.facts.get("booked_team", "")))
            return b.done("h.club_red_rival")
        b.num("discipline", "yellows", "yellows")
        _fixture(b)
        b.parts.append("s.ban")
        return b.done("h.club_ban")

    win_sentence()
    return b.done(
        "h.club_lead" if m.swing * (1 if team_id == home_id else -1) > 0 else "h.club_conceded"
    )


# -- Pundit lens ------------------------------------------------------------------------


def pundit_template(ctx: MomentContext, home_id: str, away_id: str) -> TemplateRef:
    m = ctx.moment
    b = _Builder(ctx)
    if m.type is MomentType.GOAL:
        scorer = str(ctx.facts.get("scorer", ""))
        b.name("scorer", scorer)
        assist = ctx.facts.get("assist")
        if (
            assist
            and ctx.facts.get(f"pass:{assist}:line_breaking")
            and b.has(f"pass:{assist}", "distance_m", "difficulty")
        ):
            b.name("passer", str(assist))
            b.num(f"pass:{assist}", "distance_m", "distance")
            b.num(f"pass:{assist}", "difficulty", "difficulty")
            b.num(f"share:{assist}", "share", "share", percent=True)
            kind = f"p.{ctx.facts.get(f'pass:{assist}:pass_type', 'pass')}"
            b.params["pass_label_key"] = kind if kind in STRINGS["en"] else "p.pass"
            b.parts.append("s.pundit_break")
            return b.done("h.pundit_break")
        b.num("shot", "xg", "xg")
        b.parts.append(
            "s.pundit_finish"
            if b.num("shot", "shot_speed_kmh", "shot_speed")
            else "s.pundit_finish_plain"
        )
        _pundit_swing(b, m.scoring_team)
        return b.done("h.pundit_finish")
    if m.type is MomentType.BIG_SAVE:
        keeper = next((c.player_id for c in ctx.contributors if c.role == "keeper"), "")
        b.name("keeper", keeper)
        b.num("shot", "xg", "xg")
        b.parts.append(
            "s.save_speed" if b.num("shot", "shot_speed_kmh", "shot_speed") else "s.save"
        )
        return b.done("h.pundit_save")
    if m.type is MomentType.BIG_CHANCE:
        b.num("shot", "xg", "xg")
        b.parts.append(
            "s.chance_speed" if b.num("shot", "shot_speed_kmh", "shot_speed") else "s.chance"
        )
        return b.done("h.pundit_chance")
    if m.type is MomentType.SWING:
        b.name("team", str(ctx.facts.get("team", "")))
        b.name("home", home_id)
        b.name("away", away_id)
        b.num("momentum", "home_threat", "home_threat")
        b.num("momentum", "away_threat", "away_threat")
        b.parts.append("s.threat")
        return b.done("h.pundit_swing")
    # Red card
    _pundit_swing(b, home_id if m.swing > 0 else away_id)
    return b.done("h.pundit_red")


def _pundit_swing(b: _Builder, team_id: str | None) -> None:
    if not team_id:
        return
    ref = f"win_prob:{team_id}"
    if b.has(ref, "before", "after"):
        b.name("team", team_id)
        b.num(ref, "before", "before", percent=True)
        b.num(ref, "after", "after", percent=True)
        b.parts.append("s.pundit_swing")


# -- Timeline rail ----------------------------------------------------------------------


def timeline_template(ctx: MomentContext) -> TemplateRef:
    """A one-line entry for the match-events rail every viewer sees."""
    m = ctx.moment
    b = _Builder(ctx)
    if m.type is MomentType.GOAL:
        b.name("scorer", str(ctx.facts.get("scorer", "")))
        home, away = str(ctx.facts.get("home_id", "")), str(ctx.facts.get("away_id", ""))
        b.name("home", home)
        b.name("away", away)
        b.num("score", "score_home", "score_home")
        b.num("score", "score_away", "score_away")
        b.parts.append("s.scoreline")
        return b.done("h.tl_goal")
    if m.type is MomentType.CARD:
        b.name("name", str(ctx.facts.get("booked", "")))
        return b.done("h.tl_red" if ctx.facts.get("red") else "h.tl_yellow")
    if m.type is MomentType.SWING:
        b.name("team", str(ctx.facts.get("team", "")))
        return b.done("h.tl_swing")
    if m.type is MomentType.CORNER:
        b.name("team", str(ctx.facts.get("team", "")))
        ref = "won_by" if ctx.ledger.get("won_by") else "shot"
        if b.num(ref, "xg", "xg"):
            b.parts.append("s.chance")
        return b.done("h.tl_corner")
    b.num("shot", "xg", "xg")
    b.parts.append("s.chance")
    if m.type is MomentType.BIG_SAVE:
        b.name("keeper", next((c.player_id for c in ctx.contributors if c.role == "keeper"), ""))
        return b.done("h.tl_save")
    b.name("name", next((c.player_id for c in ctx.contributors if c.role == "shooter"), ""))
    return b.done("h.tl_chance")
