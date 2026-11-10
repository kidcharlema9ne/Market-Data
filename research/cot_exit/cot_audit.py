"""COT open-interest / price-position study: reconciliation audit on the 48-market report universe (futures, ATR units).

Purpose (Michael / ChatGPT reconciliation, 10 Nov 2026): find out whether the earlier +0.94 ATR (227 trades) result is
reproducible, and whether any advantage survives across periods, markets and implementation choices. The earlier
original script and trade list were never recovered, so 227 / 87 / 22 and +0.94 / +0.63 are documented claims only.

Rules (unchanged from cot_oi_exit_test.py unless noted)
- Universe: the 48 markets in cot-history's COT report as of 2026-11-03 (cot_universe_report.csv, same selection as
  scripts/cot_report.py). NOTE: the universe is chosen on today's liquidity, which the original study shared.
- Legacy futures-only commercial net, 26-week index (current week included). Arrival at 100 (long) / 0 (short) means the
  previous week was not at that extreme. 28-day rule, reading A (primary): at least 28 calendar days since ANY earlier week
  at the same extreme. Reading B (sensitivity): at least 28 days since the previous ARRIVAL at that extreme.
- Open-interest filter: total legacy futures-only open interest at least 3% above the previous weekly report of the same
  CFTC code (previous report at most 10 days earlier).
- Price-position filter: last close before the entry session in the favourable fifth (long top 20%, short bottom 20%) of the
  preceding 20-session high-low range (range includes that session = "in"; the 20 sessions before it = "out").
- Minimum open interest 45,000 in the signal week (the report's liquidity rule; sensitivity without it).
- Entry at the open of the first futures session dated after the CFTC publication date (Friday 15:30 ET, next Monday in a
  US federal-holiday week). Fixed exit at the close of session 42 (entry session = 1). Commercial-50 exit shown as extra.
- ATR = mean true range of the 14 sessions before the entry session. Return = direction * (exit - entry) / ATR.
  Net return = gross - 0.10 ATR round-trip cost (the original log deducted 0.10).
- One position per market: an entry inside the 42-session window of an earlier taken trade is skipped; applied inside each
  period separately. Order of exclusions follows the reconciliation brief: entry/ATR validity, overlap, then complete path.
- Periods are assigned by CFTC report date: 2008-2017, 2018-2021, 2022-2026 (2022-01-01 to 2026-11-06).

Usage: python cot_audit.py <cot_weekly_full.csv.gz> <cot_universe_report.csv> <futures prices (.parquet or .csv)> [outdir]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
COT_PATH, UNI_PATH, PRICE_PATH = sys.argv[1], sys.argv[2], sys.argv[3]
OUT = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("cot_audit_out")
sys.argv = sys.argv[:1]
import cot_exit_test as base  # noqa: E402

WINDOW, GAP_DAYS, OI_RISE, HOLD, RANGE_LEN, TOP = 26, 28, 0.03, 42, 20, 0.8
COST = 0.10
MIN_OI = 45_000
PERIODS = [("2008-2017", "2008-01-01", "2017-12-31"), ("2018-2021", "2018-01-01", "2021-12-31"),
           ("2022-2026", "2022-01-01", "2026-11-06"), ("all", "2008-01-01", "2026-11-06")]
POPS = [("oi", "open interest up 3% only"), ("price", "price position only"), ("both", "both filters")]
GROUPS = {"currencies and dollar": {"6A", "6B", "6C", "6E", "6J", "6L", "6M", "6N", "6S", "DX"},
          "rates": {"ZB", "ZN", "ZF", "ZT", "TN", "UB", "SR1", "SR3", "ZQ"},
          "stock indexes": {"ES", "MES", "MNQ", "NQ", "RTY", "YM"},
          "energy": {"CL", "BZ", "HO", "RB", "NG"},
          "metals": {"GC", "SI", "HG", "PL"},
          "grains, softs, livestock": {"ZC", "ZS", "ZW", "ZL", "ZM", "KE", "CC", "CT", "KC", "SB", "GF", "HE", "LE"},
          "volatility": {"VX"}}
RATE_CONTRACTS = GROUPS["rates"]
DRAWS = 4000
RNG = np.random.default_rng(20261110)


# ------------------------------------------------------------------ data
def build_markets():
    uni = pd.read_csv(UNI_PATH, dtype={"code": str})
    df = pd.read_csv(COT_PATH, parse_dates=["date"], dtype={"code": str})
    df = df[df["code"].isin(set(uni["code"]))]
    markets = {}
    for code, g in df.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        g["pub"] = base.pub_dates(pd.DatetimeIndex(g["date"]))
        g["idx"] = base.cot_index(g["comm"], WINDOW)
        markets[g["ibkr"].iloc[-1] + "|" + code] = g
    return markets, uni


def make_candidates(markets, prices):
    """One row per ARRIVAL at an extreme (previous week not at that extreme), with every filter flag and trade data."""
    rows, hist = [], []
    for key, g in markets.items():
        ibkr, code = key.split("|")
        root = base.PRICE_ROOTS.get(ibkr, ibkr)
        s = prices.get(root)
        n_s = len(s["d"]) if s is not None else 0
        idx, oi = g["idx"].values, g["oi"].values
        dates = g["date"].values.astype("datetime64[D]")
        pub = g["pub"].values.astype("datetime64[D]")
        sess_after = np.searchsorted(s["d"], pub, side="right") if s is not None else None
        last_ext, last_arr = {1: None, -1: None}, {1: None, -1: None}
        for w in range(len(g)):
            if np.isnan(idx[w]):
                continue
            hist.append(dates[w])
            d = 1 if idx[w] >= 100 - 1e-9 else (-1 if idx[w] <= 1e-9 else 0)
            if d == 0:
                continue
            arrival = w == 0 or np.isnan(idx[w - 1]) or not (idx[w - 1] >= 100 - 1e-9 if d == 1 else idx[w - 1] <= 1e-9)
            gap_a = last_ext[d] is None or (dates[w] - last_ext[d]).astype(int) >= GAP_DAYS
            gap_b = arrival and (last_arr[d] is None or (dates[w] - last_arr[d]).astype(int) >= GAP_DAYS)
            last_ext[d] = dates[w]
            if arrival:
                last_arr[d] = dates[w]
            else:
                continue
            rec = dict(market=ibkr, code=code, dir=d, signal=pd.Timestamp(dates[w]), pub=pd.Timestamp(pub[w]),
                       gap_a=bool(gap_a), gap_b=bool(gap_b), liquid=bool(oi[w] >= MIN_OI),
                       oi_up=bool(w >= 1 and (dates[w] - dates[w - 1]).astype(int) <= 10 and oi[w - 1] > 0
                                  and oi[w] / oi[w - 1] - 1 >= OI_RISE - 1e-12),
                       has_price=False, evaluable=False, pos_in=False, pos_out=False, entry_ok=False, path_ok=False,
                       e=-1, atr=np.nan, end_cap=-1, open_exit=-1, root=root)
            if s is not None:
                e = int(sess_after[w])
                if e < n_s:
                    rec["has_price"], rec["e"] = True, e
                    if e >= RANGE_LEN + 1:
                        rec["evaluable"] = True
                        last_close = s["c"][e - 1]

                        def fav(hi, lo):
                            if hi <= lo:
                                return False
                            p = (last_close - lo) / (hi - lo)
                            return p >= TOP if d == 1 else p <= 1 - TOP
                        rec["pos_in"] = fav(s["h"][e - RANGE_LEN:e].max(), s["l"][e - RANGE_LEN:e].min())
                        rec["pos_out"] = fav(s["h"][e - RANGE_LEN - 1:e - 1].max(), s["l"][e - RANGE_LEN - 1:e - 1].min())
                    atr = s["atr_before"][e] if e >= 15 else np.nan
                    if np.isfinite(atr) and atr > 0:
                        rec["entry_ok"], rec["atr"] = True, float(atr)
                        end_cap = e + HOLD - 1
                        rec["end_cap"] = end_cap
                        if end_cap < n_s and s["gap_cum"][end_cap] - s["gap_cum"][e - 14] == 0:
                            rec["path_ok"] = True
                            for v in range(w + 1, len(g)):
                                if np.isnan(idx[v]):
                                    continue
                                if sess_after[v] > end_cap:
                                    break
                                if (d == 1 and idx[v] <= 50) or (d == -1 and idx[v] >= 50):
                                    rec["open_exit"] = int(sess_after[v])
                                    break
            rows.append(rec)
    return pd.DataFrame(rows), np.array(hist, dtype="datetime64[D]")


# ------------------------------------------------------------------ selection and audit
def in_period(series, period):
    lo, hi = pd.Timestamp(period[1]), pd.Timestamp(period[2])
    return (series >= lo) & (series <= hi)


def overlap_filter(sel):
    keep, last_market, free = [], None, -1
    for i, r in sel.sort_values(["market", "e", "signal"]).iterrows():
        if r["market"] != last_market:
            last_market, free = r["market"], -1
        if r["e"] < free:
            continue
        keep.append(i)
        free = r["e"] + HOLD
    return sel.loc[keep]


def select(c, pop, period, reading="A", floor=True, pv="in", overlap=True, markets=None):
    m = in_period(c["signal"], period) & (c["gap_a"] if reading == "A" else c["gap_b"])
    if floor:
        m &= c["liquid"]
    if pop in ("oi", "both"):
        m &= c["oi_up"]
    if pop in ("price", "both"):
        m &= c["evaluable"] & (c["pos_in"] if pv == "in" else c["pos_out"])
    if markets is not None:
        m &= c["market"].isin(markets)
    sel = c[m & c["entry_ok"]]
    if overlap and len(sel):
        sel = overlap_filter(sel)
    return sel[sel["path_ok"]]


def audit_counts(c, hist, uni, prices, markets, pop, period):
    p = in_period(c["signal"], period)
    cnt = {}
    cnt["1 eligible market codes (report universe)"] = len(uni)
    cnt["1b of which with a futures price series"] = sum(1 for k in markets if base.PRICE_ROOTS.get(k.split('|')[0], k.split('|')[0]) in prices)
    cnt["2 market-weeks with a full 26-week index"] = int(((hist >= np.datetime64(period[1])) & (hist <= np.datetime64(period[2]))).sum())
    x = c[p]
    cnt["3 fresh arrivals at 100 or 0"] = len(x)
    cnt["4 after 28-day rule, reading A (primary)"] = int(x["gap_a"].sum())
    cnt["4 (alt) after 28-day rule, reading B"] = int(x["gap_b"].sum())
    x = x[x["gap_a"]]
    cnt["5a minimum open interest 45,000 (before)"] = len(x)
    x = x[x["liquid"]]
    cnt["5b after the 45,000 floor"] = len(x)
    if pop in ("oi", "both"):
        x = x[x["oi_up"]]
        cnt["6 after open interest up 3%"] = len(x)
    if pop in ("price", "both"):
        cnt["7a price filter not evaluable (no price history)"] = int((~x["evaluable"]).sum())
        x = x[x["evaluable"] & x["pos_in"]]
        cnt["7 after favourable fifth of 20-session range"] = len(x)
    x = x[x["entry_ok"]]
    cnt["8 valid post-publication entry and prior ATR"] = len(x)
    x = overlap_filter(x) if len(x) else x
    cnt["9 after removing overlapping same-market positions"] = len(x)
    x = x[x["path_ok"]]
    cnt["10 with a complete 42-session price path"] = len(x)
    return cnt


# ------------------------------------------------------------------ trades
def evaluate(r, s, rule):
    e, d, atr, end_cap = int(r["e"]), int(r["dir"]), float(r["atr"]), int(r["end_cap"])
    entry = s["o"][e]
    if rule == "comm50" and r["open_exit"] >= 0:
        exit_i, how, px = int(r["open_exit"]), "open", s["o"][int(r["open_exit"])]
    else:
        exit_i, how, px = end_cap, "close", s["c"][end_cap]
    last = exit_i - 1 if how == "open" else exit_i
    hi, lo = s["h"][e:last + 1].max(), s["l"][e:last + 1].min()
    gross = d * (px - entry) / atr
    return dict(entry_price=entry, exit_date=s["d"][exit_i], exit_price=px, gross=gross, ret=gross - COST,
                mfe=max((hi - entry) / atr if d == 1 else (entry - lo) / atr, 0),
                mae=max((entry - lo) / atr if d == 1 else (hi - entry) / atr, 0),
                hold=exit_i - e + (0 if how == "open" else 1), how=how)


def trades(sel, prices, rule="fixed42"):
    out = []
    for _, r in sel.iterrows():
        s = prices[r["root"]]
        t = evaluate(r, s, rule)
        t.update(market=r["market"], code=r["code"], dir=int(r["dir"]), signal=r["signal"], pub=r["pub"],
                 entry_date=pd.Timestamp(s["d"][int(r["e"])]), atr=r["atr"], year=pd.Timestamp(s["d"][int(r["e"])]).year)
        out.append(t)
    return pd.DataFrame(out)


def stats(df):
    if len(df) == 0:
        return dict(n=0)
    lo, hi = base.boot_mean_ci(df)
    return dict(n=len(df), gross=df["gross"].mean(), net=df["ret"].mean(), ci_lo=lo, ci_hi=hi, median=df["ret"].median(),
                win=100 * (df["ret"] > 0).mean(), mfe=df["mfe"].mean(), mae=df["mae"].mean(), hold=df["hold"].mean(),
                worst=df["ret"].min())


def fmt(v):
    return "   --" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:+.2f}" if isinstance(v, float) else str(v))


def short(df):
    if len(df) == 0:
        return "n=   0"
    return f"n={len(df):4d} net={df['ret'].mean():+.2f} (gross {df['gross'].mean():+.2f}) median={df['ret'].median():+.2f} win={100 * (df['ret'] > 0).mean():.0f}%"


# ------------------------------------------------------------------ placebo (random entry dates, same market and direction)
def placebo_tables(prices):
    tab = {}
    for root, s in prices.items():
        n = len(s["d"])
        e = np.arange(15, n - HOLD + 1)
        if len(e) == 0:
            continue
        ok = np.isfinite(s["atr_before"][e]) & (s["atr_before"][e] > 0) & (s["gap_cum"][e + HOLD - 1] - s["gap_cum"][e - 14] == 0)
        e = e[ok]
        long_ret = (s["c"][e + HOLD - 1] - s["o"][e]) / s["atr_before"][e]
        tab[root] = (s["d"][e].astype("datetime64[D]"), long_ret)
    return tab


def placebo_p(sel, tab, period):
    """Chance that random entry dates (same market, same direction, same period, same count) reach the observed net mean."""
    arrs = []
    lo, hi = np.datetime64(period[1]), np.datetime64(period[2])
    for _, r in sel.iterrows():
        d, lr = tab.get(r["root"], (None, None))
        if d is None:
            continue
        m = (d >= lo) & (d <= hi)
        if m.any():
            arrs.append(r["dir"] * lr[m] - COST)
    if not arrs:
        return np.nan, np.nan
    sums = np.zeros(DRAWS)
    for a in arrs:
        sums += a[RNG.integers(0, len(a), size=DRAWS)]
    dist = sums / len(arrs)
    return dist, len(arrs)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prices = {k: base.prep_series(v) for k, v in base.load_prices(PRICE_PATH).items()}
    markets, uni = build_markets()
    cand, hist = make_candidates(markets, prices)
    print(f"report universe {len(uni)} markets: {' '.join(sorted(uni['ibkr']))}")
    print(f"prices {min(v['d'][0] for v in prices.values())} to {max(v['d'][-1] for v in prices.values())}; "
          f"arrival signals {len(cand)} (long {int((cand['dir'] == 1).sum())}, short {int((cand['dir'] == -1).sum())})")
    print("COT weeks by market start (markets with history starting after 2008):",
          {k.split('|')[0]: str(g['date'].min().date()) for k, g in markets.items() if g['date'].min() > pd.Timestamp('2008-01-01')})

    # ---- 1. rerun, three populations, three periods
    print("\n=== 1. POPULATIONS BY PERIOD (fixed 42 sessions; primary rules; net = gross minus 0.10 ATR)")
    print("original claims for 2022-2026 (not reproduced, no script or trades recovered): open interest 227 trades +0.94 net;"
          " price position 87 trades +0.63; both about 22")
    results, all_trades = {}, []
    for pop, label in POPS:
        for period in PERIODS:
            sel = select(cand, pop, period)
            tr = trades(sel, prices, "fixed42")
            results[(pop, period[0])] = (sel, tr)
            st = stats(tr)
            ci = f" 95% range {st['ci_lo']:+.2f} to {st['ci_hi']:+.2f}" if st["n"] else ""
            print(f"{label:28s} {period[0]:10s} {short(tr)}{ci}")
            if period[0] != "all" and len(tr):
                tc = trades(sel, prices, "comm50")
                t2 = tr.merge(tc[["signal", "market", "dir", "exit_date", "exit_price", "gross", "ret"]],
                              on=["signal", "market", "dir"], suffixes=("", "_comm50"))
                t2.insert(0, "period", period[0])
                t2.insert(0, "population", label)
                all_trades.append(t2)
    if all_trades:
        cols = ["population", "period", "market", "code", "dir", "signal", "pub", "entry_date", "entry_price", "exit_date",
                "exit_price", "atr", "gross", "ret", "exit_date_comm50", "exit_price_comm50", "gross_comm50", "ret_comm50",
                "mfe", "mae", "hold"]
        t = pd.concat(all_trades)
        t = t.rename(columns={"signal": "signal"})[cols].rename(columns={
            "signal": "cftc_report_date", "pub": "publication_date_1530_ET", "gross": "atr_return_gross_fixed42",
            "ret": "atr_return_net_fixed42", "exit_date": "exit_date_fixed42", "exit_price": "exit_price_fixed42",
            "gross_comm50": "atr_return_gross_commercial50", "ret_comm50": "atr_return_net_commercial50",
            "exit_date_comm50": "exit_date_commercial50", "exit_price_comm50": "exit_price_commercial50"})
        t.to_csv(OUT / "cot_audit_trades.csv", index=False)

    # ---- 2. eligibility audit
    print("\n=== 2. ELIGIBILITY AUDIT (observations remaining after each step; periods by CFTC report date)")
    rows = []
    for pop, label in POPS:
        print(f"\n-- {label}")
        per = {p[0]: audit_counts(cand, hist, uni, prices, markets, pop, p) for p in PERIODS}
        labels = list(per["all"].keys())
        print(f"{'step':58s}" + "".join(f"{p[0]:>11s}" for p in PERIODS))
        for lab in labels:
            vals = [per[p[0]].get(lab, "") for p in PERIODS]
            print(f"{lab:58s}" + "".join(f"{str(v):>11s}" for v in vals))
            rows.append(dict(population=label, step=lab, **{p[0]: per[p[0]].get(lab, "") for p in PERIODS}))
    pd.DataFrame(rows).to_csv(OUT / "cot_audit_steps.csv", index=False)

    # ---- 3. counts by market and year
    print("\n=== 3. FINAL TRADE COUNTS BY MARKET AND YEAR (2022-2026 populations; full tables in cot_audit_market_year.csv)")
    my = []
    for pop, label in POPS:
        tr = results[(pop, "2022-2026")][1]
        if len(tr):
            print(f"{label}: by year {tr['year'].value_counts().sort_index().to_dict()}")
            print(f"   by market {tr['market'].value_counts().to_dict()}")
        full = results[(pop, "all")][1]
        for (mk, yr), n in full.groupby(["market", "year"]).size().items():
            my.append(dict(population=label, market=mk, year=yr, trades=n))
    pd.DataFrame(my).to_csv(OUT / "cot_audit_market_year.csv", index=False)

    # ---- 4. implementation choices
    print("\n=== 4. IMPLEMENTATION CHOICES (net mean ATR / trades; fixed 42). 28-day reading A or B; 45,000 floor; one position; price range")
    grid = []
    for pop, label in POPS:
        for period in (PERIODS[2], PERIODS[3]):
            for reading in ("A", "B"):
                for floor in (True, False):
                    for ov in (True, False):
                        for pv in (("in", "out") if pop != "oi" else ("in",)):
                            sel = select(cand, pop, period, reading, floor, pv, ov)
                            tr = trades(sel, prices)
                            grid.append(dict(population=label, period=period[0], gap_reading=reading, floor_45k=floor,
                                             one_position=ov, price_range=pv if pop != "oi" else "n/a", n=len(tr),
                                             net=tr["ret"].mean() if len(tr) else np.nan,
                                             median=tr["ret"].median() if len(tr) else np.nan))
    g = pd.DataFrame(grid)
    g.to_csv(OUT / "cot_audit_grid.csv", index=False)
    for (pop, per), x in g.groupby(["population", "period"], sort=False):
        print(f"{pop:28s} {per:10s} trades {int(x['n'].min())}-{int(x['n'].max())}; net mean {x['net'].min():+.2f} to {x['net'].max():+.2f}"
              f" (primary {x.iloc[0]['net']:+.2f}); readings with net > 0: {int((x['net'] > 0).sum())} of {len(x)}")

    # ---- 5. robustness
    print("\n=== 5. ROBUSTNESS (primary rules)")
    tab = placebo_tables(prices)
    m_tests = len(POPS) * 3
    print(f"placebo = {DRAWS} random-entry-date draws with the same markets, directions, count and period, same 42-session hold and 0.10 cost."
          f" One-sided chance that random dates do at least as well. Bonferroni threshold for {m_tests} populations-by-period tests = {0.05 / m_tests:.4f}"
          " (the true number of strategies examined is larger than this and not recorded).")
    for pop, label in POPS:
        for period in PERIODS[:3]:
            sel, tr = results[(pop, period[0])]
            if len(tr) == 0:
                continue
            dist, k = placebo_p(sel, tab, period)
            obs = tr["ret"].mean()
            if isinstance(dist, float):
                continue
            p = (dist >= obs).mean()
            lo, hi = np.percentile(dist, [2.5, 97.5])
            top5 = tr.nlargest(5, "ret")["ret"].sum()
            print(f"{label:28s} {period[0]:10s} n={len(tr):4d} net={obs:+.2f} | random-date mean {dist.mean():+.2f} (95% {lo:+.2f} to {hi:+.2f}) "
                  f"| chance {p:.3f} | top 5 trades = {(str(round(100 * top5 / tr['ret'].sum())) + '%') if tr['ret'].sum() > 0 else 'n/a (no net gain)'} of total gain")
    print("\n-- excluding rate contracts (ZB ZN ZF ZT TN UB SR1 SR3 ZQ)")
    nonrate = set(uni["ibkr"]) - RATE_CONTRACTS
    for pop, label in POPS:
        print(f"{label:28s}", " | ".join(f"{p[0]} {short(trades(select(cand, pop, p, markets=nonrate), prices))}" for p in PERIODS[:3]))
    print("\n-- by market group (2022-2026 | 2008-2017 and 2018-2021 combined), net mean / trades")
    for pop, label in POPS[:1]:
        for gname, mk in GROUPS.items():
            a = trades(select(cand, pop, PERIODS[2], markets=mk), prices)
            b = pd.concat([trades(select(cand, pop, PERIODS[0], markets=mk), prices),
                           trades(select(cand, pop, PERIODS[1], markets=mk), prices)])
            print(f"{label:28s} {gname:26s} 2022-2026 {short(a)} | earlier {short(b)}")
    print("\n-- leave one market out, open interest filter, net mean range")
    for p in PERIODS[:3]:
        tr = results[("oi", p[0])][1]
        if len(tr) > 20:
            vals = [tr[tr.market != m]["ret"].mean() for m in tr["market"].unique()]
            print(f"{p[0]:10s} full {tr['ret'].mean():+.2f}; leaving one market out ranges {min(vals):+.2f} to {max(vals):+.2f}")
    print("\n-- commercial-50 exit vs fixed 42, same trades, net (paired difference with 95% week-cluster range)")
    for pop, label in POPS:
        for p in PERIODS[:3]:
            sel = results[(pop, p[0])][0]
            if len(sel) < 5:
                continue
            a, b = trades(sel, prices, "comm50"), results[(pop, p[0])][1]
            d = base.paired_diff(a, b)
            print(f"{label:28s} {p[0]:10s} fixed 42 {b['ret'].mean():+.2f}/{b['ret'].median():+.2f} | commercial-50 {a['ret'].mean():+.2f}/{a['ret'].median():+.2f}"
                  f" | difference {d.get('matched_diff', float('nan')):+.2f} ({d.get('m_lo', float('nan')):+.2f} to {d.get('m_hi', float('nan')):+.2f})")
    print("\nBenchmark: not applicable to futures ATR returns (stock SPY benchmark rule); benchmark unavailable.")


if __name__ == "__main__":
    main()
