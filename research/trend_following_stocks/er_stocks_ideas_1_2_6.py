"""Stocks, long only: three improvement ideas, each run ALONE against the same baseline so their effects are not mixed (Michael, 18 Nov 2026).
Usage: python er_stocks_ideas_1_2_6.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
  MODE rank    (idea 1) When the account cannot take every signal that day, rank the signals instead of choosing at random: strongest 126-session return first, weakest first (control), highest 20-session
                        efficiency ratio first, calmest first (lowest ATR as a percent of price), most volatile first (control), strongest 126-session return skipping the latest month first.
                        Baseline = the random pick, shown as the reference seed (+22.9% / 0.64) and as the mean of 20 random draws. Ranking only matters on days the account is full (about half of all sessions).
  MODE cluster (idea 2) Pseudo-sectors from price correlation: each month-end, the liquid stocks' last 120 daily returns (minus the average stock's return that day, so the market is removed) are grouped by spherical k-means
                        (k = 12, 20, 40; each month starts from last month's groups so the labels persist); every stock gets the label of its nearest group using only data before the trade's decision day.
                        New entries are skipped when the stock's group already holds more than 10%, 15% or 25% of the account in position value. Random pick among signals, as in the baseline.
  MODE breadth (idea 6) Breadth = share of liquid stocks closing above their own 200-session average (known at the close of the decision day). Tested alone in place of the SPY condition (at least 30, 40, 50, 60, 70%) and
                        together with the SPY 200-day condition (at least 40, 50, 60%).
Everything else is the current best rule (hand-off doc 17 Nov 2026): common stocks, one series per company, $3M floor, 20-session ratio 0.50 with rising close, 20-session watch, buy the next open after a close 1.5 ATR below the best high
since the signal, strongest 20% by 126-session return on that day, SPY above its 200-day (except in the breadth-alone rows), 4 ATR initial stop, 5 ATR trailing stop, no time limit, 0.05 ATR a side, 0.10% of $300k per ATR, caps 200% and 100%.
Post hoc on development years; data through 2021-08-06 only; sealed years not read. Compare each row with the baseline and its neighbours; noise on a 22-year Sharpe is about 0.2.
"""
import heapq
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START, FIRST_TRADE
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, run_trades, VNAME
from er_stocks_combined_er import q_long, cands_from_q

PULL = 1.5
SEED = 20261117
NSEED = 20
GROUPS_K = (12, 20, 40)
GROUP_CAPS = (0.10, 0.15, 0.25)
BREADTH_ALONE = (0.30, 0.40, 0.50, 0.60, 0.70)
BREADTH_WITH_SPY = (0.40, 0.50, 0.60)
WINDOW = 120


