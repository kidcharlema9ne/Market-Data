"""Stocks, long only: under-$5 bad-data check (hand-off doc 17 Nov 2026, next action 2).
Usage: python er_stocks_under5_check.py stock_prices.parquet OUT_DIR spy_prices.parquet [CONFIRMED_BAD.csv]
Stocks under $5 were 5% of trades but about 20% of profit and have not been checked for bad data. This script, on the current best rule (20-day ratio 0.50, 1.5 ATR pullback, strongest 20% by 126-session return,
SPY above its 200-day for new entries, 4 ATR stop, 5 ATR trail, no time limit, 0.05 ATR a side, 0.10% of $300k per ATR, caps 200% and 100%):
  1. Splits trades taken (cap 200%) by entry price bucket: number, share of trades, profit, share of profit, average ATR per trade.
  2. Lists the biggest winners (under $5, and overall) with data checks over each trade's holding period: largest one-day close jump up and down and its date; a one-day move that is within 4% of a clean split factor
     (2, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100, or the inverse); a spike that reverses within a day (a one-day move of 40% or more, then at least 70% of it undone); zero-volume days and days under 100 shares; missing sessions inside the hold;
     the share of the trade's profit that came from its single best day.
  3. Reruns the account with trades removed BEFORE the account fills (so other signals can take their place): all flagged trades (any price); the 10 biggest winners overall; the 10 biggest winners under $5; price floors
     of $1, $2, $3, $5, $10 on the trigger-day close; $5 floor plus flagged trades removed; and, if CONFIRMED_BAD.csv (columns: stock, entry_date) is given, the web-confirmed bad trades removed.
Flags are leads for a web check, not proof of bad data. Post hoc on development years; data through 2021-08-06 only; sealed years not read.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
from er_stocks import END, EPOCH, MAIN_START
from er_stocks_er_grid import er_dr, long_cands
from er_stocks_null_baseline import spy_setup, evaluate, VNAME, PULL, REF_THR, TOP
from er_stocks_combined_er import q_long, cands_from_q

FACTORS = (2, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100)
BUCKETS = ((0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 50), (50, 1e9))
VOLS = []
_orig_analyze = M.analyze


def _analyze_keep_volume(s, o, h, l, c, v):
    out = _orig_analyze(s, o, h, l, c, v)
    if out[1].any():  # same rule build() uses to keep a segment, so VOLS lines up with SEG
        VOLS.append(v)
    return out


def clean_factor(f):
    return f >= 1.8 and any(abs(f / k - 1.0) < 0.04 for k in FACTORS)


def diagnose(g, v, e_row, x_row, incr, profit_atr_total):
    c, s = g["c"], g["s"]
    j0 = max(e_row, 1)
    r = c[j0:x_row + 1] / c[j0 - 1:x_row]
    up, dn = (r.max(), r.min()) if len(r) else (np.nan, np.nan)
    dup = (j0 + int(np.argmax(r))) if len(r) else 0
    ddn = (j0 + int(np.argmin(r))) if len(r) else 0
    fac = np.maximum(r, 1.0 / r)
    factor_hit = bool(any(clean_factor(f) for f in fac))
    lr = np.log(r)
    spike = False
    for q in range(len(lr) - 1):
        if abs(lr[q]) >= np.log(1.4) and lr[q] * lr[q + 1] < 0 and abs(lr[q + 1]) >= 0.7 * abs(lr[q]):
            spike = True
            break
    vv = v[e_row:x_row + 1]
    gaps = int((np.diff(s[e_row:x_row + 1]) > 1).sum()) if x_row > e_row else 0
    best_day = float(np.max(incr)) if len(incr) else np.nan
    tot = float(np.sum(incr)) if len(incr) else np.nan
    return dict(biggest_up_ratio=up, biggest_up_row=dup, biggest_down_ratio=dn, biggest_down_row=ddn, clean_factor_jump=factor_hit, spike_and_reversal=spike,
                zero_volume_days=int((vv == 0).sum()), days_under_100_shares=int((vv < 100).sum()), missing_session_gaps=gaps,
                best_day_share_of_trade_gain_pct=(best_day / tot * 100.0) if (np.isfinite(tot) and tot > 0) else np.nan)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    confirmed = pd.read_csv(sys.argv[4]) if len(sys.argv) > 4 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    B.selftest(); M.selftest_common()
    M.VERSIONS.clear(); M.VERSIONS[VNAME] = (4.0, 5.0, None)
    M.analyze = _analyze_keep_volume
    SEG, names, dropped, cal = M.build(prices_path)
    assert len(VOLS) == len(SEG), (len(VOLS), len(SEG))
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
        g["cand"] = cands_from_q(g, q_long(g, *E20[i], REF_THR), PULL)
    BASE = {i: list(SEG[i]["cand"]) for i in live}
    dates = pd.DatetimeIndex(EPOCH + pd.to_timedelta(cal, unit="D"))
    spy_close, mk = spy_setup(spy_path, cal)
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 500)

    def run():
        return M.trades_for(SEG, dropped, cal, TOP, VNAME, market_ok=mk, long_only=True)

    R = run(); n = len(R["d"])
    key = np.random.default_rng(20261117).random(n)
    P = B.portfolio(R, cal, (1,), M.SIZE, 2.0, key)
    tk = P["taken"]; usd = P["trade_usd"]; tot = usd[tk].sum()
    r0 = evaluate(R, cal, dates, spy_close, WIN, {"scenario": "baseline"})
    w0 = [r for r in r0 if r["cap %"] == 200 and r["period"].startswith("whole")][0]
    print(f"baseline: {n:,} signals, {int(tk.sum()):,} trades taken; whole period cap 200%: {w0['profit per year %']:+.1f}% / Sharpe {w0['Sharpe ratio']:.2f} / {w0['max drawdown %']:.0f}% (documented +22.9% / 0.64 / -22%)", flush=True)
    if abs(w0["Sharpe ratio"] - 0.64) > 0.015:
        print("!!!! MISMATCH WITH THE DOCUMENTED REFERENCE: do not trust this run until explained !!!!", flush=True)

    # 1. price buckets (trades taken, cap 200%, whole period)
    rows = []
    for lo, hi in BUCKETS:
        m = tk & (R["px_e"] >= lo) & (R["px_e"] < hi)
        rows.append({"entry price": f"${lo:g} to ${hi:g}" if hi < 1e8 else f"${lo:g} and up", "trades": int(m.sum()), "share of trades %": m.sum() / tk.sum() * 100, "profit $": usd[m].sum(), "share of profit %": usd[m].sum() / tot * 100,
                     "average ATR per trade": R["res"][m].mean() if m.any() else np.nan, "win rate %": (R["res"][m] > 0).mean() * 100 if m.any() else np.nan})
    PB = pd.DataFrame(rows); PB.to_csv(out_dir / "price_buckets.csv", index=False)
    print("\n==== profit by entry price (trades taken, cap 200%, whole period) ===="); print(PB.round(2).to_string(index=False))

    # 2. diagnostics for every signal in R
    f_start = np.r_[0, np.flatnonzero(np.diff(R["f_tid"])) + 1] if len(R["f_tid"]) else np.array([], int)
    inc_by = {}
    if len(R["f_tid"]):
        for a, b in zip(f_start, np.r_[f_start[1:], len(R["f_tid"])]):
            inc_by[int(R["f_tid"][a])] = R["f_incr"][a:b]
    D = []
    for k in range(n):
        i = int(R["sym"][k]); g = SEG[i]
        e_row = int(np.searchsorted(g["s"], R["sess_e"][k])); x_row = int(np.searchsorted(g["s"], R["sess_x"][k]))
        d = diagnose(g, VOLS[i], e_row, x_row, inc_by.get(k, np.array([])), None)
        d.update(k=k, seg=i, stock=names[i], entry_date=dates[R["sess_e"][k]].date(), exit_date=dates[R["sess_x"][k]].date(), entry_price=R["px_e"][k], exit_price=R["px_x"][k],
                 result_ATR=R["res"][k], sessions_held=R["held"][k], taken=bool(tk[k]), profit_usd=usd[k], sess_e=int(R["sess_e"][k]))
        d["biggest_up_date"] = dates[g["s"][d.pop("biggest_up_row")]].date() if e_row < len(g["s"]) else None
        d["biggest_down_date"] = dates[g["s"][d.pop("biggest_down_row")]].date() if e_row < len(g["s"]) else None
        D.append(d)
    D = pd.DataFrame(D)
    D["flagged"] = D.clean_factor_jump | D.spike_and_reversal | (D.zero_volume_days > 0) | (D.missing_session_gaps > 0)
    D.to_csv(out_dir / "all_signals_diagnostics.csv", index=False)
    T = D[D.taken]
    print(f"\nflags among trades taken: clean split-like jump {int(T.clean_factor_jump.sum())}, spike and reversal {int(T.spike_and_reversal.sum())}, zero-volume days {int((T.zero_volume_days > 0).sum())}, "
          f"missing-session gaps {int((T.missing_session_gaps > 0).sum())}; any flag {int(T.flagged.sum())} of {len(T):,} (under $5: {int(T[T.entry_price < 5].flagged.sum())} of {int((T.entry_price < 5).sum())})", flush=True)
    show = ["stock", "entry_date", "exit_date", "entry_price", "exit_price", "result_ATR", "sessions_held", "profit_usd", "biggest_up_ratio", "biggest_up_date", "biggest_down_ratio", "clean_factor_jump", "spike_and_reversal",
            "zero_volume_days", "days_under_100_shares", "missing_session_gaps", "best_day_share_of_trade_gain_pct"]
    W5 = T[T.entry_price < 5].nlargest(40, "profit_usd")[show]; W5.to_csv(out_dir / "biggest_winners_under5.csv", index=False)
    WA = T.nlargest(40, "profit_usd")[show]; WA.to_csv(out_dir / "biggest_winners_all.csv", index=False)
    FL = D[D.flagged].sort_values("profit_usd", ascending=False)[show + ["taken"]]; FL.to_csv(out_dir / "flagged_trades.csv", index=False)
    print("\n==== 40 biggest winners under $5 (cap 200%, taken) ===="); print(W5.round(2).to_string(index=False))
    print("\n==== 40 biggest winners overall (cap 200%, taken) ===="); print(WA.round(2).to_string(index=False))
    print(f"\n==== flagged trades, biggest profit first (top 60 of {len(FL):,}) ===="); print(FL.head(60).round(2).to_string(index=False))

    # 3. reruns with trades removed before the account fills
    def drop_set(df):
        out = {}
        for sg, se in zip(df.seg, df.sess_e):
            out.setdefault(int(sg), set()).add(int(se))
        return out

    def scenario(name, excl=None, floor=None):
        for i in live:
            g = SEG[i]; ex = (excl or {}).get(i, ())
            g["cand"] = [(t, d) for (t, d) in BASE[i] if not (floor is not None and g["c"][t] < floor) and not (ex and t + 1 < len(g["s"]) and int(g["s"][t + 1]) in ex)]
        R2 = run()
        print(f"scenario {name}: {len(R2['d']):,} signals", flush=True)
        return evaluate(R2, cal, dates, spy_close, WIN, {"scenario": name})

    out = list(r0)
    top10 = T.nlargest(10, "profit_usd"); top10_5 = T[T.entry_price < 5].nlargest(10, "profit_usd")
    out += scenario("remove all flagged trades (any price)", excl=drop_set(D[D.flagged]))
    out += scenario("remove the 10 biggest winners overall", excl=drop_set(top10))
    out += scenario("remove the 10 biggest winners under $5", excl=drop_set(top10_5))
    for fl in (1, 2, 3, 5, 10):
        out += scenario(f"price floor ${fl} (trigger-day close)", floor=float(fl))
    out += scenario("price floor $5 and remove flagged trades", excl=drop_set(D[D.flagged]), floor=5.0)
    if confirmed is not None and len(confirmed):
        ex = {}
        key_ = {(str(a), pd.Timestamp(b).date()) for a, b in zip(confirmed["stock"], confirmed["entry_date"])}
        bad = D[[(a, b) in key_ for a, b in zip(D.stock, D.entry_date)]]
        print(f"confirmed bad trades matched: {len(bad)} of {len(confirmed)}", flush=True)
        out += scenario("remove web-confirmed bad-data trades", excl=drop_set(bad))
    S = pd.DataFrame(out); S.to_csv(out_dir / "rerun_summary.csv", index=False)
    cols = ["scenario", "trades taken", "win rate %", "average ATR per trade", "profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "years positive"]
    for wn in WIN:
        for cap in (200, 100):
            print(f"\n==== reruns | {wn} | cap {cap}% | {VNAME} ====")
            print(S[(S.period == wn) & (S["cap %"] == cap)][cols].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
