"""Exit and re-entry tests for the efficiency-ratio trend system, DEVELOPMENT YEARS ONLY (2007-12-31 to 2021-08-06; sealed years cut at load).

Usage: python trend_exit_tests.py futures_prices.parquet trend_universe.csv market_list.csv OUT_DIR

Every row is a COMPLETE system: entry ratio, minimum movement, re-entry rule, initial stop, exit(s). Common to all rows:
- Entry ratio: Kaufman efficiency ratio on closes only, 20 sessions (|close now - close 20 sessions ago| / sum of the 20 daily |close changes|). Direction = sign of the 20-session close change. Enter at the next open.
- One position per market, no pyramiding, no reversal inside a trade. Size: one ATR of the position = 0.10 percent of 300,000 (fractional contracts). Cost 0.05 ATR per side.
- Initial stop 4 ATR from entry (ATR = 20-day average true range on the signal day).
Options tested:
- minimum movement: the 20-session net close change must be at least this many ATR (blocks one-tick drift in quiet markets such as fed funds).
- re-entry rule: "any" = the market may re-enter as soon as the ratio qualifies (the old behaviour, which can flip direction right after a stop);
  "after ratio reset" = after an exit, no new entry in either direction until the ratio has closed below 0.40;
  "no flip" = same-direction re-entry allowed at once, opposite direction only after the ratio has closed below 0.40.
- trailing stop: N ATR from the best close since entry (recomputed daily with the current ATR, only moves in the trade's favour), or an N-session channel low/high.
- ratio-fall exit: exit at the close when the 20-session ratio drops below the level (trend has faded).
- volatility exit: exit at the close when today's ATR is at least k times the ATR at entry.
- resize: cut the position (or restore it, up to the original size) so one ATR stays at 0.10 percent when volatility rises; 0.05 ATR cost on the size change.
Returns are percent per year of the 300,000 account at the 0.10 percent budget; drawdown is the historical maximum in percent of the account. Both scale in proportion to the budget.
"""
import sys
import time
import numpy as np
import pandas as pd

prices_path, uni_path, list_path, out_dir = sys.argv[1:5]
prev44_path = sys.argv[5] if len(sys.argv) > 5 else None
ACCOUNT = 300_000.0
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
SPLIT = pd.Timestamp("2015-01-01")
REF = 0.10
COST = 0.05
W = 20
PATH_OVERRIDE = {"SO3": "L"}
rng = np.random.default_rng(20261112)
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")

uni = pd.read_csv(uni_path)
fam = dict(zip(uni["price_symbol"], uni["family"]))
lst = pd.read_csv(list_path)
group = dict(zip(lst["price_symbol"], lst["group"]))
rows_by_sym = px.groupby("symbol").size().to_dict()
mapping = {}
for sym in lst["price_symbol"]:
    f = fam.get(sym)
    cands = [s for s, ff in fam.items() if ff == f and s in rows_by_sym]
    best = max(cands, key=lambda s: rows_by_sym[s]) if cands else None
    own = rows_by_sym.get(sym, 0)
    if best is None:
        mapping[sym] = None
    elif own >= 0.7 * rows_by_sym[best]:
        mapping[sym] = sym
    else:
        mapping[sym] = best
    ov = PATH_OVERRIDE.get(sym)
    if ov and rows_by_sym.get(ov, 0) >= 150 and own < 0.7 * rows_by_sym[ov]:
        mapping[sym] = ov
print("price path taken from a different contract:", {k: v for k, v in mapping.items() if v != k})
print("no development-year data:", [k for k, v in mapping.items() if v is None])

calendar = pd.DatetimeIndex(sorted(px["file_date"].unique()))
NCAL = len(calendar)
first_half = np.asarray(calendar < SPLIT)


class Mkt:
    pass


