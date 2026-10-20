"""How often does each event type lead to a momentum shift, and does the playstyle change first?"""
import pickle, sys, random, statistics as st
D = pickle.load(open(sys.argv[1], 'rb')); F, M, goals, reds = D['F'], D['matches'], D['goals'], D['reds']
random.seed(4)
def w(mid, t, a, b, k): return sum(F.get((mid, t, m), {}).get(k, 0) for m in range(a, b))
def opp(mid, t): return [x for x in M[mid]['teams'] if x != t][0]
def ft(mid, t, a, b):
    x, y = w(mid, t, a, b, 'ft_events'), w(mid, opp(mid, t), a, b, 'ft_events'); return x / (x + y) if x + y >= 8 else None
SIZE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.20
def shifted(mid, tid, mn):
    """Sustained shift: tid's field tilt over the 10 min after mn differs from the 10 min before by >= SIZE."""
    before, after = ft(mid, tid, mn - 10, mn), ft(mid, tid, mn + 1, mn + 11)
    if before is None or after is None: return None
    return abs(after - before) >= SIZE
def gd(mid, t, mn): return sum(1 if g[1] == t else -1 for g in goals.get(mid, []) if g[0] < mn)
def rate(rows):
    v = [r for r in rows if r is not None]; return f'{sum(v)/len(v):.0%} (n={len(v)})'
out = {}
out['random minute (baseline)'] = [shifted(m, random.choice(M[m]['teams']), random.randint(15, 75)) for m in random.choices(list(M), k=3000)]
out['goal (conceding team)'] = [shifted(mid, opp(mid, s), mn + 1) for mid, gl in goals.items() for mn, s in gl if 10 < mn < 78]
out['red card (10-man team)'] = [shifted(mid, t, mn + 1) for mid, rl in reds.items() for mn, t in rl if 10 < mn < 78]
out['substitution (subbing team)'] = [shifted(mid, t, mn) for mid, m in M.items() for t, mn, _, _ in m['subs'] if 46 < mn < 78]
out['double/triple sub same minute'] = []
for mid, m in M.items():
    by = {}
    for t, mn, _, _ in m['subs']: by.setdefault((t, mn), 0); by[(t, mn)] += 1
    out['double/triple sub same minute'] += [shifted(mid, t, mn) for (t, mn), c in by.items() if c >= 2 and 46 < mn < 78]
out['half-time (each team)'] = [shifted(mid, t, 45) for mid, m in M.items() for t in m['teams']]
for k, v in out.items(): print(f'{k:32s} sustained shift (10 min after vs before): {rate(v)}')
# Chain test for red cards: does the 10-man team's style change (deeper defending, fewer passes) and does that precede territory loss?
print('\nRed card chain (10-man team, 15 min before vs after):')
for k, lab in (('def_x', 'defending height'), ('passes', 'passes/min'), ('ft_events', 'final-third events/min')):
    d = []
    for mid, rl in reds.items():
        for mn, t in rl:
            if not 15 < mn < 75: continue
            if k == 'def_x':
                a, b = w(mid, t, mn - 15, mn, 'def_duels'), w(mid, t, mn + 1, mn + 16, 'def_duels')
                if a and b: d.append(w(mid, t, mn + 1, mn + 16, 'def_x') / b - w(mid, t, mn - 15, mn, 'def_x') / a)
            else: d.append((w(mid, t, mn + 1, mn + 16, k) - w(mid, t, mn - 15, mn, k)) / 15)
    print(f'  {lab}: median change {st.median(d):+.2f} (n={len(d)}), share where it fell {sum(x < 0 for x in d)/len(d):.0%}')
