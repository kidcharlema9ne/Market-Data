"""Stocks, long only: sell HALF of a position when the stock gets far above its 50-day average (Michael, 18 Nov 2026: "test taking 50% of profit at various multiples of the ATR being over the 50-day moving average ... which I assume would open up more space for other stocks").
Usage: python er_stocks_partial_profit.py stock_prices.parquet OUT_DIR spy_prices.parquet

Everything is the current baseline (volume-surge ranking when the account is full, 4 ATR initial and 5 ATR trailing stops, 0.05 ATR a side, 0.10% of a fixed $300,000 per ATR, strongest 20% by 126-session return, SPY above its 200-day,
$3M floor, 1.5 ATR pullback entry, cap 200% and 100%) except for one added exit action on the position:
  extension = (close - 50-day average of closes) / 20-day average true range (the same ATR the stops use).
  The first session AFTER ENTRY whose close has an extension of N or more triggers the trim: half of the shares (rounded down, so a one-share position is not trimmed) are sold at the NEXT session's open, at the usual 0.05 ATR cost.
  The other half keeps the 4 ATR initial / 5 ATR trailing stop exactly as before and exits at the usual exit. One trim per position. A trim needs at least one more session before the exit session (a trade that exits the day after the trigger is left alone).
  Two versions: (a) any time the extension reaches N; (b) only when the extension reaches N AND the close is above the entry price (a real profit).
  N = 2, 3, 4, 5, 7 and 10 ATRs.
Account rules: the cap counts position value at entry cost, so a trimmed position's value at entry cost drops by half from the session after the trim; the freed room is available to new entries from the session after the trim.
Each variant is run with volume-surge ranking and with the mean of 8 random picks (like the earlier tests), at cap 200% and 100%, three windows, and (cap 200% only) also with a 4% a year charge on borrowed money (the account is a fixed $300,000, so borrowed = position value above $300,000).
Diagnostics: how often each extension is reached, what the sold halves would have done if held, and which trades the freed room added or removed. Start-year tables for the baseline and N = 4, 5, 10.
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

THRESHOLDS = [2, 3, 4, 5, 7, 10]
DIST_LEVELS = [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15]
START_YEAR_N = [4, 5, 10]
KSEEDS = MI.KSEEDS
BORROW_RATE = 0.04


# ---------------------------------------------------------------- per-trade price paths and trim points
def trade_paths(ctx, R):
    """For every baseline trade: entry row, exit row, and the extension and close on each session from entry to the session before the last possible trigger (exit row minus 2)."""
    SEG = ctx[0]
    n = len(R["d"]); e_row = np.empty(n, np.int64); x_row = np.empty(n, np.int64)
    ext_cache = {}
    paths = []
    for k in range(n):
        i = int(R["sym"][k]); g = SEG[i]
        e = int(np.searchsorted(g["s"], R["sess_e"][k])); x = int(np.searchsorted(g["s"], R["sess_x"][k]))
        assert g["s"][e] == R["sess_e"][k] and g["s"][x] == R["sess_x"][k]
        e_row[k] = e; x_row[k] = x
        if i not in ext_cache:
            c = g["c"].astype(float)
            ma = pd.Series(c).rolling(50, min_periods=50).mean().to_numpy()
            with np.errstate(divide="ignore", invalid="ignore"):
                ext_cache[i] = (c - ma) / g["atr"]
        ext = ext_cache[i]
        paths.append((ext[e:x - 1], g["c"][e:x - 1]))      # rows e .. x-2: a trigger on row j sells at the open of row j+1 <= x-1
    return e_row, x_row, paths


def trim_points(ctx, R, e_row, x_row, paths, N, need_profit):
    """First trigger row per trade for extension >= N (and close above entry if need_profit). Returns arrays aligned with R (session of the trim, index into the trade's daily rows, trim price, close-to-trim-open move, extension at the trigger)."""
    SEG = ctx[0]
    n = len(R["d"])
    sess = np.full(n, -1, np.int64); kk = np.zeros(n, np.int64); px = np.full(n, np.nan); gap = np.zeros(n); extv = np.full(n, np.nan)
    for k in range(n):
        ext, cl = paths[k]
        if len(ext) == 0:
            continue
        ok = np.isfinite(ext) & (ext >= N)
        if need_profit:
            ok &= cl > R["px_e"][k]
        w = np.flatnonzero(ok)
        if len(w) == 0:
            continue
        j = int(e_row[k]) + int(w[0]); r = j + 1
        g = SEG[int(R["sym"][k])]
        sess[k] = int(g["s"][r]); kk[k] = r - int(e_row[k]); px[k] = g["o"][r]; gap[k] = g["o"][r] - g["c"][j]; extv[k] = ext[w[0]]
    return dict(sess=sess, k=kk, px=px, gap=gap, ext=extv)


# ---------------------------------------------------------------- account simulation with a trim
def portfolio_trim(R, cal, cap, key, T=None):
    n = len(R["d"]); m = len(cal); tgt = CAPITAL * M.SIZE / 100.0
    base_sh = np.floor(tgt / R["a0"]); idx = np.where(base_sh >= 1)[0]
    order = idx[np.lexsort((key[idx], R["sess_e"][idx]))]
    cnt = np.bincount(R["f_tid"], minlength=n); off = np.r_[0, np.cumsum(cnt)]
    pnl = np.zeros(m); taken = np.zeros(n, bool); sold = np.zeros(n); heap = []; gross = 0.0
    for i in order:
        s = R["sess_e"][i]
        while heap and heap[0][0] < s:
            gross -= heapq.heappop(heap)[1]
        sh = base_sh[i]
        ss = float(np.floor(sh / 2)) if (T is not None and T["sess"][i] >= 0) else 0.0
        notional = sh * R["px_e"][i]
        if gross + notional > cap * CAPITAL:
            continue
        taken[i] = True; sold[i] = ss; gross += notional
        heapq.heappush(heap, (R["sess_x"][i], (sh - ss) * R["px_e"][i]))
        if ss > 0:
            heapq.heappush(heap, (T["sess"][i], ss * R["px_e"][i]))
        a, b = off[i], off[i + 1]
        pnl[R["f_sess"][a:b]] += R["f_incr"][a:b] * sh
        c_ps = 0.5 * B.COST_RT * R["a0"][i]
        pnl[s] -= c_ps * sh
        if ss > 0:
            kt = T["k"][i]
            pnl[R["f_sess"][a + kt:b]] -= R["f_incr"][a + kt:b] * ss        # the sold shares stop earning from the trim session on ...
            pnl[T["sess"][i]] += T["gap"][i] * ss - c_ps * ss               # ... except the move from the previous close to the trim open, minus the trim cost
            pnl[R["sess_x"][i]] -= c_ps * (sh - ss)
        else:
            pnl[R["sess_x"][i]] -= c_ps * sh
    dn = np.zeros(m + 1); dv = np.zeros(m + 1)
    tk = np.flatnonzero(taken)
    notional = base_sh * R["px_e"]
    np.add.at(dn, R["sess_e"][tk], 1.0); np.add.at(dn, R["sess_x"][tk] + 1, -1.0)
    np.add.at(dv, R["sess_e"][tk], notional[tk])
    np.add.at(dv, R["sess_x"][tk] + 1, -((base_sh - sold) * R["px_e"])[tk])
    tr = tk[sold[tk] > 0]
    np.add.at(dv, T["sess"][tr] + 1, -(sold * R["px_e"])[tr]) if len(tr) else None
    return dict(pnl=pnl, taken=taken, shares=base_sh * taken, sold=sold, open_n=np.cumsum(dn)[:m], gross=np.cumsum(dv)[:m])


def effective_res(R, T):
    """Per-trade result in ATR per share with the trim applied (net of the usual 0.10 ATR round-trip cost)."""
    base_sh = np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"])
    if T is None:
        return R["res"].copy(), np.zeros(len(R["d"]))
    ss = np.where(T["sess"] >= 0, np.floor(base_sh / 2), 0.0)
    frac = np.divide(ss, base_sh, out=np.zeros(len(ss)), where=base_sh > 0)
    price_part = frac * (np.nan_to_num(T["px"]) - R["px_e"]) / R["a0"] + (1 - frac) * (R["px_x"] - R["px_e"]) / R["a0"]
    return price_part - B.COST_RT, ss


def with_res(R, res):
    R2 = dict(R); R2["res"] = res
    return R2


# ---------------------------------------------------------------- scenarios
def charge(P):
    return MI.add_interest(P, 0.0, BORROW_RATE)


def extra_stats(P, dates, lo, hi, cap):
    st, _ = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
    return st


def eval_rows(R2, P, cap, dates, spy_close, WIN, label):
    rows = I1.eval_P(R2, P, cap, dates, spy_close, WIN, dict(label))
    for r in rows:
        lo, hi = WIN[r["period"]]
        st = extra_stats(P, dates, lo, hi, cap)
        r["average position value % of account"] = st.get("average position value % of account", np.nan)
        r["positions trimmed"] = int((P["sold"][P["taken"]] > 0).sum()) if "sold" in P else 0
    return rows


def run_variant(R, R2, T, cal, dates, spy_close, WIN, label, key_vs, kseeds=KSEEDS):
    """Rows for cap 200% and 100%: volume-surge ranking (one run) and the mean of K random picks; at cap 200% also the 4% borrowing-charge version."""
    out = []
    Ps = {}
    for cap in (2.0, 1.0):
        P = portfolio_trim(R, cal, cap, key_vs, T); Ps[cap] = P
        for charged in ((False, True) if cap == 2.0 else (False,)):
            Q = charge(P) if charged else P
            Q["sold"] = P["sold"]; Q["taken"] = P["taken"]
            lab = dict(label); lab.update({"ranking": "volume surge", "borrowing charge": "4% a year" if charged else "none"})
            for r in eval_rows(R2, Q, cap, dates, spy_close, WIN, lab):
                r["Sharpe lowest pick"] = np.nan; r["Sharpe highest pick"] = np.nan; out.append(r)
        allr = []
        for s in range(kseeds):
            key = np.random.default_rng(1000 + s).random(len(R["d"]))
            P = portfolio_trim(R, cal, cap, key, T)
            for charged in ((False, True) if cap == 2.0 else (False,)):
                Q = charge(P) if charged else P
                Q["sold"] = P["sold"]; Q["taken"] = P["taken"]
                lab = dict(label); lab.update({"ranking": "random pick (mean of 8)", "borrowing charge": "4% a year" if charged else "none"})
                for r in eval_rows(R2, Q, cap, dates, spy_close, WIN, lab):
                    r["seed"] = s; allr.append(r)
        D = pd.DataFrame(allr)
        for (per, chg), v in D.groupby(["period", "borrowing charge"]):
            r = dict(label); r.update({"ranking": "random pick (mean of 8)", "borrowing charge": chg, "cap %": int(cap * 100), "period": per, "Sharpe lowest pick": v["Sharpe ratio"].min(), "Sharpe highest pick": v["Sharpe ratio"].max(), "signals": len(R["d"])})
            for c in MI.NUM + ["average position value % of account", "positions trimmed"]:
                r[c] = v[c].mean()
            out.append(r)
    return out, Ps


def diagnostics(R, R2, T, P, P0, res0):
    """What the trim did, volume-surge ranking, cap 200%: the sold halves vs holding, and the trades the freed room added or removed."""
    base_sh = np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"])
    usd = base_sh * R2["res"] * R["a0"]; usd0 = base_sh * res0 * R["a0"]
    tk, tk0 = P["taken"], P0["taken"]
    both = tk & tk0; only_new = tk & ~tk0; only_old = tk0 & ~tk
    tr = tk & (P["sold"] > 0)
    hold_minus_sell = (R["px_x"][tr] - T["px"][tr]) / R["a0"][tr]
    given_up = float((P["sold"][tr] * (R["px_x"][tr] - T["px"][tr])).sum())
    d = {"trades taken": int(tk.sum()), "baseline trades taken": int(tk0.sum()), "positions trimmed": int(tr.sum()), "share of taken trades trimmed %": 100.0 * tr.sum() / max(tk.sum(), 1),
         "average extension at the trigger (ATR)": float(np.nanmean(T["ext"][tr])) if tr.any() else np.nan,
         "sold half: average ATR per share gained by holding it to the normal exit instead (negative = selling was better)": float(hold_minus_sell.mean()) if tr.any() else np.nan,
         "sold half: share of trims where the normal exit was lower than the trim price %": float((hold_minus_sell < 0).mean() * 100) if tr.any() else np.nan,
         "dollars the sold halves would have added if held to the normal exit": given_up,
         "trades taken only with the trim (freed room): count": int(only_new.sum()), "trades taken only with the trim: net dollars": float(usd[only_new].sum()),
         "trades taken only without the trim (crowded out): count": int(only_old.sum()), "trades taken only without the trim: net dollars (baseline)": float(usd0[only_old].sum()),
         "trades taken in both: net dollars with the trim": float(usd[both].sum()), "trades taken in both: net dollars baseline": float(usd0[both].sum()),
         "total net dollars with the trim": float(usd[tk].sum()), "total net dollars baseline": float(usd0[tk0].sum())}
    return d


# ---------------------------------------------------------------- checks
def selftest_trim(ctx, R, T_by, cal, e_row, x_row):
    """Rebuild a handful of trimmed trades day by day, outside the account code, and compare the daily profit rows."""
    SEG = ctx[0]; N, prof = 3, False
    T = T_by[(N, prof)]
    cand = np.flatnonzero(T["sess"] >= 0)[:5000]
    rng = np.random.default_rng(7); pick = rng.choice(cand, size=min(60, len(cand)), replace=False)
    m = len(cal); nchk = 0
    for k in pick:
        sh = float(np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"][k]))
        if sh < 2:
            continue
        ss = float(np.floor(sh / 2))
        g = SEG[int(R["sym"][k])]; e, x = int(e_row[k]), int(x_row[k]); a0 = R["a0"][k]; c_ps = 0.5 * B.COST_RT * a0
        r = int(np.searchsorted(g["s"], T["sess"][k]))
        want = np.zeros(m)
        entry = g["o"][e]
        assert entry == R["px_e"][k]
        prev = entry
        for row in range(e, x + 1):
            px_now = g["c"][row] if row < x else R["px_x"][k]
            if row < r:
                want[g["s"][row]] += sh * (px_now - prev)
            elif row == r:
                want[g["s"][row]] += ss * (g["o"][r] - prev) + (sh - ss) * (px_now - prev)
            else:
                want[g["s"][row]] += (sh - ss) * (px_now - prev)
            prev = px_now
        want[g["s"][e]] -= c_ps * sh; want[g["s"][r]] -= c_ps * ss; want[g["s"][x]] -= c_ps * (sh - ss)
        mask = np.zeros(len(R["d"]), bool); mask[k] = True
        Rs = SY.subset(R, mask); Ts = {kk: vv[mask] for kk, vv in T.items()}
        P = portfolio_trim(Rs, cal, 1e9, np.zeros(1), Ts)
        assert np.allclose(P["pnl"], want, atol=1e-6), ("daily profit rows differ", k)
        nchk += 1
    print(f"trim accounting matches a day-by-day rebuild on {nchk} trimmed trades", flush=True)


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 700); pd.set_option("display.max_colwidth", 80)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    R = MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    key_vs = SB.vs_key(R, FEAT, SEG)
    # the new account code with no trim must equal the standard one exactly
    for cap in (2.0, 1.0):
        Pa = portfolio_trim(R, cal, cap, key_vs, None); Pb = MI.portfolio_gen(R, cal, cap, key_vs)
        assert np.allclose(Pa["pnl"], Pb["pnl"]) and (Pa["taken"] == Pb["taken"]).all() and np.allclose(Pa["gross"], Pb["gross"]), "account code with no trim differs from the standard one"
    print("account code with no trim reproduces the standard one exactly (volume-surge ranking, cap 200% and 100%)", flush=True)

    e_row, x_row, paths = trade_paths(ctx, R)
    # how often each extension is reached after entry (any time before the last possible trigger)
    mx = np.array([np.nanmax(p[0]) if len(p[0]) and np.isfinite(p[0]).any() else np.nan for p in paths])
    mx_prof = np.array([np.nanmax(np.where(p[1] > R["px_e"][k], p[0], np.nan)) if len(p[0]) and (np.isfinite(np.where(p[1] > R["px_e"][k], p[0], np.nan))).any() else np.nan for k, p in enumerate(paths)])
    dist = pd.DataFrame({"extension reached (ATR above the 50-day average)": DIST_LEVELS,
                         "share of all signals' trades that reach it %": [float(np.nanmean(np.where(np.isfinite(mx), mx >= L, np.nan)) * 100) for L in DIST_LEVELS],
                         "same, counting only closes above the entry price %": [float(np.nanmean(np.where(np.isfinite(mx_prof), mx_prof >= L, np.nan)) * 100) for L in DIST_LEVELS],
                         "trades": len(R["d"])})
    dist.round(2).to_csv(out_dir / "extension_reach.csv", index=False)
    print("\n==== how often a trade's stock gets this far above its 50-day average after entry (all trades the rule generates, before account limits) ====")
    print(dist.round(1).to_string(index=False))

    T_by = {}
    for N in THRESHOLDS:
        for prof in (False, True):
            T_by[(N, prof)] = trim_points(ctx, R, e_row, x_row, paths, N, prof)
            print(f"  trigger at {N} ATR{' with a profit' if prof else ''}: {int((T_by[(N, prof)]['sess'] >= 0).sum()):,} of {len(R['d']):,} trades have a trim point", flush=True)
    selftest_trim(ctx, R, T_by, cal, e_row, x_row)

    variants = [("no profit taking (current rule)", None, None, False)]
    for prof in (False, True):
        for N in THRESHOLDS:
            variants.append((f"sell half at {N} ATR above the 50-day" + (", only when above entry price" if prof else ""), N, prof, prof))
    rows, diag_rows, Pbase = [], [], None
    res0 = R["res"].copy()
    for nm, N, prof, _ in variants:
        T = None if N is None else T_by[(N, prof)]
        res_eff, ss = effective_res(R, T)
        R2 = with_res(R, res_eff)
        lab = {"version": nm}
        out, Ps = run_variant(R, R2, T, cal, dates, spy_close, WIN, lab, key_vs)
        rows += out
        if N is None:
            Pbase = Ps[2.0]
        else:
            P = Ps[2.0]
            tot = float((np.floor(CAPITAL * M.SIZE / 100.0 / R["a0"]) * res_eff * R["a0"])[P["taken"]].sum())
            assert abs(tot - P["pnl"].sum()) < 1e-6 * max(1.0, abs(tot)) + 1e-3, ("trade dollars differ from the daily account", tot, P["pnl"].sum())
            d = diagnostics(R, R2, T, P, Pbase, res0); d["version"] = nm; diag_rows.append(d)
        w = [r for r in out if r["ranking"] == "volume surge" and r["period"].startswith("whole") and r["cap %"] == 200 and r["borrowing charge"] == "none"][-1]
        print(f"  {nm}: volume surge, cap 200%, whole period: +{w['profit per year %']:.1f}% / Sharpe {w['Sharpe ratio']:.2f} / {w['max drawdown %']:.1f}% / worst year {w['worst year %']:.1f}% / trimmed {w['positions trimmed']:.0f}", flush=True)
    S = pd.DataFrame(rows)
    S["profit per year / drawdown"] = S["profit per year %"] / S["max drawdown %"].abs()
    S.round(4).to_csv(out_dir / "partial_profit_variants.csv", index=False)
    D = pd.DataFrame(diag_rows)
    D.round(2).to_csv(out_dir / "partial_profit_diagnostics.csv", index=False)
    cols = ["version", "ranking", "profit per year %", "Sharpe ratio", "max drawdown %", "profit per year / drawdown", "worst year %", "trades taken", "positions trimmed", "average open positions", "average position value % of account", "% of sessions at the cap"]
    order = {nm: i for i, (nm, *_r) in enumerate(variants)}
    for chg in ("none", "4% a year"):
        for wn in WIN:
            for cap in ((200, 100) if chg == "none" else (200,)):
                v = S[(S.period == wn) & (S["cap %"] == cap) & (S["borrowing charge"] == chg)].copy()
                v["o"] = v.version.map(order); v = v.sort_values(["ranking", "o"], ascending=[False, True])
                print(f"\n==== {wn} | cap {cap}% | borrowing charge: {chg} ====")
                print(v[cols].round(2).to_string(index=False))
    print("\n==== what the trim did (volume-surge ranking, cap 200%, whole in-sample) ====")
    print(D.set_index("version").T.round(1).to_string())

    # ---- start-year tables (volume-surge ranking): account started empty on 1 January of each year
    tabs = []
    for nm, N, prof, _ in variants:
        if N is not None and (N not in START_YEAR_N or prof):
            continue
        T = None if N is None else T_by[(N, prof)]
        res_eff, ss = effective_res(R, T)
        for cap in (2.0, 1.0):
            for y in range(2000, 2021):
                lo = pd.Timestamp(f"{y}-01-01")
                ed = dates[R["sess_e"]]; mask = np.asarray((ed >= lo) & (ed <= END))
                if mask.sum() < 5:
                    continue
                Rs = SY.subset(R, mask); Ts = None if T is None else {kk: vv[mask] for kk, vv in T.items()}
                P = portfolio_trim(Rs, cal, cap, key_vs[mask], Ts)
                st, _ = B.wstats(P["pnl"], dates, lo, END, P["open_n"], P["gross"])
                if not st:
                    continue
                dd = abs(st["max drawdown %"])
                tabs.append({"version": nm, "cap %": int(cap * 100), "start": lo.date().isoformat(), "profit per year %": st["profit per year %"], "max drawdown % (from peak)": st["max drawdown %"],
                             "profit per year / drawdown": st["profit per year %"] / dd if dd > 0 else np.nan, "worst year %": st["worst year %"], "Sharpe ratio": st["Sharpe ratio"]})
    T2 = pd.DataFrame(tabs); T2.round(3).to_csv(out_dir / "partial_profit_start_years.csv", index=False)
    for cap in (200, 100):
        v = T2[T2["cap %"] == cap].pivot(index="start", columns="version", values=["profit per year %", "max drawdown % (from peak)", "profit per year / drawdown"])
        print(f"\n==== start-year tables | cap {cap}% | volume-surge ranking ====")
        print(v.round(1).to_string())
    print("done")


if __name__ == "__main__":
    main()
