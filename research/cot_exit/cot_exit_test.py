"""Commercial COT index exit test (futures, ATR units).

Question: does exiting when the commercial index returns to 50 beat fixed 21 / 42 session exits, and does it
change with longer index windows (26 baseline, 50, 100 weeks) and with protective stops (1.5 / 2 / 2.5 / 3 ATR)?

Rules (from Michael's handoff, Nov 2026)
- Legacy futures-only commercial net = commercial long - commercial short. Index over N weeks (current week included)
  = (net - min) / (max - min) * 100.
- Long signal: index reaches 100 (previous week below 100). Short signal: index reaches 0 (previous week above 0).
- Liquidity filter and market list as in cot-history scripts/cot_report.py (IBKR futures, open interest >= 45,000,
  thin products removed), measured in the signal week.
- A report for a Tuesday is public Friday 15:30 ET (shifted to the next Monday in a week with a US federal holiday,
  which is never earlier than the real release). Entries and exits happen at the open of the first futures daily bar
  dated AFTER the publication date. Tuesday positioning is never used before that.
- Comm-50 exit: first subsequently published index <= 50 (long) / >= 50 (short) -> exit at the next eligible open.
  If not reached, exit at the close of session 42 (session 1 = entry session).
- Fixed exits: close of session 21 or 42.
- ATR = mean true range of the 14 sessions before the entry session. Return = direction * (exit - entry) / ATR.
- Protective stop: entry -/+ k * ATR, checked on each bar's low/high from the entry session on; filled at the stop
  or at the open if the bar gaps through it.
- One position per market at a time. A signal that arrives while a position is open is skipped. Because exits differ by
  rule, the trade sets differ; the comparison reports matched entries and the extra / missing trades separately.
- No transaction costs are deducted. Prices are vendor ratio back-adjusted continuous bars.
"""
import sys
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

COT_PATH = sys.argv[1] if len(sys.argv) > 1 else "research/cot_exit/cot_weekly.csv.gz"
PRICE_PATH = sys.argv[2] if len(sys.argv) > 2 else "futures_prices.parquet"
MIN_OI = 45_000
THIN = {"SPXDIVAN", "AIGCI", "MFS", "MME", "DJUSRE", "HH", "EMD"}
PRICE_ROOTS = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6",
               "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
WINDOWS = [26, 50, 100]
STOPS = [None, 1.5, 2.0, 2.5, 3.0]
EXITS = ["fixed21", "fixed42", "comm50"]
CAP = 42
BOOT = 4000
RNG = np.random.default_rng(20261110)


# ---------------------------------------------------------------- data
def load_prices(path):
    px = pd.read_csv(path) if str(path).endswith((".csv", ".csv.gz")) else pd.read_parquet(path)
    px["date"] = pd.to_datetime(px["file_date"])
    n0 = len(px)
    px = px.dropna(subset=["open", "high", "low", "close"])
    px = px[px["high"] >= px["low"]]
    dup = px.duplicated(["symbol", "date"], keep=False).sum()
    px = px.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    print(f"price rows {n0} -> {len(px)} (duplicate symbol-date rows seen: {dup}); symbols {px['symbol'].nunique()}")
    out = {}
    for sym, g in px.groupby("symbol"):
        out[sym] = dict(d=g["date"].values.astype("datetime64[D]"), o=g["open"].values, h=g["high"].values,
                        l=g["low"].values, c=g["close"].values)
    return out


def prep_series(s):
    h, l, c = s["h"], s["l"], s["c"]
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    atr_before = np.full(len(c), np.nan)
    cs = np.cumsum(np.nan_to_num(tr))
    for i in range(15, len(c)):
        atr_before[i] = (cs[i - 1] - cs[i - 15]) / 14.0   # tr[i-14..i-1]
    s["atr_before"] = atr_before
    gaps = np.diff(s["d"]).astype(int)
    s["gap_cum"] = np.r_[0, np.cumsum(gaps > 7)]          # count of >7-day holes, for a quick data-quality guard
    return s


def pub_dates(report_dates):
    cal = USFederalHolidayCalendar()
    hol = set(cal.holidays(start=report_dates.min() - pd.Timedelta(days=7),
                           end=report_dates.max() + pd.Timedelta(days=14)))
    pubs = []
    for d in report_dates:
        monday = d - pd.Timedelta(days=d.weekday())
        week_days = [monday + pd.Timedelta(days=i) for i in range(5)]
        friday = d + pd.Timedelta(days=(4 - d.weekday()) % 7 or 3)
        if any(x in hol for x in week_days):
            friday = friday + pd.Timedelta(days=3)       # Monday after
        pubs.append(friday)
    return pd.DatetimeIndex(pubs)


