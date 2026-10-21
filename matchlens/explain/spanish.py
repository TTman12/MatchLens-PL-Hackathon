"""The rules' lines in Spanish: the offline Spanish screen, and the fallback when a translation fails
its check.

Every English template the rules write has a Spanish twin here, with the same placeholders, so a
card's reading, a MatchLens analysis lever or a recap pattern can be written straight into Spanish
from the same facts. A Foundry or Azure translation of the English line is preferred when it passes
its check (matchlens/agents/translator.py); these lines are what the screen shows when it doesn't.

Clubs are singular in Spanish ("Brackenford ha pasado al ataque"), where English has them plural.
"""

from __future__ import annotations

import re
from typing import Any

# insight.LINES, in Spanish
LINES: dict[str, dict[str, Any]] = {
    "attacking": {
        "neutral": {
            "behind": "{T} se ha lanzado al ataque en busca de meterse en el partido.",
            "leading": "{T} no se conforma con la ventaja: sigue yendo hacia delante.",
            "*": "{T} ha subido una marcha y juega en campo contrario.",
        },
        "own": {
            "behind": "{T} se vuelca en ataque y tiene más pinta de marcar el siguiente.",
            "leading": "{T} va a por la sentencia.",
            "*": "{T} manda en campo contrario y está cada vez más cerca del gol.",
        },
        "other": {
            "behind": "{O} tiene que defenderse mientras {T} lo echa todo arriba.",
            "leading": "{O} no logra asentarse mientras {T} sigue atacando.",
            "*": "{O} está encerrado atrás y le cuesta salir.",
        },
    },
    "pressing": {
        "neutral": "{T} presiona arriba y no deja respirar a {O}.",
        "own": "{T} aprieta fuerte y fuerza errores de {O}.",
        "other": "{O} comete errores por la presión y no puede salir jugando.",
    },
    "under_pressure": {
        "neutral": {
            "leading": "{T} se ha replegado para proteger la ventaja.",
            "*": "{T} ha retrocedido y pasa largos ratos defendiendo.",
        },
        "own": {
            "leading": "{T} aprieta los dientes para conservar lo que tiene.",
            "*": "{T} lo está pasando mal y necesita salir de su campo.",
        },
        "other": {
            "leading": "{O} tiene encerrado a {T}, pero aún debe encontrar el hueco.",
            "*": "{O} está instalado en campo de {T} y lleva la iniciativa.",
        },
    },
    "control": {
        "neutral": {
            "leading": "{T} conserva el balón y le quita ritmo al partido.",
            "*": "{T} se ha hecho con el balón y marca el ritmo.",
        },
        "own": {
            "leading": "{T} tiene el balón y gestiona el partido.",
            "*": "{T} manda ahora y hace correr a {O}.",
        },
        "other": "{O} corre detrás del balón mientras {T} lo mueve.",
    },
    "direct": {
        "neutral": "{T} ha pasado a un juego más directo, en largo para saltarse el centro del campo.",
        "own": "{T} juega más directo para llevar el balón arriba más rápido.",
        "other": "{T} ha dejado de construir por el centro y busca el balón largo ante {O}.",
    },
    "losing_control": {
        "neutral": "{T} ha perdido el control del partido y no para de regalar el balón.",
        "own": "{T} está impreciso con el balón y necesita calmarse.",
        "other": "{O} se aprovecha de las pérdidas de {T}.",
    },
    "physical": {
        "neutral": "El partido se ha vuelto una batalla, y {T} la está ganando.",
        "own": "{T} está ganando la batalla física.",
        "other": "{O} pierde los duelos ante {T}.",
    },
    "blunted": {
        "neutral": "{T} ha perdido la pegada en ataque.",
        "own": "A {T} le cuesta cada vez más generar ocasiones.",
        "other": "{O} ha apagado el ataque de {T}.",
    },
    "player_drive": {
        "neutral": "{P} {VERB} tirando de {T}.",
        "own": "{P} {VERB} empujando a {T} hacia delante.",
        "other": "{P} {VERB} siendo el problema de {O} ahora mismo.",
    },
    "fresh_legs": {
        "neutral": "{P} le ha dado energía nueva a {T}.",
        "own": "{P} ha dado un impulso a {T} desde el banquillo.",
        "other": "{P} ha marcado la diferencia para {T} desde que entró.",
    },
    "sub_quiet": {
        "neutral": "{P} no ha tenido el mismo impacto desde que entró.",
        "own": "{P} todavía está entrando en el partido.",
        "other": "El cambio de {T} no ha inquietado a {O} por ahora.",
    },
    "tiring": {
        "neutral": "{T} se está cansando y el partido se abre.",
        "own": "A {T} le fallan las piernas y tiene que aguantar.",
        "other": "{O} nota que {T} se está cansando.",
    },
    "ten_men": {
        "neutral": "Con diez, {T} ha tenido que reorganizarse y replegarse.",
        "own": "{T} se sacrifica para competir con diez.",
        "other": "{O} tiene un hombre más y {T} tiene que resistir.",
    },
    "holding_shape": {
        "neutral": "Incluso con diez, {T} mantiene su orden.",
        "own": "{T} lo está llevando bien con diez por ahora.",
        "other": "{O} todavía no ha sacado partido del hombre de más.",
    },
    "no_change": {
        "neutral": "Nada ha cambiado: el partido sigue igual.",
        "own": "Todo sigue igual para {T}.",
        "other": "Todo sigue igual para {O}.",
    },
    "taking_over": {
        "neutral": {
            "leading": "{T} manda y controla su ventaja.",
            "*": "{T} se ha impuesto en este tramo.",
        },
        "own": "{T} manda y va a más.",
        "other": "{O} está a la defensiva en este tramo.",
    },
}

