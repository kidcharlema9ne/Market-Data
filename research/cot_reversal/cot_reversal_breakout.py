#!/usr/bin/env python3
"""COT reversal-day breakout backtest: MAE / MFE study on the 48-market COT report universe.

Usage:
  python cot_reversal_breakout.py audit  <cot.csv.gz> <universe.csv> <prices.parquet|csv> <outdir> [--unseal]
  python cot_reversal_breakout.py run    <cot.csv.gz> <universe.csv> <prices.parquet|csv> <outdir> [--unseal]
  python cot_reversal_breakout.py selftest

RULES (all fixed before any run; see research/cot_reversal/SPEC.md copy of Michael's specification)
- LONG setup on signal day i ("reversal day"): higher high than day i-1 AND lower close than day i-1 AND the COT filter passes.
  Next session only (j = i+1): buy stop at high[i] + 1 tick. Filled if high[j] >= trigger; fill = max(open[j], trigger)
  (a gap above the trigger fills at the open). Otherwise cancelled. Initial stop = low[i].
- SHORT is the exact mirror: lower low, higher close, sell stop at low[i] - 1 tick, fill = min(open[j], trigger), stop = high[i].
- COT: legacy futures-only, 26-week index of commercial / large-speculator / small-speculator NET positions
  (index = (net - min)/(max - min)*100 over the latest 26 weekly reports, min_periods 26; same formula as cot-history/scripts/cot_report.py).
  Test A: comm >= 80 (long) / <= 20 (short).  Test B: comm >= 95, large <= 5, small <= 5 (short mirrored).
  Test C: comm = 100, large = 0, small = 0 (short mirrored).  A contains B contains C.
- COT timing: a Tuesday report is public Friday 15:30 ET (next Monday in a week containing a US federal holiday, never earlier than real).
  A signal day D may use only reports whose publication date is STRICTLY BEFORE D. Reports delayed by the 2013 and 2018-19 shutdowns
  are treated as published no earlier than the end of the delay window, and signal days inside those windows are excluded.
- ATR = mean true range of the 14 sessions ending at the signal day (the last completed session before the entry session).
- Excursions: session 1 = entry session. Windows of N = 1,2,3,4,5,10 sessions. A window is eligible only if all N sessions exist
  in the data with no hole > 5 calendar days.
  Long MFE = max(high over window) - fill; MAE = fill - min(low over window).  Short mirrored. Normalised by ATR.
  Entry-session ambiguity (daily bars hide intraday order): when the fill happens intraday (no gap through the trigger), the part of the
  entry-session range that came BEFORE the fill is unknown. The favourable extreme of the entry session is always post-entry (every
  pre-entry price is on the unfavourable side of the trigger), but the adverse extreme may be pre-entry. So MAE is reported as
  MAE_cons (whole entry-session range counted, a worst case) and MAE_opt (entry-session adverse range ignored, a best case). MAE in the
  headline tables is the conservative one; the bounds are reported side by side.
- Primary study = EVENT STUDY (every valid filled signal, overlapping signals in the same market allowed).
  Executable set = one open position per market, using the two-day / one-day trailing-stop exit path to decide when a position is open.
- Trailing exits (secondary): long stop starts at low[i], then each session = max(previous stop, min(low of the previous two completed
  sessions)); short stop starts at high[i], then min(previous stop, high of the previous completed session). Stop touched -> exit at the
  stop (open if it gapped through). Entry-session stop touches in intraday fills are order-ambiguous: pessimistic = stopped (primary),
  optimistic = ignored (sensitivity). Maximum hold 60 sessions then exit at that close. Trades that run out of data are censored.
- Sealed period (Michael's standing rule, 11 Nov 2026): unless --unseal, only signals up to 2021-08-06 are used and no price after
  2021-11-05 is read by any calculation.
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

HORIZONS = [1, 2, 3, 4, 5, 10]
MAX_HOLD = 60
DEV_LAST_SIGNAL = pd.Timestamp("2021-08-06")
SEAL_FIRST_DAY = pd.Timestamp("2021-11-08")
HOLE_DAYS = 5          # calendar-day gap between consecutive bars that marks missing data
STALE_REPORT_DAYS = 17  # latest usable report older than this (as-of to signal day) is treated as missing
COSTS_ATR = [0.05, 0.10]  # ASSUMED round-turn costs in ATR units for the cost-adjusted sensitivity (not measured)
SHUTDOWNS = [  # (first signal day to exclude, last day = publication catch-up end, first as-of date delayed)
    (pd.Timestamp("2013-10-01"), pd.Timestamp("2013-11-08"), pd.Timestamp("2013-10-01")),
    (pd.Timestamp("2018-12-22"), pd.Timestamp("2019-03-08"), pd.Timestamp("2018-12-24")),
]

PRICE_ROOTS = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6",
               "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}

# Minimum price increment in the exchange's conventional quote units (a unit check against the vendor prices is printed by `audit`).
TICKS = {
    "ZW": 0.25, "KE": 0.25, "ZC": 0.25, "ZS": 0.25, "ZL": 0.01, "ZM": 0.10, "CT": 0.01, "CC": 1.0, "KC": 0.05, "SB": 0.01,
    "ZB": 1 / 32, "UB": 1 / 32, "ZN": 1 / 64, "TN": 1 / 64, "ZF": 1 / 128, "ZT": 1 / 256, "ZQ": 0.0025, "SR3": 0.0025, "SR1": 0.0025,
    "HO": 0.0001, "RB": 0.0001, "NG": 0.001, "CL": 0.01, "BZ": 0.01, "PL": 0.10, "GC": 0.10, "SI": 0.005, "HG": 0.0005,
    "HE": 0.025, "LE": 0.025, "GF": 0.025,
    "6A": 0.0001, "6B": 0.0001, "6C": 0.00005, "6E": 0.00005, "6J": 0.0000005, "6L": 0.00005, "6M": 0.00001, "6N": 0.0001,
    "6S": 0.0001, "DX": 0.005, "VX": 0.05,
    "ES": 0.25, "MES": 0.25, "NQ": 0.25, "MNQ": 0.25, "RTY": 0.10, "YM": 1.0,
}


# ----------------------------------------------------------------------------------------------- COT
def pub_dates(report_dates):
    cal = USFederalHolidayCalendar()
    hol = set(cal.holidays(start=report_dates.min() - pd.Timedelta(days=7), end=report_dates.max() + pd.Timedelta(days=14)))
    pubs = []
    for d in report_dates:
        monday = d - pd.Timedelta(days=d.weekday())
        week_days = [monday + pd.Timedelta(days=i) for i in range(5)]
        friday = d + pd.Timedelta(days=(4 - d.weekday()) % 7 or 3)
        if any(x in hol for x in week_days):
            friday = friday + pd.Timedelta(days=3)
        pubs.append(friday)
    return pd.DatetimeIndex(pubs)


def cot_index(s, n=26):
    lo, hi = s.rolling(n, min_periods=n).min(), s.rolling(n, min_periods=n).max()
    return (s - lo) / (hi - lo).replace(0, np.nan) * 100


def build_cot(path, uni):
    cot = pd.read_csv(path, parse_dates=["date"], dtype={"code": str})
    cot = cot[cot["code"].isin(uni["code"])].sort_values(["code", "date"])
    out = {}
    for code, g in cot.groupby("code"):
        g = g.drop_duplicates("date").reset_index(drop=True)
        g["comm_idx"] = cot_index(g["comm"]).values
        g["large_idx"] = cot_index(g["large"]).values
        g["small_idx"] = cot_index(g["small"]).values
        # Continuity rule: the 26 reports must span at most 26 weeks + 4 weeks of slack, otherwise missing weeks make the window stale.
        span = (g["date"] - g["date"].shift(25)).dt.days
        stale = ~(span <= 26 * 7 + 28)
        for c_ in ("comm_idx", "large_idx", "small_idx"):
            g.loc[stale, c_] = np.nan
        g["pub"] = pub_dates(pd.DatetimeIndex(g["date"]))
        for start, end, first_asof in SHUTDOWNS:
            m = (g["date"] >= first_asof) & (g["pub"] <= end)
            g.loc[m, "pub"] = end
        g = g.rename(columns={"date": "asof"}).dropna(subset=["comm_idx", "large_idx", "small_idx"])
        out[code] = g.sort_values(["pub", "asof"]).reset_index(drop=True)[
            ["asof", "pub", "comm_idx", "large_idx", "small_idx", "comm", "large", "small", "oi"]]
    return out


# ----------------------------------------------------------------------------------------------- prices
def read_prices(path):
    if str(path).endswith(".parquet"):
        px = pd.read_parquet(path)
    else:
        px = pd.read_csv(path)
    px = px.copy()
    px["date"] = pd.to_datetime(px["file_date"])
    return px[["symbol", "date", "open", "high", "low", "close", "volume"]]


def clean_series(g):
    """One symbol's bars -> arrays; returns (dict of arrays, number of bars dropped as invalid)."""
    g = g.sort_values("date").drop_duplicates("date", keep="last")
    n0 = len(g)
    ok = g[["open", "high", "low", "close"]].notna().all(axis=1) & (g[["open", "high", "low", "close"]] > 0).all(axis=1)
    ok &= g["high"] >= g["low"]
    ok &= g["high"] >= g[["open", "close"]].max(axis=1) * (1 - 1e-9)
    ok &= g["low"] <= g[["open", "close"]].min(axis=1) * (1 + 1e-9)
    g = g[ok].reset_index(drop=True)
    d = g["date"].values.astype("datetime64[D]")
    h, l, c, o = (g[k].values.astype(float) for k in ("high", "low", "close", "open"))
    tr = np.full(len(g), np.nan)
    if len(g) > 1:
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    gap = np.r_[0, np.diff(d).astype(int)]
    hole = np.r_[False, gap[1:] > HOLE_DAYS]
    cs = np.cumsum(np.nan_to_num(tr))
    atr = np.full(len(g), np.nan)       # ATR ending AT bar k (tr[k-13..k]); the signal day is bar k, so ATR is known before entry
    for k in range(14, len(g)):
        atr[k] = (cs[k] - cs[k - 14]) / 14.0
    return dict(d=d, o=o, h=h, l=l, c=c, atr=atr, hole=hole, hole_cum=np.cumsum(hole)), n0 - len(g)


