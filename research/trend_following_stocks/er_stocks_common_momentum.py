"""Efficiency ratio rule on COMMON stocks, one series per company, strongest 6-month performers only: old version vs version 2, in-sample (Michael, 17 Nov 2026: "only common stocks ... definitely one series
per company ... take ones that are up the most over the last 6 months. So take the highest performing stocks").

Usage: python er_stocks_common_momentum.py stock_prices.parquet OUT_DIR [spy_prices.parquet]

Same rule, costs, sizing and account limits as er_stocks.py (Entry 134); this script imports its simulator and portfolio code. Differences (all declared before the run):
  1. COMMON STOCKS ONLY, decided from the symbol (the archive labels every row 'Stock'). Base ticker = symbol without '-DELISTED'. A ticker with a dot is kept only if it is on a short list of known
     common share classes (BRK.A, BRK.B, BF.A, BF.B, HEI.A, MOG.A, MOG.B, LGF.A, LGF.B, JW.A, JW.B, HUB.A, HUB.B, RDS.A, RDS.B, FCE.A, FCE.B, KV.A, KV.B, GEF.B, CRD.A, CRD.B); every other dotted ticker
     is a preferred series or similar and is dropped. A ticker of 5 or more letters ending in W, U, R, Z, P, O, N, Y, F or L is dropped (warrants, units, rights, preferreds, other-series, foreign ordinary
     or ADR lines) except GOOGL. Letters A, B, C, K (share classes) and Q (bankruptcy, still the common shares) are kept. A stock whose price stayed inside $9 to $11 for the prior 60 sessions is treated
     as a SPAC shell and is not eligible that day.
  2. ONE SERIES PER COMPANY: two series are the same company if on at least 12 sessions where both had a daily move of 3% or more the moves agree within 0.4 points, and over their overlapping sessions
     (60 or more) the median difference in daily move is under 0.3 points and 95% of days agree within 1 point. This also catches a series copied under another ticker at a different price scale
     (CCIV and LCID). The series with fewer sessions is dropped (a tie drops the one ending in -DELISTED, then the larger code).
  3. STRONGEST PERFORMERS: on each decision day every eligible stock (common, liquid at $3M, not a SPAC shell, 126 sessions of history, not a duplicate) is ranked by its 126-session (6-month) close-to-close
     return. A LONG may be entered only if the stock is in the top X of that day's ranking; a SHORT only if it is in the bottom X (the weakest). X = 5%, 10%, 20%, 50% and 100% (no ranking; the same pool
     for every row so the cleaning and the ranking can be told apart). X was not tuned; the five values are a declared grid and the best row of a grid is not a result.
Everything else as in er_stocks.py: efficiency ratio 0.50 on 20 sessions, 2.5 ATR pullback within 20 sessions, next open, one position per stock, old version 1 ATR stop + 5 ATR trail, version 2 2 ATR
stop + 5 ATR trail, neither has a time limit, 0.05 ATR a side, $3M floor (15-session average close x volume), whole shares, 0.10% of $300k per ATR, position value capped at 200% (100% shown), data
through 2021-08-06 only.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
from er_stocks import CAPITAL, END, EPOCH, FIRST_TRADE, MAIN_START, COST_RT, ER_N, ER_MIN, ATR_N, PULL, WATCH, ADV_N, FLOOR, TRAIL

VERSIONS = {"old version (1 ATR stop, 5 ATR trail, no time limit)": (1.0, TRAIL, None), "new version 2 (2 ATR stop, 5 ATR trail, no time limit)": (2.0, TRAIL, None)}
TOPS = (0.05, 0.10, 0.20, 0.50, 1.0)
SIZE = 0.10
CAPS = (2.0, 1.0)
SIDES = {"long and short": (1, -1), "long only": (1,), "short only": (-1,)}
RET_N = 126
SEED = 20261117
CLASS_OK = {"BRK.A", "BRK.B", "BF.A", "BF.B", "HEI.A", "MOG.A", "MOG.B", "LGF.A", "LGF.B", "JW.A", "JW.B", "HUB.A", "HUB.B", "RDS.A", "RDS.B", "FCE.A", "FCE.B", "KV.A", "KV.B", "GEF.B", "CRD.A", "CRD.B"}


def is_common(sym):
    base = sym[:-len("-DELISTED")] if sym.endswith("-DELISTED") else sym
    if "." in base:
        return base in CLASS_OK
    if not (base.isalpha() and base.isupper()):
        return False
    if len(base) >= 5 and base[-1] in "WURZPONYFL" and base != "GOOGL":
        return False
    return True


def selftest_common():
    for s_, ok in (("AAPL", True), ("BRK.B", True), ("BAC.L", False), ("BAC.C-DELISTED", False), ("CLOVW-DELISTED", False), ("CTAQU-DELISTED", False), ("GOOGL", True), ("CMCSA", True), ("LBTYK", True),
                   ("DYNIQ-DELISTED", True), ("AGNCO", False), ("ACGLN", False), ("CHRW", True), ("SHPGY-DELISTED", False), ("LGF.A-DELISTED", True), ("ABC1", False)):
        assert is_common(s_) == ok, (s_, ok)
    print("symbol filter self-test passed", flush=True)


def analyze(s, o, h, l, c, v):
    """Indicators for one stock segment. Returns atr, liquid flag, SPAC-shell flag, 126-session return, first pullback entries (decision row, direction), one-day returns."""
    n = len(c)
    pc_ = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc_), np.abs(l - pc_)])
    tr[0] = h[0] - l[0]
    atr = pd.Series(tr).rolling(ATR_N).mean().to_numpy()
    cs = pd.Series(c)
    path = pd.Series(np.abs(np.diff(c, prepend=np.nan))).rolling(ER_N).sum()
    er = ((cs - cs.shift(ER_N)).abs() / path).to_numpy()
    dr = np.sign(cs - cs.shift(ER_N)).fillna(0).to_numpy()
    adv = pd.Series(c * v).rolling(ADV_N).mean().to_numpy()
    span = np.r_[np.full(ADV_N - 1, False), (s[ADV_N - 1:] - s[:-(ADV_N - 1)]) == ADV_N - 1]
    liq = span & np.isfinite(adv) & (adv >= FLOOR)
    hi60 = pd.Series(h).rolling(60).max().to_numpy(); lo60 = pd.Series(l).rolling(60).min().to_numpy()
    spac = np.isfinite(hi60) & (hi60 <= 11.0) & (lo60 >= 9.0)
    ret = (cs / cs.shift(RET_N) - 1.0).to_numpy()
    ret1 = (cs / cs.shift(1) - 1.0).to_numpy()
    q = np.isfinite(er) & (er >= ER_MIN) & (dr != 0) & np.isfinite(atr) & (atr > 1e-6 * c)
    qprev = np.r_[False, q[:-1]]; dprev = np.r_[0.0, dr[:-1]]
    starts = np.where(q & ~(qprev & (dprev == dr)))[0]
    cand = []
    for st in starts:
        dn = dr[st]
        peak = h[st] if dn > 0 else l[st]
        for t in range(st + 1, min(st + WATCH, n - 2) + 1):
            peak = max(peak, h[t]) if dn > 0 else min(peak, l[t])
            a = atr[t]
            if not (a == a and a > 0):
                continue
            dep = (peak - c[t]) / a if dn > 0 else (c[t] - peak) / a
            if dep >= PULL:
                cand.append((t, int(dn)))
                break
    return atr, liq, spac, ret, cand, ret1


def find_duplicates(SEG, names):
    """Return (set of dropped segment indices, list of (kept name, dropped name, overlap sessions))."""
    sid, ss, rr = [], [], []
    for i, g in enumerate(SEG):
        m = g["liq"] & np.isfinite(g["ret1"]) & (np.abs(g["ret1"]) >= 0.03)
        if m.any():
            sid.append(np.full(m.sum(), i)); ss.append(g["s"][m]); rr.append(g["ret1"][m])
    sid, ss, rr = np.concatenate(sid), np.concatenate(ss), np.concatenate(rr)
    order = np.lexsort((rr, ss)); sid, ss, rr = sid[order], ss[order], rr[order]
    A, Bb = [], []
    for k in range(1, 60):
        if len(ss) <= k:
            break
        m = (ss[k:] == ss[:-k]) & ((rr[k:] - rr[:-k]) <= 0.004) & (sid[k:] != sid[:-k])
        if not m.any():
            break
        a, b = sid[:-k][m], sid[k:][m]
        A.append(np.minimum(a, b)); Bb.append(np.maximum(a, b))
    if not A:
        return set(), []
    A, Bb = np.concatenate(A), np.concatenate(Bb)
    key = A.astype(np.int64) * len(SEG) + Bb
    uk, cnt = np.unique(key, return_counts=True)
    pairs = [(int(k // len(SEG)), int(k % len(SEG)), int(cn)) for k, cn in zip(uk, cnt) if cn >= 12]
    print(f"duplicate detection: {len(pairs)} candidate pairs from matching big moves", flush=True)
    dropped, log = set(), []
    for a, b, cn in sorted(pairs, key=lambda x: -x[2]):
        if a in dropped or b in dropped:
            continue
        ga, gb = SEG[a], SEG[b]
        common, ia, ib = np.intersect1d(ga["s"], gb["s"], return_indices=True)
        if len(common) < 60:
            continue
        ra, rb = ga["ret1"][ia], gb["ret1"][ib]
        ok = np.isfinite(ra) & np.isfinite(rb)
        if ok.sum() < 60:
            continue
        d = np.abs(ra[ok] - rb[ok])
        if np.median(d) < 0.003 and (d <= 0.01).mean() >= 0.95:
            la, lb = len(ga["s"]), len(gb["s"])
            if la != lb:
                drop = b if lb < la else a
            else:
                da, db = names[a].endswith("-DELISTED"), names[b].endswith("-DELISTED")
                drop = a if (da and not db) else b if (db and not da) else max(a, b)
            keep = a if drop == b else b
            dropped.add(drop); log.append((names[keep], names[drop], int(ok.sum())))
    return dropped, log


def build(path):
    t0 = time.time()
    sym, uni, date_i, o, h, l, c, v = B.load(path)
    end_i = (END - EPOCH).days
    keep = (date_i <= end_i) & np.isfinite(c) & (c > 0) & (o > 0) & (h >= l) & (l > 0)
    sym, date_i, o, h, l, c, v = (x[keep] for x in (sym, date_i, o, h, l, c, v))
    common_code = np.array([is_common(str(x)) for x in uni])
    n_all = len(uni)
    keep = common_code[sym]
    sym, date_i, o, h, l, c, v = (x[keep] for x in (sym, date_i, o, h, l, c, v))
    print(f"common-stock filter: kept {int(common_code.sum()):,} of {n_all:,} symbols ({keep.mean()*100:.1f}% of rows); load {time.time()-t0:.0f}s", flush=True)
    order = np.lexsort((date_i, sym))
    sym, date_i, o, h, l, c, v = (x[order] for x in (sym, date_i, o, h, l, c, v))
    dup = np.r_[False, (np.diff(sym) == 0) & (np.diff(date_i) == 0)]
    if dup.any():
        sym, date_i, o, h, l, c, v = (x[~dup] for x in (sym, date_i, o, h, l, c, v))
    cal = np.unique(date_i)
    first_i = (FIRST_TRADE - EPOCH).days
    SEG, names = [], []
    for code, q, s, so, sh, sl, sc, sv in B.segments(sym, date_i, o, h, l, c, v):
        atr, liq, spac, ret, cand, ret1 = analyze(s, so, sh, sl, sc, sv)
        if not liq.any():
            continue
        SEG.append(dict(code=int(code), s=s, o=so, h=sh, l=sl, c=sc, atr=atr, liq=liq, spac=spac, ret=ret, ret1=ret1, cand=cand))
        names.append(str(uni[code]) + ("" if q == 0 else f"#{q}"))
    print(f"{len(SEG):,} common-stock segments ever liquid; {time.time()-t0:.0f}s", flush=True)
    dropped, dup_log = find_duplicates(SEG, names)
    print(f"duplicate companies removed: {len(dropped):,} series; examples (kept | dropped | overlapping sessions): {dup_log[:25]}", flush=True)
    # ranking universe and percentile ranks by session
    ids, rows_, sess_, rets = [], [], [], []
    for i, g in enumerate(SEG):
        if i in dropped:
            continue
        m = g["liq"] & ~g["spac"] & np.isfinite(g["ret"])
        if m.any():
            idx = np.where(m)[0]
            ids.append(np.full(len(idx), i)); rows_.append(idx); sess_.append(g["s"][idx]); rets.append(g["ret"][idx])
    ids, rows_, sess_, rets = (np.concatenate(x) for x in (ids, rows_, sess_, rets))
    pct = pd.Series(rets).groupby(sess_).rank(pct=True, method="average").to_numpy()
    for i, g in enumerate(SEG):
        g["rank"] = np.full(len(g["c"]), np.nan)
    order2 = np.argsort(ids, kind="stable")
    ids, rows_, pct = ids[order2], rows_[order2], pct[order2]
    cuts = np.r_[0, np.flatnonzero(np.diff(ids)) + 1, len(ids)]
    for a_, b_ in zip(cuts[:-1], cuts[1:]):
        SEG[ids[a_]]["rank"][rows_[a_:b_]] = pct[a_:b_]
    per_day = pd.Series(1, index=sess_).groupby(level=0).sum()
    print(f"ranking universe: {len(ids):,} stock-days; eligible stocks per session median {int(per_day.median())}, min {int(per_day.min())}, max {int(per_day.max())}; {time.time()-t0:.0f}s", flush=True)
    return SEG, names, dropped, cal


def trades_for(SEG, dropped, cal, top, version, market_ok=None, long_only=False):
    init, mm, cap = VERSIONS[version]
    first_i = (FIRST_TRADE - EPOCH).days
    R = dict(sess_e=[], sess_x=[], d=[], px_e=[], px_x=[], a0=[], res=[], held=[], how=[], sym=[], rank=[], f_sess=[], f_incr=[], f_tid=[])
    for i, g in enumerate(SEG):
        if i in dropped or not g["cand"]:
            continue
        s, so, sh, sl, sc, atr = g["s"], g["o"], g["h"], g["l"], g["c"], g["atr"]
        last_exit = -1
        for t, d in g["cand"]:
            rk = g["rank"][t]
            if t < last_exit or not np.isfinite(rk) or g["spac"][t] or not g["liq"][t] or t + 1 >= len(sc) or cal[s[t + 1]] < first_i:
                continue
            if top < 1.0 and not ((d > 0 and rk >= 1.0 - top) or (d < 0 and rk <= top)):
                continue
            if long_only and d < 0:
                continue
            if market_ok is not None and d > 0 and not market_ok[s[t]]:
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
            R["f_sess"].append(s[e:x + 1]); R["f_incr"].append(incr); R["f_tid"].append(np.full(len(incr), tid))
    for k in ("sess_e", "sess_x", "d", "sym"):
        R[k] = np.asarray(R[k], dtype=np.int64)
    for k in ("px_e", "px_x", "a0", "res", "held", "rank"):
        R[k] = np.asarray(R[k], dtype=float)
    R["how"] = np.asarray(R["how"])
    for k in ("f_sess", "f_incr", "f_tid"):
        R[k] = np.concatenate(R[k]) if R[k] else np.array([])
    return R


def main():
    prices_path, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); selftest_common()
    SEG, names, dropped, cal = build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows, pt, ext, yr = [], [], [], []
    for top in TOPS:
        for vname in VERSIONS:
            R = trades_for(SEG, dropped, cal, top, vname)
            n = len(R["d"])
            print(f"top {int(top*100)}%: {vname[:11]}: {n:,} trades", flush=True)
            if n == 0:
                continue
            rng_key = np.random.default_rng(SEED).random(n)
            ed = dates[R["sess_e"]]
            for sname, sides in SIDES.items():
                for wn, (lo, hi) in WIN.items():
                    m = np.isin(R["d"], sides) & np.asarray((ed >= lo) & (ed <= hi))
                    if m.any():
                        pt.append({"strongest share kept": top, "version": vname[:11], "sides": sname, "window": wn, "trades": int(m.sum()), "win rate %": float((R["res"][m] > 0).mean() * 100), "average ATR per trade": float(R["res"][m].mean()),
                                   "median ATR per trade": float(np.median(R["res"][m])), "average sessions held": float(R["held"][m].mean()), "stocks traded": int(len(set(R["sym"][m])))})
                for cap in CAPS:
                    P = B.portfolio(R, cal, sides, SIZE, cap, rng_key)
                    capl = f"position value capped at {int(cap*100)}% of the account"
                    for wn, (lo, hi) in WIN.items():
                        st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                        if not st:
                            continue
                        inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                        usd = P["trade_usd"][inw]; resa = R["res"][inw]; top10 = np.sort(usd)[::-1][:10]
                        st.update({"strongest share kept": top, "version": vname, "sides": sname, "size per ATR %": SIZE, "account limit": capl, "window": wn, "trades": int(inw.sum()), "stocks traded": int(len(set(R["sym"][inw]))),
                                   "win rate %": float((resa > 0).mean() * 100) if inw.any() else np.nan, "average ATR per trade": float(resa.mean()) if inw.any() else np.nan,
                                   "ten biggest trades share of profit %": float(top10.sum() / usd.sum() * 100) if usd.sum() > 0 else np.nan, "total profit $": float(usd.sum()), "signals skipped, account full": P["skipped_cap"]})
                        rows.append(st)
                        if wn.startswith("whole") and cap == 2.0 and top in (0.10, 1.0):
                            yr.append(pd.Series(cal_y, name=f"top {int(top*100)}% | {vname[:11]} | {sname}"))
            if top in (0.10, 1.0):
                T = pd.DataFrame({"strongest share kept": top, "version": vname[:11], "stock": [names[i] for i in R["sym"]], "direction": np.where(R["d"] > 0, "long", "short"), "entry date": ed.date, "exit date": dates[R["sess_x"]].date,
                                  "entry price": R["px_e"], "exit price": R["px_x"], "ATR percent of price": R["a0"] / R["px_e"] * 100, "6-month rank at entry (1 = strongest)": R["rank"], "result in ATR": R["res"], "sessions held": R["held"]})
                ext.append(T.nsmallest(12, "result in ATR")); ext.append(T.nlargest(12, "result in ATR"))
    S = pd.DataFrame(rows); S.to_csv(out_dir / "common_momentum_summary.csv", index=False)
    PT = pd.DataFrame(pt); PT.to_csv(out_dir / "per_trade_before_sizing.csv", index=False)
    pd.concat(ext).to_csv(out_dir / "extreme_trades.csv", index=False)
    pd.DataFrame(yr).T.round(2).to_csv(out_dir / "profit_by_year_pct.csv")
    spy = None
    if len(sys.argv) > 3:
        sp = pd.read_parquet(sys.argv[3])
        sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
        pnl_spy = np.zeros(len(cal)); pos = np.searchsorted(cal, sp["date_i"].to_numpy()); cc = sp["close"].to_numpy(float)
        pnl_spy[pos[1:]] = np.floor(CAPITAL / cc[0]) * np.diff(cc)
        spy = pd.DataFrame({wn: B.wstats(pnl_spy, dates, lo, hi)[0] for wn, (lo, hi) in WIN.items()}).T
        spy.to_csv(out_dir / "spy_buy_and_hold.csv")
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600)
    cols = ["strongest share kept", "sides", "version", "trades", "stocks traded", "win rate %", "average ATR per trade", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %",
            "first date account below zero", "average open positions", "average position value % of account", "signals skipped, account full"]
    print("\n==== per trade before sizing and account limits (ATR, net of cost) ====")
    print(PT[PT.window.str.startswith("whole")].round(3).to_string(index=False))
    for wn in WIN:
        v = S[(S.window == wn) & (S["account limit"] == "position value capped at 200% of the account")].copy()
        v["version"] = v["version"].str.slice(0, 11)
        v = v.sort_values(["sides", "strongest share kept", "version"], key=lambda col: col.map({"long only": 0, "long and short": 1, "short only": 2}) if col.name == "sides" else col)
        print(f"\n==== {wn} | 0.10% per ATR | position value capped at 200% of the account ====")
        print(v[cols].round(2).to_string(index=False))
    v = S[(S.window.str.startswith("whole")) & (S["account limit"] == "position value capped at 100% of the account") & (S.sides == "long only")].copy()
    v["version"] = v["version"].str.slice(0, 11)
    print("\n==== whole in-sample | long only | cap 100% of the account (fully paid) ====")
    print(v.sort_values(["strongest share kept", "version"])[cols].round(2).to_string(index=False))
    if spy is not None:
        print("\n==== SPY buy and hold, price only ===="); print(spy[["profit per year %", "Sharpe ratio", "max drawdown %"]].round(2).to_string())
    print("\n==== profit by calendar year, percent of $300k (cap 200%) ===="); print(pd.DataFrame(yr).T.round(1).to_string())
    print("\n==== 12 worst and 12 best trades (top 10% and 100% rows) ===="); print(pd.concat(ext).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
