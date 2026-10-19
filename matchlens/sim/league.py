"""The fictional league: twenty invented clubs with generated squads.

No club, player, stadium or town here refers to a real one. The first four clubs and the
named players below match ``data/sample`` so the sample match and simulated matches tell
the same story.
"""

from __future__ import annotations

import random
from typing import Any

from matchlens.contracts import SCHEMA_VERSION, League

from .formations import BENCH, FORMATIONS

LEAGUE_ID = "fl"
LEAGUE_NAME = "The Fictional League"

# (team_id, name, short_name, city, stadium, primary, secondary, text, rating, formation)
_CLUBS: list[tuple[str, str, str, str, str, str, str, str, int, str]] = [
    ("ash", "Ashmere Athletic", "Ashmere", "Ashmere", "Kilnside Park",
     "#B3202A", "#F2E8D5", "#FFFFFF", 74, "4-3-3"),
    ("brk", "Brackenford", "Brackenford", "Brackenford", "The Weir Ground",
     "#1D4E89", "#F5C518", "#F5C518", 71, "4-2-3-1"),
    ("cal", "Calderwick Town", "Calderwick", "Calderwick", "Saltmarsh Lane",
     "#2E7D4F", "#FFFFFF", "#FFFFFF", 76, "4-3-3"),
    ("els", "Elsbridge Rovers", "Elsbridge", "Elsbridge", "Pennant Road",
     "#5B2A86", "#C9C9C9", "#FFFFFF", 68, "3-5-2"),
    ("dun", "Dunmoor City", "Dunmoor", "Dunmoor", "The Lantern",
     "#6CABDD", "#0B1F3A", "#0B1F3A", 79, "4-3-3"),
    ("fen", "Fenwater United", "Fenwater", "Fenwater", "Reedbank Stadium",
     "#C8102E", "#111111", "#FFFFFF", 77, "4-2-3-1"),
    ("gry", "Greyhollow", "Greyhollow", "Greyhollow", "Quarry Hill",
     "#7A7A7A", "#E4002B", "#FFFFFF", 66, "4-4-2"),
    ("hrt", "Hartcliffe Albion", "Hartcliffe", "Hartcliffe", "Gull Point",
     "#0057B8", "#FFFFFF", "#FFFFFF", 70, "4-2-3-1"),
    ("ivy", "Ivybourne", "Ivybourne", "Ivybourne", "The Glasshouse",
     "#00843D", "#FDB913", "#FDB913", 64, "4-4-2"),
    ("kes", "Kestrel Vale", "Kestrel Vale", "Kestrel Vale", "Highfield Moor",
     "#8B5A2B", "#F3D9B1", "#FFFFFF", 67, "3-5-2"),
    ("lum", "Lumsden Forge", "Lumsden", "Lumsden", "Anvil Park",
     "#E35205", "#1C1C1C", "#1C1C1C", 69, "4-3-3"),
    ("mrw", "Marrowgate", "Marrowgate", "Marrowgate", "Ferry Lane",
     "#004C54", "#A2AAAD", "#FFFFFF", 73, "4-2-3-1"),
    ("nor", "Northwold Wanderers", "Northwold", "Northwold", "The Heath",
     "#FFCD00", "#1A1A1A", "#1A1A1A", 65, "4-4-2"),
    ("ott", "Otterburn Harbour", "Otterburn", "Otterburn", "Lighthouse Road",
     "#003A70", "#9ADBE8", "#FFFFFF", 63, "4-4-2"),
    ("pen", "Pendlecross", "Pendlecross", "Pendlecross", "Millstone Park",
     "#701C2E", "#7EBBE6", "#FFFFFF", 72, "4-3-3"),
    ("qns", "Queensferry Athletic", "Queensferry", "Queensferry", "Tollgate Stadium",
     "#3D195B", "#FFFFFF", "#FFFFFF", 75, "4-2-3-1"),
    ("rav", "Ravenscar", "Ravenscar", "Ravenscar", "Cliff Top",
     "#101820", "#D4AF37", "#D4AF37", 62, "3-5-2"),
    ("stn", "Stonebridge Town", "Stonebridge", "Stonebridge", "The Arches",
     "#A6192E", "#00205B", "#FFFFFF", 68, "4-4-2"),
    ("thr", "Thornbury Park", "Thornbury", "Thornbury", "Bramble Lane",
     "#228B22", "#000000", "#FFFFFF", 66, "4-3-3"),
    ("wyc", "Wychwood", "Wychwood", "Wychwood", "Oakfold Ground",
     "#F28C28", "#0E2240", "#0E2240", 61, "4-2-3-1"),
]  # fmt: skip