# ----------------------------------------------------------------------------------------------- trade mechanics
def make_trade(s, i, side, tick):
    """Simulate the next-session-only stop entry for signal bar i. Returns dict or None (not filled / invalid)."""
    j = i + 1
    n = len(s["d"])
    if j >= n or s["hole"][j] or not np.isfinite(s["atr"][i]) or s["atr"][i] <= 0:
        return None
    o, h, l = s["o"], s["h"], s["l"]
    if side == "long":
        trig = h[i] + tick
        if not h[j] >= trig:
            return None
        fill = max(o[j], trig)
        gapfill = o[j] >= trig
        stop = l[i]
        risk = fill - stop
    else:
        trig = l[i] - tick
        if not l[j] <= trig:
            return None
        fill = min(o[j], trig)
        gapfill = o[j] <= trig
        stop = h[i]
        risk = stop - fill
    if risk <= 0:
        return None
    return dict(i=i, j=j, side=side, trig=trig, fill=fill, gapfill=bool(gapfill), stop=stop, risk=risk, atr=s["atr"][i])


def excursions(s, t, N):
    """MFE/MAE (price units) over the N-session window starting at entry session. None if the window is not complete."""
    j = t["j"]
    k = j + N - 1
    n = len(s["d"])
    if k >= n or s["hole_cum"][k] != s["hole_cum"][j]:
        return None
    h, l, c = s["h"], s["l"], s["c"]
    fill = t["fill"]
    if t["side"] == "long":
        mfe = max(h[j:k + 1].max() - fill, 0.0)
        lo_cons = l[j:k + 1].min()
        lo_opt = lo_cons if t["gapfill"] else (min(l[j + 1:k + 1].min(), fill) if k > j else fill)
        mae_c, mae_o = max(fill - lo_cons, 0.0), max(fill - lo_opt, 0.0)
        ret = c[k] - fill
    else:
        mfe = max(fill - l[j:k + 1].min(), 0.0)
        hi_cons = h[j:k + 1].max()
        hi_opt = hi_cons if t["gapfill"] else (max(h[j + 1:k + 1].max(), fill) if k > j else fill)
        mae_c, mae_o = max(hi_cons - fill, 0.0), max(hi_opt - fill, 0.0)
        ret = fill - c[k]
    return mfe, mae_c, mae_o, ret


def stop_target_order(s, t, N, mult):
    """Return (reached_pessimistic, reached_optimistic, stop_touched_cons, stop_touched_opt) for target = mult * initial risk
    within the first N sessions. Same-session stop+target is order-unknown: pessimistic = stop first, optimistic = target first."""
    j = t["j"]
    k = j + N - 1
    h, l = s["h"], s["l"]
    fill, stop, risk, side = t["fill"], t["stop"], t["risk"], t["side"]
    first_t = first_sc = first_so = None
    for q in range(j, k + 1):
        if side == "long":
            hit_t = h[q] >= fill + mult * risk
            hit_s = l[q] <= stop
        else:
            hit_t = l[q] <= fill - mult * risk
            hit_s = h[q] >= stop
        if hit_t and first_t is None:
            first_t = q
        if hit_s and first_sc is None:
            first_sc = q
        if hit_s and first_so is None and (q > j or t["gapfill"]):
            first_so = q
    stop_c = first_sc is not None
    stop_o = first_so is not None
    if first_t is None:
        return False, False, stop_c, stop_o
    pess = (first_sc is None) or (first_t < first_sc)             # tie (same session) -> stop first
    opt = (first_so is None) or (first_t <= first_so)             # tie -> target first
    return pess, opt, stop_c, stop_o


