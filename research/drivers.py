import pickle, sys, random, statistics as st
D = pickle.load(open(sys.argv[1], 'rb')); F, M = D['F'], D['matches']
random.seed(3)
def w(mid, t, a, b, k): return sum(F.get((mid, t, m), {}).get(k, 0) for m in range(a, b))
def opp(mid, t): return [x for x in M[mid]['teams'] if x != t][0]
def feats(mid, g, a, b):
    l = opp(mid, g); f = {}
    gp, lp = w(mid, g, a, b, 'passes'), w(mid, l, a, b, 'passes')
    f['gainer pass share'] = gp / max(1, gp + lp)
    f['loser pass accuracy'] = w(mid, l, a, b, 'acc') / max(1, lp)
    f['gainer pass accuracy'] = w(mid, g, a, b, 'acc') / max(1, gp)
    dd = w(mid, g, a, b, 'def_duels'); f['gainer defending height (x)'] = w(mid, g, a, b, 'def_x') / dd if dd else None
    dl = w(mid, l, a, b, 'def_duels'); f['loser defending height (x)'] = w(mid, l, a, b, 'def_x') / dl if dl else None
    f['loser own-half pass share'] = w(mid, l, a, b, 'own_half_passes') / max(1, lp)
    f['gainer metres progressed/min'] = w(mid, g, a, b, 'prog_m') / (b - a)
    f['gainer duels won share'] = w(mid, g, a, b, 'duels_won') / max(1, w(mid, g, a, b, 'duels_won') + w(mid, l, a, b, 'duels_won'))
    f['loser fouls/min'] = w(mid, l, a, b, 'fouls') / (b - a)
    return f
def ft(mid, t, a, b):
    x, y = w(mid, t, a, b, 'ft_events'), w(mid, opp(mid, t), a, b, 'ft_events'); return x / (x + y) if x + y >= 8 else None
shifts, rand = [], []
for mid, m in M.items():
    hm = m['teams'][0]; last = -99
    for t in range(15, 92):
        now, before = ft(mid, hm, t - 5, t), ft(mid, hm, t - 15, t - 5)
        if now is None or before is None: continue
        if abs(now - before) >= 0.30 and t - last >= 10:
            shifts.append((mid, t, hm if now > before else opp(mid, hm))); last = t
for _ in range(3000):
    mid = random.choice(list(M)); rand.append((mid, random.randint(15, 91), random.choice(M[mid]['teams'])))
def deltas(lst):
    out = {}
    for mid, t, g in lst:
        a, b = feats(mid, g, t - 15, t - 5), feats(mid, g, t - 5, t)
        for k in a:
            if a[k] is not None and b[k] is not None: out.setdefault(k, []).append(b[k] - a[k])
    return out
S, R = deltas(shifts), deltas(rand)
for k in S:
    sd = st.pstdev(R[k])
    print(f'{k:34s} shift mean {st.mean(S[k]):+.3f}  random {st.mean(R[k]):+.3f}  effect {((st.mean(S[k])-st.mean(R[k]))/sd):+.2f} SD')