RIVALS: list[tuple[str, str]] = [
    ("ash", "brk"), ("cal", "els"), ("dun", "fen"), ("gry", "hrt"), ("kes", "lum"),
    ("mrw", "pen"), ("nor", "ott"), ("qns", "rav"), ("stn", "thr"), ("ivy", "wyc"),
]  # fmt: skip

FIRST_NAMES = [
    "Tomas", "Rafe", "Idris", "Mateo", "Kofi", "Luka", "Oren", "Silas", "Jonah", "Emil",
    "Bram", "Caio", "Nico", "Yannick", "Aurel", "Dario", "Felix", "Kian", "Lior", "Marek",
    "Osei", "Pavel", "Ruben", "Soren", "Teo", "Ulrik", "Vito", "Wren", "Ezra", "Hugo",
    "Anselm", "Bastien", "Cyrus", "Davor", "Elio", "Florin", "Gideon", "Halvard", "Ilya",
    "Jory", "Kasimir", "Leandro", "Milan", "Noam", "Otto", "Piet", "Quentin", "Rasmus",
    "Sami", "Tiago", "Uriel", "Valen", "Wilmer", "Yusuf", "Zoran", "Amadou", "Benedikt",
    "Callum", "Dmitri", "Eamon", "Femi", "Gaspard", "Hamza", "Ignas", "Joaquin", "Kwame",
]  # fmt: skip
_SURNAME_HEADS = [
    "Ash", "Brack", "Cald", "Dun", "Ell", "Fen", "Garr", "Hal", "Ivers", "Kest", "Lath",
    "Morr", "Nett", "Orr", "Penn", "Quill", "Ross", "Sall", "Thorn", "Vall", "Wex", "Yarr",
    "Brenn", "Corv", "Drav", "Holl", "Kil", "Marr", "Strand", "Tull", "Abern", "Belc",
    "Crom", "Dew", "Est", "Fall", "Gorr", "Hesk", "Jess", "Korv", "Lunn", "Merr",
]  # fmt: skip
_SURNAME_TAILS = [
    "ow", "ley", "by", "wick", "ton", "more", "ard", "ett", "ane", "ick", "holt", "mere",
    "well", "stead", "ing", "worth", "ham", "combe", "den", "ford", "ander", "is", "ovic",
    "elli", "anu", "ez", "ade",
]  # fmt: skip

# Players the sample match's story depends on. Same names and key ratings here.
OVERRIDES: dict[str, dict[str, Any]] = {
    "ash-09": {"name": "Idris Varrow", "short_name": "Varrow", "top_speed_kmh": 34.6,
               "attributes": {"pace": 91, "acceleration": 89, "finishing": 84}},
    "ash-08": {"name": "Teo Kestley", "short_name": "Kestley",
               "attributes": {"passing": 88, "vision": 90}},
    "ash-06": {"name": "Osei Brennick", "short_name": "Brennick"},
    "ash-03": {"name": "Rafe Halloway", "short_name": "Halloway",
               "attributes": {"discipline": 38, "tackling": 77}},
    "ash-01": {"name": "Bram Ostrand", "short_name": "Ostrand"},
    "brk-01": {"name": "Soren Quillan", "short_name": "Quillan"},
    "brk-08": {"name": "Caio Penthorne", "short_name": "Penthorne"},
    "brk-10": {"name": "Luka Dravik", "short_name": "Dravik"},
}  # fmt: skip

