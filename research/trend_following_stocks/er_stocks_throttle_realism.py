"""Stocks, long only: (A) drawdown throttle judged by profit per year divided by max drawdown, and (B) realism stress tests (Michael, 19 Nov 2026: "use profit to maximum drawdown, not the Sharpe ratio, as the main measure; look at the drawdown throttle; then do the realism stress tests").
Usage: python er_stocks_throttle_realism.py stock_prices.parquet OUT_DIR spy_prices.parquet

Everything is the current baseline (volume-surge ranking when the account is full, 1.5 ATR pullback, 4 ATR initial and 5 ATR trailing stop, SPY above its 200-day, strongest 20% by 126-session return, $3M floor, 0.10% of a fixed $300,000 per ATR,
cost 0.10 ATR round trip = 0.05 ATR a side, cap 200% and 100%) plus one change per variant. Every variant is run with volume-surge ranking (one run) and the mean of 8 random picks (with the lowest and highest pick).
Main measure: profit per year divided by max drawdown from peak (the account is a fixed $300,000). Sharpe ratio is only a side column.

PART A, drawdown throttle: risk per ATR for NEW entries is cut while the account (closed trades plus open marks) is a set distance below its previous peak. Positions already open keep their size.
  Triggers 5, 10, 15, 20% below peak; size multipliers 0.5, 0.25 and 0 (no new entries); and a smooth version that shrinks size in a straight line from full at the peak to a quarter at 20% below it.
  Also the same at cap 200% with a 4% a year charge on borrowed money. Start-year tables (account started empty on 1 January of each year 2000 to 2020) for the baseline and the best-looking throttles.
PART B, realism (all against the same baseline):
  1 cost multiples: round-trip cost 0.10 ATR x 1, 2, 3, 4, 6.
  2 extra cost as a share of the fill day's high-to-low range, entry only, exit only (the stop fill) and both: 5, 10, 20%.
  3 profit and cost by liquidity bucket (15-day average dollar volume 3-10M, 10-30M, 30-100M, 100M+): trades, average ATR per trade with the SPY move beside it, share of profit, and the position as a share of the stock's daily dollar volume;
    then costs that rise for the thinner buckets (ASSUMED multiples, not measured).
  4 trades that end because the price series ends before the sample does (delisting-type, "data end" exits): how many and how much profit, then an extra loss of 10, 25, 50 and 100% of the last price on those trades.
  5 a combined hostile case: 2x cost, tiered liquidity cost and a 25% haircut on delisting-type exits.
In-sample only (data through 2021-08-06); the sealed years are never read. Post hoc: nothing here is validated.
"""
import heapq
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
import er_stocks_spy_buffer as SB
import er_stocks_start_years as SY
from er_stocks import CAPITAL, END

KSEEDS = MI.KSEEDS
BORROW_RATE = 0.04
BASE_COST = B.COST_RT          # 0.10 ATR round trip
BUCKET_EDGES = [3e6, 10e6, 30e6, 100e6, np.inf]
BUCKET_NAMES = ["3-10M a day", "10-30M a day", "30-100M a day", "100M+ a day"]