mk = {}
for sym, src in mapping.items():
    if src is None:
        continue
    g = px[px["symbol"] == src].sort_values("file_date").drop_duplicates("file_date").dropna(subset=["close", "high", "low"])
    if len(g) < 150:
        print(f"  skipped {sym}: only {len(g)} development sessions")
        continue
    c = g["close"].to_numpy(float).copy()
    o = g["open"].fillna(g["close"]).to_numpy(float).copy()
    h, l = g["high"].to_numpy(float).copy(), g["low"].to_numpy(float).copy()
    # unit glitch repair: a one-day close ratio near a power of ten (e.g. 98.5 -> 985.5) is a quoting change, not a move; rescale everything before it
    for k in range(1, len(c)):
        r = c[k] / c[k - 1]
        if r > 5 or r < 0.2:
            f = 10.0 ** round(np.log10(r))
            if f != 1.0:
                print(f"  unit glitch in {sym} (from {src}) at {g['file_date'].iloc[k].date()}: close ratio {r:.2f}; scaling earlier bars by {f:g}")
                c[:k] *= f; o[:k] *= f; h[:k] *= f; l[:k] *= f
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(W).mean()
    hh, ll = pd.Series(h).rolling(W).max(), pd.Series(l).rolling(W).min()
    cs = pd.Series(c)
    m = Mkt()
    m.sym, m.src = sym, src
    m.idx = calendar.get_indexer(g["file_date"])
    m.first_date = g["file_date"].iloc[0]
    m.o, m.h, m.l, m.c = o.tolist(), h.tolist(), l.tolist(), c.tolist()
    m.atr = atr.tolist()
    er_hl = (hh - ll) / (W * atr)
    path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(W).sum()
    er_close = (cs - cs.shift(W)).abs() / path
    er_atr = (cs - cs.shift(W)).abs() / (W * atr)   # net close change over the sum of the 20 true ranges (closes decide the numerator, ATR is the yardstick)
    m.er = {"hl": er_hl.tolist(), "close": er_close.tolist(), "atr": er_atr.tolist()}
    m.lo = {n: pd.Series(l).rolling(n).min().tolist() for n in (20, 40, 55, 100)}
    m.hi = {n: pd.Series(h).rolling(n).max().tolist() for n in (20, 40, 55, 100)}
    m.dir = np.sign(cs - cs.shift(W)).fillna(0).astype(int).tolist()
    mk[sym] = m
print(f"{len(mk)} markets in the test; first date of the shortest series: {min(m.first_date for m in mk.values()).date()} to {max(m.first_date for m in mk.values()).date()}")
for k in ("atr", "close", "hl"):
    allv = np.concatenate([np.array(m.er[k], float) for m in mk.values()])
    allv = allv[~np.isnan(allv)]
    print(f"efficiency ratio ({k}) across all market-days: percentiles 10/25/50/75/90/95 = " + " ".join(f"{np.percentile(allv, q):.2f}" for q in (10, 25, 50, 75, 90, 95)))



for _m in mk.values():
    _c = pd.Series(_m.c)
    _m.mv = ((_c - _c.shift(W)).abs() / pd.Series(_m.atr)).tolist()
SHORT = ["ZQ", "SR1", "SR3", "ER", "SO3"]
REARM_LEVEL = 0.40


