"""Common stocks, long only, strongest 6-month performers, frozen rule: initial stop 4 ATR, trailing stop 5 ATR, no time limit, new entries only while SPY closes above its 200-session average.
Michael, 17 Nov 2026: (1) "Try that" = tighten the stops on open longs when SPY is below its 200-day average instead of selling everything; (2) ROTATION: when the account is full, do not skip good new signals, sell the
worst-performing holdings and buy the best; keep rotating out of weak stocks into the strongest.
Usage: python er_stocks_rotation.py stock_prices.parquet OUT_DIR spy_prices.parquet
Variants (all long only, SPY above its 200-day average (no band) required for new entries, 0.10% of $300k per ATR, cap 200% unless stated, costs 0.05 ATR a side so every forced sale pays it too):
  entries only (current rule); the same at a 100% cap; tighten the trailing stop on every open long to 3 ATR (or 2 ATR) from the best close for as long as SPY is below its average (never loosens, the stop stays);
  ROTATE when full: a new signal arrives and the 200% cap has no room: rank the open positions by their strength today (126-session return percentile among eligible stocks); sell the weakest ones at THE CLOSE of the decision day
    (the close before the new entry's open) until there is room, but only those whose strength is at least delta below the new signal's strength (delta = 0, or 0.10); if that cannot free enough room, nothing is sold and the signal is skipped;
  SELL WEAK HOLDINGS: sell a long at the next open once its strength falls below the median (0.50) at a close; and the same together with ROTATE (delta 0.10).
Strength rank needs the stock to be liquid and not a shell on that day; a missing rank counts as the weakest for rotation and as 'not weak' for the weak-holdings sale.
Post hoc on development years; grid; best row is not a result. Data through 2021-08-06 only; sealed years untouched.
"""
import heapq
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START, COST_RT, FIRST_TRADE
from er_stocks_market_band import switch, max_dd, EPISODES

TOPS = (0.20, 1.0)
SMA_N = 200
SEED = 20261117
VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
REG = {}   # id(open array of a stock segment) -> (sell_next_open boolean per row or None, tighten boolean per row or None, tight width)
_orig_run_trade = B.run_trade


def flex_trade(o, h, l, c, atr, t, d, init, mm, cap):
    reg = REG.get(id(o))
    if reg is None:
        return _orig_run_trade(o, h, l, c, atr, t, d, init, mm, cap)
    sell, tight, tw = reg
    n = len(c); e = t + 1
    if e >= n:
        return None
    a0 = atr[t]; entry = o[e]; stop = entry - d * init * a0; best = entry; marks = []
    for j in range(e, n):
        k = j - e
        if k > 0 and sell is not None and sell[j - 1]:
            return j, o[j], marks, "sold by rule"
        hit = (l[j] <= stop) if d > 0 else (h[j] >= stop)
        if hit:
            gap = k > 0 and ((o[j] <= stop) if d > 0 else (o[j] >= stop))
            return j, (o[j] if gap else stop), marks, "stop"
        marks.append(c[j])
        best = max(best, c[j]) if d > 0 else min(best, c[j])
        na = atr[j]
        if na == na:
            w = tw if (tight is not None and tight[j]) else mm
            new = best - d * w * na
            stop = max(stop, new) if d > 0 else min(stop, new)
        if cap is not None and k == cap - 1:
            return j, c[j], marks[:-1], "time limit"
    return n - 1, c[n - 1], marks[:-1], "data end"


