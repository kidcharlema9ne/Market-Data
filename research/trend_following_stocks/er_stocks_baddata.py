"""Stocks, long only: bad-data check on the current best rule, especially stocks under $5 (Michael, 17 Nov 2026; step 2 of the hand-off).
Usage: python er_stocks_baddata.py stock_prices.parquet OUT_DIR spy_prices.parquet
Rule: the current best rule (20-session efficiency ratio 0.50, 1.5 ATR pullback, strongest 20% by 126-session return, SPY above its 200-day for entries, 4 ATR initial / 5 ATR trailing, no time limit,
0.05 ATR a side, 0.10% of $300k per ATR, cap 200% and 100%). Reference must reproduce +22.9% / 0.64 / -22%.
Flags (per stock-day, from the price file itself; nothing is repaired, suspicious data is only flagged and then removed in the reruns):
  clean jump : close-to-close move of more than 30% that is within 4% of a clean split ratio (1/2, 1/3, 1/4, 2, 3, 4): looks like an unadjusted split
  spike      : close-to-close move of more than 40% that is undone within a day (close two days later within -15% to +18% of the close before)
  bad range  : open or close outside that day's high-low range by more than 0.1%
  zero volume: volume of zero
  wide range : high more than 1.8 times the low (soft flag, only reported)
  exit outside range: the recorded exit price is outside that day's high-low range
A trade is flagged if any hard flag (clean jump, spike, bad range, zero volume, exit outside range) falls on the session before entry through the session after exit.
Outputs: top winners table (all, and entry price under $5) with flags; profit concentration; reruns: reference; flagged trades removed; stocks with any clean jump / spike / bad range removed;
10 biggest winning stocks removed; entry-day close floors of $2, $3 and $5. In-sample only (data through 2021-08-06); sealed years untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import EPOCH, MAIN_START, END, CAPITAL
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, run_trades, evaluate, VNAME

PULL = 1.5
CLEAN = (0.5, 1 / 3, 0.25, 2.0, 3.0, 4.0)
HARD = ("clean jump", "spike", "bad range", "zero volume")
CAPTURE = {}


def flag_arrays(o, h, l, c, v):
    n = len(c)
    with np.errstate(all="ignore"):
        r = np.r_[np.nan, c[1:] / c[:-1]]
        clean = np.zeros(n, bool)
        for f in CLEAN:
            clean |= np.abs(r / f - 1) < 0.04
        clean &= np.abs(r - 1) > 0.30
        back = np.r_[c[1:], np.nan] / np.r_[np.nan, c[:-1]]
        spike = (np.abs(r - 1) > 0.40) & (back > 0.85) & (back < 1.18)
        ohlc = (o > h * 1.001) | (o < l * 0.999) | (c > h * 1.001) | (c < l * 0.999)
        zero = v <= 0
        wide = h / l > 1.8
    return {"clean jump": clean, "spike": spike, "bad range": ohlc, "zero volume": zero, "wide range": wide}


def selftest_flags():
    c = np.array([10, 10, 10, 5, 5, 5, 5, 8, 4, 8, 8.0]); o = c.copy(); h = c * 1.01; l = c * 0.99; v = np.full(len(c), 1e6); v[2] = 0
    f = flag_arrays(o, h, l, c, v)
    assert f["clean jump"][3] and not f["clean jump"][4] and f["zero volume"][2] and not f["zero volume"][3]
    assert f["spike"][8] and not f["spike"][3]  # 4 -> 8 returns (8/8... see below)
    print("flag self-test passed", flush=True)


_orig_analyze = M.analyze


def analyze_capture(s, o, h, l, c, v):
    CAPTURE[(int(s[0]), int(s[-1]), len(s), round(float(np.sum(c)), 4))] = v
    return _orig_analyze(s, o, h, l, c, v)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    selftest_flags()
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    M.analyze = analyze_capture
    SEG, names, dropped, cal = M.build(prices_path)
    live = [i for i in range(len(SEG)) if i not in dropped]
    ERC = {i: er_dr(SEG[i], M.ER_N) for i in live}
    M.PULL = 2.5
    chk = [i for i in live if SEG[i]["cand"]][:: 25]
    for i in chk:
        er, dr = ERC[i]
        assert long_cands(SEG[i], er, dr, M.ER_MIN) == [(t, d) for (t, d) in SEG[i]["cand"] if d > 0], f"mismatch in segment {i}"
    print(f"signal check passed on {len(chk)} segments", flush=True)
    M.PULL = PULL
    base = {i: long_cands(SEG[i], *ERC[i], M.ER_MIN) for i in live}
    FL, CUM = {}, {}
    nmiss = 0
    for i in live:
        g = SEG[i]
        v = CAPTURE.get((int(g["s"][0]), int(g["s"][-1]), len(g["s"]), round(float(np.sum(g["c"])), 4)))
        if v is None:
            nmiss += 1
            v = np.full(len(g["c"]), 1.0)
        FL[i] = flag_arrays(g["o"], g["h"], g["l"], g["c"], v)
        CUM[i] = {k: np.r_[0, np.cumsum(a)] for k, a in FL[i].items()}
    print(f"flags computed for {len(live):,} series (volume not matched for {nmiss})", flush=True)
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 600); pd.set_option("display.max_colwidth", 40)

    def run(dropset, cand_fn=None):
        for i in live:
            SEG[i]["cand"] = base[i] if cand_fn is None else cand_fn(i, base[i])
        return run_trades(SEG, dropset, cal, mk)

    R = run(dropped)
    n = len(R["d"])
    key = np.random.default_rng(20261117).random(n)
    P = B.portfolio(R, cal, (1,), M.SIZE, 2.0, key)
    st, _ = B.wstats(P["pnl"], dates, pd.Timestamp("2000-01-01"), END, P["open_n"], P["gross"])
    print(f"REPRODUCTION CHECK (whole, cap 200%, expect +22.9 / 0.64 / -22): {st['profit per year %']:+.1f} / {st['Sharpe ratio']:.2f} / {st['max drawdown %']:.0f}", flush=True)
    if abs(st["Sharpe ratio"] - 0.64) > 0.015:
        print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)

    # per-trade flags
    ex, en, ntr = [], [], n
    tf = {k: np.zeros(n, bool) for k in HARD + ("exit outside range", "wide range")}
    t_row = np.zeros(n, np.int64)
    for k in range(n):
        i = int(R["sym"][k]); g = SEG[i]
        e = int(np.searchsorted(g["s"], R["sess_e"][k])); x = int(np.searchsorted(g["s"], R["sess_x"][k]))
        t_row[k] = e - 1
        a, b = max(e - 1, 0), min(x + 1, len(g["c"]) - 1)
        for name in HARD + ("wide range",):
            tf[name][k] = (CUM[i][name][b + 1] - CUM[i][name][a]) > 0
        px = R["px_x"][k]
        tf["exit outside range"][k] = bool(px > g["h"][x] * 1.001 or px < g["l"][x] * 0.999)
    hard_trade = np.zeros(n, bool)
    for name in HARD + ("exit outside range",):
        hard_trade |= tf[name]
    taken = P["taken"]; usd = P["trade_usd"]
    ed, xd = dates[R["sess_e"]], dates[R["sess_x"]]
    T = pd.DataFrame({"stock": [names[int(i)] for i in R["sym"]], "entry date": ed.date, "exit date": xd.date, "entry price": R["px_e"], "exit price": R["px_x"], "sessions held": R["held"],
                      "ATR gained (net)": R["res"], "net dollars if taken": usd, "taken": taken, "exit type": R["how"]})
    for name in tf:
        T["flag: " + name] = tf[name]
    T["any hard flag"] = hard_trade
    T.to_csv(out_dir / "all_trades.csv.gz", index=False)
    Tt = T[T.taken].copy()
    cols = ["stock", "entry date", "exit date", "entry price", "exit price", "sessions held", "ATR gained (net)", "net dollars if taken", "any hard flag"] + [c for c in T.columns if c.startswith("flag: ")]
    top = Tt.sort_values("net dollars if taken", ascending=False)
    top.head(60)[cols].to_csv(out_dir / "top_winners_all.csv", index=False)
    u5 = top[top["entry price"] < 5]
    u5.head(60)[cols].to_csv(out_dir / "top_winners_under5.csv", index=False)
    tot = Tt["net dollars if taken"].sum()
    print(f"\n==== profit concentration (taken trades, cap 200%, whole): total net ${tot:,.0f} on {len(Tt):,} trades ====")
    conc = {"entry price under $5": Tt[Tt["entry price"] < 5]["net dollars if taken"].sum(), "entry price under $3": Tt[Tt["entry price"] < 3]["net dollars if taken"].sum(),
            "entry price under $10": Tt[Tt["entry price"] < 10]["net dollars if taken"].sum(), "trades with any hard flag": Tt[Tt["any hard flag"]]["net dollars if taken"].sum(),
            "trades with a wide-range day (soft flag)": Tt[Tt["flag: wide range"]]["net dollars if taken"].sum()}
    for k_ in (10, 25, 50, 100):
        conc[f"top {k_} trades"] = top["net dollars if taken"].head(k_).sum()
    cdf = pd.DataFrame({"measure": list(conc), "net dollars": list(conc.values())}); cdf["share of total profit %"] = cdf["net dollars"] / tot * 100
    cdf.to_csv(out_dir / "profit_concentration.csv", index=False); print(cdf.round(1).to_string(index=False))
    fc = pd.DataFrame({"flag": list(tf) + ["any hard flag"], "trades flagged (all signals)": [int(tf[k].sum()) for k in tf] + [int(hard_trade.sum())],
                       "taken trades flagged": [int((tf[k] & taken).sum()) for k in tf] + [int((hard_trade & taken).sum())],
                       "net dollars of flagged taken trades": [float(usd[tf[k] & taken].sum()) for k in tf] + [float(usd[hard_trade & taken].sum())]})
    fc.to_csv(out_dir / "flag_counts.csv", index=False); print("\n==== flagged trades ===="); print(fc.round(0).to_string(index=False))
    print("\n==== 40 biggest winning trades (taken, cap 200%) ===="); print(top.head(40)[cols].round(2).to_string(index=False))
    print("\n==== 40 biggest winning trades with entry price under $5 ===="); print(u5.head(40)[cols].round(2).to_string(index=False))
    seg_flag = {i: {k: int(FL[i][k].sum()) for k in HARD} for i in live}
    sdf = pd.DataFrame([{"stock": names[i], **seg_flag[i]} for i in live if sum(seg_flag[i].values()) > 0])
    sdf.to_csv(out_dir / "flagged_series.csv", index=False)
    print(f"\nseries with any hard flag anywhere in their life: {len(sdf):,} of {len(live):,}; with a clean jump {int((sdf['clean jump'] > 0).sum())}, spike {int((sdf['spike'] > 0).sum())}, bad range {int((sdf['bad range'] > 0).sum())}, zero volume {int((sdf['zero volume'] > 0).sum())}", flush=True)

    # reruns
    rows = []
    def add(label, Rx):
        rows.extend(evaluate(Rx, cal, dates, spy_close, WIN, {"version": label}))
        print(f"{label}: {len(Rx['d']):,} signals", flush=True)
    add("reference (current best rule)", R)
    flagged_set = {(int(R["sym"][k]), int(t_row[k])) for k in range(n) if hard_trade[k]}
    add("flagged trades removed", run(dropped, lambda i, c: [(t, d) for (t, d) in c if (i, t) not in flagged_set]))
    bad_series = {i for i in live if (seg_flag[i]["clean jump"] + seg_flag[i]["spike"] + seg_flag[i]["bad range"]) > 0}
    add(f"stocks with any clean jump, spike or bad range removed ({len(bad_series):,} series)", run(dropped | bad_series))
    top_series = list(dict.fromkeys(int(R["sym"][k]) for k in np.argsort(-np.where(taken, usd, -np.inf))[:10]))
    add(f"10 biggest winning trades' stocks removed ({', '.join(names[i] for i in top_series)})", run(dropped | set(top_series)))
    for fl in (2.0, 3.0, 5.0):
        add(f"close of at least ${fl:g} on the entry day", run(dropped, lambda i, c, fl=fl: [(t, d) for (t, d) in c if SEG[i]["c"][t] >= fl]))
    S = pd.DataFrame(rows); S.to_csv(out_dir / "rerun_summary.csv", index=False)
    for wn in WIN:
        for cap in (200, 100):
            v_ = S[(S.period == wn) & (S["cap %"] == cap)]
            print(f"\n==== bad-data reruns | current best rule | cap {cap}% | {wn} ====")
            print(v_[["version", "signals", "trades taken", "win rate %", "average ATR per trade", "SPY move over the same holds (ATR units)", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %"]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
