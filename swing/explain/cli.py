"""swing-explain: run the Watcher, the specialists and the Explainer over any match folder.

    swing-explain out/matches/ash-brk-7                 # print the cards that would go on screen
    swing-explain out/matches/ash-brk-7 --json cards.json

The folder only needs match.json and events.jsonl in the public format (docs/data-format.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .explainer import explain_match
from .match import load


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--json", type=Path, help="write every card, with all findings, to this file")
    ap.add_argument("--all", action="store_true", help="also print cards the Director would hold back")
    args = ap.parse_args()
    md = load(args.folder)
    result = explain_match(md)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1) + "\n")
    home, away = md.teams
    print(f"{md.short(home)} {'-'.join(map(str, md.meta.get('final_score', [])))} {md.short(away)}")
    for c in result["cards"]:
        if not (c["show"] or args.all):
            continue
        mo = c["momentum"]
        bar = f"{mo['before']:.0f}% -> {mo['now']:.0f}% {md.short(home)}"
        print(f"\n{c['clock']:>7}  {c['anchor']['label']}   [{c['mode']}, {c['cause']['kind']}]   tilt {bar}")
        for s in c["stats"]:
            who = s.get("name") or md.short(s["team"])
            vs = f" (vs {s['vs']})" if s.get("vs") else " (match so far)"
            print(f"         {who:>12}  {s['label']}: {s['after']:g} {s['unit']}  was {s['before']:g}{vs}")


if __name__ == "__main__":
    main()