def setup(prices_path, spy_path):
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    E20 = {i: er_dr(SEG[i], 20) for i in live}
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    M.PULL = 2.5
    for i in chk:
        er, dr = E20[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    M.PULL = PULL
    for i in live:
        g = SEG[i]
        g["cand"] = cands_from_q(g, q_long(g, *E20[i], 0.50), PULL)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk200 = spy_setup(spy_path, cal)
    return SEG, names, dropped, cal, live, E20, dates, spy_close, mk200


def finish_portfolio(R, cal, shares, notional, taken):
    n = len(R["d"]); m = len(cal)
    w = shares * taken
    pnl = np.bincount(R["f_sess"], weights=R["f_incr"] * w[R["f_tid"]], minlength=m).astype(float)
    cost_ps = 0.5 * B.COST_RT * R["a0"] * w
    pnl -= np.bincount(R["sess_e"], weights=cost_ps, minlength=m) + np.bincount(R["sess_x"], weights=cost_ps, minlength=m)
    trade_usd = w * (R["res"] * R["a0"])
    assert abs(pnl.sum() - trade_usd.sum()) < 1e-6 * max(1.0, abs(trade_usd).sum())
    diff_n = np.zeros(m + 1); diff_v = np.zeros(m + 1)
    for arr, wt in ((diff_n, np.ones(n)), (diff_v, notional)):
        np.add.at(arr, R["sess_e"][taken], wt[taken]); np.add.at(arr, R["sess_x"][taken] + 1, -wt[taken])
    return dict(pnl=pnl, taken=taken, trade_usd=trade_usd, open_n=np.cumsum(diff_n)[:m], gross=np.cumsum(diff_v)[:m])


def portfolio_groupcap(R, cal, cap, key, grp, gfrac):
    """Same account rules as er_stocks.portfolio (same order of entries, same cap), plus an optional limit on position value per group."""
    n = len(R["d"]); tgt = CAPITAL * M.SIZE / 100.0
    shares = np.floor(tgt / R["a0"]); ok = np.isin(R["d"], (1,)) & (shares >= 1)
    notional = shares * R["px_e"]; idx = np.where(ok)[0]
    order = idx[np.lexsort((key[idx], R["sess_e"][idx]))]
    taken = np.zeros(n, bool); heap = []; gross = 0.0; gg = {}
    for i in order:
        while heap and heap[0][0] < R["sess_e"][i]:
            _, nv, gi = heapq.heappop(heap); gross -= nv
            if gi >= 0:
                gg[gi] -= nv
        if cap is not None and gross + notional[i] > cap * CAPITAL:
            continue
        gi = int(grp[i]) if grp is not None else -1
        if gfrac is not None and gi >= 0 and gg.get(gi, 0.0) + notional[i] > gfrac * CAPITAL:
            continue
        taken[i] = True; heapq.heappush(heap, (R["sess_x"][i], notional[i], gi)); gross += notional[i]
        if gi >= 0:
            gg[gi] = gg.get(gi, 0.0) + notional[i]
    return finish_portfolio(R, cal, shares, notional, taken)


def eval_P(R, P, cap, dates, spy_close, WIN, label, on=None):
    ed = dates[R["sess_e"]]
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    rows = []
    for wn, (lo, hi) in WIN.items():
        st, _ = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
        if not st:
            continue
        sel = np.asarray((dates >= max(lo, FIRST_TRADE)) & (dates <= hi))
        g = P["gross"][sel] / CAPITAL * 100
        full = g >= cap * 100 * 0.95
        inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
        ra = R["res"][inw]; bm = bench[inw]; bm = bm[np.isfinite(bm)]
        avg = float(ra.mean()) if inw.any() else np.nan
        bavg = float(bm.mean()) if len(bm) else np.nan
        row = dict(label)
        row.update({"cap %": int(cap * 100), "period": wn, "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"],
                    "worst year %": st["worst year %"], "years positive": st["years positive"], "signals": len(R["d"]), "trades taken": int(inw.sum()),
                    "average open positions": st["average open positions"], "% of sessions at the cap": float(full.mean() * 100),
                    "% of sessions condition on": float(on[sel].mean() * 100) if on is not None else np.nan,
                    "average ATR per trade": avg, "SPY move over the same holds (ATR units)": bavg, "excess over SPY (ATR units)": avg - bavg if np.isfinite(bavg) else np.nan})
        rows.append(row)
    return rows


def trade_rows(SEG, R):
    n = len(R["d"]); sym = R["sym"].astype(int); t = np.empty(n, int)
    for k in range(n):
        t[k] = int(np.searchsorted(SEG[sym[k]]["s"], R["sess_e"][k])) - 1
    return sym, t


def trade_scores(SEG, E20, sym, t):
    n = len(sym)
    S = {k: np.full(n, np.nan) for k in ("rank", "er", "atrpct", "skipmonth")}
    for k in range(n):
        i = sym[k]; g = SEG[i]; tt = t[k]
        assert 0 <= tt < len(g["c"])
        S["rank"][k] = g["rank"][tt]; S["er"][k] = E20[i][0][tt]; S["atrpct"][k] = g["atr"][tt] / g["c"][tt]
        if tt >= 126:
            S["skipmonth"][k] = g["c"][tt - 21] / g["c"][tt - 126] - 1.0
    return S


