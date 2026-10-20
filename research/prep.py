"""Build per team-minute aggregates from Wyscout England events -> pickle."""
import json, sys, pickle, collections
d = sys.argv[1]
ev = json.load(open(f'{d}/events_England.json'))
ms = json.load(open(f'{d}/matches_England.json'))
GOAL, ACC, RED, SECOND_Y, OWN = 101, 1801, 1701, 1703, 102
matches = {}
for m in ms:
    teams = list(m['teamsData'].keys())
    subs = []
    for tid, td in m['teamsData'].items():
        for s in (td['formation'].get('substitutions') or []):
            if isinstance(s, dict):
                subs.append((int(tid), s['minute'], s['playerIn'], s['playerOut']))
    matches[m['wyId']] = dict(teams=[int(t) for t in teams], subs=subs,
                              side={int(t): td['side'] for t, td in m['teamsData'].items()})
# per (match, team, minute) counters; minute = 0..44 1H, 45..89+ 2H (cap stoppage into last minute)
F = collections.defaultdict(lambda: collections.Counter())
goals = collections.defaultdict(list); reds = collections.defaultdict(list)
P = collections.defaultdict(lambda: collections.Counter())  # (match, player, minute)
for e in ev:
    if e['matchPeriod'] not in ('1H', '2H'): continue
    mn = int(e['eventSec'] // 60)
    mn = min(mn, 44) + (45 if e['matchPeriod'] == '2H' else 0) if e['matchPeriod']=='1H' else 45 + min(mn, 49)
    key = (e['matchId'], e['teamId'], mn)
    tags = {t['id'] for t in e['tags']}
    x = e['positions'][0]['x'] if e['positions'] else 50
    c = F[key]; pc = P[(e['matchId'], e['playerId'], mn)]
    c['events'] += 1; pc['events'] += 1
    if e['eventName'] == 'Pass':
        c['passes'] += 1; pc['passes'] += 1
        if ACC in tags: c['acc'] += 1; pc['acc'] += 1
        if x >= 66.7: c['ft_passes'] += 1
        if x < 50: c['own_half_passes'] += 1
        if len(e['positions']) > 1:
            c['prog_m'] += max(0, e['positions'][1]['x'] - x) * 1.05
    elif e['eventName'] == 'Duel':
        c['duels'] += 1; pc['duels'] += 1
        if 703 in tags: c['duels_won'] += 1; pc['duels_won'] += 1
        if e['subEventName'] in ('Ground defending duel',) : c['def_duels'] += 1; c['def_x'] += x; pc['def_duels'] += 1
    elif e['eventName'] == 'Shot':
        c['shots'] += 1; pc['shots'] += 1
        if GOAL in tags: goals[e['matchId']].append((mn, e['teamId']))
    elif e['eventName'] == 'Foul':
        c['fouls'] += 1
        if RED in tags or SECOND_Y in tags: reds[e['matchId']].append((mn, e['teamId']))
    elif e['eventName'] == 'Free Kick' and e['subEventName'] == 'Penalty' and GOAL in tags:
        goals[e['matchId']].append((mn, e['teamId']))
    if x >= 66.7: c['ft_events'] += 1
    c['x_sum'] += x
# own goals: tag 102 on any event -> goal for the other team
for e in ev:
    if any(t['id'] == OWN for t in e['tags']) and e['matchPeriod'] in ('1H','2H'):
        mn = int(e['eventSec']//60); mn = min(mn,44) if e['matchPeriod']=='1H' else 45+min(mn,49)
        other = [t for t in matches[e['matchId']]['teams'] if t != e['teamId']][0]
        goals[e['matchId']].append((mn, other))
pickle.dump(dict(F={k: dict(v) for k, v in F.items()}, P={k: dict(v) for k, v in P.items()},
                 goals=dict(goals), reds=dict(reds), matches=matches), open(sys.argv[2], 'wb'))
print(len(F), sum(len(g) for g in goals.values()), 'goals', sum(len(r) for r in reds.values()), 'reds')