def cot_index(s, n):
    lo, hi = s.rolling(n, min_periods=n).min(), s.rolling(n, min_periods=n).max()
    return (s - lo) / (hi - lo).replace(0, np.nan) * 100


def build_cot(path):
    cot = pd.read_csv(path, parse_dates=["date"])
    cot = cot[(~cot["ibkr"].isin(THIN))]
    markets = {}
    for code, g in cot.groupby("code"):
        g = g.sort_values("date").reset_index(drop=True)
        g["pub"] = pub_dates(pd.DatetimeIndex(g["date"]))
        for n in WINDOWS:
            g[f"idx{n}"] = cot_index(g["comm"], n)
        g["large26"] = cot_index(g["large"], 26)
        g["small26"] = cot_index(g["small"], 26)
        markets[g["ibkr"].iloc[-1] + "|" + code] = g
    return markets


# ---------------------------------------------------------------- simulation
def simulate(window, exit_rule, stop_k, markets, prices, subset="all"):
    trades, skipped = [], dict(no_price=0, short_hist=0, gap=0, bad_atr=0)
    for key, g in markets.items():
        ibkr = key.split("|")[0]
        root = PRICE_ROOTS.get(ibkr, ibkr)
        s = prices.get(root)
        if s is None:
            skipped["no_price"] += 1
            continue
        idx = g[f"idx{window}"].values
        pub = g["pub"].values.astype("datetime64[D]")
        oi = g["oi"].values
        sess_after = np.searchsorted(s["d"], pub, side="right")      # first session dated after the release
        free_from = 0
        for w in range(1, len(g)):
            if np.isnan(idx[w]) or np.isnan(idx[w - 1]):
                continue
            if idx[w] >= 100 - 1e-9 and idx[w - 1] < 100 - 1e-9:
                d = 1
            elif idx[w] <= 1e-9 and idx[w - 1] > 1e-9:
                d = -1
            else:
                continue
            if oi[w] < MIN_OI:
                continue
            if subset == "aligned":   # report group 1: large and small specs each at 0 or 100 (26-week) in the same week
                lg, sm = g["large26"].values[w], g["small26"].values[w]
                if not (np.isfinite(lg) and np.isfinite(sm)) or not ((lg >= 100 - 1e-9 or lg <= 1e-9) and (sm >= 100 - 1e-9 or sm <= 1e-9)):
                    continue
            e = sess_after[w]
            if e >= len(s["d"]) or e < 15 or e < free_from:
                if e < 15 and e < len(s["d"]):
                    skipped["short_hist"] += 1
                continue
            atr = s["atr_before"][e]
            if not np.isfinite(atr) or atr <= 0:
                skipped["bad_atr"] += 1
                continue
            end_cap = e + CAP - 1 if exit_rule != "fixed21" else e + 21 - 1
            if end_cap >= len(s["d"]):
                continue                                              # trade would not be complete yet
            if s["gap_cum"][end_cap] - s["gap_cum"][e - 14] > 0:
                skipped["gap"] += 1
                continue
            entry = s["o"][e]
            # scheduled open-exit for comm50
            open_exit = None
            if exit_rule == "comm50":
                for v in range(w + 1, len(g)):
                    if np.isnan(idx[v]):
                        continue
                    if (d == 1 and idx[v] <= 50) or (d == -1 and idx[v] >= 50):
                        j = sess_after[v]
                        open_exit = j if j <= end_cap else None
                        break
                    if sess_after[v] > end_cap:
                        break
            stop = None if stop_k is None else entry - d * stop_k * atr
            exit_px, exit_i, how = None, None, None
            last_full = None
            for i in range(e, end_cap + 1):
                if open_exit is not None and i == open_exit and i > e:
                    exit_px, exit_i, how = s["o"][i], i, "open"
                    break
                if stop is not None:
                    if d == 1 and s["l"][i] <= stop:
                        exit_px = min(s["o"][i], stop) if i > e else stop
                        exit_i, how = i, "stop"
                        break
                    if d == -1 and s["h"][i] >= stop:
                        exit_px = max(s["o"][i], stop) if i > e else stop
                        exit_i, how = i, "stop"
                        break
            if exit_px is None:
                exit_px, exit_i, how = s["c"][end_cap], end_cap, "close"
            # MFE / MAE (ATR) over the holding period
            lo_i, hi_i = e, exit_i if how != "open" else exit_i - 1
            if hi_i >= lo_i:
                hi = s["h"][lo_i:hi_i + 1].max()
                lo = s["l"][lo_i:hi_i + 1].min()
            else:
                hi = lo = entry
            fav = (hi - entry) / atr if d == 1 else (entry - lo) / atr
            adv = (entry - lo) / atr if d == 1 else (hi - entry) / atr
            if how == "stop":
                adv = min(adv, abs(entry - exit_px) / atr) if (d * (exit_px - entry)) < 0 else adv
            ret = d * (exit_px - entry) / atr
            trades.append(dict(market=ibkr, dir=d, signal=g["date"].iloc[w], entry_date=s["d"][e],
                               exit_date=s["d"][exit_i], hold=exit_i - e + (0 if how == "open" else 1),
                               ret=ret, mfe=max(fav, 0), mae=max(adv, 0), how=how, year=pd.Timestamp(s["d"][e]).year))
            free_from = exit_i if how == "open" else exit_i + 1
    return pd.DataFrame(trades), skipped


