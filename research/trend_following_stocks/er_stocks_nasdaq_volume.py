"""Stocks, long only: Nasdaq-vs-SPY leading or lagging, volume at the signal, and ways to choose among the day's signals when the account is full (Michael, 18 Nov 2026).
Usage: python er_stocks_nasdaq_volume.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE [nasdaq_etfs.parquet]
Everything else is the current best rule (hand-off doc 17 Nov 2026), exactly as in er_stocks_many_ideas.py: common stocks, one series per company, $3M floor, 20-session ratio 0.50 with rising close, 20-session watch,
buy the next open after a close 1.5 ATR below the best high since the signal, strongest 20% by 126-session return that day, SPY above its 200-day, 4 ATR initial stop, 5 ATR trailing, no time limit, 0.05 ATR a side,
0.10% of $300k per ATR, caps 200% and 100%. Gate rows run with 8 random picks (mean and lowest/highest Sharpe shown). Ranking rows have no random pick (the strongest-ranked signal is taken first), so compare them with the
baseline's lowest-to-highest range. In-sample only (data through 2021-08-06); sealed years are not read. Post hoc: a result counts only if it helps in both 2000-2007 and 2008-2021 and its neighbours look similar.
MODES
  nasdaq  QQQ (Nasdaq-100 ETF) versus SPY. Leading or lagging over 20, 60, 126 sessions by more than 0, 2, 5 points; QQQ/SPY ratio above or below its 50, 100, 200-day average; graded cap (full when leading, half when lagging).
  volume  Volume on the signal day (the first day the 20-session ratio qualifies) divided by the average of the 20 or 50 sessions before it; up-day volume divided by down-day volume over the 20 sessions ending on the signal day
          (shares and dollars). Gates at several minimums, "at most" controls, and the same measures on the trigger day as controls.
  rank    When the account is full, take the strongest first by: 3-month (63-session), 6-month (126), 12-month (252) return rank, average of the three, signal-day volume surge, up/down volume ratio; weakest-first controls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
from er_stocks import END, EPOCH
from er_stocks_combined_er import q_long

PULL = 1.5


def sig_map(g, q):
    """trigger row -> signal row, same logic as er_stocks_combined_er.cands_from_q."""
    c, h, atr = g["c"], g["h"], g["atr"]; n = len(c)
    qprev = np.r_[False, q[:-1]]; out = {}
    for st in np.where(q & ~qprev)[0]:
        peak = h[st]
        for t in range(st + 1, min(st + M.WATCH, n - 2) + 1):
            peak = max(peak, h[t]); a = atr[t]
            if not (a == a and a > 0):
                continue
            if (peak - c[t]) / a >= PULL:
                out[t] = st; break
    return out


def roll_sum(x, w):
    return pd.Series(x).rolling(w, min_periods=w).sum().to_numpy()


def build_features(ctx, E20):
    """FEAT[(segment, trigger row)] = dict of volume measures on the signal day (sig) and on the trigger day (trg). NaN when there is too little history."""
    SEG, dropped = ctx[0], ctx[1]
    FEAT = {}; nchk = 0
    for i, g in enumerate(SEG):
        if i in dropped or not g["cand"]:
            continue
        sm = sig_map(g, q_long(g, *E20[i], 0.50))
        assert set(sm) == {t for t, _ in g["cand"]}, f"signal map differs from candidates in segment {i}"
        c = g["c"].astype(float); v = np.asarray(MI.VOLS[i], float); n = len(c)
        assert len(v) == n
        vs = pd.Series(v); prev = vs.shift(1)
        m20 = prev.rolling(20, min_periods=20).mean().to_numpy(); m50 = prev.rolling(50, min_periods=50).mean().to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            s20 = np.where(m20 > 0, v / m20, np.nan); s50 = np.where(m50 > 0, v / m50, np.nan)
        up = np.r_[False, c[1:] > c[:-1]]; dn = np.r_[False, c[1:] < c[:-1]]
        def udr(w):
            a = roll_sum(np.where(up, w, 0.0), 20); b = roll_sum(np.where(dn, w, 0.0), 20)
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(b > 0, a / b, np.where(a > 0, 100.0, np.nan))
        ud = udr(v); udd = udr(v * c)
        for t, st in sm.items():
            FEAT[(i, t)] = dict(s20_sig=s20[st], s50_sig=s50[st], ud_sig=ud[st], udd_sig=udd[st], s20_trg=s20[t], ud_trg=ud[t], udd_trg=udd[t])
            nchk += 1
    print(f"volume features built for {nchk:,} signals", flush=True)
    return FEAT


def gate(FEAT, key, fn):
    def cond(i, g, t):
        x = FEAT[(i, t)][key]
        return bool(np.isfinite(x) and fn(x))
    return cond


def scen_key(ctx, R, label, key):
    """One run per cap with a fixed priority order (smaller key first) instead of random picks."""
    SEG, dropped, cal, (dates, spy_close, WIN) = ctx
    rows = []
    for cap in (2.0, 1.0):
        P = MI.portfolio_gen(R, cal, cap, key)
        for r in I1.eval_P(R, P, cap, dates, spy_close, WIN, dict(label)):
            r["Sharpe lowest pick"] = r["Sharpe ratio"]; r["Sharpe highest pick"] = r["Sharpe ratio"]; r["signals"] = len(R["d"]); rows.append(r)
    return rows


def qqq_series(path, cal):
    df = pd.read_parquet(path); df = df[df["date_i"] <= (END - EPOCH).days]
    d = df[df.symbol == "QQQ"].sort_values("date_i").drop_duplicates("date_i")
    assert len(d) > 1000, f"QQQ not found in {path} (rows {len(d)})"
    ser = pd.Series(d["close"].to_numpy(float), index=np.searchsorted(cal, d["date_i"].to_numpy()))
    ser = ser[ser.index < len(cal)]; ser = ser[~ser.index.duplicated(keep="last")]
    full = ser.reindex(range(len(cal))).ffill()
    full.iloc[:int(np.searchsorted(cal, d["date_i"].min()))] = np.nan
    print(f"QQQ: {len(d):,} days from {pd.Timestamp(EPOCH) + pd.Timedelta(days=int(d['date_i'].min())):%Y-%m-%d}", flush=True)
    return full.to_numpy(float)


def run_nasdaq(ctx, mk200, spy_close, path, rows):
    SEG, dropped, cal, (dates, _, WIN) = ctx
    base = MI.gen(ctx, mk200)
    rows += MI.scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); MI.line(rows, "baseline")
    Q = qqq_series(path, cal); S = spy_close
    sel = np.asarray((dates >= pd.Timestamp("2000-01-01")) & (dates <= END))
    qs, ss = pd.Series(Q), pd.Series(S)
    def mask_run(name, idea, mask):
        mask = np.asarray(mask, bool)
        R = MI.gen(ctx, mk200 & mask)
        r = MI.scen(ctx, R, {"idea": idea, "scenario": name}, on=(mk200 & mask)); rows.extend(r); MI.line(r, name)
        print(f"     (Nasdaq condition on {mask[sel].mean()*100:.0f}% of sessions; with SPY condition {(mk200 & mask)[sel].mean()*100:.0f}%; {len(R['d']):,} signals)", flush=True)
    for L in (20, 60, 126):
        rel = ((qs / qs.shift(L)) - (ss / ss.shift(L))).to_numpy() * 100.0          # points of return
        for x in (0, 2, 5):
            mask_run(f"Nasdaq leading SPY by more than {x} points over {L} sessions", f"nasdaq {L}-session relative return", rel > x)
        for x in (0, 2, 5):
            mask_run(f"Nasdaq lagging SPY by more than {x} points over {L} sessions", f"nasdaq {L}-session relative return", rel < -x)
    ratio = qs / ss
    for W in (50, 100, 200):
        ma = ratio.rolling(W, min_periods=W).mean()
        mask_run(f"QQQ/SPY ratio above its {W}-day average (Nasdaq trending up versus SPY)", "nasdaq ratio trend", (ratio > ma).to_numpy())
        mask_run(f"QQQ/SPY ratio below its {W}-day average (Nasdaq trending down versus SPY)", "nasdaq ratio trend", (ratio < ma).to_numpy())
    rel60 = ((qs / qs.shift(60)) - (ss / ss.shift(60))).to_numpy() * 100.0
    for nm, lead in (("leading", rel60 > 0), ("lagging", rel60 < 0)):
        R = MI.gen(ctx, mk200)
        r = MI.scen(ctx, R, {"idea": "nasdaq graded cap", "scenario": f"cap full when Nasdaq is {nm} SPY over 60 sessions, half otherwise"}, cap_t_fn=lambda cap, lead=lead: np.where(lead, cap, cap * 0.5))
        rows.extend(r); MI.line(r, f"graded cap, full when {nm}")


def run_volume(ctx, mk200, E20, rows):
    FEAT = build_features(ctx, E20)
    base = MI.gen(ctx, mk200)
    rows += MI.scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); MI.line(rows, "baseline")
    def go(name, idea, key, fn):
        R = MI.gen(ctx, mk200, cond=gate(FEAT, key, fn))
        r = MI.scen(ctx, R, {"idea": idea, "scenario": name}); rows.extend(r); MI.line(r, name)
    for key, nm in (("s20_sig", "20"), ("s50_sig", "50")):
        for x in (1.0, 1.25, 1.5, 2.0):
            go(f"signal-day volume at least {x:g} times its {nm}-session average", "volume surge on the signal day", key, lambda v, x=x: v >= x)
    go("signal-day volume at most 1.0 times its 20-session average (control: quiet signal)", "volume surge on the signal day", "s20_sig", lambda v: v <= 1.0)
    go("signal-day volume at most 0.7 times its 20-session average (control: very quiet signal)", "volume surge on the signal day", "s20_sig", lambda v: v <= 0.7)
    for x in (1.0, 1.5):
        go(f"trigger-day volume at least {x:g} times its 20-session average (control: surge on the pullback day instead)", "volume surge on the trigger day", "s20_trg", lambda v, x=x: v >= x)
    for key, nm in (("ud_sig", "shares"), ("udd_sig", "dollars")):
        for x in (1.0, 1.25, 1.5, 2.0):
            go(f"up-day volume at least {x:g} times down-day volume over the 20 sessions ending on the signal day ({nm})", "up/down volume ratio on the run", key, lambda v, x=x: v >= x)
    go("up/down volume at most 1.0 over the run (control: more selling volume, shares)", "up/down volume ratio on the run", "ud_sig", lambda v: v <= 1.0)
    go("up/down volume at most 0.8 over the run (control, shares)", "up/down volume ratio on the run", "ud_sig", lambda v: v <= 0.8)
    for x in (1.25, 1.5):
        go(f"up-day volume at least {x:g} times down-day volume over the 20 sessions ending on the trigger day (control, shares)", "up/down volume ratio at the trigger", "ud_trg", lambda v, x=x: v >= x)
    # both together
    R = MI.gen(ctx, mk200, cond=lambda i, g, t: bool(np.isfinite(FEAT[(i, t)]["s20_sig"]) and np.isfinite(FEAT[(i, t)]["ud_sig"]) and FEAT[(i, t)]["s20_sig"] >= 1.25 and FEAT[(i, t)]["ud_sig"] >= 1.25))
    r = MI.scen(ctx, R, {"idea": "volume surge and up/down together", "scenario": "signal-day surge at least 1.25 (20-session) AND up/down volume at least 1.25"}); rows.extend(r); MI.line(r, "surge and up/down together")


def run_rank(ctx, mk200, E20, rows):
    SEG, dropped, cal, _ = ctx
    FEAT = build_features(ctx, E20)
    base = MI.gen(ctx, mk200)
    rows += MI.scen(ctx, base, {"idea": "baseline", "scenario": "random pick among the day's signals (current rule)"}); MI.line(rows, "baseline (random pick)")
    n = len(base["d"]); sym, t = I1.trade_rows(SEG, base)
    ranks = {"3-month (63-session) return": MI.make_rank(ctx, MI.ret_score(63)),
             "6-month (126-session) return": {i: SEG[i]["rank"] for i in range(len(SEG)) if i not in dropped},
             "12-month (252-session) return": MI.make_rank(ctx, MI.ret_score(252))}
    ranks["average of the 3, 6 and 12-month ranks"] = {i: (ranks["3-month (63-session) return"][i] + ranks["6-month (126-session) return"][i] + ranks["12-month (252-session) return"][i]) / 3.0 for i in ranks["3-month (63-session) return"]}
    score = {}
    for nm, rk in ranks.items():
        score[nm] = np.array([rk[sym[k]][t[k]] for k in range(n)], float)
    score["signal-day volume surge (20-session)"] = np.array([FEAT[(sym[k], t[k])]["s20_sig"] for k in range(n)], float)
    score["up-day / down-day volume ratio over the run (shares)"] = np.array([FEAT[(sym[k], t[k])]["ud_sig"] for k in range(n)], float)
    tiny = np.random.default_rng(20261118).random(n) * 1e-9
    for nm, sc in score.items():
        print(f"  {nm}: score available for {np.isfinite(sc).mean()*100:.1f}% of {n:,} signals", flush=True)
        for direction, tag in ((1, "strongest first"), (-1, "weakest first (control)")):
            key = -np.where(np.isfinite(sc), direction * sc, -1e9) + tiny        # smaller key is taken first; signals without a score go last
            r = scen_key(ctx, base, {"idea": "ranking when the account is full", "scenario": f"{nm}, {tag}"}, key); rows.extend(r); MI.line(r, f"{nm}, {tag}")
    # rank only matters on full days: how often is the account full and how many signals compete?
    key = np.random.default_rng(MI.SEED).random(n)
    P = MI.portfolio_gen(base, cal, 2.0, key)
    print(f"reference pick: {P['taken'].sum():,} of {n:,} signals taken ({P['taken'].mean()*100:.0f}%)", flush=True)


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 120)
    MI.check_baseline(ctx, mk200)
    rows = []
    if mode == "nasdaq":
        run_nasdaq(ctx, mk200, spy_close, sys.argv[5], rows)
    elif mode == "volume":
        run_volume(ctx, mk200, E20, rows)
    elif mode == "rank":
        run_rank(ctx, mk200, E20, rows)
    else:
        raise SystemExit(f"unknown mode {mode}")
    S = pd.DataFrame(rows)
    S.to_csv(out_dir / f"nasdaq_volume_{mode}.csv", index=False)
    cols = ["idea", "scenario", "profit per year %", "Sharpe ratio", "Sharpe lowest pick", "Sharpe highest pick", "max drawdown %", "worst year %", "trades taken", "average open positions", "% of sessions at the cap"]
    for wn in ctx[3][2]:
        for cap in (200, 100):
            print(f"\n==== {mode} | {wn} | cap {cap}% | gate rows: mean of {MI.KSEEDS} random picks; ranking rows: one run ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