def trailing_exit(s, t, optimistic=False):
    """Two-day trailing (long) / one-day trailing (short) stop. Returns (exit_price, exit_idx, reason) or None if censored."""
    j, i = t["j"], t["i"]
    n = len(s["d"])
    o, h, l, c = s["o"], s["h"], s["l"], s["c"]
    side = t["side"]
    stop = t["stop"]
    last = min(j + MAX_HOLD - 1, n - 1)
    for q in range(j, last + 1):
        if q > j:
            if s["hole"][q]:
                return None
            if side == "long":
                stop = max(stop, min(l[q - 1], l[q - 2]))
            else:
                stop = min(stop, h[q - 1])
        if side == "long":
            if q > j and o[q] <= stop:
                return o[q], q, "gap"
            touched = l[q] <= stop
        else:
            if q > j and o[q] >= stop:
                return o[q], q, "gap"
            touched = h[q] >= stop
        if touched and (q > j or t["gapfill"] or not optimistic):
            return stop, q, "stop"
    if j + MAX_HOLD - 1 <= n - 1:
        return c[j + MAX_HOLD - 1], j + MAX_HOLD - 1, "time"
    return None


# ----------------------------------------------------------------------------------------------- signals
def tests_pass(row, side):
    c, lg, sm = row.comm_idx, row.large_idx, row.small_idx
    if side == "long":
        a = c >= 80
        b = c >= 95 and lg <= 5 and sm <= 5
        cc = c >= 100 - 1e-9 and lg <= 1e-9 and sm <= 1e-9
        neutral = 20 < c < 80
    else:
        a = c <= 20
        b = c <= 5 and lg >= 95 and sm >= 95
        cc = c <= 1e-9 and lg >= 100 - 1e-9 and sm >= 100 - 1e-9
        neutral = 20 < c < 80
    return dict(A=a, B=b, C=cc, NOFILTER=True, NEUTRAL=neutral)


def in_shutdown(day):
    return any(a <= day <= b for a, b, _ in SHUTDOWNS)


def collect_signals(prices, cot, uni, unseal):
    sym_of = {r.code: PRICE_ROOTS.get(r.ibkr, r.ibkr) for r in uni.itertuples()}
    ibkr_of = {r.code: r.ibkr for r in uni.itertuples()}
    rows, dropped, cover = [], {}, []
    for code, sym in sym_of.items():
        g = prices[prices["symbol"] == sym]
        if g.empty or code not in cot:
            cover.append(dict(code=code, ibkr=ibkr_of[code], price_symbol=sym, bars=0))
            continue
        if not unseal:
            g = g[g["date"] < SEAL_FIRST_DAY]
        s, ndrop = clean_series(g)
        n = len(s["d"])
        cover.append(dict(code=code, ibkr=ibkr_of[code], price_symbol=sym, bars=n, first=str(s["d"][0]), last=str(s["d"][-1]),
                          dropped_invalid=ndrop, holes=int(s["hole"].sum())))
        tick = TICKS[ibkr_of[code]]
        dates = pd.DatetimeIndex(s["d"]).astype("datetime64[ns]")
        sig = pd.DataFrame({"date": dates, "idx": np.arange(n)})
        cc = cot[code].copy()
        cc["pub"] = cc["pub"].astype("datetime64[ns]")
        cc["asof"] = cc["asof"].astype("datetime64[ns]")
        merged = pd.merge_asof(sig, cc, left_on="date", right_on="pub", direction="backward", allow_exact_matches=False)
        for q in merged.itertuples():
            i = q.idx
            if i < 14 or s["hole"][i] or pd.isna(q.comm_idx):
                continue
            day = q.date
            if (not unseal) and day > DEV_LAST_SIGNAL:
                continue
            if in_shutdown(day) or (day - q.asof).days > STALE_REPORT_DAYS:
                continue
            assert q.pub < day and q.asof < q.pub + pd.Timedelta(days=1)   # never use a report before its release
            long_pat = s["h"][i] > s["h"][i - 1] and s["c"][i] < s["c"][i - 1]
            short_pat = s["l"][i] < s["l"][i - 1] and s["c"][i] > s["c"][i - 1]
            for side, pat in (("long", long_pat), ("short", short_pat)):
                if not pat:
                    continue
                flags = tests_pass(q, side)
                t = make_trade(s, i, side, tick)
                row = dict(code=code, ibkr=ibkr_of[code], side=side, signal_date=day, cot_asof=q.asof, cot_pub=q.pub,
                           comm_idx=q.comm_idx, large_idx=q.large_idx, small_idx=q.small_idx, filled=t is not None, **flags)
                if t is not None:
                    assert t["j"] == i + 1 and s["d"][t["j"]] > s["d"][i]
                    row.update(entry_date=pd.Timestamp(s["d"][t["j"]]), tick=tick, fill=t["fill"], trig=t["trig"], gapfill=t["gapfill"],
                               atr=t["atr"], risk_atr=t["risk"] / t["atr"])
                    for N in HORIZONS:
                        e = excursions(s, t, N)
                        if e is None:
                            continue
                        mfe, mc, mo, ret = e
                        row.update({f"mfe{N}": mfe / t["atr"], f"mae{N}": mc / t["atr"], f"maeopt{N}": mo / t["atr"],
                                    f"ret{N}": ret / t["atr"], f"amb{N}": bool(mc != mo)})
                        for mult in (1, 2):
                            p, op, sc, so = stop_target_order(s, t, N, mult)
                            row[f"r{mult}p{N}"], row[f"r{mult}o{N}"] = p, op
                            row[f"stopc{N}"], row[f"stopo{N}"] = sc, so
                        row[f"mfeR{N}"] = mfe / t["risk"]
                    for label, opt in (("trail", False), ("trailopt", True)):
                        ex = trailing_exit(s, t, optimistic=opt)
                        if ex is None:
                            row[f"{label}_ret"] = np.nan
                            continue
                        px, qx, why = ex
                        gross = ((px - t["fill"]) if side == "long" else (t["fill"] - px))
                        row[f"{label}_ret"] = gross / t["atr"]
                        row[f"{label}_R"] = gross / t["risk"]
                        row[f"{label}_dur"] = qx - t["j"] + 1
                        row[f"{label}_exit_idx"] = qx
                        row[f"{label}_why"] = why
                    row["entry_idx"] = t["j"]
                rows.append(row)
    tr = pd.DataFrame(rows)
    return tr, pd.DataFrame(cover)


def one_position_per_market(sub):
    """sub = trades of one test, sorted by entry; keep a trade only if the market's previous kept trade has exited before entry."""
    keep, busy_until = [], {}
    sub = sub.sort_values(["ibkr", "entry_idx"])
    for r in sub.itertuples():
        free = busy_until.get(r.ibkr, -1)
        ok = r.entry_idx > free and not np.isnan(r.trail_ret)
        keep.append(ok)
        if ok:
            busy_until[r.ibkr] = r.trail_exit_idx
    return sub[np.array(keep, dtype=bool)] if len(sub) else sub


# ----------------------------------------------------------------------------------------------- statistics
def pct(x):
    return float(np.mean(x) * 100) if len(x) else np.nan