# ---------------------------------------------------------------- statistics
def cluster_stats(df):
    cl = df.groupby("signal")["ret"].agg(["sum", "count"])
    return cl["sum"].values, cl["count"].values


def boot_mean_ci(df):
    s, c = cluster_stats(df)
    k = len(s)
    idx = RNG.integers(0, k, size=(BOOT, k))
    m = s[idx].sum(1) / c[idx].sum(1)
    return np.percentile(m, [2.5, 97.5])


def max_dd(df):
    eq = df.sort_values(["exit_date", "entry_date"])["ret"].cumsum().values
    if len(eq) == 0:
        return np.nan
    peak = np.maximum.accumulate(np.r_[0, eq])[1:]
    return float((eq - peak).min())


def summarize(df):
    if len(df) == 0:
        return {}
    lo, hi = boot_mean_ci(df)
    return dict(n=len(df), mean=df["ret"].mean(), median=df["ret"].median(), win=(df["ret"] > 0).mean() * 100,
                hold=df["hold"].mean(), mfe=df["mfe"].mean(), mae=df["mae"].mean(), maxdd=max_dd(df),
                worst=df["ret"].min(), ci_lo=lo, ci_hi=hi, stop_pct=(df["how"] == "stop").mean() * 100)


def paired_diff(a, b):
    """Rule A minus rule B. Matched = same market, direction, signal week."""
    key = ["market", "dir", "signal"]
    m = a.merge(b, on=key, suffixes=("_a", "_b"))
    out = dict(n_matched=len(m), extra_a=len(a) - len(m), missing_vs_b=len(b) - len(m))
    if len(m):
        diff = m["ret_a"] - m["ret_b"]
        tmp = pd.DataFrame({"signal": m["signal"], "ret": diff})
        s, c = cluster_stats(tmp)
        k = len(s)
        bi = RNG.integers(0, k, size=(BOOT, k))
        bm = s[bi].sum(1) / c[bi].sum(1)
        out.update(matched_diff=diff.mean(), m_lo=np.percentile(bm, 2.5), m_hi=np.percentile(bm, 97.5),
                   m_p=min(1.0, 2 * min((bm <= 0).mean(), (bm >= 0).mean())))
    # all-trades difference of means, resampling signal weeks jointly
    weeks = np.union1d(a["signal"].unique(), b["signal"].unique())
    sa = a.groupby("signal")["ret"].agg(["sum", "count"]).reindex(weeks).fillna(0)
    sb = b.groupby("signal")["ret"].agg(["sum", "count"]).reindex(weeks).fillna(0)
    k = len(weeks)
    bi = RNG.integers(0, k, size=(BOOT, k))
    da = sa["sum"].values[bi].sum(1) / np.maximum(sa["count"].values[bi].sum(1), 1)
    db = sb["sum"].values[bi].sum(1) / np.maximum(sb["count"].values[bi].sum(1), 1)
    dd = da - db
    out.update(all_diff=a["ret"].mean() - b["ret"].mean(), a_lo=np.percentile(dd, 2.5), a_hi=np.percentile(dd, 97.5),
               a_p=min(1.0, 2 * min((dd <= 0).mean(), (dd >= 0).mean())))
    return out


