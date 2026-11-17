"""Common stocks, long only, frozen rule: initial stop 4 ATR, trailing stop 5 ATR, no time limit, new entries only while SPY closes above its 200-session average (no band), 0.10% of $300k per ATR, cap 200%.
Michael, 17 Nov 2026: (a) neighbour check of the strength cutoff (15/20/25/30%) and the SPY average length (150/250); (b) rank by 3-month and 12-month return instead of 6 months; (c) are we buying penny stocks / cheap stocks with big
costs? what share of what we hold is under $2, and would a higher dollar-volume floor or a minimum price be better?
Usage: python er_stocks_variants.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE
MODE: look63 | look126 | look252 (rank by that many sessions of return; tops 10/15/20/25/30%; look126 also SPY average 150 and 250 at top 20%)
      price   (6-month ranking, top 20%: results by entry price and by dollar volume of what is bought; minimum-price floors $2/$5/$10/$20; cost stress 2x and 4x)
      floor10 | floor25 | floor50 (dollar-volume floor $10M/$25M/$50M instead of $3M, rebuilt so the ranking universe also changes; tops 10/20/30%)
Everything else as Entries 136 to 140. Costs 0.05 ATR a side (0.10 round trip) unless stressed: THE ARCHIVE HAS NO BID/ASK, so real spreads of cheap stocks cannot be measured, only stressed.
Post hoc on development years; grid; best row is not a result. Data through 2021-08-06 only; sealed years untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START
from er_stocks_market_band import switch

VNAME = "initial stop 4 ATR, trailing stop 5 ATR"
SEED = 20261117
ADV = {}
_orig_analyze = M.analyze


def analyze_keep_adv(s, o, h, l, c, v):
    r = _orig_analyze(s, o, h, l, c, v)
    ADV[id(r[0])] = pd.Series(c * v).rolling(M.ADV_N).mean().to_numpy()      # 15-session average dollar volume, keyed by the ATR array of that segment
    return r


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    if mode.startswith("look"):
        M.RET_N = int(mode[4:])
    if mode.startswith("floor"):
        M.FLOOR = float(mode[5:]) * 1e6
    if mode == "price":
        M.analyze = analyze_keep_adv
    print(f"mode {mode}: ranking lookback {M.RET_N} sessions; dollar-volume floor ${M.FLOOR:,.0f}", flush=True)
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    SEG, names, dropped, cal = M.build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()

    def market(n_avg):
        sma = full.rolling(n_avg, min_periods=n_avg).mean()
        return switch(((full / sma - 1.0) * 100).to_numpy(), 0, 0)

    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows = []

    def run(label, top, mk, caps=(2.0,), filt=None):
        saved = None
        if filt is not None:                                   # keep only signals whose decision-day close passes the filter
            saved = [g["cand"] for g in SEG]
            for g in SEG:
                g["cand"] = [(t, d) for (t, d) in g["cand"] if filt(g, t)]
        R = M.trades_for(SEG, dropped, cal, top, VNAME, market_ok=mk, long_only=True)
        if saved is not None:
            for g, cd in zip(SEG, saved):
                g["cand"] = cd
        n = len(R["d"])
        out = []
        if n == 0:
            return R, None, out
        key = np.random.default_rng(SEED).random(n)
        ed = dates[R["sess_e"]]
        for cap in caps:
            P = B.portfolio(R, cal, (1,), M.SIZE, cap, key)
            for wn, (lo, hi) in WIN.items():
                st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                if not st:
                    continue
                inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                ra = R["res"][inw]
                rec = {"setting": label, "strongest share kept": top, "cap %": int(cap * 100), "window": wn, "trades": int(inw.sum()), "win rate %": float((ra > 0).mean() * 100) if inw.any() else np.nan,
                       "average ATR per trade": float(ra.mean()) if inw.any() else np.nan, "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"],
                       "worst year %": st["worst year %"], "years positive": st["years positive"], "average position value % of account": st["average position value % of account"]}
                rows.append(rec); out.append(rec)
            if cap == caps[0]:
                P0 = P
        print(f"{label} | top {int(top*100)}% | {n:,} signals, {int(P0['taken'].sum()):,} taken", flush=True)
        return R, P0, out

    mk200 = market(200)
    diag = []
    if mode.startswith("look"):
        for top in (0.10, 0.15, 0.20, 0.25, 0.30):
            run(f"rank by {M.RET_N}-session return, SPY average 200", top, mk200, caps=(2.0, 1.0))
        if M.RET_N == 126:
            for navg in (150, 250):
                run(f"rank by {M.RET_N}-session return, SPY average {navg}", 0.20, market(navg), caps=(2.0, 1.0))
    elif mode.startswith("floor"):
        for top in (0.10, 0.20, 0.30):
            R, P0, _ = run(f"dollar-volume floor ${M.FLOOR/1e6:g}M", top, mk200)
            if top == 0.20 and P0 is not None:
                px = R["px_e"][P0["taken"]]
                diag.append(f"share of trades taken priced under $2: {np.mean(px<2)*100:.1f}%, under $5: {np.mean(px<5)*100:.1f}%, under $10: {np.mean(px<10)*100:.1f}%; median entry price ${np.median(px):.2f}")
    else:  # price
        R, P0, _ = run("baseline: dollar-volume floor $3M, no price floor", 0.20, mk200)
        tk = P0["taken"]
        px, a0, notional = R["px_e"], R["a0"], np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"]) * R["px_e"]
        usd = P0["trade_usd"]
        # dollar volume at the decision day
        adv = np.full(len(px), np.nan)
        for k in np.where(tk)[0]:
            g = SEG[R["sym"][k]]
            r_e = int(np.searchsorted(g["s"], R["sess_e"][k]))
            a_ = ADV.get(id(g["atr"]))
            if a_ is not None and r_e >= 1:
                adv[k] = a_[r_e - 1]
        def table(vals, edges, labels, title):
            print(f"\n==== {title}: trades taken by the baseline rule (top 20%, 200% cap, whole 2000 to Aug 2021) ====")
            tot_n, tot_n_usd, tot_profit = tk.sum(), notional[tk].sum(), usd[tk].sum()
            lines = []
            for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
                m = tk & (vals >= lo) & (vals < hi)
                if m.sum() == 0:
                    continue
                lines.append({"bucket": lab, "trades": int(m.sum()), "% of trades": m.sum() / tot_n * 100, "% of dollars invested": notional[m].sum() / tot_n_usd * 100,
                              "% of total profit": usd[m].sum() / tot_profit * 100 if tot_profit else np.nan, "win rate %": float((R["res"][m] > 0).mean() * 100), "average ATR per trade": float(R["res"][m].mean()),
                              "typical ATR % of price (median)": float(np.median(a0[m] / px[m] * 100)), "round-trip cost assumed, % of price (average)": float(np.mean(B.COST_RT * a0[m] / px[m] * 100))})
            T = pd.DataFrame(lines); print(T.round(2).to_string(index=False)); T.to_csv(out_dir / (title.split(":")[0].replace(" ", "_") + ".csv"), index=False)
        pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
        table(px, [0, 1, 2, 5, 10, 20, 50, 1e9], ["under $1", "$1 to $2", "$2 to $5", "$5 to $10", "$10 to $20", "$20 to $50", "$50 and up"], "by entry price")
        table(adv, [0, 5e6, 10e6, 25e6, 50e6, 100e6, 1e15], ["$3M to $5M", "$5M to $10M", "$10M to $25M", "$25M to $50M", "$50M to $100M", "$100M and up"], "by 15-session average dollar volume")
        print(f"\nunder $2: {np.mean(px[tk]<2)*100:.1f}% of trades, {notional[tk&(px<2)].sum()/notional[tk].sum()*100:.1f}% of dollars; under $5: {np.mean(px[tk]<5)*100:.1f}% of trades; under $10: {np.mean(px[tk]<10)*100:.1f}% of trades; median entry price ${np.median(px[tk]):.2f}", flush=True)
        for floor_px in (2.0, 5.0, 10.0, 20.0):
            run(f"minimum price ${floor_px:g} at the decision-day close", 0.20, mk200, filt=lambda g, t, fp=floor_px: g["c"][t] >= fp)
        base_cost = B.COST_RT
        for mult in (2.0, 4.0):
            B.COST_RT = M.COST_RT = base_cost * mult
            run(f"cost stress: round trip {B.COST_RT:.2f} ATR ({mult:g}x), no price floor", 0.20, mk200)
            run(f"cost stress: round trip {B.COST_RT:.2f} ATR ({mult:g}x), minimum price $5", 0.20, mk200, filt=lambda g, t: g["c"][t] >= 5.0)
        B.COST_RT = M.COST_RT = base_cost
    S = pd.DataFrame(rows); S.to_csv(out_dir / f"{mode}_summary.csv", index=False)
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
    for wn in WIN:
        for cap in sorted(S["cap %"].unique(), reverse=True):
            v = S[(S.window == wn) & (S["cap %"] == cap)]
            print(f"\n==== {mode} | long only | {VNAME} | cap {cap}% | {wn} ====")
            print(v.drop(columns=["window", "cap %"]).round(2).to_string(index=False))
    for d in diag:
        print(d)
    print("done")


if __name__ == "__main__":
    main()