def horizon_stats(d, N):
    col = f"mfe{N}"
    if col not in d:
        return None
    x = d[d[col].notna()]
    if x.empty:
        return None
    mfe, mae, maeo, ret = x[f"mfe{N}"], x[f"mae{N}"], x[f"maeopt{N}"], x[f"ret{N}"]
    return dict(n=len(x), mfe_mean=mfe.mean(), mfe_med=mfe.median(), mae_mean=mae.mean(), mae_med=mae.median(),
                maeopt_mean=maeo.mean(), maeopt_med=maeo.median(), ret_mean=ret.mean(), ret_med=ret.median(),
                mfe_ge1=pct(mfe >= 1), mfe_ge2=pct(mfe >= 2), mae_ge1=pct(mae >= 1), mae_ge2=pct(mae >= 2),
                maeopt_ge1=pct(maeo >= 1), pct_mfe_gt_mae=pct(mfe > mae), pct_mfe_gt_maeopt=pct(mfe > maeo),
                ambiguous_pct=pct(x[f"amb{N}"]), mfe_minus_mae_mean=(mfe - mae).mean(), mfe_minus_maeopt_mean=(mfe - maeo).mean())


def cluster_ci(d, N, reps=2000, seed=7, opt=False):
    """95% bootstrap CI of mean(MFE-MAE) resampling calendar-month clusters (signals in a month are correlated across markets)."""
    col = f"mfe{N}"
    x = d[d[col].notna()]
    if len(x) < 30:
        return (np.nan, np.nan)
    v = (x[col] - x[f"maeopt{N}" if opt else f"mae{N}"]).values
    cl = x["signal_date"].dt.to_period("M").astype(str).values
    uniq, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=v)
    cnts = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    m = len(uniq)
    idx = rng.integers(0, m, size=(reps, m))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def fmt(v, f="{:.2f}"):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f.format(v)


def table(title, rows, cols, widths=None):
    out = [title]
    head = "  ".join(f"{c:>9}" if k else f"{c:<28}" for k, c in enumerate(cols))
    out.append(head)
    for r in rows:
        out.append("  ".join(f"{v:>9}" if k else f"{v:<28}" for k, v in enumerate(r)))
    return "\n".join(out) + "\n"


TEST_LABEL = {"A": "A  Comm>=80/<=20", "B": "B  Three-way 95/5", "C": "C  Three-way 100/0",
              "NOFILTER": "ref: no COT filter", "NEUTRAL": "ref: Comm 21-79"}


def sides(tr, test, which):
    d = tr[tr["filled"] & tr[test]]
    return d if which == "combined" else d[d["side"] == which]


def metric_tables(tr, tests, which, metric, label):
    rows = []
    for tname in tests:
        d = sides(tr, tname, which)
        r = [TEST_LABEL[tname], str(len(d))]
        for N in HORIZONS:
            st = horizon_stats(d, N)
            r.append(fmt(st[metric]) if st else "n/a")
        rows.append(r)
    return table(f"{label} - {which} (ATR units)", rows, ["COT filter", "Trades"] + [f"{N}D" for N in HORIZONS])


