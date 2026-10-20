import pickle, sys, random, statistics as st, collections
D = pickle.load(open(sys.argv[1], 'rb'))
F, P, goals, reds, M = D['F'], D['P'], D['goals'], D['reds'], D['matches']
random.seed(1)
def win(mid, tid, a, b, k):
    return sum(F.get((mid, tid, m), {}).get(k, 0) for m in range(a, b))
def share(mid, t, o, a, b, k):
    x, y = win(mid, t, a, b, k), win(mid, o, a, b, k)
    return x / (x + y) if x + y >= 8 else None
def opp(mid, t): return [x for x in M[mid]['teams'] if x != t][0]
def gd(mid, t, mn):
    return sum(1 if g[1] == t else -1 for g in goals.get(mid, []) if g[0] < mn)
def eventful(mid, a, b):
    return any(a <= g[0] < b for g in goals.get(mid, [])) or any(a <= r[0] < b for r in reds.get(mid, []))
def q(v): v = sorted(v); n = len(v); return f"median {st.median(v):+.3f}, IQR [{v[n//4]:+.3f}, {v[3*n//4]:+.3f}], mean {st.mean(v):+.3f}, n={n}"
out = []
def p(*a): out.append(' '.join(str(x) for x in a))

# --- 1. Momentum shifts: field tilt (final-third events share) 5-min window vs previous 10 min
p('## Shifts'); shifts = []
for mid, m in M.items():
    home = m['teams'][0]; last = -99
    for t in range(15, 92):
        if t in range(45, 52): pass
        now = share(mid, home, opp(mid, home), t - 5, t, 'ft_events'); before = share(mid, home, opp(mid, home), t - 15, t - 5, 'ft_events')
        if now is None or before is None: continue
        if abs(now - before) >= 0.30 and t - last >= 10:
            gainer = home if now > before else opp(mid, home)
            shifts.append((mid, t, gainer, abs(now - before))); last = t
p('shifts', len(shifts), 'per match', len(shifts) / len(M))
def causes(mid, t, gainer):
    c = []
    loser = opp(mid, gainer)
    for g in goals.get(mid, []):
        if t - 15 <= g[0] < t: c.append('goal_by_loser' if g[1] == loser else 'goal_by_gainer')
    for s in M[mid]['subs']:
        if t - 15 <= s[1] < t: c.append('sub_by_gainer' if s[0] == gainer else 'sub_by_loser')
    for r in reds.get(mid, []):
        if t - 15 <= r[0] < t: c.append('red_to_loser' if r[1] == loser else 'red_to_gainer')
    if 45 <= t < 60: c.append('half_time')
    return set(c)
cc = collections.Counter(); none = 0
for s in shifts:
    c = causes(*s[:3]); cc.update(c); none += not c
# baseline: random (match, minute, team) windows
base = collections.Counter(); N = 4000
for _ in range(N):
    mid = random.choice(list(M)); t = random.randint(15, 91); g = random.choice(M[mid]['teams']); base.update(causes(mid, t, g))
for k in sorted(set(cc) | set(base)):
    p(f'{k}: {cc[k]/len(shifts):.1%} of shifts vs {base[k]/N:.1%} of random windows')
p(f'no candidate trigger in prior 15 min: {none/len(shifts):.1%}')
p('shifts by gainer game state:', collections.Counter(('losing' if gd(s[0], s[2], s[1]) < 0 else 'drawing' if gd(s[0], s[2], s[1]) == 0 else 'winning') for s in shifts))

# --- 2. Substitution effect on the subbing team (10 min after vs 10 before), quiet windows only, vs control
p('\n## Subs')
def delta(mid, t, tid, k, w=10):
    o = opp(mid, tid); a = share(mid, tid, o, t - w, t, k); b = share(mid, tid, o, t, t + w, k)
    return None if a is None or b is None else b - a
for state in ('losing', 'drawing', 'winning'):
    ds = []
    for mid, m in M.items():
        for (tid, mn, pin, pout) in m['subs']:
            mn = min(mn, 90)
            if mn < 50 or mn > 85 or eventful(mid, mn - 10, mn + 10): continue
            g = gd(mid, tid, mn); s = 'losing' if g < 0 else 'drawing' if g == 0 else 'winning'
            if s != state: continue
            d = delta(mid, mn, tid, 'ft_events');
            if d is not None: ds.append(d)
    ctrl = []
    for _ in range(3000):
        mid = random.choice(list(M)); tid = random.choice(M[mid]['teams']); mn = random.randint(55, 80)
        if eventful(mid, mn - 10, mn + 10) or any(abs(s[1] - mn) < 12 and s[0] == tid for s in M[mid]['subs']): continue
        g = gd(mid, tid, mn); s = 'losing' if g < 0 else 'drawing' if g == 0 else 'winning'
        if s != state: continue
        d = delta(mid, mn, tid, 'ft_events')
        if d is not None: ctrl.append(d)
    p(f'{state}: sub field-tilt delta {q(ds)}; control {q(ctrl)}')