def run_rank(SEG, E20, R, cal, dates, spy_close, WIN, out):
    n = len(R["d"]); sym, t = trade_rows(SEG, R)
    S = trade_scores(SEG, E20, sym, t)
    rows = []
    ref_key = np.random.default_rng(SEED).random(n)
    seeds = []
    for cap in (2.0, 1.0):
        P = B.portfolio(R, cal, (1,), M.SIZE, cap, ref_key)
        rows += eval_P(R, P, cap, dates, spy_close, WIN, {"idea": "1 rank signals", "scenario": "random pick (reference seed, as in the hand-off)"})
        for s in range(NSEED):
            key = np.random.default_rng(1000 + s).random(n)
            Ps = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
            seeds += eval_P(R, Ps, cap, dates, spy_close, WIN, {"idea": "1 rank signals", "scenario": "random pick", "seed": s})
    SD = pd.DataFrame(seeds)
    num = ["profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "trades taken", "average open positions", "% of sessions at the cap", "average ATR per trade", "excess over SPY (ATR units)"]
    mean_rows = []
    for (cap, per), v in SD.groupby(["cap %", "period"]):
        r = {"idea": "1 rank signals", "scenario": f"random pick, mean of {NSEED} draws", "cap %": cap, "period": per, "Sharpe lowest draw": v["Sharpe ratio"].min(), "Sharpe highest draw": v["Sharpe ratio"].max()}
        for c in num:
            r[c] = v[c].mean()
        mean_rows.append(r)
    rows += mean_rows
    tiny = np.random.default_rng(SEED + 1).random(n) * 1e-9
    spec = {"strongest 126-session return first": S["rank"], "weakest 126-session return first (control)": -S["rank"], "highest 20-session efficiency ratio first": S["er"],
            "calmest first (lowest ATR as % of price)": -S["atrpct"], "most volatile first (control)": S["atrpct"], "strongest 126-session return skipping the latest month first": S["skipmonth"]}
    for name, sc in spec.items():
        key = -np.where(np.isfinite(sc), sc, -1e9) + tiny      # higher score first; signals without a score go last
        for cap in (2.0, 1.0):
            P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
            rows += eval_P(R, P, cap, dates, spy_close, WIN, {"idea": "1 rank signals", "scenario": name})
    print(f"signals with a score: rank {np.isfinite(S['rank']).mean()*100:.1f}%, efficiency ratio {np.isfinite(S['er']).mean()*100:.1f}%, skip-month {np.isfinite(S['skipmonth']).mean()*100:.1f}%", flush=True)
    return rows


def build_dense(SEG, live, ns):
    C = np.full((ns, len(live)), np.nan, np.float32); L = np.zeros((ns, len(live)), bool)
    for j, i in enumerate(live):
        g = SEG[i]; C[g["s"], j] = g["c"]; L[g["s"], j] = g["liq"]
    return C, L


def standardize(X):
    X = X - np.nanmean(X, axis=1, keepdims=True)
    sd = np.sqrt(np.nanmean(X ** 2, axis=1, keepdims=True))
    X = np.nan_to_num(X / np.where(sd > 0, sd, 1.0), nan=0.0)
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)


def monthly_groups(RET, L, reb, k):
    """labels[r, col] = group of each stock (nearest centroid) at rebalance r; -1 if fewer than 100 valid returns in the window. Groups persist because each month starts from last month's membership."""
    ncol = RET.shape[1]
    labels = np.full((len(reb), ncol), -1, np.int8)
    prev = None
    cents_all = []
    for r, p in enumerate(reb):
        W = RET[p - WINDOW + 1:p + 1]
        nvalid = np.isfinite(W).sum(0)
        has = nvalid >= 100
        liq = has & L[p]
        if liq.sum() < max(60, 3 * k):
            cents_all.append(None)
            continue
        Xl = standardize(W[:, liq].T)
        rng = np.random.default_rng(p)
        C = np.zeros((k, WINDOW))
        cols_l = np.flatnonzero(liq)
        for c in range(k):
            members = Xl[prev[cols_l] == c] if prev is not None else Xl[:0]
            C[c] = members.mean(0) if len(members) >= 3 else Xl[rng.integers(len(Xl))]
        C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-12
        for _ in range(15):
            a = np.argmax(Xl @ C.T, axis=1)
            for c in range(k):
                sel = a == c
                C[c] = Xl[sel].sum(0) if sel.any() else Xl[rng.integers(len(Xl))]
            C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-12
        Xa = standardize(W[:, has].T)
        lab = np.full(ncol, -1, np.int8)
        lab[has] = np.argmax(Xa @ C.T, axis=1)
        labels[r] = lab
        prev = np.where(lab >= 0, lab, -1)
        cents_all.append(C)
    return labels


