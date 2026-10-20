import pickle, sys, random
D = pickle.load(open(sys.argv[1], 'rb')); F, M = D['F'], D['matches']
random.seed(2)
def detect(h, a):
    n = 0; last = -99
    for t in range(15, 92):
        def s(x, y):
            u, v = sum(h[x:y]), sum(a[x:y]); return u / (u + v) if u + v >= 8 else None
        now, before = s(t-5, t), s(t-15, t-5)
        if now is None or before is None: continue
        if abs(now - before) >= 0.30 and t - last >= 10: n += 1; last = t
    return n
real = sim = 0; sizes = []
for mid, m in M.items():
    hm, aw = m['teams']
    h = [F.get((mid, hm, t), {}).get('ft_events', 0) for t in range(96)]
    a = [F.get((mid, aw, t), {}).get('ft_events', 0) for t in range(96)]
    sizes.append(sum(h[0:5]) + sum(a[0:5]))
    p = sum(h) / max(1, sum(h) + sum(a))
    real += detect(h, a)
    for _ in range(5):
        hs = [sum(random.random() < p for _ in range(h[t] + a[t])) for t in range(96)]
        as_ = [h[t] + a[t] - hs[t] for t in range(96)]
        sim += detect(hs, as_) / 5
print(f'real shifts/match {real/len(M):.2f}; pure-noise shifts/match {sim/len(M):.2f}; mean final-third events per 5 min (both teams) {sum(sizes)/len(sizes):.1f}')