# player-level: sub-in vs replaced (rates per minute)
ins, outs = collections.defaultdict(list), collections.defaultdict(list)
for mid, m in M.items():
    for (tid, mn, pin, pout) in m['subs']:
        if mn < 50 or mn > 80: continue
        for k in ('events', 'passes', 'duels'):
            o = sum(P.get((mid, pout, x), {}).get(k, 0) for x in range(mn - 15, mn)) / 15
            i = sum(P.get((mid, pin, x), {}).get(k, 0) for x in range(mn, mn + 15)) / 15
            outs[k].append(o); ins[k].append(i)
for k in ins: p(f'{k}/min: replaced player last 15 min {st.mean(outs[k]):.2f} -> sub first 15 min {st.mean(ins[k]):.2f} ({st.mean(ins[k])/st.mean(outs[k])-1:+.0%})')

# --- 3. Half-time: 2H first 10 vs 1H last 10
p('\n## Half-time')
for state in ('losing', 'drawing', 'winning'):
    ds = []; big = 0
    for mid, m in M.items():
        for tid in m['teams']:
            g = gd(mid, tid, 45); s = 'losing' if g < 0 else 'drawing' if g == 0 else 'winning'
            if s != state or eventful(mid, 35, 56): continue
            o = opp(mid, tid); a = share(mid, tid, o, 35, 45, 'ft_events'); b = share(mid, tid, o, 45, 55, 'ft_events')
            if a is None or b is None: continue
            ds.append(b - a); big += abs(b - a) >= 0.2
    p(f'{state} at HT: field-tilt delta {q(ds)}; |delta|>=0.20 in {big/len(ds):.0%}')

# --- 4. After conceding: conceding team, 10 after vs 10 before
p('\n## After a goal')
for k in ('ft_events', 'passes'):
    ds = []
    for mid, gl in goals.items():
        for (mn, scorer) in gl:
            if mn < 12 or mn > 80: continue
            if any(0 < abs(g[0] - mn) <= 10 for g in gl) or any(abs(r[0]-mn) <= 10 for r in reds.get(mid, [])): continue
            d = delta(mid, mn + 1, opp(mid, scorer), k)
            if d is not None: ds.append(d)
    p(f'conceding team {k} share delta: {q(ds)}')

# --- 5. Red cards: team down to 10, 15 after vs 15 before
p('\n## Red cards')
ds = []
for mid, rl in reds.items():
    for (mn, tid) in rl:
        if 15 < mn < 75:
            d = delta(mid, mn + 1, tid, 'passes', 15)
            if d is not None: ds.append(d)
p(f'team with red: pass share delta {q(ds)}')

# --- 6. Game state territory: winning vs losing late
p('\n## Late game by state (minutes 75-90 share)')
by = collections.defaultdict(list)
for mid, m in M.items():
    for tid in m['teams']:
        g = gd(mid, tid, 75); s = 'losing' if g < 0 else 'drawing' if g == 0 else 'winning'
        a = share(mid, tid, opp(mid, tid), 75, 95, 'passes'); b = share(mid, tid, opp(mid, tid), 75, 95, 'ft_events')
        if a is not None: by[s].append((a, b))
for s, v in by.items(): p(f'{s}: pass share {st.mean(x[0] for x in v):.1%}, field tilt {st.mean(x[1] for x in v):.1%}, n={len(v)}')

# --- 7. Fatigue: players who played 90, passes+duels per min by 15-min block
p('\n## Per-player activity over the match (full-90 outfield players)')
full = collections.defaultdict(lambda: [0]*7)
players_full = set()
subbed = {(mid, s[3]) for mid, m in M.items() for s in m['subs']} | {(mid, s[2]) for mid, m in M.items() for s in m['subs']}
for (mid, pid, mn), c in P.items():
    if (mid, pid) in subbed or pid == 0: continue
    b = min(mn // 15, 6) if mn < 90 else 5
    full[(mid, pid)][b] += c.get('events', 0)
blocks = [st.mean(v[i] for v in full.values()) / 15 for i in range(6)]
p('events/min by 15-min block:', ' '.join(f'{b:.2f}' for b in blocks))
print('\n'.join(out))