def run_cluster(SEG, names, live, R, cal, dates, spy_close, WIN, ns):
    n = len(R["d"]); sym, t = trade_rows(SEG, R)
    C, L = build_dense(SEG, live, ns)
    RET = np.full_like(C, np.nan)
    RET[1:] = C[1:] / C[:-1] - 1.0
    RET = np.clip(RET, -0.5, 0.5)
    mkt = np.nanmean(np.where(L, RET, np.nan), axis=1)
    RET = RET - mkt[:, None]
    mo = dates.to_period("M")
    reb = np.flatnonzero(np.r_[mo[1:] != mo[:-1], False])
    reb = reb[(reb >= WINDOW + 5)]
    col_of = {i: j for j, i in enumerate(live)}
    colk = np.array([col_of[i] for i in sym])
    trig = np.array([SEG[sym[k]]["s"][t[k]] for k in range(n)])
    rk = np.searchsorted(reb, trig, side="left") - 1          # last rebalance strictly before the decision day
    ref_key = np.random.default_rng(SEED).random(n)
    rows = []
    for cap in (2.0, 1.0):
        P = B.portfolio(R, cal, (1,), M.SIZE, cap, ref_key)
        P2 = portfolio_groupcap(R, cal, cap, ref_key, None, None)
        assert np.allclose(P["pnl"], P2["pnl"]) and (P["taken"] == P2["taken"]).all(), "group-cap portfolio without a group cap differs from the standard one"
        rows += eval_P(R, P, cap, dates, spy_close, WIN, {"idea": "2 group cap", "scenario": "no group cap (baseline, reference seed)", "groups": 0})
    print("group-cap portfolio matches the standard portfolio when no cap is set", flush=True)
    for k in GROUPS_K:
        labels = monthly_groups(RET, L, reb, k)
        grp = np.array([int(labels[rk[q], colk[q]]) if rk[q] >= 0 else -1 for q in range(n)])
        print(f"k={k}: {(grp >= 0).mean()*100:.1f}% of signals have a group", flush=True)
        if k == 20:
            for target in ("2008-12-31", "2015-12-31", "2020-12-31"):
                r = int(np.argmin(np.abs((dates[reb] - pd.Timestamp(target)).days)))
                lab = labels[r]; p = reb[r]
                print(f"\n-- example groups (k=20) at the month-end {dates[p].date()}: size, then the 8 most typical members --", flush=True)
                W = RET[p - WINDOW + 1:p + 1]
                for c in range(k):
                    cols = np.flatnonzero((lab == c) & L[p])
                    if len(cols) < 3:
                        continue
                    X = standardize(W[:, cols].T); cen = X.mean(0); cen /= np.linalg.norm(cen) + 1e-12
                    top = cols[np.argsort(-(X @ cen))[:8]]
                    print(f"group {c:2d} ({len(cols):4d} liquid stocks): " + ", ".join(str(names[live[j]]).replace("-DELISTED", "") for j in top), flush=True)
        # how concentrated is the baseline (cap 200%, random pick)?
        P = B.portfolio(R, cal, (1,), M.SIZE, 2.0, ref_key)
        tk = np.flatnonzero(P["taken"] & (grp >= 0))
        shares = np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"]); notional = shares * R["px_e"]
        ng = int(k); mm = len(cal)
        dv = np.zeros((ng, mm + 1))
        for q in tk:
            dv[grp[q], R["sess_e"][q]] += notional[q]; dv[grp[q], R["sess_x"][q] + 1] -= notional[q]
        share = np.cumsum(dv, axis=1)[:, :mm] / CAPITAL * 100
        sel = np.asarray((dates >= FIRST_TRADE) & (dates <= END)) & (P["gross"] > 0)
        mx = share[:, sel].max(0)
        print(f"k={k}: baseline largest single group as % of the account (sessions with positions): mean {mx.mean():.1f}, 90th percentile {np.percentile(mx, 90):.1f}, maximum {mx.max():.1f}", flush=True)
        for gf in GROUP_CAPS:
            for cap in (2.0, 1.0):
                P = portfolio_groupcap(R, cal, cap, ref_key, grp, gf)
                rows += eval_P(R, P, cap, dates, spy_close, WIN, {"idea": "2 group cap", "scenario": f"k={k} groups, at most {int(gf*100)}% of the account in one group", "groups": k})
    return rows