def run_market2(m, p, risk, want_trades=False):
    o, h, l, c, atr = m.o, m.h, m.l, m.c, m.atr
    er, dr, mv = m.er["close"], m.dir, m.mv
    er_min, init_atr = p["er_min"], p["init_atr"]
    trail_atr, chan, tmax = p.get("trail_atr"), p.get("chan"), p.get("tmax")
    minmove, er_exit, vol_exit = p.get("minmove", 0.0), p.get("er_exit"), p.get("vol_exit")
    resize, rearm = p.get("resize", False), p.get("rearm")
    n = len(c)
    pnl = [0.0] * n
    inpos = [0] * n
    trades = []
    reasons = {}
    side = pending = last_side = 0
    pend_atr = atr0 = stop = stop0 = best = prev = entry = shares = shares0 = tpnl = 0.0
    start = 0
    armed = True
    for i in range(n):
        if pending:
            side, atr0, entry = pending, pend_atr, o[i]
            shares = shares0 = risk / atr0
            stop = stop0 = entry - side * init_atr * atr0
            best = prev = entry
            start = i
            pending = 0
            cst = -COST * atr0 * shares
            pnl[i] += cst
            tpnl = cst
            armed = False
        if side:
            inpos[i] = 1
            hit = (l[i] <= stop) if side == 1 else (h[i] >= stop)
            reason = None
            if hit:
                if side == 1:
                    pxe = stop if o[i] >= stop else o[i]
                else:
                    pxe = stop if o[i] <= stop else o[i]
                d = shares * side * (pxe - prev) - COST * atr0 * shares
                pnl[i] += d
                tpnl += d
                moved = (stop > stop0) if side == 1 else (stop < stop0)
                reason = "trailing stop" if moved else "initial stop"
            else:
                d = shares * side * (c[i] - prev)
                pnl[i] += d
                tpnl += d
                prev = c[i]
                if side == 1:
                    if c[i] > best:
                        best = c[i]
                else:
                    if c[i] < best:
                        best = c[i]
                new = float("nan")
                if trail_atr is not None and atr[i] == atr[i]:
                    new = best - side * trail_atr * atr[i]
                elif chan is not None:
                    new = m.lo[chan][i] if side == 1 else m.hi[chan][i]
                if new == new:
                    if side == 1:
                        if new > stop:
                            stop = new
                    else:
                        if new < stop:
                            stop = new
                if tmax is not None and i - start + 1 >= tmax:
                    reason = "time stop"
                elif er_exit is not None and i > start and er[i] == er[i] and er[i] < er_exit:
                    reason = "ratio fell"
                elif vol_exit is not None and atr[i] == atr[i] and atr[i] >= vol_exit * atr0:
                    reason = "volatility rose"
                elif i == n - 1:
                    reason = "end of development window"
                if reason:
                    d = -COST * atr0 * shares
                    pnl[i] += d
                    tpnl += d
                    pxe = c[i]
                elif resize and atr[i] == atr[i] and atr[i] > 0:
                    tgt = min(shares0, risk / atr[i])
                    if abs(tgt - shares) > 1e-9 * shares0:
                        cs_ = -COST * atr[i] * abs(tgt - shares)
                        pnl[i] += cs_
                        tpnl += cs_
                        shares = tgt
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
                if want_trades:
                    trades.append((m.sym, side, start, i, shares0, atr0, entry, pxe, tpnl, reason))
                last_side = side
                side = 0
                armed = bool(er[i] == er[i] and er[i] < REARM_LEVEL)
        if side == 0 and i < n - 1:
            e, a = er[i], atr[i]
            if e == e and a == a:
                if e < REARM_LEVEL:
                    armed = True
                if a > 1e-5 * c[i] and e >= er_min and dr[i] != 0 and mv[i] >= minmove:
                    ok = True
                    if rearm == "reset" and not armed:
                        ok = False
                    elif rearm == "noflip" and not armed and last_side != 0 and dr[i] != last_side:
                        ok = False
                    if ok:
                        pending, pend_atr = dr[i], a
    ntr = sum(reasons.values())
    return pnl, inpos, ntr, reasons, trades


def max_dd(daily):
    cum = np.cumsum(np.r_[0.0, daily])
    return float((np.maximum.accumulate(cum) - cum).max())


def sharpe_of(x):
    sd = x.std() * np.sqrt(252)
    return float(x.mean() * 252 / sd) if sd > 0 else np.nan


REARM_WORDS = {None: "any", "reset": "after ratio reset", "noflip": "no flip"}


def describe(p):
    t = "none" if (p.get("trail_atr") is None and p.get("chan") is None) else (f"{p['trail_atr']:g} ATR trailing from best close" if p.get("trail_atr") is not None else f"{p['chan']}-session channel")
    ex = [t]
    if p.get("tmax"):
        ex.append(f"time stop {p['tmax']}")
    if p.get("er_exit") is not None:
        ex.append(f"exit if ratio < {p['er_exit']:g}")
    if p.get("vol_exit") is not None:
        ex.append(f"exit if ATR x{p['vol_exit']:g}")
    if p.get("resize"):
        ex.append("resize to hold risk")
    return f"ratio {p['er_min']:g} | min move {p.get('minmove', 0):g} ATR | re-entry {REARM_WORDS[p.get('rearm')]} | exits: " + " + ".join(ex)