# ---------------------------------------------------------------- account simulator (a copy of MI.portfolio_gen with extra realism hooks; with no hooks it must equal it exactly)
def account(R, cal, cap, key, mult_fn=None, cost_rt=None, cost_trade=None, slip_e=0.0, slip_x=0.0, hair=None):
    """cost_rt: round-trip cost in ATR (default the baseline 0.10). cost_trade: per-trade multiple of that cost. slip_e / slip_x: extra cost per side as a share of the high-to-low range of the entry / exit day.
    hair: per-trade extra loss as a share of the exit price, charged on the exit day. mult_fn(equity, peak): size multiple for a new entry."""
    cost_rt = BASE_COST if cost_rt is None else cost_rt
    n = len(R["d"]); m = len(cal); tgt = CAPITAL * M.SIZE / 100.0
    base_sh = np.floor(tgt / R["a0"])
    idx = np.where(base_sh >= 1)[0]
    order = idx[np.lexsort((key[idx], R["sess_e"][idx]))]
    cnt = np.bincount(R["f_tid"], minlength=n); off = np.r_[0, np.cumsum(cnt)]
    pnl = np.zeros(m); taken = np.zeros(n, bool); shares = np.zeros(n); heap = []; gross = 0.0
    ptr = 0; cum = 0.0; peak = 0.0
    par = R["parent"]
    for i in order:
        s = R["sess_e"][i]
        while heap and heap[0][0] < s:
            _x = heapq.heappop(heap); gross -= _x[1]
        if par[i] >= 0 and not taken[par[i]]:
            continue
        sh = base_sh[i]
        if mult_fn is not None:
            if s > ptr:
                cs = cum + np.cumsum(pnl[ptr:s]); peak = max(peak, cs.max()); cum = cs[-1]; ptr = s
            sh = np.floor(tgt * mult_fn(CAPITAL + cum, CAPITAL + peak) / R["a0"][i])
        if sh < 1:
            continue
        notional = sh * R["px_e"][i]
        if gross + notional > cap * CAPITAL:
            continue
        taken[i] = True; shares[i] = sh; gross += notional; heapq.heappush(heap, (R["sess_x"][i], notional, -1))
        a, b = off[i], off[i + 1]
        pnl[R["f_sess"][a:b]] += R["f_incr"][a:b] * sh
        c_ps = 0.5 * cost_rt * R["a0"][i] * (1.0 if cost_trade is None else cost_trade[i])
        ee = slip_e * R["rng_e"][i]; ex = slip_x * R["rng_x"][i]
        if hair is not None and hair[i] > 0:
            ex += hair[i] * R["px_x"][i]
        pnl[s] -= (c_ps + ee) * sh; pnl[R["sess_x"][i]] -= (c_ps + ex) * sh
    notional = shares * R["px_e"]
    dn = np.zeros(m + 1); dv = np.zeros(m + 1)
    tk = np.flatnonzero(taken)
    np.add.at(dn, R["sess_e"][tk], 1.0); np.add.at(dn, R["sess_x"][tk] + 1, -1.0)
    np.add.at(dv, R["sess_e"][tk], notional[tk]); np.add.at(dv, R["sess_x"][tk] + 1, -notional[tk])
    return dict(pnl=pnl, taken=taken, shares=shares, open_n=np.cumsum(dn)[:m], gross=np.cumsum(dv)[:m])


# ---------------------------------------------------------------- evaluation
NUMCOLS = ["profit per year %", "max drawdown %", "profit per year / drawdown", "worst year %", "Sharpe ratio", "trades taken", "average open positions", "% of sessions at the cap"]


def eval_rows(R, P, cap, dates, spy_close, WIN, label):
    rows = I1.eval_P(R, P, cap, dates, spy_close, WIN, dict(label))
    for r in rows:
        dd = abs(r["max drawdown %"])
        r["profit per year / drawdown"] = r["profit per year %"] / dd if dd > 0 else np.nan
    return rows


def run_set(R, cal, dates, spy_close, WIN, label, key_vs, kseeds=KSEEDS, charge=False, **kw):
    """Rows for cap 200% and 100%: volume-surge ranking (one run) and the mean of K random picks. charge=True adds the cap-200% version with a 4% a year charge on borrowed money."""
    out = []
    for cap in (2.0, 1.0):
        for chg in ((False, True) if (charge and cap == 2.0) else (False,)):
            def fin(P):
                return MI.add_interest(P, 0.0, BORROW_RATE) if chg else P
            P0 = account(R, cal, cap, key_vs, **kw)
            lab = dict(label); lab.update({"ranking": "volume surge", "borrowing charge": "4% a year" if chg else "none"})
            for r in eval_rows(R, fin(P0) | {"taken": P0["taken"]}, cap, dates, spy_close, WIN, lab):
                r["ratio lowest pick"] = np.nan; r["ratio highest pick"] = np.nan; out.append(r)
            allr = []
            for s in range(kseeds):
                key = np.random.default_rng(1000 + s).random(len(R["d"]))
                P = account(R, cal, cap, key, **kw)
                lab = dict(label); lab.update({"ranking": "random pick (mean of 8)", "borrowing charge": "4% a year" if chg else "none"})
                for r in eval_rows(R, fin(P) | {"taken": P["taken"]}, cap, dates, spy_close, WIN, lab):
                    r["seed"] = s; allr.append(r)
            D = pd.DataFrame(allr)
            for per, v in D.groupby("period"):
                r = dict(label); r.update({"ranking": "random pick (mean of 8)", "borrowing charge": "4% a year" if chg else "none", "cap %": int(cap * 100), "period": per,
                                           "ratio lowest pick": v["profit per year / drawdown"].min(), "ratio highest pick": v["profit per year / drawdown"].max(), "signals": len(R["d"])})
                for c in NUMCOLS:
                    r[c] = v[c].mean()
                out.append(r)
    return out