def breadth_series(SEG, live, ns):
    above = np.zeros(ns); valid = np.zeros(ns)
    for i in live:
        g = SEG[i]; c = g["c"].astype(float)
        if len(c) < 200:
            continue
        cs = np.cumsum(np.r_[0.0, c]); sma = (cs[200:] - cs[:-200]) / 200.0
        ok = np.asarray(g["liq"][199:], bool); s = g["s"][199:]; a = c[199:] > sma
        np.add.at(valid, s[ok], 1); np.add.at(above, s[ok & a], 1)
    return np.where(valid >= 100, above / np.maximum(valid, 1), np.nan), valid


def run_breadth(SEG, live, dropped, cal, dates, spy_close, mk200, WIN):
    b, valid = breadth_series(SEG, live, len(cal))
    ok = np.isfinite(b)
    sel = np.asarray((dates >= FIRST_TRADE) & (dates <= END))
    print(f"breadth (share of liquid stocks above their own 200-day average): first available {dates[np.argmax(ok)].date()}, percentiles 10/25/50/75/90 = " + "/".join(f"{np.nanpercentile(b[sel & ok], q):.2f}" for q in (10, 25, 50, 75, 90)), flush=True)
    both = ok & np.isfinite(spy_close)
    print(f"agreement with the SPY 200-day condition on days both exist: correlation of breadth with SPY-above-200day {np.corrcoef(b[both], mk200[both].astype(float))[0, 1]:.2f}", flush=True)
    masks = {"SPY above its 200-day average (baseline)": mk200.copy()}
    for x in BREADTH_ALONE:
        masks[f"breadth alone at least {int(x*100)}% (no SPY condition)"] = ok & (np.nan_to_num(b, nan=0.0) >= x)
    for x in BREADTH_WITH_SPY:
        masks[f"SPY above 200-day AND breadth at least {int(x*100)}%"] = mk200 & ok & (np.nan_to_num(b, nan=0.0) >= x)
    rows = []
    for name, on in masks.items():
        on = np.asarray(on, bool)
        R = run_trades(SEG, dropped, cal, on)
        key = np.random.default_rng(SEED).random(len(R["d"]))
        print(f"{name}: on {on[sel].mean()*100:.1f}% of sessions, {len(R['d']):,} signals", flush=True)
        for cap in (2.0, 1.0):
            P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
            rows += eval_P(R, P, cap, dates, spy_close, WIN, {"idea": "6 breadth", "scenario": name}, on=on)
    return rows


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    SEG, names, dropped, cal, live, E20, dates, spy_close, mk200 = setup(prices_path, spy_path)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 800); pd.set_option("display.max_colwidth", 90)
    if mode == "breadth":
        rows = run_breadth(SEG, live, dropped, cal, dates, spy_close, mk200, WIN)
    else:
        R = run_trades(SEG, dropped, cal, mk200)
        key = np.random.default_rng(SEED).random(len(R["d"]))
        P = B.portfolio(R, cal, (1,), M.SIZE, 2.0, key)
        st, _ = B.wstats(P["pnl"], dates, pd.Timestamp("2000-01-01"), END, P["open_n"], P["gross"])
        print(f"baseline: {len(R['d']):,} signals, whole period cap 200%: {st['profit per year %']:+.1f}% / Sharpe {st['Sharpe ratio']:.2f} / {st['max drawdown %']:.0f}% (documented +22.9% / 0.64 / -22%)", flush=True)
        if abs(st["Sharpe ratio"] - 0.64) > 0.015:
            print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)
        rows = run_rank(SEG, E20, R, cal, dates, spy_close, WIN, out_dir) if mode == "rank" else run_cluster(SEG, names, live, R, cal, dates, spy_close, WIN, len(cal))
    S = pd.DataFrame(rows)
    S.to_csv(out_dir / f"ideas_{mode}.csv", index=False)
    cols = ["scenario", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "years positive", "trades taken", "average open positions", "% of sessions at the cap", "% of sessions condition on",
            "average ATR per trade", "excess over SPY (ATR units)"]
    if mode == "rank":
        cols += ["Sharpe lowest draw", "Sharpe highest draw"]
    for wn in WIN:
        for cap in (200, 100):
            print(f"\n==== idea {mode} | {wn} | cap {cap}% | long only | strongest 20% | 4 ATR stop, 5 ATR trail ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
