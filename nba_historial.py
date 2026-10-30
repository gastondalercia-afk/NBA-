#!/usr/bin/env python3
"""Baja los partidos recientes de TODOS los jugadores de la NBA (PTS, REB, AST, minutos)
y genera nba_historial.json para cargarlo en el simulador ("Cargar historial").
Uso:  pip install nba_api   y despues   python nba_historial.py
Corre en tu computadora (nba.com bloquea muchos servidores en la nube)."""
import json, sys, time, datetime
try:
    from nba_api.stats.endpoints import leaguegamelog
except ImportError:
    sys.exit("Falta nba_api. Instalalo con:  pip install nba_api")

SEASONS = [("2026-27", 0), ("2025-26", 1)]   # (temporada, 0 = actual / 1 = anterior)
KEEP = {0: 20, 1: 15}                        # partidos a guardar por jugador y temporada

def fetch(season, kind="P"):
    for n in range(4):
        try:
            return leaguegamelog.LeagueGameLog(season=season, player_or_team_abbreviation=kind,
                       season_type_all_star="Regular Season", timeout=90).get_data_frames()[0]
        except Exception as e:
            print(f"  intento {n+1} fallo: {e}"); time.sleep(3 * (n + 1))
    return None


from collections import defaultdict
import pandas as pd

def compute_splits(pdf, tdf, flag, acc):
    """Con/sin cada jugador clave y descanso, a partir de los partidos completos de una temporada."""
    w = 1.0 if flag == 0 else 0.7              # la temporada pasada pesa menos
    tdf = tdf.copy(); tdf["GAME_DATE"] = pd.to_datetime(tdf["GAME_DATE"])
    pdf = pdf.copy(); pdf["MIN"] = pd.to_numeric(pdf["MIN"], errors="coerce").fillna(0)
    for T, g in tdf.groupby("TEAM_ABBREVIATION"):
        g = g.sort_values("GAME_DATE")
        dates = list(g["GAME_DATE"]); gids = list(g["GAME_ID"])
        total = {gid: 2 * int(pt) - int(pm) for gid, pt, pm in zip(gids, g["PTS"], g["PLUS_MINUS"])}
        bucket = {}
        for k, gid in enumerate(gids):
            rest = 3 if k == 0 else (dates[k] - dates[k - 1]).days - 1
            bucket[gid] = "b" if rest <= 0 else ("1" if rest == 1 else "2")
            a = acc["trest"][T][bucket[gid]]; a[0] += w; a[1] += w * total[gid]
        gidx = {gid: k for k, gid in enumerate(gids)}
        pg = pdf[pdf["TEAM_ABBREVIATION"] == T]
        byp = defaultdict(dict)
        for r in pg.itertuples():
            if r.GAME_ID in gidx and r.MIN > 0:
                byp[r.PLAYER_NAME][r.GAME_ID] = (r.MIN, int(r.PTS), int(r.REB), int(r.AST))
        for name, d in byp.items():                       # descanso por jugador
            for gid, (m, pt, rb, ast) in d.items():
                if m >= 8:
                    a = acc["rest"][name][bucket[gid]]
                    a[0] += w; a[1] += w * pt; a[2] += w * rb; a[3] += w * ast; a[4] += w * m
        keys = sorted(byp, key=lambda n: -sum(v[0] for v in byp[n].values()))[:9]
        for X in keys:
            played = {gid for gid, v in byp[X].items() if v[0] >= 10}
            if len(played) < 8: continue
            ix = [gidx[gid] for gid in played]
            window = gids[min(ix):max(ix) + 1]
            con = [gid for gid in window if gid in played]; sin = [gid for gid in window if gid not in played]
            if len(sin) < 3: continue
            t = acc["spl"][T][X]["t"]
            t[0] += w * len(con); t[1] += w * sum(total[x] for x in con); t[2] += w * len(sin); t[3] += w * sum(total[x] for x in sin)
            for Y, dy in byp.items():
                if Y == X or len(dy) < 12: continue
                a = [v for x in con if x in dy and (v := dy[x])[0] >= 10]
                b = [v for x in sin if x in dy and (v := dy[x])[0] >= 10]
                if len(a) < 4 or len(b) < 2: continue
                s = acc["spl"][T][X]["p"][Y]
                s[0] += w * len(a); s[5] += w * len(b)
                for q in range(4):                          # pts, reb, ast, min
                    s[1 + q] += w * sum(v[(1, 2, 3, 0)[q]] for v in a)
                    s[6 + q] += w * sum(v[(1, 2, 3, 0)[q]] for v in b)