# Attribute offsets from the club rating, by detailed role.
_PROFILES: dict[str, dict[str, int]] = {
    "GK": {"keeping": 12, "pace": -14, "acceleration": -10, "passing": -6, "finishing": -40,
           "tackling": -30, "vision": -8},
    "CB": {"tackling": 9, "pace": -4, "finishing": -22, "passing": -4, "vision": -6},
    "RB": {"pace": 6, "stamina": 6, "tackling": 3, "finishing": -15},
    "LB": {"pace": 6, "stamina": 6, "tackling": 3, "finishing": -15},
    "FB": {"pace": 5, "stamina": 5, "tackling": 3, "finishing": -15},
    "RWB": {"pace": 7, "stamina": 8, "finishing": -10},
    "LWB": {"pace": 7, "stamina": 8, "finishing": -10},
    "DM": {"tackling": 7, "passing": 3, "stamina": 4, "finishing": -12},
    "CM": {"passing": 5, "vision": 4, "stamina": 5, "finishing": -6},
    "AM": {"vision": 8, "passing": 6, "finishing": 2, "tackling": -12},
    "RM": {"pace": 6, "stamina": 5, "passing": 2, "tackling": -6},
    "LM": {"pace": 6, "stamina": 5, "passing": 2, "tackling": -6},
    "RW": {"pace": 9, "acceleration": 9, "tackling": -16, "finishing": 1},
    "LW": {"pace": 9, "acceleration": 9, "tackling": -16, "finishing": 1},
    "W": {"pace": 8, "acceleration": 8, "tackling": -16},
    "ST": {"finishing": 10, "pace": 3, "tackling": -20, "passing": -4},
}  # fmt: skip
_ATTRIBUTES = ("pace", "acceleration", "passing", "vision", "finishing", "tackling",
               "keeping", "discipline", "stamina")  # fmt: skip


def _surnames(rng: random.Random) -> list[str]:
    names = sorted({h + t for h in _SURNAME_HEADS for t in _SURNAME_TAILS})
    reserved = {o["short_name"] for o in OVERRIDES.values()}
    names = [n for n in names if n not in reserved]
    rng.shuffle(names)
    return names


def build_league(seed: int = 7) -> League:
    """The league universe. The same seed always gives the same squads."""
    rng = random.Random(seed)
    surnames = _surnames(rng)
    rivals: dict[str, list[str]] = {}
    for a, b in RIVALS:
        rivals.setdefault(a, []).append(b)
        rivals.setdefault(b, []).append(a)
    clubs: list[dict[str, Any]] = []
    for tid, name, short, city, stadium, c1, c2, c3, rating, formation in _CLUBS:
        roster = [(s, p, r) for s, p, r, _ in FORMATIONS[formation]] + BENCH
        squad = [
            _player(rng, f"{tid}-{shirt:02d}", shirt, position, role, rating, surnames)
            for shirt, position, role in roster
        ]
        clubs.append(
            {
                "team_id": tid,
                "name": name,
                "short_name": short,
                "city": city,
                "stadium": stadium,
                "colours": {"primary": c1, "secondary": c2, "text": c3},
                "rating": rating,
                "formation": formation,
                "rival_ids": rivals.get(tid, []),
                "squad": squad,
            }
        )
    return League.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "league_id": LEAGUE_ID,
            "name": LEAGUE_NAME,
            "clubs": clubs,
        }
    )


def _player(
    rng: random.Random,
    pid: str,
    shirt: int,
    position: str,
    role: str,
    rating: int,
    surnames: list[str],
) -> dict[str, Any]:
    profile = _PROFILES.get(role, {})
    # Bench players are a little weaker than starters.
    base = rating - (3 if shirt > 11 else 0)
    attrs = {
        key: max(15, min(97, base + profile.get(key, 0) + rng.randint(-7, 7)))
        for key in _ATTRIBUTES
    }
    if position != "GK":
        attrs["keeping"] = rng.randint(8, 22)
    attrs["discipline"] = rng.randint(38, 92)
    pace = attrs["pace"]
    top_speed = 26.5 + pace * 0.04 if position == "GK" else 28.6 + pace * 0.074
    last = surnames.pop()
    player: dict[str, Any] = {
        "player_id": pid,
        "name": f"{rng.choice(FIRST_NAMES)} {last}",
        "short_name": last,
        "shirt": shirt,
        "position": position,
        "role": role,
        "foot": rng.choice(["right", "right", "right", "left", "left", "both"]),
        "top_speed_kmh": round(min(top_speed, 36.4), 1),
        "attributes": attrs,
    }
    override = OVERRIDES.get(pid, {})
    player.update({k: v for k, v in override.items() if k != "attributes"})
    player["attributes"].update(override.get("attributes", {}))
    return player