def headline(rows, name):
    for rk in ("volume surge", "random pick (mean of 8)"):
        for cap in (200, 100):
            w = [r for r in rows if r["ranking"] == rk and r["period"].startswith("whole") and r["cap %"] == cap and r["borrowing charge"] == "none"]
            if w:
                r = w[-1]
                print(f"  {name} | {rk} | cap {cap}%: +{r['profit per year %']:.1f}% a year / drawdown {r['max drawdown %']:.1f}% / profit÷drawdown {r['profit per year / drawdown']:.2f} / worst year {r['worst year %']:.1f}% / Sharpe {r['Sharpe ratio']:.2f} / trades {r['trades taken']:.0f}", flush=True)


def print_tables(S, order, WIN, title, cols_extra=()):
    cols = ["version", "ranking", "profit per year %", "max drawdown %", "profit per year / drawdown", "ratio lowest pick", "ratio highest pick", "worst year %", "Sharpe ratio", "trades taken", "average open positions"] + list(cols_extra)
    for chg in ("none", "4% a year"):
        for wn in WIN:
            for cap in ((200, 100) if chg == "none" else (200,)):
                v = S[(S.period == wn) & (S["cap %"] == cap) & (S["borrowing charge"] == chg)].copy()
                if v.empty:
                    continue
                v["o"] = v.version.map(order); v = v.sort_values(["ranking", "o"], ascending=[False, True])
                print(f"\n==== {title} | {wn} | cap {cap}% | borrowing charge: {chg} ====")
                print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))


# ---------------------------------------------------------------- part A: throttles
def throttle_fn(dd, mult):
    return lambda eq, pk: mult if eq < pk * (1.0 - dd) else 1.0


def smooth_fn(eq, pk):
    """Full size at the peak, a quarter at 20% or more below it, straight line between."""
    d = max(0.0, 1.0 - eq / pk)
    return max(0.25, 1.0 - d / 0.20 * 0.75)


def start_year_table(R, cal, dates, key_vs, variants, label_fn):
    tabs = []
    ed = dates[R["sess_e"]]
    for nm, kw in variants:
        for cap in (2.0, 1.0):
            for y in range(2000, 2021):
                lo = pd.Timestamp(f"{y}-01-01")
                mask = np.asarray((ed >= lo) & (ed <= END))
                if mask.sum() < 5:
                    continue
                Rs = SY.subset(R, mask)
                P = account(Rs, cal, cap, key_vs[mask], **kw)
                st, _ = B.wstats(P["pnl"], dates, lo, END, P["open_n"], P["gross"])
                if not st:
                    continue
                dd = abs(st["max drawdown %"])
                tabs.append({"version": nm, "cap %": int(cap * 100), "start": lo.date().isoformat(), "profit per year %": st["profit per year %"], "max drawdown % (from peak)": st["max drawdown %"],
                             "profit per year / drawdown": st["profit per year %"] / dd if dd > 0 else np.nan, "worst year %": st["worst year %"], "Sharpe ratio": st["Sharpe ratio"]})
    return pd.DataFrame(tabs)


# ---------------------------------------------------------------- part B helpers
def bucket_of(adv):
    b = np.full(len(adv), -1, int)
    for k in range(len(BUCKET_NAMES)):
        b[(adv >= BUCKET_EDGES[k]) & (adv < BUCKET_EDGES[k + 1])] = k
    return b


def delist_flags(R, last_session, gap=10):
    """Delisting-type: the exit is the last bar of the stock's own series (how == 'data end') and that bar is well before the end of the sample."""
    return (R["how"] == "data end") & (R["sess_x"] < last_session - gap)