def finish_splits(acc):
    r1 = lambda x: round(x, 1)
    spl = {}
    for T, xs in acc["spl"].items():
        for X, d in xs.items():
            t = d["t"]
            if t[0] < 5 or t[2] < 3: continue
            ps = {}
            for Y, s in d["p"].items():
                if s[0] < 4 or s[5] < 2: continue
                ps[Y] = [round(s[0]), round(s[5])] + [r1(s[1 + q] / s[0]) for q in range(4)] + [r1(s[6 + q] / s[5]) for q in range(4)]
            if ps:
                spl.setdefault(T, {})[X] = {"n": [round(t[0]), round(t[2])], "t": [r1(t[1] / t[0]), r1(t[3] / t[2])], "p": ps}
    rest = {n: {b: [round(a[0])] + [r1(a[q] / a[0]) for q in range(1, 5)] for b, a in bs.items() if a[0] >= 2} for n, bs in acc["rest"].items()}
    trest = {T: {b: [round(a[0]), r1(a[1] / a[0])] for b, a in bs.items() if a[0] >= 2} for T, bs in acc["trest"].items()}
    return spl, rest, trest

players = {}
RAW = {}
acc = {"spl": defaultdict(lambda: defaultdict(lambda: {"t": [0, 0, 0, 0], "p": defaultdict(lambda: [0] * 10)})),
       "rest": defaultdict(lambda: defaultdict(lambda: [0] * 5)), "trest": defaultdict(lambda: defaultdict(lambda: [0, 0]))}
for season, flag in SEASONS:
    print("Bajando", season, "...")
    df = fetch(season)
    if df is None or df.empty:
        print("  sin datos para", season); continue
    RAW[flag] = {"P": df}
    df = df.sort_values("GAME_DATE", ascending=False)
    for r in df.itertuples():
        mn = r.MIN
        try: mn = float(mn)
        except Exception: mn = 0
        p = players.setdefault(r.PLAYER_NAME, {"n": r.PLAYER_NAME, "tm": r.TEAM_ABBREVIATION, "g": []})
        if flag == 0 and not p["g"]: p["tm"] = r.TEAM_ABBREVIATION
        if sum(1 for g in p["g"] if g[6] == flag) >= KEEP[flag]: continue
        # [fecha, minutos, pts, reb, ast, local(1/0), temporada(0 actual / 1 anterior)]
        p["g"].append([r.GAME_DATE[:10], round(mn, 1), int(r.PTS), int(r.REB), int(r.AST),
                       0 if "@" in r.MATCHUP else 1, flag])
    time.sleep(1)

# partidos de cada equipo (puntos a favor y en contra) para el Over/Under
teams = {}
for season, flag in SEASONS:
    print("Bajando equipos", season, "...")
    df = fetch(season, "T")
    if df is None or df.empty: continue
    if flag in RAW: compute_splits(RAW[flag]["P"], df, flag, acc)
    df = df.sort_values("GAME_DATE", ascending=False)
    for r in df.itertuples():
        t = teams.setdefault(r.TEAM_ABBREVIATION, [])
        if sum(1 for g in t if g[4] == flag) >= (20 if flag == 0 else 12): continue
        # [fecha, puntos a favor, puntos en contra, local(1/0), temporada(0 actual / 1 anterior)]
        t.append([r.GAME_DATE[:10], int(r.PTS), int(r.PTS - r.PLUS_MINUS), 0 if "@" in r.MATCHUP else 1, flag])
    time.sleep(1)

spl, rest, trest = finish_splits(acc)
out = {"generated": datetime.date.today().isoformat(), "players": list(players.values()), "teams": teams, "splits": spl, "rest": rest, "trest": trest}
with open("nba_historial.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(f"Listo: {len(players)} jugadores, {sum(len(v) for v in spl.values())} jugadores clave con datos con/sin, guardados en nba_historial.json")