def report(tr, cover, uni, outdir, unseal, extra_header=""):
    out = io.StringIO()
    w = out.write
    tests = ["A", "B", "C"]
    refs = ["NOFILTER", "NEUTRAL"]
    filled = tr[tr["filled"]]
    w("COT REVERSAL-DAY BREAKOUT BACKTEST - RESULTS\n")
    w(extra_header)
    w(f"Signals evaluated (pattern days passing data checks, any COT): {len(tr)}; filled next session: {len(filled)}\n")
    w(f"Signal-day range: {tr['signal_date'].min():%Y-%m-%d} to {tr['signal_date'].max():%Y-%m-%d}; "
      f"entry range {filled['entry_date'].min():%Y-%m-%d} to {filled['entry_date'].max():%Y-%m-%d}\n")
    w("Benchmark note: ATR-unit stock benchmarks do not apply to futures; the same-window reference rows are the unfiltered pattern (no COT filter) and the neutral-COT pattern (commercial index 21-79).\n")
    w(f"Period: {'FULL (sealed period unsealed)' if unseal else 'DEVELOPMENT ONLY (signals to 2021-08-06; no price after 2021-11-05 read)'}\n\n")
    w("== 1. TRADE COUNTS (event study = every filled signal; executable = one position per market via trailing-exit path) ==\n")
    rows = []
    for t in tests + refs:
        for sd in ("long", "short", "combined"):
            d = sides(tr, t, sd)
            sig = tr[tr[t]]
            sig = sig if sd == "combined" else sig[sig["side"] == sd]
            ex = one_position_per_market(d.dropna(subset=["trail_ret"])) if len(d) else d
            ep = d.drop_duplicates(["ibkr", "side", "cot_asof"]) if len(d) else d
            rows.append([f"{TEST_LABEL[t]} {sd}", str(len(sig)), str(len(d)), str(len(ex)), str(len(ep)), str(d["ibkr"].nunique())])
    w(table("COT test / side", rows, ["", "setups", "filled", "execut.", "mkt-week", "markets"]))
    w("  setups = pattern days passing the COT filter; filled = next-session stop triggered; execut. = one open position per market;\n"
      "  mkt-week = distinct market x COT-report clusters among filled trades (daily signals in one COT week are not independent).\n\n")

    w("== 2. MFE / MAE (ATR units, nonnegative). MFE is exact. MAE is a RANGE: the true value lies between the lower and upper bound (see section 5) ==\n")
    for which in ("long", "short", "combined"):
        for metric, label in (("mfe_mean", "Mean MFE"), ("mfe_med", "Median MFE"), ("mae_mean", "Mean MAE UPPER bound (entry session fully counted)"), ("maeopt_mean", "Mean MAE LOWER bound (entry-session adverse range ignored)"),
                              ("mae_med", "Median MAE UPPER bound"), ("maeopt_med", "Median MAE LOWER bound"),
                              ("ret_mean", "Mean close-to-entry return"), ("ret_med", "Median close-to-entry return")):
            w(metric_tables(tr, tests + refs, which, metric, label))
        w("\n")

    w("== 3. FULL STATISTICS PER TEST AND SIDE ==\n")
    cols = ["horizon", "n", "MFEmean", "MFEmed", "MAEmean", "MAEmed", "ret.mean", "ret.med", "MFE>=1", "MFE>=2", "MAE>=1", "MAE>=2", "MFE>MAE%"]
    for t in tests:
        for which in ("long", "short", "combined"):
            d = sides(tr, t, which)
            rows = []
            for N in HORIZONS:
                st = horizon_stats(d, N)
                if st:
                    rows.append([f"{N}D", str(st["n"]), fmt(st["mfe_mean"]), fmt(st["mfe_med"]), fmt(st["mae_mean"]), fmt(st["mae_med"]),
                                 fmt(st["ret_mean"], "{:+.2f}"), fmt(st["ret_med"], "{:+.2f}"), fmt(st["mfe_ge1"], "{:.0f}%"),
                                 fmt(st["mfe_ge2"], "{:.0f}%"), fmt(st["mae_ge1"], "{:.0f}%"), fmt(st["mae_ge2"], "{:.0f}%"),
                                 fmt(st["pct_mfe_gt_mae"], "{:.0f}%")])
            if rows:
                w(table(f"Test {TEST_LABEL[t]} - {which}", rows, cols))
    w("\n")

    w("== 4. DOES MFE BEAT MAE?  mean(MFE - MAE) with 95% bootstrap range (calendar-month clusters) ==\n")
    for opt in (False, True):
        w("Using MAE " + ("LOWER bound (best case)" if opt else "UPPER bound (worst case)") + "\n")
        rows = []
        for t_ in tests + refs:
            for which in ("long", "short", "combined"):
                d = sides(tr, t_, which)
                r = [f"{TEST_LABEL[t_]} {which}"]
                for N in HORIZONS:
                    st = horizon_stats(d, N)
                    if not st:
                        r.append("n/a")
                        continue
                    lo, hi = cluster_ci(d, N, opt=opt)
                    m_ = st["mfe_minus_maeopt_mean"] if opt else st["mfe_minus_mae_mean"]
                    r.append(f"{m_:+.2f}[{lo:+.2f},{hi:+.2f}]")
                rows.append(r)
        w("\n".join(["  ".join(f"{c:>22}" if k else f"{c:<28}" for k, c in enumerate(["COT filter / side"] + [f"{N}D" for N in HORIZONS])),
                     *["  ".join(f"{v:>22}" if k else f"{v:<28}" for k, v in enumerate(r)) for r in rows]]) + "\n\n")
    w("== 4b. WHEN DOES THE FAVOURABLE MOVE HAPPEN?  mean MFE at N sessions as % of mean MFE at 10 sessions (combined) ==\n")
    rows = []
    for t_ in tests + refs:
        d = sides(tr, t_, "combined")
        st10 = horizon_stats(d, 10)
        r = [TEST_LABEL[t_]]
        for N in HORIZONS:
            st = horizon_stats(d, N)
            r.append(fmt(st["mfe_mean"] / st10["mfe_mean"] * 100, "{:.0f}%") if st and st10 else "n/a")
        rows.append(r)
    w(table("", rows, ["COT filter"] + [f"{N}D" for N in HORIZONS]))
    w("  (a pure random walk would give 32% / 45% / 55% / 63% / 71% / 100% because range grows with the square root of time)\n\n")
    w("== 4c. DISTRIBUTIONS (combined): percentiles 10/25/50/75/90 of MFE and of MAE bounds, ATR ==\n")
    rows = []
    for t_ in tests + refs:
        d = sides(tr, t_, "combined")
        for N in (1, 5, 10):
            x = d[d[f"mfe{N}"].notna()]
            if len(x) < 20:
                continue
            q = lambda s: "/".join(f"{v:.2f}" for v in np.percentile(s, [10, 25, 50, 75, 90]))
            rows.append([f"{TEST_LABEL[t_]} {N}D", str(len(x)), q(x[f"mfe{N}"]), q(x[f"maeopt{N}"]), q(x[f"mae{N}"])])
    w("\n".join(["  ".join(f"{c:>34}" if k > 1 else (f"{c:<28}" if k == 0 else f"{c:>6}") for k, c in enumerate(["", "n", "MFE p10/25/50/75/90", "MAE lower p10..p90", "MAE upper p10..p90"])),
                 *["  ".join(f"{v:>34}" if k > 1 else (f"{v:<28}" if k == 0 else f"{v:>6}") for k, v in enumerate(r)) for r in rows]]) + "\n\n")

    w("== 5. ENTRY-SESSION AMBIGUITY (daily bars cannot order the entry session) ==\n")
    rows = []
    for t in tests:
        d = sides(tr, t, "combined")
        for N in (1, 5, 10):
            st = horizon_stats(d, N)
            if st:
                rows.append([f"{TEST_LABEL[t]} {N}D", str(st["n"]), fmt(st["ambiguous_pct"], "{:.0f}%"), fmt(st["mae_mean"]),
                             fmt(st["maeopt_mean"]), fmt(st["mfe_mean"]), fmt(st["pct_mfe_gt_mae"], "{:.0f}%"), fmt(st["pct_mfe_gt_maeopt"], "{:.0f}%")])
    w(table("combined", rows, ["", "n", "ambig.", "MAEcons", "MAEbest", "MFE", "MFE>MAEc", "MFE>MAEb"]))
    d = filled
    w(f"Share of fills that gapped through the trigger (fully reliable entry session): {pct(d['gapfill']):.1f}%\n\n")

    w("== 6. INITIAL RISK, R-MULTIPLES, STOP TOUCHES (stop = reversal-day extreme) ==\n")
    rows = []
    for t in tests + refs:
        d = sides(tr, t, "combined")
        if d.empty:
            continue
        r = [TEST_LABEL[t], str(len(d)), fmt(d["risk_atr"].mean()), fmt(d["risk_atr"].median())]
        for N in (5, 10):
            x = d[d[f"mfe{N}"].notna()]
            if x.empty:
                r += ["n/a"] * 6
                continue
            r += [fmt(x[f"mfeR{N}"].median()), fmt(pct(x[f"mfeR{N}"] >= 1), "{:.0f}%"), fmt(pct(x[f"mfeR{N}"] >= 2), "{:.0f}%"),
                  fmt(pct(x[f"stopc{N}"]), "{:.0f}%"), fmt(pct(x[f"r1p{N}"]), "{:.0f}-") + fmt(pct(x[f"r1o{N}"]), "{:.0f}%"),
                  fmt(pct(x[f"r2p{N}"]), "{:.0f}-") + fmt(pct(x[f"r2o{N}"]), "{:.0f}%")]
        rows.append(r)
    w(table("combined; risk in ATR; per horizon: median MFE/risk, %MFE>=1R, %MFE>=2R, %touch stop (cons.), %+1R before stop (pess-opt), %+2R before stop (pess-opt)",
            rows, ["", "n", "riskMean", "riskMed", "5D:MFE/R", "5D:>=1R", "5D:>=2R", "5D:stop", "5D:1R<stop", "5D:2R<stop",
                   "10D:MFE/R", "10D:>=1R", "10D:>=2R", "10D:stop", "10D:1R<stop", "10D:2R<stop"]))
    w("  1R<stop / 2R<stop: share reaching +1R / +2R before touching the stop; first number assumes the stop came first when both were hit in\n"
      "  the same session, second assumes the target came first. The truth lies between.\n\n")

    w("== 7. TRAILING-STOP EXITS (secondary; gross of costs unless stated; pessimistic entry-session stop handling) ==\n")
    rows = []
    for t in tests + refs:
        for which in ("long", "short", "combined"):
            d = sides(tr, t, which)
            d = d.dropna(subset=["trail_ret"])
            if d.empty:
                continue
            ex = one_position_per_market(d)
            for label, x in (("event", d), ("exec", ex)):
                if x.empty:
                    continue
                r = x["trail_ret"]
                rows.append([f"{TEST_LABEL[t]} {which} {label}", str(len(x)), fmt(pct(r > 0), "{:.0f}%"), fmt(r.mean(), "{:+.3f}"),
                             fmt(r.median(), "{:+.3f}"), fmt(x["trail_R"].mean(), "{:+.3f}"), fmt(x["trail_dur"].mean(), "{:.1f}"),
                             fmt(x["trail_dur"].median(), "{:.0f}"), fmt((r - COSTS_ATR[0]).mean(), "{:+.3f}"), fmt((r - COSTS_ATR[1]).mean(), "{:+.3f}"),
                             fmt(x["trailopt_ret"].mean(), "{:+.3f}")])
    w(table("returns in ATR units (R = initial risk). cost columns subtract an ASSUMED round-turn cost of 0.05 / 0.10 ATR (not measured)",
            rows, ["", "n", "win%", "meanATR", "medianATR", "meanR", "avgDur", "medDur", "net.05", "net.10", "optimist."]))
    w("  optimist. = mean gross ATR return if entry-session stop touches (intraday fills) are ignored; the headline columns treat them as stopped.\n")
    cens = tr[tr["filled"]]["trail_ret"].isna().sum()
    w(f"  Censored (ran out of data before an exit; excluded): {int(cens)} of {len(filled)} fills\n\n")

    w("== 8. PER-MARKET BREAKDOWN (combined long+short; Test A, B, C counts; 5-session means for Test A) ==\n")
    rows = []
    for m in uni["ibkr"]:
        r = [m]
        for t in tests:
            r.append(str(len(sides(tr, t, "combined")[lambda x: x["ibkr"] == m])))
        d = sides(tr, "A", "combined")
        d = d[(d["ibkr"] == m) & d["mfe5"].notna()]
        if len(d):
            r += [fmt(d["mfe5"].mean()), fmt(d["mae5"].mean()), fmt(d["ret5"].mean(), "{:+.2f}"), fmt(d["trail_ret"].mean(), "{:+.2f}")]
        else:
            r += ["n/a"] * 4
        rows.append(r)
    w(table("market", rows, ["market", "nA", "nB", "nC", "A:MFE5", "A:MAE5", "A:ret5", "A:trail"]))
    w("\n")

    w("== 9. BREADTH AND CONCENTRATION (Test A and B, 5-session mean MFE-MAE, per-market) ==\n")
    for t in ("A", "B"):
        d = sides(tr, t, "combined")
        d = d[d["mfe5"].notna()].copy()
        d["edge"] = d["mfe5"] - d["mae5"]
        g = d.groupby("ibkr")["edge"].agg(["count", "mean"])
        gg = g[g["count"] >= 10]
        if len(gg):
            w(f"Test {t}: markets with >=10 trades: {len(gg)}; positive mean edge in {int((gg['mean'] > 0).sum())} of them "
              f"({(gg['mean'] > 0).mean() * 100:.0f}%); median market mean {gg['mean'].median():+.2f}\n")
        top = d["ibkr"].value_counts()
        if len(top):
            w(f"  trade concentration: top 5 markets hold {top.head(5).sum() / len(d) * 100:.0f}% of {len(d)} trades ({', '.join(top.head(5).index)})\n")
            d2 = d[~d["ibkr"].isin(top.head(3).index)]
            w(f"  mean edge all {d['edge'].mean():+.2f}; without the 3 most frequent markets {d2['edge'].mean():+.2f} (n={len(d2)})\n")
    w("\n")

    w("== 10. PERIOD ROBUSTNESS (combined, 5-session): mean MFE, MAE, MFE-MAE, close return, trailing return by period ==\n")
    periods = [("2008-2010", "2008-01-01", "2010-12-31"), ("2011-2013", "2011-01-01", "2013-12-31"),
               ("2014-2016", "2014-01-01", "2016-12-31"), ("2017-2021", "2017-01-01", "2021-12-31")]
    if unseal:
        periods += [("2022-2026", "2022-01-01", "2026-12-31")]
    rows = []
    for t in tests + refs:
        d0 = sides(tr, t, "combined")
        for name, a, b in periods:
            d = d0[(d0["signal_date"] >= a) & (d0["signal_date"] <= b)]
            x = d[d["mfe5"].notna()]
            rows.append([f"{TEST_LABEL[t]} {name}", str(len(x)), fmt(x["mfe5"].mean()) if len(x) else "n/a", fmt(x["mae5"].mean()) if len(x) else "n/a",
                         fmt((x["mfe5"] - x["mae5"]).mean(), "{:+.2f}") if len(x) else "n/a", fmt(x["ret5"].mean(), "{:+.2f}") if len(x) else "n/a",
                         fmt(d["trail_ret"].mean(), "{:+.3f}") if len(d) else "n/a"])
    w(table("", rows, ["", "n", "MFE5", "MAE5", "MFE-MAE", "ret5", "trail"]))
    text = out.getvalue()
    (Path(outdir) / "reversal_breakout_results.txt").write_text(text, encoding="utf-8")
    cols = [c for c in tr.columns]
    tr.to_csv(Path(outdir) / "signals_and_trades.csv.gz", index=False, compression="gzip")
    return text


