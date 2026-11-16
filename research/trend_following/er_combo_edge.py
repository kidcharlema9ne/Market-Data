"""Combined 20-session and 60-session efficiency ratio on Michael's 48 COT markets. DEVELOPMENT YEARS ONLY.

Same rules as er_window_edge.py (close-based ratio, next-open entry, 3 ATR initial stop then 3 ATR trailing from best close, cost 0.05 ATR a side, no reversal).
COMBINATIONS (Michael, 16 Nov 2026): "both" = the 20-session ratio is at least its threshold AND the 60-session ratio is at least its threshold AND both windows point the same way;
"either" = one window qualifies on its own (a window qualifies when its ratio meets its threshold); if both qualify but point opposite ways the market is skipped.
Original description follows.


Usage: python er_combo_edge.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

SEALED YEARS: prices after 2021-08-06 are removed the moment the file is read (development window 2007-12-31 to 2021-08-06). Nothing sealed is used.

THE TEST (Michael, 16 Nov 2026)
- Windows: 10, 20, 40, 60 sessions. Efficiency ratio is CLOSE-BASED: the net close change over the window divided by the sum of the absolute daily close changes over the window
  (1.0 = a straight line, near 0 = back and forth).
- Thresholds (entry when the ratio is at least the threshold): 10 and 20 sessions 0.30 to 0.60; 40 sessions 0.20 to 0.50; 60 sessions 0.15 to 0.45 (0.60 is not run on the long windows).
- Entry: flat, ratio at or above the threshold; direction = sign of (close now minus close one window ago); filled at the NEXT session's open. No reversal: after an exit the
  market may enter again only when the entry condition holds again (any direction the signal then gives, one position per market, no pyramiding).
- Exit: 3 ATR initial stop from the entry price, then a 3 ATR trailing stop measured from the best close since entry (recomputed each close with the current ATR, only ever
  moving in the trade's favour). A touched stop exits at the stop price, or at the open if the market gaps through it. No time stop (the development window ends the last trade).
- ATR is always the 20-day average true range (the same yardstick for every window, so results are comparable). Cost 0.05 ATR per side (Michael's standing 0.10 ATR round trip).
- MAE (maximum adverse excursion) and MFE (maximum favourable excursion) are measured on the daily highs and lows from the entry fill to the exit, in units of the ATR at entry.
- Fixed-horizon "edge ratio" (no stops involved): from each entry fill, the average best move in the trade's favour divided by the average worst move against it over the next
  10, 20 and 40 sessions, both in entry ATR. Above 1.0 means that, before any stop or exit rule, the entry gives more room in your favour than against you.
- Portfolio line: every market is risked at 0.10 percent of a 300,000 account per 1 ATR (fractional contracts, so this is a SCREENING number, not the whole-contract result).
Everything chosen after looking at the development years is a lead, not a rule.
"""
import sys
import time
import numpy as np
import pandas as pd

