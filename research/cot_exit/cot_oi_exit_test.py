"""Commercial-50 exit vs fixed 42-session exit on the ORIGINAL open-interest populations (futures, ATR units).

Corrected specification (Michael, 10 Nov 2026)
- COT data is read straight from the cot-history repo (its own loader, all history back to 1992), NOT from the
  committed extract cot_weekly.csv.gz. That extract lost pre-2022 history for about 25 renamed markets (CL, ES, ZN, ZB,
  NG, HG, DX ...), which invalidated the earlier run.
- Legacy futures-only commercial net = commercial long - commercial short; 26-week index, current week included.
- Fresh extreme: index at 100 (long) or 0 (short) AND at least 28 calendar days since the previous report at the same
  extreme. No speculative-position condition.
- Open-interest filter: total legacy futures-only open interest (all delivery months) is at least 3% higher than in the
  immediately preceding weekly report.
- Price-position filter (separate test): the last close before the entry session lies in the top 20% (long) or bottom 20%
  (short) of the preceding 20-session high-low range. Two readings are run: range includes that last session, or covers
  the 20 sessions before it.
- Liquidity universe as in cot-history scripts/cot_report.py (IBKR futures, thin products removed, open interest >= 45,000
  in the signal week). A run without the 45,000 floor is shown as a sensitivity.
- Entry at the open of the first futures session dated AFTER the CFTC publication date (Friday, next Monday in a US
  federal-holiday week). Tuesday data is never used before release.
- Fixed exit: close of session 42 (session 1 = entry session). Commercial-50 exit: first later published report with the
  index <= 50 (long) / >= 50 (short), executed at the next eligible open; otherwise close of session 42.
- ATR = mean true range of the 14 sessions before the entry session. Return = direction * (exit - entry) / ATR.
- One position per market: a signal whose entry falls inside the 42-session fixed holding window of an earlier taken trade
  is skipped ("blocked"). A run with no blocking is shown as a sensitivity. Both exits are evaluated on the SAME entries.
- No costs. Prices: vendor ratio back-adjusted continuous daily bars from R2.

Usage: python cot_oi_exit_test.py <cot-history repo> [futures_prices.parquet]
       (without prices it only counts signals)
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = Path(sys.argv[1])
PRICE_PATH = sys.argv[2] if len(sys.argv) > 2 else None
sys.argv = sys.argv[:1]                       # cot_exit_test reads argv at import; keep its defaults
import cot_exit_test as base                  # noqa: E402  (helpers: price loading, publication dates, statistics)

spec = importlib.util.spec_from_file_location("cot_report", REPO / "scripts" / "cot_report.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

WINDOW = 26
GAP_DAYS = 28
OI_RISE = 0.03
HOLD = 42
RANGE_LEN = 20
TOP = 0.8


def build_markets():
    df = cr.load(REPO)
    markets = {}
    for code, g in df.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        nm = g["name"].iloc[-1]
        if nm not in cr.IBKR or len(g) < WINDOW + 2:
            continue
        ibkr = cr.IBKR[nm][0]
        if ibkr in cr.THIN:
            continue
        g["ibkr"] = ibkr
        g["pub"] = base.pub_dates(pd.DatetimeIndex(g["date"]))
        g["idx"] = base.cot_index(g["comm"], WINDOW)
        markets[ibkr + "|" + code] = g
    return markets


def candidates(markets, prices):
    """Every fresh-extreme signal with its filter flags; trade data attached when a price series exists."""
    rows = []
    for key, g in markets.items():
        ibkr = key.split("|")[0]
        s = prices.get(base.PRICE_ROOTS.get(ibkr, ibkr)) if prices is not None else None
        idx, oi, dates = g["idx"].values, g["oi"].values, g["date"].values.astype("datetime64[D]")
        pub = g["pub"].values.astype("datetime64[D]")
        last_ext = {1: None, -1: None}
        sess_after = np.searchsorted(s["d"], pub, side="right") if s is not None else None
        for w in range(len(g)):
            if np.isnan(idx[w]):
                continue
            d = 1 if idx[w] >= 100 - 1e-9 else (-1 if idx[w] <= 1e-9 else 0)
            if d == 0:
                continue
            prev = last_ext[d]
            last_ext[d] = dates[w]
            if prev is not None and (dates[w] - prev).astype(int) < GAP_DAYS:
                continue
            rec = dict(market=ibkr, dir=d, signal=pd.Timestamp(dates[w]), w=w,
                       liquid=bool(oi[w] >= cr.MIN_OI),
                       oi_up=bool(w >= 1 and (dates[w] - dates[w - 1]).astype(int) <= 10 and oi[w - 1] > 0
                                  and oi[w] / oi[w - 1] - 1 >= OI_RISE - 1e-12),
                       pos_in=False, pos_out=False, ok=False)
            if s is not None:
                e = int(sess_after[w])
                n = len(s["d"])
                if RANGE_LEN + 2 <= e < n:
                    atr = s["atr_before"][e]
                    end_cap = e + HOLD - 1
                    if np.isfinite(atr) and atr > 0 and end_cap < n and \
                            s["gap_cum"][end_cap] - s["gap_cum"][e - 14] == 0:
                        hi_in, lo_in = s["h"][e - RANGE_LEN:e].max(), s["l"][e - RANGE_LEN:e].min()
                        hi_out, lo_out = s["h"][e - RANGE_LEN - 1:e - 1].max(), s["l"][e - RANGE_LEN - 1:e - 1].min()
                        last_close = s["c"][e - 1]

                        def top(hi, lo):
                            if hi <= lo:
                                return False
                            p = (last_close - lo) / (hi - lo)
                            return p >= TOP if d == 1 else p <= 1 - TOP
                        # scheduled commercial-50 exit
                        open_exit = None
                        for v in range(w + 1, len(g)):
                            if np.isnan(idx[v]):
                                continue
                            if sess_after[v] > end_cap:
                                break
                            if (d == 1 and idx[v] <= 50) or (d == -1 and idx[v] >= 50):
                                open_exit = int(sess_after[v])
                                break
                        rec.update(ok=True, e=e, atr=atr, end_cap=end_cap, open_exit=open_exit,
                                   pos_in=top(hi_in, lo_in), pos_out=top(hi_out, lo_out), root=base.PRICE_ROOTS.get(ibkr, ibkr))
            rows.append(rec)
    return pd.DataFrame(rows)


def evaluate(r, s, rule):
    e, d, atr, end_cap = r["e"], r["dir"], r["atr"], r["end_cap"]
    entry = s["o"][e]
    if rule == "comm50" and r["open_exit"] is not None:
        exit_i, how, exit_px = r["open_exit"], "open", s["o"][r["open_exit"]]
    else:
        exit_i, how, exit_px = end_cap, "close", s["c"][end_cap]
    last = exit_i - 1 if how == "open" else exit_i
    hi, lo = s["h"][e:last + 1].max(), s["l"][e:last + 1].min()
    fav = max((hi - entry) / atr if d == 1 else (entry - lo) / atr, 0)
    adv = max((entry - lo) / atr if d == 1 else (hi - entry) / atr, 0)
    return dict(market=r["market"], dir=d, signal=r["signal"], entry_date=s["d"][e], exit_date=s["d"][exit_i],
                hold=exit_i - e + (0 if how == "open" else 1), ret=d * (exit_px - entry) / atr, mfe=fav, mae=adv,
                how=how, year=pd.Timestamp(s["d"][e]).year)


def pick(cand, mask, blocked):
    sel = cand[cand["ok"] & mask].sort_values(["market", "e", "signal"])
    if not blocked:
        return sel
    keep, last_market, free = [], None, -1
    for i, r in sel.iterrows():
        if r["market"] != last_market:
            last_market, free = r["market"], -1
        if r["e"] < free:
            continue
        keep.append(i)
        free = r["e"] + HOLD
    return sel.loc[keep]


def run_rule(sel, prices, rule):
    return pd.DataFrame([evaluate(r, prices[r["root"]], rule) for _, r in sel.iterrows()])


def line(df):
    return f"n={len(df):4d} mean={df['ret'].mean():+.2f} median={df['ret'].median():+.2f} win={100 * (df['ret'] > 0).mean():.0f}%"


def population_mask(cand, name, liquid, price_variant):
    m = pd.Series(True, index=cand.index)
    if liquid:
        m &= cand["liquid"]
    posc = "pos_in" if price_variant == "in" else "pos_out"
    if name == "oi":
        m &= cand["oi_up"]
    elif name == "price":
        m &= cand[posc]
    elif name == "both":
        m &= cand["oi_up"] & cand[posc]
    return m


def full_report(title, sel, prices):
    fx, cm = run_rule(sel, prices, "fixed42"), run_rule(sel, prices, "comm50")
    print(f"\n----- {title} -----")
    print("trades:", len(sel), "| longs", int((sel['dir'] == 1).sum()), "shorts", int((sel['dir'] == -1).sum()),
          "| markets", sel["market"].nunique(), "| signal weeks", sel["signal"].nunique(),
          "| entries", sel["signal"].min().date(), "to", sel["signal"].max().date())
    if len(fx) == 0:
        return
    pd.set_option("display.width", 250, "display.max_columns", 30)
    rows = []
    for nm, df in (("fixed 42", fx), ("commercial-50 exit", cm)):
        rows.append(dict(exit=nm, **base.summarize(df)))
    out = pd.DataFrame(rows)[["exit", "n", "mean", "ci_lo", "ci_hi", "median", "win", "hold", "mfe", "mae", "maxdd", "worst"]]
    print(out.round(2).to_string(index=False))
    pdf = base.paired_diff(cm, fx)
    print("paired commercial-50 minus fixed 42 (same trades):",
          {k: (round(v, 3) if isinstance(v, float) else v) for k, v in pdf.items()})
    print("commercial-50 exits by type:", cm["how"].value_counts().to_dict(),
          "| exited early", f"{100 * (cm['how'] == 'open').mean():.0f}%")
    for nm, mask in (("longs", sel["dir"] == 1), ("shorts", sel["dir"] == -1)):
        f2, c2 = fx[fx["dir"] == (1 if nm == "longs" else -1)], cm[cm["dir"] == (1 if nm == "longs" else -1)]
        if len(f2):
            print(f"  {nm}: fixed 42 {line(f2)} | commercial-50 {line(c2)}")
    for nm, lo, hi in (("entries to 2016", 0, 2016), ("entries 2017+", 2017, 3000)):
        f2, c2 = fx[(fx.year >= lo) & (fx.year <= hi)], cm[(cm.year >= lo) & (cm.year <= hi)]
        if len(f2):
            print(f"  {nm}: fixed 42 {line(f2)} | commercial-50 {line(c2)}")
    f5 = fx.sort_values("ret")
    print(f"  fixed 42 mean without the 5 best trades: {f5['ret'].iloc[:-5].mean():+.2f}; top market share "
          f"{fx['market'].value_counts(normalize=True).iloc[0]:.2f}")


def main():
    prices = None
    if PRICE_PATH:
        prices = {k: base.prep_series(v) for k, v in base.load_prices(PRICE_PATH).items()}
    markets = build_markets()
    print(f"markets from cot-history: {len(markets)}; COT weeks {min(g['date'].min() for g in markets.values()).date()} "
          f"to {max(g['date'].max() for g in markets.values()).date()}")
    starts = pd.Series({k: g['date'].min() for k, g in markets.items()})
    print("markets whose COT history starts after 2008:", sorted(k.split('|')[0] for k in starts[starts > '2008-01-01'].index))
    cand = candidates(markets, prices)
    print(f"fresh-extreme signals: {len(cand)} (longs {int((cand['dir'] == 1).sum())}, shorts {int((cand['dir'] == -1).sum())})"
          f" | with open interest up 3%: {int(cand['oi_up'].sum())}")
    if prices is None:
        return
    cand = cand.reset_index(drop=True)
    print("tradable signals (price history, ATR and 42 sessions available):", int(cand["ok"].sum()),
          "| missing price series:", sorted({k.split('|')[0] for k in markets
                                              if base.PRICE_ROOTS.get(k.split('|')[0], k.split('|')[0]) not in prices}))

    print("\n=== REPRODUCTION GRID: trade counts and fixed 42-session results by reading of the rules")
    print("(targets: open-interest filter alone ~227 trades, ~+0.94 ATR; price position alone ~87; both ~22)")
    for pop in ("oi", "price", "both"):
        for pv in (("in",) if pop == "oi" else ("in", "out")):
            for liquid in (True, False):
                for blocked in (True, False):
                    sel = pick(cand, population_mask(cand, pop, liquid, pv), blocked)
                    fx = run_rule(sel, prices, "fixed42")
                    tag = f"{pop:5s} range={'incl' if pv == 'in' else 'excl'} 45k floor={'on ' if liquid else 'off'} " \
                          f"one-position={'on ' if blocked else 'off'}"
                    print(tag, line(fx) if len(fx) else "n=0")

    print("\n\n=== DETAILED RESULTS (primary reading: 45,000 floor on, one position per market, range includes last session)")
    for title, pop in (("open-interest filter alone", "oi"), ("price-position filter alone", "price"),
                       ("both filters combined", "both")):
        full_report(title, pick(cand, population_mask(cand, pop, True, "in"), True), prices)
    print("\nBenchmark: not applicable to futures ATR returns (stock SPY benchmark rule); benchmark unavailable.")


if __name__ == "__main__":
    main()