def trades_with_rank(SEG, dropped, cal, top, version, market_ok):
    """Same as er_stocks_common_momentum.trades_for (long only) plus the strength rank on every held session (f_rank)."""
    init, mm, cap = M.VERSIONS[version]
    first_i = (FIRST_TRADE - EPOCH).days
    R = dict(sess_e=[], sess_x=[], d=[], px_e=[], px_x=[], a0=[], res=[], held=[], how=[], sym=[], rank=[], f_sess=[], f_incr=[], f_tid=[], f_rank=[], f_len=[])
    for i, g in enumerate(SEG):
        if i in dropped or not g["cand"]:
            continue
        s, so, sh, sl, sc, atr = g["s"], g["o"], g["h"], g["l"], g["c"], g["atr"]
        last_exit = -1
        for t, d in g["cand"]:
            rk = g["rank"][t]
            if d < 0 or t < last_exit or not np.isfinite(rk) or g["spac"][t] or not g["liq"][t] or t + 1 >= len(sc) or cal[s[t + 1]] < first_i:
                continue
            if top < 1.0 and not (rk >= 1.0 - top):
                continue
            if market_ok is not None and not market_ok[s[t]]:
                continue
            res = B.run_trade(so, sh, sl, sc, atr, t, d, init, mm, cap)
            if res is None:
                continue
            x, xpx, marks, how = res
            e = t + 1
            entry, a0 = so[e], atr[t]
            last_exit = x
            incr = d * np.diff(np.r_[entry, np.asarray(marks, float), xpx])
            tid = len(R["d"])
            R["sess_e"].append(int(s[e])); R["sess_x"].append(int(s[x])); R["d"].append(d); R["px_e"].append(entry); R["px_x"].append(xpx); R["a0"].append(a0)
            R["res"].append(d * (xpx - entry) / a0 - COST_RT); R["held"].append(x - e + 1); R["how"].append(how); R["sym"].append(i); R["rank"].append(rk)
            R["f_sess"].append(s[e:x + 1]); R["f_incr"].append(incr); R["f_tid"].append(np.full(len(incr), tid)); R["f_rank"].append(g["rank"][e:x + 1]); R["f_len"].append(len(incr))
    for k in ("sess_e", "sess_x", "d", "sym", "f_len"):
        R[k] = np.asarray(R[k], dtype=np.int64)
    for k in ("px_e", "px_x", "a0", "res", "held", "rank"):
        R[k] = np.asarray(R[k], dtype=float)
    R["how"] = np.asarray(R["how"])
    for k in ("f_sess", "f_incr", "f_tid", "f_rank"):
        R[k] = np.concatenate(R[k]) if R[k] else np.array([])
    R["f_off"] = np.r_[0, np.cumsum(R["f_len"])]
    return R


def portfolio_rotate(R, cal, tp, cap, rng_key, delta):
    """Like er_stocks.portfolio (long only) but when the cap is full and a new signal is stronger than the weakest holdings by at least delta, those holdings are sold at the close of the decision day."""
    n = len(R["d"])
    tgt = CAPITAL * tp / 100.0
    shares = np.floor(tgt / R["a0"])
    ok = (R["d"] > 0) & (shares >= 1)
    notional = shares * R["px_e"]
    idx = np.where(ok)[0]
    order = idx[np.lexsort((rng_key[idx], R["sess_e"][idx]))]
    taken = np.zeros(n, bool)
    cut = np.full(n, np.iinfo(np.int64).max, dtype=np.int64)       # last session held if sold early
    heap, openp, gross = [], {}, 0.0
    f_off, f_sess, f_rank = R["f_off"], R["f_sess"], R["f_rank"]
    for i in order:
        e_i = R["sess_e"][i]
        while heap and heap[0][0] < e_i:
            x, tid = heapq.heappop(heap)
            if tid in openp:
                gross -= openp.pop(tid)
        if gross + notional[i] > cap * CAPITAL:
            if delta is None:
                continue
            q = e_i - 1
            new_rank = R["rank"][i]
            cands = []
            for tid in openp:
                if R["sess_e"][tid] <= q and R["sess_x"][tid] > q:
                    a, b = f_off[tid], f_off[tid + 1]
                    p = int(np.searchsorted(f_sess[a:b], q, side="right")) - 1
                    rk = f_rank[a + max(p, 0)]
                    rk = -1.0 if not np.isfinite(rk) else rk
                    if rk <= new_rank - delta and rk < new_rank:
                        cands.append((rk, tid))
            if not cands:
                continue
            cands.sort()
            freed, sold = 0.0, []
            for rk, tid in cands:
                sold.append(tid); freed += openp[tid]
                if gross - freed + notional[i] <= cap * CAPITAL:
                    break
            if gross - freed + notional[i] > cap * CAPITAL:
                continue
            for tid in sold:
                cut[tid] = q; gross -= openp.pop(tid)
        taken[i] = True
        openp[i] = notional[i]; heapq.heappush(heap, (R["sess_x"][i], i)); gross += notional[i]
    m = len(cal)
    w = shares * taken
    keep = R["f_sess"] <= cut[R["f_tid"]]
    pnl = np.bincount(R["f_sess"][keep], weights=R["f_incr"][keep] * w[R["f_tid"][keep]], minlength=m).astype(float)
    x_sess = np.minimum(R["sess_x"], cut)
    cost_ps = 0.5 * COST_RT * R["a0"] * w
    pnl -= np.bincount(R["sess_e"], weights=cost_ps, minlength=m) + np.bincount(x_sess, weights=cost_ps, minlength=m)
    gain = np.bincount(R["f_tid"][keep], weights=R["f_incr"][keep], minlength=n)
    res = gain / R["a0"] - COST_RT
    trade_usd = w * (res * R["a0"])
    assert abs(pnl.sum() - trade_usd.sum()) < 1e-6 * max(1.0, abs(trade_usd).sum()), (pnl.sum(), trade_usd.sum())
    diff_n = np.zeros(m + 1); diff_v = np.zeros(m + 1)
    for arr, wt in ((diff_n, np.ones(n)), (diff_v, notional)):
        np.add.at(arr, R["sess_e"][taken], wt[taken]); np.add.at(arr, x_sess[taken] + 1, -wt[taken])
    rotated = (taken & (cut < np.iinfo(np.int64).max))
    return dict(pnl=pnl, taken=taken, trade_usd=trade_usd, res=res, open_n=np.cumsum(diff_n)[:m], gross=np.cumsum(diff_v)[:m], rotated=rotated, x_sess=x_sess)