prices_path, uni_path, out_dir = sys.argv[1:4]
ACCOUNT = 300_000.0
DEV_START, DEV_END = pd.Timestamp("2007-12-31"), pd.Timestamp("2021-08-06")
SPLIT = pd.Timestamp("2015-01-01")
RISK = 0.10 / 100 * ACCOUNT          # dollars risked per 1 ATR per market
COST = 0.05                          # ATR per side
ATRW = 20
INIT, TRAIL = 3.0, 3.0
HORIZONS = (10, 20, 40)
GRID = {
    10: [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60],
    20: [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60],
    40: [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
    60: [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45],
}
# report-universe (IBKR) symbol -> price-archive symbol, where they differ (FUTURES_DATA.md)
PRICE_MAP = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6", "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
t0 = time.time()

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px[(px["file_date"] >= DEV_START) & (px["file_date"] <= DEV_END)].copy()
assert px["file_date"].max() <= DEV_END
print(f"development rows {len(px):,}; {px['file_date'].min().date()} to {px['file_date'].max().date()}; sealed years removed at load")

uni = pd.read_csv(uni_path)
calendar = pd.DatetimeIndex(sorted(px["file_date"].unique()))
NCAL = len(calendar)
first_half = np.asarray(calendar < SPLIT)
years = np.asarray(calendar.year)
WINDOWS = [20, 60]
T20 = [0.45, 0.50, 0.55, 0.60]
T60 = [0.20, 0.25, 0.30, 0.35, 0.40]


class Mkt:
    pass


mk = {}
for ib in uni["ibkr"]:
    sym = PRICE_MAP.get(ib, ib)
    g = px[px["symbol"] == sym].sort_values("file_date").drop_duplicates("file_date").dropna(subset=["close", "high", "low"])
    if len(g) < 250:
        print(f"  skipped {ib} (price symbol {sym}): only {len(g)} development sessions")
        continue
    c = g["close"].to_numpy(float).copy()
    o = g["open"].fillna(g["close"]).to_numpy(float).copy()
    h, l = g["high"].to_numpy(float).copy(), g["low"].to_numpy(float).copy()
    for k in range(1, len(c)):          # unit glitch repair: a one-day close ratio near a power of ten is a quoting change, not a move
        r = c[k] / c[k - 1]
        if r > 5 or r < 0.2:
            f = 10.0 ** round(np.log10(r))
            if f != 1.0:
                print(f"  unit glitch in {sym} at {g['file_date'].iloc[k].date()}: close ratio {r:.2f}; scaling earlier bars by {f:g}")
                c[:k] *= f; o[:k] *= f; h[:k] *= f; l[:k] *= f
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    tr[0] = h[0] - l[0]
    cs = pd.Series(c)
    m = Mkt()
    m.sym, m.ib = sym, ib
    m.idx = calendar.get_indexer(g["file_date"])
    m.o, m.h, m.l, m.c = o, h, l, c
    m.atr = pd.Series(tr).rolling(ATRW).mean().to_numpy()
    m.er, m.dir = {}, {}
    for w in WINDOWS:
        path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(w).sum()
        m.er[w] = ((cs - cs.shift(w)).abs() / path).to_numpy()
        m.dir[w] = np.sign(cs - cs.shift(w)).fillna(0).astype(int).to_numpy()
    mk[ib] = m
print(f"{len(mk)} of {len(uni)} markets in the test")


def run_market(m, mode, t20, t60):
    o, h, l, c, atr = m.o, m.h, m.l, m.c, m.atr
    e20, e60, d20, d60 = m.er[20], m.er[60], m.dir[20], m.dir[60]
    n = len(c)
    pnl = np.zeros(n)
    trades = []
    side = pending = 0
    pend_atr = atr0 = stop = best = prev = entry = shares = tpnl = mae = mfe = 0.0
    start = 0
    for i in range(n):
        if pending:
            side, atr0, entry = pending, pend_atr, o[i]
            shares = RISK / atr0
            stop = entry - side * INIT * atr0
            best = prev = entry
            start = i
            pending = 0
            mae = mfe = 0.0
            tpnl = -COST * atr0 * shares
            pnl[i] += tpnl
        if side:
            if side == 1:
                mae = max(mae, entry - l[i]); mfe = max(mfe, h[i] - entry)
                hit = l[i] <= stop
            else:
                mae = max(mae, h[i] - entry); mfe = max(mfe, entry - l[i])
                hit = h[i] >= stop
            reason = None
            if hit:
                pxe = (stop if o[i] >= stop else o[i]) if side == 1 else (stop if o[i] <= stop else o[i])
                d = shares * side * (pxe - prev) - COST * atr0 * shares
                pnl[i] += d; tpnl += d
                reason = "stop"
            else:
                d = shares * side * (c[i] - prev)
                pnl[i] += d; tpnl += d
                prev = c[i]
                best = max(best, c[i]) if side == 1 else min(best, c[i])
                a = atr[i]
                if a == a:
                    new = best - side * TRAIL * a
                    if (side == 1 and new > stop) or (side == -1 and new < stop):
                        stop = new
                if i == n - 1:
                    d = -COST * atr0 * shares
                    pnl[i] += d; tpnl += d
                    pxe = c[i]
                    reason = "end"
            if reason:
                row = dict(market=m.ib, side=side, start=start, end=i, sessions=i - start + 1, atr0=atr0,
                           result_atr=tpnl / (shares * atr0), mae_atr=mae / atr0, mfe_atr=mfe / atr0, reason=reason,
                           year=int(years[m.idx[start]]), first_half=bool(first_half[m.idx[start]]))
                for H in HORIZONS:
                    if start + H <= n:
                        if side == 1:
                            row[f"mfe{H}"] = max(0.0, h[start:start + H].max() - entry) / atr0
                            row[f"mae{H}"] = max(0.0, entry - l[start:start + H].min()) / atr0
                        else:
                            row[f"mfe{H}"] = max(0.0, entry - l[start:start + H].min()) / atr0
                            row[f"mae{H}"] = max(0.0, h[start:start + H].max() - entry) / atr0
                trades.append(row)
                side = 0
        if side == 0 and i < n - 1:
            a = atr[i]
            if a == a and a > 1e-5 * c[i]:
                q20 = e20[i] == e20[i] and e20[i] >= t20 and d20[i] != 0
                q60 = e60[i] == e60[i] and e60[i] >= t60 and d60[i] != 0
                dd = 0
                if mode == "both":
                    if q20 and q60 and d20[i] == d60[i]:
                        dd = d20[i]
                else:
                    if q20 and q60:
                        dd = d20[i] if d20[i] == d60[i] else 0
                    elif q20:
                        dd = d20[i]
                    elif q60:
                        dd = d60[i]
                if dd:
                    pending, pend_atr = dd, a
    return pnl, trades


def sharpe_of(x):
    sd = x.std() * np.sqrt(252)
    return float(x.mean() * 252 / sd) if sd > 0 else np.nan


def max_dd_pct(daily):
    cum = ACCOUNT + np.cumsum(daily)
    return float(((np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)).max() * 100)


summary, by_market, by_year = [], [], []
for mode in ("both", "either"):
    for t20 in T20:
        for t60 in T60:
            w, thr = mode, (t20, t60)
            tot = np.zeros(NCAL)
            T = []
            for ib, m in mk.items():
                pnl, tr = run_market(m, mode, t20, t60)
                sx = np.zeros(NCAL); sx[m.idx] = pnl
                tot += sx
                T.extend(tr)
            df = pd.DataFrame(T)
            if len(df) < 30:
                continue
            win, lose = df[df.result_atr > 0], df[df.result_atr <= 0]
            yrs = NCAL / 252
            r = dict(mode=mode, er20_min=t20, er60_min=t60, trades=len(df), trades_per_month=len(df) / yrs / 12, win_rate=len(win) / len(df),
                     expectancy_atr=df.result_atr.mean(), profit_factor=win.result_atr.sum() / -lose.result_atr.sum(),
                     avg_mae_atr=df.mae_atr.mean(), avg_mfe_atr=df.mfe_atr.mean(), mfe_over_mae=df.mfe_atr.mean() / df.mae_atr.mean(),
                     avg_sessions=df.sessions.mean(), pct_over_100_sessions=(df.sessions > 100).mean() * 100,
                     expectancy_first_half=df[df.first_half].result_atr.mean(), expectancy_second_half=df[~df.first_half].result_atr.mean(),
                     pct_years_positive=(df.groupby("year").result_atr.mean() > 0).mean() * 100,
                     annual_return_pct=tot.sum() / yrs / ACCOUNT * 100, sharpe=sharpe_of(tot), max_drawdown_pct=max_dd_pct(tot),
                     sharpe_first_half=sharpe_of(tot[first_half]), sharpe_second_half=sharpe_of(tot[~first_half]))
            for H in HORIZONS:
                sub = df.dropna(subset=[f"mfe{H}"])
                r[f"edge_ratio_{H}"] = sub[f"mfe{H}"].mean() / sub[f"mae{H}"].mean()
            summary.append(r)
            g = df.groupby("market").result_atr.agg(["count", "mean", "sum"]).reset_index()
            g.insert(0, "er60_min", t60); g.insert(0, "er20_min", t20); g.insert(0, "mode", mode); by_market.append(g)
            y = df.groupby("year").result_atr.agg(["count", "mean", "sum"]).reset_index()
            y.insert(0, "er60_min", t60); y.insert(0, "er20_min", t20); y.insert(0, "mode", mode); by_year.append(y)
            print(f"{mode:>6} ER20>={t20:.2f} ER60>={t60:.2f}: trades {len(df):>5} exp {r['expectancy_atr']:+.3f} PF {r['profit_factor']:.2f} edge40 {r['edge_ratio_40']:.2f} "
                  f"| ret {r['annual_return_pct']:+.2f}% Sharpe {r['sharpe']:.2f} DD {r['max_drawdown_pct']:.1f}% ({time.time()-t0:.0f}s)", flush=True)

pd.DataFrame(summary).to_csv(f"{out_dir}/er_combo_summary.csv", index=False)
pd.concat(by_market).to_csv(f"{out_dir}/er_combo_by_market.csv", index=False)
pd.concat(by_year).to_csv(f"{out_dir}/er_combo_by_year.csv", index=False)
print("done", f"{time.time()-t0:.0f}s")