# ----------------------------------------------------------------------------------------------- audit
def audit(prices, cot, uni, outdir, unseal):
    out = io.StringIO()
    w = out.write
    w("DATA AUDIT\n")
    w(f"Universe file markets: {len(uni)}; unique codes {uni['code'].nunique()}; unique IBKR symbols {uni['ibkr'].nunique()}\n")
    syms = set(prices["symbol"].unique())
    w(f"Price symbols in table: {len(syms)}; rows {len(prices)}; dates {prices['date'].min():%Y-%m-%d} to {prices['date'].max():%Y-%m-%d}; "
      f"distinct dates {prices['date'].nunique()}\n")
    rows = []
    for r in uni.itertuples():
        sym = PRICE_ROOTS.get(r.ibkr, r.ibkr)
        g = prices[prices["symbol"] == sym]
        if not unseal:
            g = g[g["date"] < SEAL_FIRST_DAY]
        c = cot.get(r.code)
        if g.empty:
            rows.append([r.ibkr, sym, "MISSING", "", "", "", "", "", "", ""])
            continue
        s, nd = clean_series(g)
        recent = g.sort_values("date").tail(20)["close"].median()
        tick = TICKS[r.ibkr]
        rows.append([r.ibkr, sym, str(len(s["d"])), str(s["d"][0]), str(s["d"][-1]), str(nd), str(int(s["hole"].sum())),
                     f"{recent:.6g}", f"{tick:.3g}", f"{tick / recent:.2e}",
                     f"{c['asof'].min():%Y-%m-%d}" if c is not None else "NO COT"])
    w(table("Per market (bars; first; last; invalid bars dropped; holes >5 days; recent median close; tick; tick/price; first COT index date)",
            rows, ["IBKR", "pxsym", "bars", "first", "last", "dropped", "holes", "price", "tick", "tick/px", "COT first"]))
    bad = [r[0] for r in rows if r[2] == "MISSING"]
    w(f"\nMarkets with no price series: {bad if bad else 'none'}\n")
    w(f"Markets with no COT series: {[r.ibkr for r in uni.itertuples() if r.code not in cot] or 'none'}\n")
    flag = [r[0] for r in rows if r[2] != "MISSING" and not (1e-7 < float(r[9]) < 5e-3)]
    w(f"Tick-size unit sanity (tick/price outside 1e-7..5e-3 means a unit mismatch to fix): {flag if flag else 'all plausible'}\n")
    # COT chronology checks
    viol = 0
    for code, g in cot.items():
        viol += int((g["pub"] <= g["asof"]).sum())
    w(f"COT reports whose publication date is not after the as-of date: {viol}\n")
    gaps = []
    for code, g in cot.items():
        dd = g["asof"].sort_values().diff().dt.days
        gaps.append(int((dd > 10).sum()))
    w(f"Weekly COT series with gaps > 10 days (total gap count across markets): {sum(gaps)}\n")
    text = out.getvalue()
    (Path(outdir) / "data_audit.txt").write_text(text, encoding="utf-8")
    return text