def fmt_stop(k):
    return "none" if k is None else f"{k:g}"


def main():
    prices = {k: prep_series(v) for k, v in load_prices(PRICE_PATH).items()}
    markets = build_cot(COT_PATH)
    liquid = [k for k, g in markets.items() if (g["oi"].iloc[-1] >= MIN_OI)]
    miss = sorted({k.split('|')[0] for k in markets if PRICE_ROOTS.get(k.split('|')[0], k.split('|')[0]) not in prices})
    print(f"COT markets {len(markets)}; with price series {len(markets) - len(miss)}; no price series: {miss}")
    first = min(v['d'][0] for v in prices.values())
    last = max(v['d'][-1] for v in prices.values())
    print(f"price dates {first} to {last}")
    print("\n=== REPLICATION CHECK, 26-week, no stop (handoff: 227 trades, fixed42 +0.94 mean / +0.45 median, comm50 +0.91 / +0.67, 33 sessions)")
    for sub in ("all", "aligned"):
        for ex in ("fixed42", "comm50"):
            df, _ = simulate(26, ex, None, markets, prices, sub)
            print(f"subset={sub:8s} exit={ex:8s} n={len(df):5d} mean={df['ret'].mean():+.2f} median={df['ret'].median():+.2f} hold={df['hold'].mean():.1f}")
    results, runs = [], {}
    for w in WINDOWS:
        for ex in EXITS:
            for sk in STOPS:
                df, sk_info = simulate(w, ex, sk, markets, prices)
                runs[(w, ex, sk)] = df
                row = dict(window=w, exit=ex, stop=fmt_stop(sk), **summarize(df))
                results.append(row)
        print(f"window {w}: skipped counts (last config) {sk_info}", flush=True)
    res = pd.DataFrame(results)
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 500)
    cols = ["window", "exit", "stop", "n", "mean", "ci_lo", "ci_hi", "median", "win", "hold", "mfe", "mae", "maxdd",
            "worst", "stop_pct"]
    print("\n=== GRID (ATR units; ci = 95% week-cluster bootstrap for the mean; maxdd = cumulative ATR, trades by exit date)")
    print(res[cols].round(2).to_string(index=False))

    print("\n=== PAIRED DIFFERENCE vs fixed42 with the same window and stop (A minus B)")
    rows = []
    for w in WINDOWS:
        for sk in STOPS:
            b = runs[(w, "fixed42", sk)]
            for ex in ("comm50", "fixed21"):
                a = runs[(w, ex, sk)]
                rows.append(dict(window=w, stop=fmt_stop(sk), A=ex, **paired_diff(a, b)))
    pdx = pd.DataFrame(rows)
    print(pdx.round(3).to_string(index=False))

    print("\n=== comm50 vs fixed21 (matched), no stop")
    rows = []
    for w in WINDOWS:
        rows.append(dict(window=w, **paired_diff(runs[(w, "comm50", None)], runs[(w, "fixed21", None)])))
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    print("\n=== SUBPERIODS, no stop (mean / median / n by entry year half)")
    rows = []
    for w in WINDOWS:
        for ex in EXITS:
            df = runs[(w, ex, None)]
            for name, sub in (("2008-2016", df[df.year <= 2016]), ("2017-2026", df[df.year >= 2017]),
                              ("long", df[df.dir == 1]), ("short", df[df.dir == -1])):
                rows.append(dict(window=w, exit=ex, subset=name, n=len(sub), mean=sub["ret"].mean(),
                                 median=sub["ret"].median()))
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n=== comm50 exit reasons, no stop")
    for w in WINDOWS:
        df = runs[(w, "comm50", None)]
        print(w, df["how"].value_counts().to_dict(), "avg hold", round(df["hold"].mean(), 1))

    print("\n=== concentration: comm50 no stop, mean after dropping the 5 best trades / by market count")
    for w in WINDOWS:
        df = runs[(w, "comm50", None)].sort_values("ret")
        print(w, "mean", round(df["ret"].mean(), 2), "drop top5", round(df["ret"].iloc[:-5].mean(), 2),
              "markets", df["market"].nunique(), "top market share", round(df["market"].value_counts(normalize=True).iloc[0], 2))
    print("\nBenchmark: not applicable to futures ATR returns (stock SPY benchmark rule); benchmark unavailable.")
    print(f"Comparisons run: {len(res)} configurations; treat p-values as uncorrected for multiple testing.")


if __name__ == "__main__":
    main()
