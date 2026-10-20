"""Lead-lag: which team stats move BEFORE field tilt swings? Compare [t-10,t-5) vs [t-20,t-10) where the swing is measured
as [t,t+5) vs [t-10,t). Leading features are candidates for causes; reported vs random windows in SD units."""
import pickle, sys, random, statistics as st
D = pickle.load(open(sys.argv[1], 'rb')); F, M = D['F'], D['matches']
random.seed(5)
def w(mid, t, a, b, k): return sum(F.get((mid, t, m), {}).get(k, 0) for m in range(max(a, 0), b))
def opp(mid, t): return [x for x in M[mid]['teams'] if x != t][0]
def ft(mid, t, a, b):
    x, y = w(mid, t, a, b, 'ft_events'), w(mid, opp(mid, t), a, b, 'ft_events'); return x / (x + y) if x + y >= 8 else None
def feats(mid, g, a, b):
    l = opp(mid, g); f = {}
    gp, lp = w(mid, g, a, b, 'passes'), w(mid, l, a, b, 'passes')
    f['gainer pass share'] = gp / max(1, gp + lp)
    f['loser pass accuracy'] = w(mid, l, a, b, 'acc') / lp if lp >= 5 else None
    f['gainer pass accuracy'] = w(mid, g, a, b, 'acc') / gp if gp >= 5 else None
    dd = w(mid, g, a, b, 'def_duels'); f['gainer defending height'] = w(mid, g, a, b, 'def_x') / dd if dd >= 2 else None
    dl = w(mid, l, a, b, 'def_duels'); f['loser defending height'] = w(mid, l, a, b, 'def_x') / dl if dl >= 2 else None
    gd_, ld = w(mid, g, a, b, 'duels_won'), w(mid, l, a, b, 'duels_won')
    f['gainer duels won share'] = gd_ / (gd_ + ld) if gd_ + ld >= 5 else None
    f['gainer duels/min'] = w(mid, g, a, b, 'duels') / (b - a)
    f['gainer metres progressed/min'] = w(mid, g, a, b, 'prog_m') / (b - a)
    f['loser fouls/min'] = w(mid, l, a, b, 'fouls') / (b - a)
    return f
def swings():
    out = []
    for mid, m in M.items():
        hm = m['teams'][0]; last = -99
        for t in range(25, 86):
            now, before = ft(mid, hm, t, t + 5), ft(mid, hm, t - 10, t)
            if now is None or before is None: continue
            if abs(now - before) >= 0.30 and t - last >= 10:
                out.append((mid, t, hm if now > before else opp(mid, hm))); last = t
    return out
S = swings(); R = [(m, random.randint(25, 85), random.choice(M[m]['teams'])) for m in random.choices(list(M), k=4000)]
def lead(lst):
    o = {}
    for mid, t, g in lst:
        a, b = feats(mid, g, t - 20, t - 10), feats(mid, g, t - 10, t - 5)
        for k in a:
            if a[k] is not None and b[k] is not None: o.setdefault(k, []).append(b[k] - a[k])
    return o
LS, LR = lead(S), lead(R)
print(f'swings: {len(S)}')
for k in sorted(LS, key=lambda k: -abs(st.mean(LS[k]) - st.mean(LR[k])) / st.pstdev(LR[k])):
    eff = (st.mean(LS[k]) - st.mean(LR[k])) / st.pstdev(LR[k])
    print(f'{k:32s} lead change {st.mean(LS[k]):+.3f} vs random {st.mean(LR[k]):+.3f}  effect {eff:+.2f} SD')
# Also: field tilt itself trending before? (pre-trend)
pre = [ft(m, g, t - 10, t - 5) - ft(m, g, t - 20, t - 10) for m, t, g in S if ft(m, g, t - 10, t - 5) is not None and ft(m, g, t - 20, t - 10) is not None]
prr = [ft(m, g, t - 10, t - 5) - ft(m, g, t - 20, t - 10) for m, t, g in R if ft(m, g, t - 10, t - 5) is not None and ft(m, g, t - 20, t - 10) is not None]
print(f'gainer field tilt pre-trend: {st.mean(pre):+.3f} vs random {st.mean(prr):+.3f} ({(st.mean(pre)-st.mean(prr))/st.pstdev(prr):+.2f} SD)')