def verify(cot_path, uni_path, px_path, outdir, unseal):
    """Independent recomputation of a random sample of trades from the raw bars and raw COT file, using different code paths."""
    uni = pd.read_csv(uni_path, dtype={"code": str})
    tr = pd.read_csv(Path(outdir) / "signals_and_trades.csv.gz", parse_dates=["signal_date", "entry_date", "cot_asof", "cot_pub"],
                     dtype={"code": str})
    px = read_prices(px_path)
    raw = pd.read_csv(cot_path, parse_dates=["date"], dtype={"code": str})
    out = []
    fails = 0
    f = tr[tr["filled"]]
    # global invariants over every row
    out.append(f"rows {len(tr)}, filled {len(f)}")
    inv = {
        "COT publication strictly before signal day": int((tr["cot_pub"] >= tr["signal_date"]).sum()),
        "COT as-of before publication": int((tr["cot_asof"] >= tr["cot_pub"]).sum()),
        "entry date after signal date": int((f["entry_date"] <= f["signal_date"]).sum()),
        "entry more than 5 days after signal": int(((f["entry_date"] - f["signal_date"]).dt.days > 5).sum()),
        "fill below long trigger": int(((f["side"] == "long") & (f["fill"] < f["trig"] - 1e-9)).sum()),
        "fill above short trigger": int(((f["side"] == "short") & (f["fill"] > f["trig"] + 1e-9)).sum()),
        "negative MFE": int((f["mfe5"] < 0).sum()),
        "negative MAE": int((f["mae5"] < 0).sum()),
        "MAE lower bound above upper bound": int((f["maeopt5"] > f["mae5"] + 1e-9).sum()),
        "test C not inside B": int((tr["C"] & ~tr["B"]).sum()),
        "test B not inside A": int((tr["B"] & ~tr["A"]).sum()),
        "dates after sealed cut-off used": 0 if unseal else int((tr["signal_date"] > DEV_LAST_SIGNAL).sum()),
    }
    for k, v in inv.items():
        out.append(f"  invariant: {k}: {v} violations")
        fails += v
    HOL = set(USFederalHolidayCalendar().holidays(start="1992-01-01", end="2027-12-31"))
    rng = np.random.default_rng(11)
    sample = f.iloc[rng.choice(len(f), size=min(400, len(f)), replace=False)]
    cache = {}
    chk = dict(fill=0, mfe5=0, mae5=0, maeopt5=0, ret5=0, mfe10=0, trail=0, cot=0, pattern=0, n=0)
    sym_of = {r.code: PRICE_ROOTS.get(r.ibkr, r.ibkr) for r in uni.itertuples()}
    for r in sample.itertuples():
        sym = sym_of[r.code]
        if sym not in cache:
            g = px[px["symbol"] == sym].sort_values("date").reset_index(drop=True)
            cache[sym] = g
        g = cache[sym]
        chk["n"] += 1
        pos = g.index[g["date"] == r.signal_date][0]
        prev, sig, nxt = g.iloc[pos - 1], g.iloc[pos], g.iloc[pos + 1]
        ok_pat = (sig.high > prev.high and sig.close < prev.close) if r.side == "long" else (sig.low < prev.low and sig.close > prev.close)
        chk["pattern"] += int(not ok_pat)
        if nxt.date != r.entry_date:
            chk["fill"] += 1
            continue
        # independent ATR and tick-based fill
        tr_list = []
        for k in range(pos - 13, pos + 1):
            a, b = g.iloc[k], g.iloc[k - 1]
            tr_list.append(max(a.high - a.low, abs(a.high - b.close), abs(a.low - b.close)))
        atr = sum(tr_list) / 14.0
        tick = r.tick
        if r.side == "long":
            trig = sig.high + tick
            fill = max(nxt.open, trig)
            ok = nxt.high >= trig
        else:
            trig = sig.low - tick
            fill = min(nxt.open, trig)
            ok = nxt.low <= trig
        if not ok or abs(fill - r.fill) > 1e-9 * max(1, abs(fill)):
            chk["fill"] += 1
            continue
        for N, key in ((5, "5"), (10, "10")):
            w = g.iloc[pos + 1: pos + 1 + N]
            if len(w) < N or pd.isna(getattr(r, f"mfe{N}")):
                continue
            if r.side == "long":
                mfe, lo_c, ret = w.high.max() - fill, w.low.min(), w.close.iloc[-1] - fill
                mae_c = max(fill - lo_c, 0)
                later = w.iloc[1:]
                lo_o = min(later.low.min() if len(later) else fill, fill) if not (nxt.open >= trig) else lo_c
                mae_o = max(fill - lo_o, 0)
            else:
                mfe, hi_c, ret = fill - w.low.min(), w.high.max(), fill - w.close.iloc[-1]
                mae_c = max(hi_c - fill, 0)
                later = w.iloc[1:]
                hi_o = max(later.high.max() if len(later) else fill, fill) if not (nxt.open <= trig) else hi_c
                mae_o = max(hi_o - fill, 0)
            for name, mine, theirs in ((f"mfe{N}", mfe / atr, getattr(r, f"mfe{N}")), (f"mae{N}", mae_c / atr, getattr(r, f"mae{N}")),
                                       (f"maeopt{N}", mae_o / atr, getattr(r, f"maeopt{N}")), (f"ret{N}", ret / atr, getattr(r, f"ret{N}"))):
                if name in chk and abs(mine - theirs) > 1e-7:
                    chk[name] += 1
        # trailing stop, written independently
        stop = sig.low if r.side == "long" else sig.high
        ex = None
        for q in range(pos + 1, min(pos + 1 + MAX_HOLD, len(g))):
            b = g.iloc[q]
            if q > pos + 1:
                if r.side == "long":
                    stop = max(stop, min(g.iloc[q - 1].low, g.iloc[q - 2].low))
                    if b.open <= stop:
                        ex = (b.open, q); break
                else:
                    stop = min(stop, g.iloc[q - 1].high)
                    if b.open >= stop:
                        ex = (b.open, q); break
            hit = b.low <= stop if r.side == "long" else b.high >= stop
            if hit:
                ex = (stop, q); break
        if ex is None and pos + MAX_HOLD < len(g):
            ex = (g.iloc[pos + MAX_HOLD].close, pos + MAX_HOLD)
        if ex is not None:
            gross = (ex[0] - fill) if r.side == "long" else (fill - ex[0])
            if abs(gross / atr - r.trail_ret) > 1e-7:
                chk["trail"] += 1
        # COT: recompute the report available on the signal day with a brute-force loop
        rc = raw[raw["code"] == r.code].sort_values("date").drop_duplicates("date").reset_index(drop=True)
        best = None
        near = np.where((rc["date"] < r.signal_date) & (rc["date"] > r.signal_date - pd.Timedelta(days=140)))[0]
        for k in near:
            d0 = rc["date"].iloc[k]
            pub = d0 + pd.Timedelta(days=(4 - d0.weekday()) % 7 or 3)   # Friday of that week (a Friday as-of date -> next Monday)
            mon = d0 - pd.Timedelta(days=d0.weekday())
            if any((mon + pd.Timedelta(days=q_)) in HOL for q_ in range(5)):
                pub = pub + pd.Timedelta(days=3)
            for a, b_, c_ in SHUTDOWNS:
                if d0 >= c_ and pub <= b_:
                    pub = b_
            if pub < r.signal_date and (best is None or (pub, d0) > (best[0], best[1])):
                best = (pub, d0, k)
        if best is None or best[1] != r.cot_asof:
            chk["cot"] += 1
        else:
            k = best[2]
            for col, key in (("comm", "comm_idx"), ("large", "large_idx"), ("small", "small_idx")):
                win = rc[col].iloc[k - 25:k + 1]
                lo, hi = win.min(), win.max()
                val = (rc[col].iloc[k] - lo) / (hi - lo) * 100 if hi > lo else np.nan
                if not (abs(val - getattr(r, key)) < 1e-6):
                    chk["cot"] += 1
                    break
    out.append(f"independent recomputation of {chk['n']} random filled trades: mismatches {({k: v for k, v in chk.items() if k != 'n'})}")
    fails += sum(v for k, v in chk.items() if k != "n")
    out.append("VERIFICATION " + ("PASSED" if fails == 0 else f"FAILED ({fails} problems)"))
    text = "\n".join(out) + "\n"
    (Path(outdir) / "verification.txt").write_text(text, encoding="utf-8")
    return text