def evaluate(p):
    risk = REF / 100 * ACCOUNT
    tot = np.zeros(NCAL)
    act = np.zeros(NCAL)
    ntr = 0
    reasons = {}
    msum = {}
    inpos_total = 0
    for sym, m in mk.items():
        pnl, inpos, k, rs, _ = run_market2(m, p, risk)
        s = np.zeros(NCAL)
        a = np.zeros(NCAL)
        s[m.idx] = pnl
        a[m.idx] = inpos
        tot += s
        act += a
        ntr += k
        inpos_total += sum(inpos)
        msum[sym] = s.sum()
        for key, v in rs.items():
            reasons[key] = reasons.get(key, 0) + v
    yrs = NCAL / 252
    ann = tot.sum() / yrs
    dd = max_dd(tot)
    total = sum(msum.values())
    wins = None
    return dict(system=describe(p), annual_pct=100 * ann / ACCOUNT, sharpe=sharpe_of(tot), max_drawdown_pct=100 * dd / ACCOUNT,
                annual_over_drawdown=ann / dd if dd > 0 else np.nan, trades=ntr, average_hold_sessions=inpos_total / ntr if ntr else np.nan,
                markets_in_trade=float(act.mean()), sharpe_before_2015=sharpe_of(tot[first_half]), sharpe_2015_on=sharpe_of(tot[~first_half]),
                fed_funds_trades=0, fed_funds_share_pct=100 * msum.get("ZQ", 0) / total if total else np.nan,
                short_rate_share_pct=100 * sum(msum.get(s, 0) for s in SHORT) / total if total else np.nan,
                exits=", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))


def with_zq_trades(p, r):
    _, _, k, _, _ = run_market2(mk["ZQ"], p, REF / 100 * ACCOUNT)
    r["fed_funds_trades"] = k
    return r


systems = []
def add(section, **p):
    p.setdefault("init_atr", 4.0)
    systems.append((section, p))

# A. benchmarks: the system as it stands (entry ratio 0.60)
add("A. current system and the same without a time stop", er_min=0.60, chan=100, tmax=90)
add("A. current system and the same without a time stop", er_min=0.60, chan=100)
# B. trailing stop only, minimum movement and re-entry rules
for er_min in (0.60, 0.55):
    for trail in (4.0, 5.0, 6.0, 8.0):
        for mm in (0.0, 2.0):
            for rearm in (None, "reset", "noflip"):
                add("B. ATR trailing stop, no time stop", er_min=er_min, trail_atr=trail, minmove=mm, rearm=rearm)
# C. minimum movement size (5 ATR trail, ratio 0.60)
for mm in (0.0, 1.5, 2.0, 3.0, 4.0):
    for rearm in (None, "reset"):
        add("C. minimum movement size", er_min=0.60, trail_atr=5.0, minmove=mm, rearm=rearm)
# D. ratio-fall exit added to a trailing stop
for trail in (5.0, 6.0, 8.0):
    for ex in (0.30, 0.20):
        for mm in (0.0, 2.0):
            for rearm in (None, "reset"):
                add("D. ATR trailing stop plus exit when the ratio falls", er_min=0.60, trail_atr=trail, er_exit=ex, minmove=mm, rearm=rearm)
# E. volatility exit and position resizing (min move 2 ATR, after-reset re-entry)
for trail in (5.0, 8.0):
    for er_exit in (None, 0.30):
        for vol, rs in ((None, False), (3.0, False), (2.0, False), (None, True), (3.0, True)):
            add("E. volatility exit and resizing", er_min=0.60, trail_atr=trail, er_exit=er_exit, minmove=2.0, rearm="reset", vol_exit=vol, resize=rs)

# F. ratio-fall exit at lower levels (the 0.3 and 0.2 levels cut winners short)
for trail in (5.0, 8.0):
    for ex in (0.15, 0.10, 0.05):
        add("F. ratio-fall exit at lower levels", er_min=0.60, trail_atr=trail, er_exit=ex, minmove=0.0, rearm=None)

rows = []
t1 = time.time()
for sec, p in systems:
    r = with_zq_trades(p, evaluate(p))
    r["section"] = sec
    rows.append(r)
print(f"{len(rows)} systems in {time.time() - t1:.0f} seconds")
df = pd.DataFrame(rows)
cols = ["section", "system", "annual_pct", "sharpe", "max_drawdown_pct", "annual_over_drawdown", "trades", "average_hold_sessions", "markets_in_trade",
        "sharpe_before_2015", "sharpe_2015_on", "fed_funds_trades", "fed_funds_share_pct", "short_rate_share_pct", "exits"]
df = df[cols]
df.round(3).to_csv(f"{out_dir}/exit_tests_all_systems.csv", index=False)
pd.set_option("display.width", 300, "display.max_rows", 500, "display.max_columns", 40, "display.max_colwidth", 120)
for sec in df["section"].unique():
    print("\n=== " + sec + " ===")
    d = df[df["section"] == sec].drop(columns=["section"])
    print(d.round(2).to_string(index=False))
print("\n=== all systems ranked by annual percent over drawdown percent (top 25) ===")
print(df.sort_values("annual_over_drawdown", ascending=False).head(25)[["system", "annual_pct", "sharpe", "max_drawdown_pct", "trades", "fed_funds_trades", "fed_funds_share_pct"]].round(2).to_string(index=False))


# direction flips right after an exit, for three complete systems
def flip_stats(p, label):
    risk = REF / 100 * ACCOUNT
    recs = []
    for sym, m in mk.items():
        _, _, _, _, trades = run_market2(m, p, risk, True)
        trades = sorted(trades, key=lambda t: t[2])
        for j, t in enumerate(trades):
            gap = t[2] - trades[j - 1][3] if j > 0 else None
            recs.append(dict(symbol=sym, side=t[1], gap=gap, prev_side=trades[j - 1][1] if j > 0 else 0, atr_pnl=t[8] / (t[4] * t[5])))
    d = pd.DataFrame(recs)
    d2 = d.dropna(subset=["gap"])
    imm = d2[d2["gap"] <= 3]
    flip = imm[imm["side"] != imm["prev_side"]]
    same = imm[imm["side"] == imm["prev_side"]]
    rest = d[~d.index.isin(flip.index)]
    print(f"{label}: trades {len(d)}; entries within 3 sessions of the previous exit {len(imm)} ({100 * len(imm) / len(d2):.1f}%); of these opposite direction (flips) {len(flip)}, same direction {len(same)}; "
          f"average result in ATR: flips {flip['atr_pnl'].mean():.2f}, same-direction immediate {same['atr_pnl'].mean():.2f}, all other trades {rest['atr_pnl'].mean():.2f}; flips in fed funds {int((flip['symbol'] == 'ZQ').sum())}")
    return dict(system=label, trades=len(d), immediate_entries=len(imm), flips=len(flip), same_direction_immediate=len(same),
                flip_avg_atr=flip["atr_pnl"].mean(), same_immediate_avg_atr=same["atr_pnl"].mean(), other_avg_atr=rest["atr_pnl"].mean(), flips_in_fed_funds=int((flip["symbol"] == "ZQ").sum()))

print("\n=== direction flips right after an exit (entry within 3 sessions, opposite direction) ===")
fl = [flip_stats(dict(er_min=0.60, init_atr=4.0, chan=100, tmax=90), "current system (100-session channel + 90-session time stop)"),
      flip_stats(dict(er_min=0.60, init_atr=4.0, trail_atr=5.0), "5 ATR trailing stop, no time stop"),
      flip_stats(dict(er_min=0.60, init_atr=4.0, trail_atr=8.0), "8 ATR trailing stop, no time stop")]
pd.DataFrame(fl).round(3).to_csv(f"{out_dir}/flip_statistics.csv", index=False)