def selftest_flex():
    f = np.float64
    o = np.array([100, 100, 101, 102, 103, 104, 105, 106], f); h = o + 1; l = o - 1; c = o + 0.5; atr = np.full(8, 2.0)
    sell = np.array([False, False, True, False, False, False, False, False])
    REG[id(o)] = (sell, None, 0.0)
    r = flex_trade(o, h, l, c, atr, 0, 1, 4.0, 5.0, None)
    assert r[0] == 3 and r[1] == 102.0 and r[3] == "sold by rule" and r[2] == [c[1], c[2]], r
    # tighten: switch off at the close of row 2 (best close reaches 102.5 by row 3) -> trail 1 ATR (2.0) = stop 100.5; row 4 low 99 hits it and fills at 100.5; without tightening the stop sits near 92 and nothing happens
    l2 = l.copy(); l2[4] = 99.0
    tight = np.array([False, False, True, True, True, True, True, True])
    REG[id(o)] = (None, tight, 1.0)
    r = flex_trade(o, h, l2, c, atr, 0, 1, 4.0, 5.0, None)
    assert r[3] == "stop" and r[0] == 4 and abs(r[1] - 100.5) < 1e-9, r
    REG[id(o)] = (None, np.zeros(8, bool), 1.0)
    r = flex_trade(o, h, l2, c, atr, 0, 1, 4.0, 5.0, None)
    assert r[3] == "data end", r
    REG.clear()
    print("flexible-exit self-test passed", flush=True)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common(); selftest_flex()
    B.run_trade = flex_trade
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(SMA_N, min_periods=SMA_N).mean()
    dist = ((full / sma - 1.0) * 100).to_numpy()
    mk = switch(dist, 0, 0)
    fc = full.to_numpy()
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows, yr, epi = [], {}, []

    def record(top, name, R, P, taken, res, extra):
        ed = dates[R["sess_e"]]
        for wn, (lo, hi) in WIN.items():
            m = np.asarray((ed >= lo) & (ed <= hi))
            st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
            if not st:
                continue
            inw = taken & m
            ra = res[inw]
            st.update({"strongest share kept": top, "variant": name, "window": wn, "trades": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                       "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "average sessions held": float(R["held"][inw].mean()) if inw.any() else np.nan})
            st.update(extra(inw))
            rows.append(st)
            if wn.startswith("whole"):
                yr[f"top {int(top*100)}% | {name}"] = pd.Series(cal_y)
        for en, a, b in EPISODES:
            mm_ = np.asarray((dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b)))
            if mm_.sum() < 2:
                continue
            ps = P["pnl"][mm_]
            epi.append({"strongest share kept": top, "variant": name, "episode": en, "strategy profit % of $300k": float(ps.sum() / CAPITAL * 100), "strategy worst drop %": max_dd(ps),
                        "SPY change %": float(fc[mm_][-1] / fc[mm_][0] * 100 - 100), "SPY worst drop %": float((fc[mm_] / np.maximum.accumulate(fc[mm_]) - 1).min() * 100)})

    for top in TOPS:
        def gen(sell_weak=None, tight_w=None):
            REG.clear()
            if sell_weak is not None or tight_w is not None:
                for g in SEG:
                    sw = (np.isfinite(g["rank"]) & (g["rank"] < sell_weak)) if sell_weak is not None else None
                    th = (~mk[g["s"]]) if tight_w is not None else None
                    REG[id(g["o"])] = (sw, th, tight_w if tight_w is not None else 0.0)
            R = trades_with_rank(SEG, dropped, cal, top, VNAME, mk)
            REG.clear()
            return R
        base = gen()
        n = len(base["d"]); key = np.random.default_rng(SEED).random(n)
        print(f"top {int(top*100)}% baseline: {n:,} trades", flush=True)
        P0 = B.portfolio(base, cal, (1,), M.SIZE, 2.0, key)
        # rotation with an impossible threshold must reproduce the plain portfolio exactly
        Pchk = portfolio_rotate(base, cal, M.SIZE, 2.0, key, None)
        assert np.allclose(Pchk["pnl"], P0["pnl"]) and (Pchk["taken"] == P0["taken"]).all(), "rotation code does not reproduce the plain portfolio"
        record(top, "entries only (current rule, 200% cap)", base, P0, P0["taken"], base["res"], lambda inw: {})
        P1 = B.portfolio(base, cal, (1,), M.SIZE, 1.0, key)
        record(top, "entries only, 100% cap", base, P1, P1["taken"], base["res"], lambda inw: {})
        for tw in (3.0, 2.0):
            Rt = gen(tight_w=tw)
            kt = np.random.default_rng(SEED).random(len(Rt["d"]))
            Pt = B.portfolio(Rt, cal, (1,), M.SIZE, 2.0, kt)
            print(f"top {int(top*100)}% tighten to {tw:g} ATR: {len(Rt['d']):,} trades", flush=True)
            record(top, f"tighten stops to {tw:g} ATR while SPY below average", Rt, Pt, Pt["taken"], Rt["res"], lambda inw: {})
        for dl in (0.0, 0.10):
            Pr = portfolio_rotate(base, cal, M.SIZE, 2.0, key, dl)
            print(f"top {int(top*100)}% rotate delta {dl}: {int(Pr['taken'].sum()):,} trades, {int(Pr['rotated'].sum()):,} sold early to make room", flush=True)
            record(top, f"rotate when full (new signal at least {dl:.2f} stronger)" if dl else "rotate when full (any stronger signal)", base, Pr, Pr["taken"], Pr["res"], lambda inw, Pr=Pr: {"holdings sold to make room": int((Pr["rotated"] & inw).sum())})
        Rw = gen(sell_weak=0.5)
        kw = np.random.default_rng(SEED).random(len(Rw["d"]))
        Pw = B.portfolio(Rw, cal, (1,), M.SIZE, 2.0, kw)
        print(f"top {int(top*100)}% sell below median: {len(Rw['d']):,} trades, {int((Rw['how']=='sold by rule').sum()):,} sold as weak", flush=True)
        record(top, "sell holdings that fall below median strength", Rw, Pw, Pw["taken"], Rw["res"], lambda inw, Rw=Rw: {"holdings sold as weak": int((Rw["how"][inw] == "sold by rule").sum())})
        Pwr = portfolio_rotate(Rw, cal, M.SIZE, 2.0, kw, 0.10)
        record(top, "sell below-median holdings and rotate when full (10 points)", Rw, Pwr, Pwr["taken"], Pwr["res"], lambda inw, Rw=Rw, Pwr=Pwr: {"holdings sold as weak": int((Rw["how"][inw] == "sold by rule").sum()), "holdings sold to make room": int((Pwr["rotated"] & inw).sum())})
    S = pd.DataFrame(rows); S.to_csv(out_dir / "rotation_summary.csv", index=False)
    E = pd.DataFrame(epi); E.to_csv(out_dir / "declines.csv", index=False)
    pd.DataFrame(yr).round(2).to_csv(out_dir / "profit_by_year_pct.csv")
    order = list(dict.fromkeys(S["variant"]))
    pd.set_option("display.width", 330); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 800)
    cols = ["variant", "trades", "win rate %", "average ATR per trade", "average sessions held", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %", "average position value % of account", "first date account below zero", "holdings sold to make room", "holdings sold as weak"]
    for top in TOPS:
        for wn in WIN:
            v = S[(S.window == wn) & (S["strongest share kept"] == top)]
            print(f"\n==== top {int(top*100)}% | {VNAME} | long only | SPY above 200-day average for entries | {wn} ====")
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    for top in TOPS:
        print(f"\n==== named market declines, top {int(top*100)}%: strategy profit % of $300k (worst drop inside window %) ====")
        e = E[E["strongest share kept"] == top]
        tab = e.pivot(index="variant", columns="episode", values="strategy profit % of $300k").reindex(index=order, columns=[x[0] for x in EPISODES])
        tab2 = e.pivot(index="variant", columns="episode", values="strategy worst drop %").reindex(index=order, columns=[x[0] for x in EPISODES])
        print((tab.round(1).astype(str) + " (" + tab2.round(1).astype(str) + ")").to_string())
        s1 = e[e["variant"] == order[0]].set_index("episode")
        print("SPY change (worst drop):", {k: f"{s1.loc[k,'SPY change %']:.1f} ({s1.loc[k,'SPY worst drop %']:.1f})" for k, _, _ in EPISODES if k in s1.index})
    print("\n==== profit by calendar year, percent of $300k ===="); print(pd.DataFrame(yr).round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