def liquidity_table(R, P, dates, spy_close, label):
    bk = bucket_of(R["adv"]); tk = P["taken"]
    bench = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    dollars = P["shares"] * R["res"] * R["a0"]
    part = P["shares"] * R["px_e"] / np.where(R["adv"] > 0, R["adv"], np.nan) * 100
    rows = []
    tot = float(dollars[tk].sum())
    for k, nm in enumerate(BUCKET_NAMES):
        m = tk & (bk == k)
        if not m.any():
            continue
        b = bench[m]; b = b[np.isfinite(b)]
        rows.append({"scenario": label, "liquidity bucket": nm, "trades taken": int(m.sum()), "% of trades": float(m.sum() / tk.sum() * 100), "average ATR per trade (after the 0.10 ATR cost)": float(R["res"][m].mean()),
                     "SPY move over the same holds (ATR units)": float(b.mean()) if len(b) else np.nan, "profit $": float(dollars[m].sum()), "% of total profit": float(dollars[m].sum() / tot * 100) if tot else np.nan,
                     "median position as % of daily dollar volume": float(np.nanmedian(part[m])), "95th percentile position as % of daily dollar volume": float(np.nanpercentile(part[m], 95)),
                     "win rate %": float((R["res"][m] > 0).mean() * 100)})
    return pd.DataFrame(rows)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 90)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    R = MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    key_vs = SB.vs_key(R, FEAT, SEG)
    # the account code in this script, with no extra hooks, must equal the standard one exactly
    for cap in (2.0, 1.0):
        Pa = account(R, cal, cap, key_vs); Pb = MI.portfolio_gen(R, cal, cap, key_vs)
        assert np.allclose(Pa["pnl"], Pb["pnl"]) and (Pa["taken"] == Pb["taken"]).all() and np.allclose(Pa["gross"], Pb["gross"]), "account code differs from the standard one"
        Pc = account(R, cal, cap, key_vs, mult_fn=throttle_fn(0.10, 0.5)); Pd = MI.portfolio_gen(R, cal, cap, key_vs, mult_fn=lambda eq, pk: 0.5 if eq < pk * 0.9 else 1.0)
        assert np.allclose(Pc["pnl"], Pd["pnl"]) and (Pc["taken"] == Pd["taken"]).all(), "throttle differs from the standard one"
        Pe = account(R, cal, cap, key_vs, slip_e=0.05, slip_x=0.05); Pf = MI.portfolio_gen(R, cal, cap, key_vs, slip_frac=0.05)
        assert np.allclose(Pe["pnl"], Pf["pnl"]), "range-share cost differs from the standard one"
    print("account code reproduces the standard one exactly: baseline, throttle and range-share cost (volume-surge ranking, cap 200% and 100%)", flush=True)

    last_session = int(len(dates) - 1)
    assert dates[last_session] <= END, "data run past the in-sample end"
    dl = delist_flags(R, last_session)
    print(f"{len(R['d']):,} signals; {int((R['how'] == 'data end').sum()):,} end at the last bar of their data ({int(dl.sum()):,} well before the end of the sample = delisting-type); exits by stop {int((R['how'] == 'stop').sum()):,}", flush=True)

    # ---------------- PART A
    print("\n######## PART A: drawdown throttle ########", flush=True)
    varsA = [("no throttle (current rule)", {})]
    for dd in (0.05, 0.10, 0.15, 0.20):
        for mult in (0.5, 0.25, 0.0):
            varsA.append((f"new entries x{mult:g} while the account is {int(dd * 100)}%+ below its peak", dict(mult_fn=throttle_fn(dd, mult))))
    varsA.append(("smooth: full size at the peak, a quarter at 20%+ below, straight line between", dict(mult_fn=smooth_fn)))
    rowsA = []
    for nm, kw in varsA:
        out = run_set(R, cal, dates, spy_close, WIN, {"version": nm}, key_vs, charge=True, **kw)
        rowsA += out; headline(out, nm)
    SA = pd.DataFrame(rowsA); SA.round(4).to_csv(out_dir / "throttle_variants.csv", index=False)
    orderA = {nm: i for i, (nm, _) in enumerate(varsA)}
    print_tables(SA, orderA, WIN, "THROTTLE")

    # best-looking throttles by profit÷drawdown (volume surge, cap 200%, whole period) for start-year tables
    w = SA[(SA.ranking == "volume surge") & SA.period.str.startswith("whole") & (SA["cap %"] == 200) & (SA["borrowing charge"] == "none")].copy()
    w = w[w.version != "no throttle (current rule)"].sort_values("profit per year / drawdown", ascending=False)
    pick = list(w.version.head(2))
    wr = SA[(SA.ranking != "volume surge") & SA.period.str.startswith("whole") & (SA["cap %"] == 200) & (SA["borrowing charge"] == "none") & (SA.version != "no throttle (current rule)")].sort_values("profit per year / drawdown", ascending=False)
    for v in wr.version.head(2):
        if v not in pick:
            pick.append(v)
    vm = dict(varsA)
    sy_vars = [("no throttle (current rule)", {})] + [(v, vm[v]) for v in pick]
    T2 = start_year_table(R, cal, dates, key_vs, sy_vars, None); T2.round(3).to_csv(out_dir / "throttle_start_years.csv", index=False)
    for cap in (200, 100):
        v = T2[T2["cap %"] == cap].pivot(index="start", columns="version", values=["profit per year %", "max drawdown % (from peak)", "profit per year / drawdown"])
        print(f"\n==== THROTTLE start-year tables | cap {cap}% | volume-surge ranking ====")
        print(v.round(1).to_string())
        base = T2[(T2["cap %"] == cap) & (T2.version == "no throttle (current rule)")].set_index("start")
        for nm in pick:
            t = T2[(T2["cap %"] == cap) & (T2.version == nm)].set_index("start")
            print(f"  {nm}: profit÷drawdown higher than no throttle in {int((t['profit per year / drawdown'] > base['profit per year / drawdown']).sum())} of {len(t)} starts; drawdown shallower in {int((t['max drawdown % (from peak)'] > base['max drawdown % (from peak)']).sum())}; profit per year lower in {int((t['profit per year %'] < base['profit per year %']).sum())}; worst-start drawdown {t['max drawdown % (from peak)'].min():.1f}% vs {base['max drawdown % (from peak)'].min():.1f}%")

    # ---------------- PART B
    print("\n######## PART B: realism stress tests ########", flush=True)
    varsB = [("baseline (cost 0.10 ATR round trip)", {})]
    for mult in (2, 3, 4, 6):
        varsB.append((f"1 cost x{mult}: round trip {BASE_COST * mult:.2f} ATR", dict(cost_rt=BASE_COST * mult)))
    for f in (0.05, 0.10, 0.20):
        varsB.append((f"2 extra {int(f * 100)}% of the day's range at ENTRY only", dict(slip_e=f)))
        varsB.append((f"2 extra {int(f * 100)}% of the day's range at EXIT (stop fill) only", dict(slip_x=f)))
        varsB.append((f"2 extra {int(f * 100)}% of the day's range at entry and exit", dict(slip_e=f, slip_x=f)))
    bk = bucket_of(R["adv"])
    for nm, mults in (("mild (x3, x2, x1.5, x1)", (3.0, 2.0, 1.5, 1.0)), ("harsh (x5, x3, x2, x1)", (5.0, 3.0, 2.0, 1.0))):
        ct = np.array([mults[b] if b >= 0 else 1.0 for b in bk])
        varsB.append((f"3 thinner stocks cost more, {nm} by liquidity bucket (ASSUMED)", dict(cost_trade=ct)))
    for h in (0.10, 0.25, 0.50, 1.00):
        varsB.append((f"4 extra loss of {int(h * 100)}% of the last price on delisting-type exits", dict(hair=np.where(dl, h, 0.0))))
    ct_h = np.array([(3.0, 2.0, 1.5, 1.0)[b] if b >= 0 else 1.0 for b in bk])
    varsB.append(("5 combined hostile case: cost x2, tiered liquidity (x3, x2, x1.5, x1) on top, 25% loss on delisting-type exits", dict(cost_rt=BASE_COST * 2, cost_trade=ct_h, hair=np.where(dl, 0.25, 0.0))))
    rowsB = []
    for nm, kw in varsB:
        out = run_set(R, cal, dates, spy_close, WIN, {"version": nm}, key_vs, **kw)
        rowsB += out; headline(out, nm)
    SB_ = pd.DataFrame(rowsB); SB_.round(4).to_csv(out_dir / "realism_variants.csv", index=False)
    orderB = {nm: i for i, (nm, _) in enumerate(varsB)}
    print_tables(SB_, orderB, WIN, "REALISM")

    # liquidity buckets and delisting-type trades under the baseline account (volume-surge ranking, cap 200% and 100%)
    for cap in (2.0, 1.0):
        P = account(R, cal, cap, key_vs)
        L = liquidity_table(R, P, dates, spy_close, f"baseline, cap {int(cap * 100)}%, volume surge")
        L.round(3).to_csv(out_dir / f"liquidity_buckets_cap{int(cap * 100)}.csv", index=False)
        print(f"\n==== profit by liquidity bucket | cap {int(cap * 100)}% | volume-surge ranking | taken trades ====")
        print(L.drop(columns=["scenario"]).round(2).to_string(index=False))
        tk = P["taken"]; dollars = P["shares"] * R["res"] * R["a0"]
        d_tk = tk & dl
        print(f"  delisting-type exits among taken trades: {int(d_tk.sum())} of {int(tk.sum())} ({d_tk.sum() / tk.sum() * 100:.1f}%); their profit ${dollars[d_tk].sum():,.0f} of total ${dollars[tk].sum():,.0f}; average ATR per trade {R['res'][d_tk].mean():.2f} vs {R['res'][tk & ~dl].mean():.2f} for the rest")
        sc = tk & (R["how"] == "stop")
        print(f"  stop exits: {int(sc.sum())} trades; average exit gap past the stop level cannot be read here (gap fills at the open are already in the baseline)")
    print("done")


if __name__ == "__main__":
    main()