# insight.PLAYER_LINES, in Spanish
PLAYER_LINES: dict[str, dict[str, str]] = {
    "sprints": {
        "neutral": "Los desmarques de {P} estiran a {O} y dan más opciones a {T} en ataque.",
        "own": "Las carreras de {P} dan a {T} más opciones arriba y meten presión a {O}.",
        "other": "{O} no puede seguir los desmarques de {P}, y {T} aprieta cada vez más.",
    },
    "distance_m": {
        "neutral": "El despliegue de {P} le da a {T} un hombre más por todo el campo y le quita espacio a {O}.",
        "own": "{P} está en todas partes, y {T} llega primero a cada balón suelto.",
        "other": "{P} está en todas partes, y {O} se queda sin espacio para jugar.",
    },
    "progressive_passes": {
        "neutral": "Los pases hacia delante de {P} rompen las líneas de {O} y hacen avanzar a {T}.",
        "own": "{P} mueve los hilos, rompe las líneas de {O} y lleva a {T} arriba.",
        "other": "{P} siempre encuentra el pase entre las líneas de {O}, y {T} avanza gracias a ello.",
    },
    "defensive_actions": {
        "neutral": "{P} no para de recuperar balones, así que {T} lo recupera rápido y {O} no coge ritmo.",
        "own": "{P} corta una y otra vez el juego de {O} y le devuelve el balón a {T}.",
        "other": "{P} corta las jugadas de {O} antes de que empiecen, y {T} se está imponiendo.",
    },
    "duels_won": {
        "neutral": "{P} gana los duelos, así que {T} conserva el balón y {O} retrocede.",
        "own": "{P} gana cada duelo, y eso permite a {T} imponerse a {O}.",
        "other": "{O} no puede con {P}, y cada duelo perdido le da el balón a {T}.",
    },
    "duels": {
        "neutral": "{P} se faja en cada balón, da mordiente a {T} e impide jugar a {O}.",
        "own": "{P} se faja en cada balón y le da ventaja a {T} ante {O}.",
        "other": "{P} se faja en cada balón, y {O} no tiene un segundo de calma.",
    },
    "touches": {
        "neutral": "{P} participa mucho más, y {T} tiene una salida para superar a {O}.",
        "own": "{P} siempre se ofrece y le da a {T} una salida cada vez que recupera.",
        "other": "{O} no logra apagar a {P}, y {T} aprovecha esa salida.",
    },
}

