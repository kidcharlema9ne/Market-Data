"""Common stocks, strongest 6-month performers, LONG ONLY, with a market condition: enter a long only if SPY closed above its 200-session average on the decision day (Michael, 17 Nov 2026: "do it").
Usage: python er_stocks_spy_filter.py stock_prices.parquet OUT_DIR spy_prices.parquet
Everything else exactly as er_stocks_common_momentum.py (Entry 135): common stocks, one series per company, $3M floor, ranking by 126-session return (top X only), efficiency ratio 0.50 on 20 sessions,
2.5 ATR pullback, next open, one position per stock, old version 1 ATR stop + 5 ATR trail, version 2 2 ATR stop + 5 ATR trail, no time limits, 0.05 ATR a side, whole shares, 0.10% of $300k per ATR,
cap 200% (100% shown), data through 2021-08-06 only. The condition only blocks NEW entries; open positions keep their stops. SPY needs 200 sessions of history, so entries start about Nov 2000.
Shorts are not run (they lost at every cutoff in Entries 134 and 135). X = 10%, 20% and 100% (no ranking); with and without the SPY condition, so its effect is separate from everything else.
The 200-session average is the usual round number, not tuned; the condition was suggested after seeing losses in bear years of these same development years, so it is post hoc.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END, EPOCH, MAIN_START

TOPS = (0.10, 0.20, 1.0)
CAPS = (2.0, 1.0)
SMA_N = 200
SEED = 20261117


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    SEG, names, dropped, cal = M.build(prices_path)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    sp = (pd.read_csv(spy_path) if spy_path.endswith('.csv') else pd.read_parquet(spy_path))
    sp = sp[sp["date_i"] <= (END - EPOCH).days].sort_values("date_i").drop_duplicates("date_i")
    spc = pd.Series(sp["close"].to_numpy(float), index=np.searchsorted(cal, sp["date_i"].to_numpy()))
    spc = spc[spc.index < len(cal)]
    full = spc.reindex(range(len(cal))).ffill()
    sma = full.rolling(SMA_N, min_periods=SMA_N).mean()
    market_ok = (full > sma).fillna(False).to_numpy()
    print(f"SPY condition: {market_ok.mean()*100:.1f}% of sessions SPY above its {SMA_N}-session average; first session allowed {dates[np.argmax(market_ok)].date()}", flush=True)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021 (futures development years)": (MAIN_START, END), "whole in-sample 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    rows, pt, yr, ext = [], [], [], []
    for top in TOPS:
        for vname in M.VERSIONS:
            for cond in ("SPY above 200-day average", "no market condition"):
                R = M.trades_for(SEG, dropped, cal, top, vname, market_ok=(market_ok if cond.startswith("SPY") else None), long_only=True)
                n = len(R["d"])
                print(f"top {int(top*100)}% | {vname[:11]} | {cond}: {n:,} trades", flush=True)
                if n == 0:
                    continue
                rng_key = np.random.default_rng(SEED).random(n)
                ed = dates[R["sess_e"]]
                for wn, (lo, hi) in WIN.items():
                    m = np.asarray((ed >= lo) & (ed <= hi))
                    if m.any():
                        pt.append({"strongest share kept": top, "version": vname[:11], "market condition": cond, "window": wn, "trades": int(m.sum()), "win rate %": float((R["res"][m] > 0).mean() * 100),
                                   "average ATR per trade": float(R["res"][m].mean()), "median ATR per trade": float(np.median(R["res"][m])), "average sessions held": float(R["held"][m].mean())})
                for cap in CAPS:
                    P = B.portfolio(R, cal, (1,), M.SIZE, cap, rng_key)
                    capl = f"position value capped at {int(cap*100)}% of the account"
                    for wn, (lo, hi) in WIN.items():
                        st, cal_y = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                        if not st:
                            continue
                        inw = P["taken"] & np.asarray((ed >= lo) & (ed <= hi))
                        usd = P["trade_usd"][inw]; resa = R["res"][inw]; top10 = np.sort(usd)[::-1][:10]
                        st.update({"strongest share kept": top, "version": vname, "market condition": cond, "account limit": capl, "window": wn, "trades": int(inw.sum()), "stocks traded": int(len(set(R["sym"][inw]))),
                                   "win rate %": float((resa > 0).mean() * 100) if inw.any() else np.nan, "average ATR per trade": float(resa.mean()) if inw.any() else np.nan,
                                   "ten biggest trades share of profit %": float(top10.sum() / usd.sum() * 100) if usd.sum() > 0 else np.nan, "total profit $": float(usd.sum()), "signals skipped, account full": P["skipped_cap"]})
                        rows.append(st)
                        if wn.startswith("whole") and cap == 2.0 and top in (0.10, 1.0):
                            yr.append(pd.Series(cal_y, name=f"top {int(top*100)}% | {vname[:11]} | {cond[:12]}"))
                if top == 0.10:
                    T = pd.DataFrame({"version": vname[:11], "market condition": cond, "stock": [names[i] for i in R["sym"]], "entry date": ed.date, "exit date": dates[R["sess_x"]].date, "result in ATR": R["res"], "sessions held": R["held"]})
                    ext.append(T.nsmallest(8, "result in ATR")); ext.append(T.nlargest(8, "result in ATR"))
    S = pd.DataFrame(rows); S.to_csv(out_dir / "spy_filter_summary.csv", index=False)
    pd.DataFrame(pt).to_csv(out_dir / "per_trade_before_sizing.csv", index=False)
    pd.concat(ext).to_csv(out_dir / "extreme_trades.csv", index=False)
    pd.DataFrame(yr).T.round(2).to_csv(out_dir / "profit_by_year_pct.csv")
    pnl_spy = np.zeros(len(cal)); pos = np.searchsorted(cal, sp["date_i"].to_numpy()); cc = sp["close"].to_numpy(float)
    pnl_spy[pos[1:]] = np.floor(CAPITAL / cc[0]) * np.diff(cc)
    spy = pd.DataFrame({wn: B.wstats(pnl_spy, dates, lo, hi)[0] for wn, (lo, hi) in WIN.items()}).T
    spy.to_csv(out_dir / "spy_buy_and_hold.csv")
    # SPY trend-following itself: hold SPY only while above its 200-day average (a plain benchmark for the condition)
    held = np.r_[False, market_ok[:-1]]
    pnl_tf = np.zeros(len(cal)); sh = np.floor(CAPITAL / cc[0])
    ps = pd.Series(cc, index=pos).reindex(range(len(cal))).ffill().to_numpy()
    d1 = np.r_[0.0, np.diff(ps)]
    pnl_tf = np.where(held, sh * d1, 0.0)
    tf = pd.DataFrame({wn: B.wstats(pnl_tf, dates, lo, hi)[0] for wn, (lo, hi) in WIN.items()}).T
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600)
    cols = ["strongest share kept", "version", "market condition", "trades", "stocks traded", "win rate %", "average ATR per trade", "profit per year %", "Sharpe ratio", "max drawdown %", "years positive", "worst year %",
            "first date account below zero", "average open positions", "average position value % of account", "signals skipped, account full"]
    print("\n==== per trade before sizing (ATR, net of cost), whole window ====")
    print(pd.DataFrame(pt).query("window.str.startswith('whole')", engine="python").round(3).to_string(index=False))
    for wn in WIN:
        for capn in ("200%", "100%"):
            v = S[(S.window == wn) & (S["account limit"] == f"position value capped at {capn} of the account")].copy()
            v["version"] = v["version"].str.slice(0, 11)
            print(f"\n==== {wn} | long only | 0.10% per ATR | position value capped at {capn} of the account ====")
            print(v.sort_values(["strongest share kept", "version", "market condition"])[cols].round(2).to_string(index=False))
    print("\n==== SPY buy and hold, price only ===="); print(spy[["profit per year %", "Sharpe ratio", "max drawdown %"]].round(2).to_string())
    print("\n==== SPY held only while above its 200-day average (no stocks), price only ===="); print(tf[["profit per year %", "Sharpe ratio", "max drawdown %"]].round(2).to_string())
    print("\n==== profit by calendar year, percent of $300k (cap 200%) ===="); print(pd.DataFrame(yr).T.round(1).to_string())
    print("\n==== 8 worst and 8 best trades (top 10% rows) ===="); print(pd.concat(ext).round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