# ----------------------------------------------------------------------------------------------- self test
def selftest():
    # Hand-built bars. Day 0..15 are filler with a stable range; day 16 is a bearish reversal day with a higher high.
    n = 40
    d = pd.bdate_range("2020-01-01", periods=n)
    o = np.full(n, 100.0); h = np.full(n, 101.0); l = np.full(n, 99.0); c = np.full(n, 100.0)
    # reversal day i=20: higher high than day 19 (101 -> 102), lower close than day 19 (100 -> 99.5), low 98.5
    h[20], l[20], c[20], o[20] = 102.0, 98.5, 99.5, 100.5
    # entry session 21: opens 101.5 (below trigger 102.5), trades up through 102.5, high 106, low 98 (pre- or post-entry unknown)
    o[21], h[21], l[21], c[21] = 101.5, 106.0, 98.0, 105.0
    o[22], h[22], l[22], c[22] = 105.0, 107.0, 103.0, 104.0
    px = pd.DataFrame({"symbol": "T", "file_date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c, "volume": 1})
    px["date"] = pd.to_datetime(px["file_date"])
    s, nd = clean_series(px)
    assert nd == 0
    t = make_trade(s, 20, "long", 0.5)
    assert t is not None and t["j"] == 21 and abs(t["trig"] - 102.5) < 1e-12 and abs(t["fill"] - 102.5) < 1e-12 and not t["gapfill"]
    assert abs(t["stop"] - 98.5) < 1e-12 and abs(t["risk"] - 4.0) < 1e-12
    mfe, mac, mao, ret = excursions(s, t, 1)
    assert abs(mfe - 3.5) < 1e-12                       # 106 - 102.5
    assert abs(mac - 4.5) < 1e-12 and abs(mao - 0.0) < 1e-12   # cons: whole-session low 98 counts; best case: none
    mfe2, mac2, mao2, ret2 = excursions(s, t, 2)
    assert abs(mfe2 - 4.5) < 1e-12                      # high 107
    assert abs(mao2 - 0.0) < 1e-12                      # later low 103 is above the fill -> best case zero
    assert abs(ret2 - 1.5) < 1e-12                      # close 104 - 102.5
    # not filled when the next session never reaches high+tick
    h2 = h.copy(); h2[21] = 102.4
    s2 = dict(s); s2["h"] = h2
    assert make_trade(s2, 20, "long", 0.5) is None
    # gap through the trigger fills at the open
    o3 = o.copy(); o3[21] = 103.0
    s3 = dict(s); s3["o"] = o3
    t3 = make_trade(s3, 20, "long", 0.5)
    assert abs(t3["fill"] - 103.0) < 1e-12 and t3["gapfill"]
    mfe3, mac3, mao3, _ = excursions(s3, t3, 1)
    assert abs(mac3 - mao3) < 1e-12                     # gap fill: no ambiguity
    # the spec's own example: entry 100, ATR 2, high 106, low 98 -> long MFE 3 ATR, MAE 1 ATR
    assert abs((106 - 100) / 2 - 3) < 1e-12 and abs((100 - 98) / 2 - 1) < 1e-12
    # mirror: build a short setup by negating prices around 200
    s4 = dict(s)
    for k, kk in (("o", "o"), ("c", "c")):
        s4[k] = 200 - s[kk]
    s4["h"], s4["l"] = 200 - s["l"], 200 - s["h"]
    t4 = make_trade(s4, 20, "short", 0.5)
    assert abs(t4["fill"] - (200 - 102.5)) < 1e-12 and abs(t4["risk"] - 4.0) < 1e-12
    m4 = excursions(s4, t4, 2)
    assert abs(m4[0] - 4.5) < 1e-12 and abs(m4[1] - 4.5) < 1e-12 or abs(m4[1] - mac2) < 1e-12
    # publication timing: Tuesday report published Friday; holiday week pushes to Monday
    p = pub_dates(pd.DatetimeIndex(["2020-01-07", "2020-01-14", "2019-12-31"]))
    assert p[0] == pd.Timestamp("2020-01-10") and p[1] == pd.Timestamp("2020-01-17")
    assert p[2] == pd.Timestamp("2020-01-06")           # week of 1 Jan 2020 holiday -> next Monday
    # trailing stop: long keeps initial stop at low[i]=98.5 while session 21 (intraday fill) low 98 is ambiguous
    ex = trailing_exit(s, t, optimistic=False)
    assert ex is not None and abs(ex[0] - 98.5) < 1e-12 and ex[1] == 21     # pessimistic: stopped in the entry session
    exo = trailing_exit(s, t, optimistic=True)
    assert exo is None or exo[1] > 21                                         # optimistic: ignored
    print("selftest OK")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        selftest()
        return
    mode, cot_path, uni_path, px_path, outdir = sys.argv[1:6]
    unseal = "--unseal" in sys.argv
    Path(outdir).mkdir(parents=True, exist_ok=True)
    uni = pd.read_csv(uni_path, dtype={"code": str})
    cot = build_cot(cot_path, uni)
    prices = read_prices(px_path)
    if mode == "audit":
        print(audit(prices, cot, uni, outdir, unseal))
        return
    if mode == "verify":
        print(verify(cot_path, uni_path, px_path, outdir, unseal))
        return
    print(audit(prices, cot, uni, outdir, unseal))
    tr, cover = collect_signals(prices, cot, uni, unseal)
    cover.to_csv(Path(outdir) / "coverage.csv", index=False)
    hdr = ""
    print(report(tr, cover, uni, outdir, unseal, hdr))


if __name__ == "__main__":
    main()