NO_CHANGE = {
    "goal_no_reaction": "El gol de {T} no ha cambiado el guion del partido.",
    "sub_no_change": "El cambio de {T} no ha alterado el partido por ahora.",
    "half_time_no_change": "{T} y {O} han seguido donde lo dejaron.",
}
VERB = {"is": "está", "are": "están"}


def off_the_bench(line: str) -> str:
    """'Desde el banquillo, ' before a player line, as English puts 'Off the bench, '."""
    head = line if line.startswith("{") else line[0].lower() + line[1:]
    return "Desde el banquillo, " + head


# analysis.LEVERS' lines, in Spanish: lever key -> (neutral, fan), each one line or one per game state
LEVERS: dict[str, tuple[str | dict[str, str], str | dict[str, str]]] = {
    "higher_line": (
        "{T} se ha hundido demasiado. Adelantar la línea quitaría el espacio que está disfrutando {O}.",
        "{T} tiene que adelantar la línea y dejar de invitar a {O} a atacar.",
    ),
    "press_again": (
        "{T} ya no roba arriba. Volver a presionar impediría a {O} salir jugando desde atrás.",
        "{T} tiene que volver a presionar y dejar de permitir que {O} salga jugando.",
    ),
    "keep_ball": (
        {
            "behind": "{T} no puede remontar sin el balón. Necesita tenerlo más tiempo.",
            "*": "{T} necesita tener más el balón y hacer correr a {O}.",
        },
        "{T} tiene que juntarse con el balón y hacer correr a {O} para variar.",
    ),
    "settle": (
        "{T} regala el balón con demasiada facilidad. Pases más sencillos y cortos le ayudarían a asentarse.",
        "{T} necesita calmarse con el balón y jugar sencillo.",
    ),
    "get_out": (
        "{T} está atascado pasándose el balón en su campo. Necesita llevarlo arriba más rápido.",
        "{T} tiene que ser más valiente y sacar el balón de su campo.",
    ),
    "through_the_middle": (
        "{T} no para de jugar en largo y devolver el balón. Jugar por el centro del campo le daría un punto de apoyo.",
        "{T} tiene que dejar el balón largo y jugar por el centro.",
    ),
    "beat_the_press": (
        "La presión de {O} está forzando errores. {T} tiene que mover el balón más rápido para superarla.",
        "{T} tiene que mover el balón más rápido y superar la presión de {O}.",
    ),
    "cover_the_flanks": (
        "{O} llega a las bandas con demasiada facilidad. {T} necesita más ayudas por fuera.",
        "{T} tiene que cerrar las bandas antes de que {O} ponga centros.",
    ),
    "win_battles": (
        "{T} está perdiendo los duelos individuales. Recuperarlos tiene que ser lo primero.",
        "{T} tiene que volver a ganar duelos y segundas jugadas.",
    ),
    "more_bodies": (
        "{T} no llega al último tercio. Necesita más gente arriba para inquietar a {O}.",
        "{T} tiene que sumar más jugadores en ataque y poner a prueba a {O}.",
    ),
    "keep_going_forward": (
        "Llevar el balón arriba rápido le está funcionando a {T}. Seguir así mantiene a {O} encerrado.",
        "{T} debe seguir llevando el balón arriba rápido: {O} no puede con ello.",
    ),
    "keep_pressing": (
        "La presión de {T} está robando balones arriba. Mantenerla impedirá que {O} se asiente.",
        "{T} debe seguir presionando arriba y tener a {O} encerrado.",
    ),
    "keep_the_line_high": (
        "{T} ha adelantado la línea y ha llevado el partido al campo de {O}. Mantenerla ahí sostiene la presión.",
        "{T} debe mantener la línea alta y seguir apretando a {O}.",
    ),
    "keep_the_ball": (
        {
            "leading": "{T} puede cerrar el partido teniendo el balón y haciendo correr a {O}.",
            "*": "{T} debe tener el balón y hacer correr a {O}.",
        },
        {
            "leading": "Balón, que corra {O}, y {T} cierra el partido.",
            "*": "{T} debe tener el balón, mover a {O} y esperar los huecos.",
        },
    ),
    "keep_going_wide": (
        "{T} está haciendo daño por las bandas. Más centros desde fuera podrían romper a {O}.",
        "{T} debe seguir atacando por las bandas: {O} no sabe defenderlo.",
    ),
    "keep_getting_in": (
        "{T} pisa cada vez más el área. Si sigue sumando gente arriba, pondrá a prueba a {O}.",
        "{T} debe seguir metiendo gente en el área: {O} lo está pasando mal.",
    ),
    "keep_battling": (
        "{T} está ganando los duelos. Mantenerlo tiene a {O} a la defensiva.",
        "{T} debe seguir ganando duelos y tener a {O} a la defensiva.",
    ),
    "keep_going_direct": (
        "El juego directo le está funcionando a {T}. Los balones a la espalda obligan a {O} a girarse.",
        "{T} debe seguir jugando en largo por encima del centro del campo de {O}.",
    ),
}

# every stat label the screen can show, in Spanish
LABELS = {
    "Field tilt": "Dominio territorial",
    "Possession": "Posesión",
    "Pass accuracy": "Precisión de pase",
    "Passes in final third": "Pases en el último tercio",
    "Progressive passes": "Pases progresivos",
    "Box entries": "Llegadas al área",
    "Shots": "Tiros",
    "Shots on target": "Tiros a puerta",
    "xG": "xG",
    "Goals": "Goles",
    "Defending height": "Altura defensiva",
    "Passes allowed per defensive action": "Pases permitidos por acción defensiva",
    "High turnovers": "Robos en campo rival",
    "Duels won": "Duelos ganados",
    "Duels": "Duelos",
    "Long balls": "Balones largos",
    "Average pass length": "Longitud media de pase",
    "Passes": "Pases",
    "Passes in own half": "Pases en campo propio",
    "Clearances": "Despejes",
    "Crosses": "Centros",
    "Fouls": "Faltas",
    "Distance per player": "Distancia por jugador",
    "Distance": "Distancia",
    "Sprints": "Sprints",
    "Sprints per player": "Sprints por jugador",
    "High-speed running": "Carrera a alta velocidad",
    "Final-third entries": "Entradas al último tercio",
    "Corners": "Córners",
    "Aerials won": "Duelos aéreos ganados",
    "Defensive actions": "Acciones defensivas",
    "Yellow cards": "Amarillas",
    "Offsides": "Fueras de juego",
    "Minutes": "Minutos",
    "Touches": "Toques",
}

# card anchors (explainer.anchor_label), English pattern -> Spanish
ANCHORS = [
    (re.compile(r"^Since half-time$"), "Desde el descanso"),
    (re.compile(r"^Since (.+) came on$"), r"Desde que entró \1"),
    (re.compile(r"^Since (.+) red card$"), r"Desde la roja a \1"),
    (re.compile(r"^Since (.+) goal (\S+)$"), r"Desde el gol de \1 (\2)"),
    (re.compile(r"^Since (.+) double change$"), r"Desde el doble cambio de \1"),
    (re.compile(r"^Since (.+) triple change$"), r"Desde el triple cambio de \1"),
    (re.compile(r"^Since (\d.*)$"), r"Desde el \1"),
]


def anchor(label: str) -> str:
    for pattern, out in ANCHORS:
        if pattern.match(label):
            return pattern.sub(out, label)
    return label
