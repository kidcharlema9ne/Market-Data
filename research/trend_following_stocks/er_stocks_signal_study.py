"""Stocks, long only: SIGNAL-LEVEL STUDY (Michael, 18 Nov 2026: "let's do 1 and 2"). Which facts about a signal, known on the trigger day, go with a better or worse trade?
Usage: python er_stocks_signal_study.py stock_prices.parquet OUT_DIR spy_prices.parquet [nasdaq_etfs.parquet]

Signal set = EVERY signal of the current rule (hand-off doc 17 Nov 2026), traded or not: common stocks, one series per company, $3M floor, 20-session efficiency ratio 0.50 with rising close, 20-session watch, trigger = first close 1.5 ATR
below the best high since the signal, strongest 20% by 126-session return, SPY above its 200-day, one position per stock at a time. Each signal is traded with the standard exits (buy next open, 4 ATR initial stop, 5 ATR trailing stop,
gap fills at the open, no time limit, 0.05 ATR a side) with NO account limit, so the 75% of signals the account skips are measured too. Outcome = result in ATR units, net of the 0.10 ATR round-trip cost, with the SPY move over the
same holds beside it (the benchmark rule in AGENTS.md). In-sample only (data through 2021-08-06); the sealed years are never read. Post hoc and PROVISIONAL.

PART 1 - one fact at a time. About 45 facts per signal (strength, smoothness, volatility, volume, news gaps, liquidity, the stock's own history, the market that day). For each: ten equal-count buckets (mean, median, trimmed mean without the
  top and bottom 1%, win rate, share of 5-ATR winners, SPY move beside it); the rank correlation with the outcome; the same rank correlation computed year by year (average, t-statistic, years with the same sign as the whole);
  top 30% minus bottom 30% of the fact and the number of years it was positive; the correlation measured WITHIN each month (stock facts only: removes the market's level, which is what matters when the account is full and has to choose),
  and a permutation benchmark: the biggest |t| the best of the stock facts reaches when the outcomes are shuffled within each month (how much a lucky winner looks like when there is nothing to find).
PART 2 - the ceiling. Walk-forward, test years 2006 to 2021: for each test year a model is trained on signals that had already EXITED before 1 January of that year (no look-ahead), then scores that year's signals. Two models: ridge
  regression and shallow boosted trees, both on within-month ranks of the stock facts, predicting the within-month winsorized outcome. Scored by the within-month top-fifth minus the month's average (ATR per trade), year by year, beside the
  same score for volume-surge ranking. Then the model's order is used as the ranking when the account is full (profit per year, Sharpe ratio, max drawdown, worst year, profit per year over drawdown, 2006 to Aug 2021), beside volume-surge
  ranking and the mean of 8 random picks on the same window.
PART 3 - the gates. All signals of the rule with the strength filter and the SPY condition switched off, by strength bucket and SPY state.
"""
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
from er_stocks import CAPITAL, END, EPOCH
from er_stocks_combined_er import q_long

warnings.filterwarnings("ignore", message="An input array is constant")
NPERM = 300
TEST_FIRST_YEAR = int(os.environ.get("TEST_FIRST_YEAR", 2006))
MIN_TRAIN = int(os.environ.get("MIN_TRAIN", 1500))


# ---------------------------------------------------------------- market and cross-section series (one value per session)
def market_series(ctx, live, spy_close, qqq=None):
    SEG, dropped, cal, (dates, _, _) = ctx
    m = len(cal)
    s = pd.Series(spy_close)
    out = {"spy_above_200d": (s / s.rolling(200, min_periods=200).mean() - 1).to_numpy(), "spy_return_20d": (s / s.shift(20) - 1).to_numpy(), "spy_return_60d": (s / s.shift(60) - 1).to_numpy(),
           "spy_volatility_20d": (s.pct_change().rolling(20, min_periods=20).std() * np.sqrt(252)).to_numpy(), "spy_below_20d_high": (s / s.rolling(20, min_periods=20).max() - 1).to_numpy()}
    if qqq is not None:
        q = pd.Series(qqq)
        out["nasdaq_minus_spy_60d"] = ((q / q.shift(60)) - (s / s.shift(60))).to_numpy()
    n_abv = np.zeros(m); n_el = np.zeros(m); sum_r = np.zeros(m); n_r = np.zeros(m); n_trig = np.zeros(m)
    for i in live:
        g = SEG[i]; c = g["c"]; ses = g["s"]
        ok = g["liq"] & ~g["spac"]
        ma = pd.Series(c).rolling(200, min_periods=200).mean().to_numpy()
        w = ok & np.isfinite(ma)
        np.add.at(n_el, ses[w], 1.0); np.add.at(n_abv, ses[w], (c[w] > ma[w]).astype(float))
        r = g["ret1"]; w2 = ok & np.isfinite(r) & (np.abs(r) < 1.0)
        np.add.at(sum_r, ses[w2], r[w2]); np.add.at(n_r, ses[w2], 1.0)
        for t, d in g["cand"]:
            if g["liq"][t] and not g["spac"][t]:
                n_trig[ses[t]] += 1
    with np.errstate(divide="ignore", invalid="ignore"):
        out["breadth_above_own_200d"] = np.where(n_el >= 30, n_abv / n_el, np.nan)
        ew = np.where(n_r >= 30, sum_r / n_r, 0.0)
    ewi = pd.Series(np.cumprod(1 + ew))
    out["small_stock_index_above_200d"] = (ewi / ewi.rolling(200, min_periods=200).mean() - 1).to_numpy()
    out["small_stock_index_return_60d"] = (ewi / ewi.shift(60) - 1).to_numpy()
    out["signals_triggered_today"] = n_trig
    return out


FACTS_STOCK = ["return_63d", "return_126d", "return_252d", "rank_63d", "rank_126d", "rank_252d", "return_per_volatility_126d", "trend_slope_times_fit_90d", "smoothness_126d", "up_day_share_126d", "worst_dip_126d",
               "below_52w_high", "above_own_200d", "er_at_signal", "run_up_20d_atr", "pullback_atr", "pullback_pct", "days_signal_to_trigger", "trigger_day_return", "trigger_day_gap", "trigger_day_close_position",
               "atr_pct_of_price", "atr_now_vs_50d_ago", "recent_range_vs_atr", "beta_120d", "residual_return_126d", "volume_surge_signal_20d", "volume_surge_signal_50d", "updown_volume_run_shares",
               "updown_volume_run_dollars", "volume_surge_trigger_20d", "updown_volume_trigger_shares", "log10_dollar_volume_15d", "log10_price", "biggest_gap_up_60d", "volume_surge_on_that_gap",
               "days_since_that_gap", "prior_signals_250d", "last_trade_result_atr", "days_since_last_exit"]
FACTS_MARKET = ["spy_above_200d", "spy_return_20d", "spy_return_60d", "spy_volatility_20d", "spy_below_20d_high", "nasdaq_minus_spy_60d", "breadth_above_own_200d", "small_stock_index_above_200d",
                "small_stock_index_return_60d", "signals_triggered_today"]


def seg_arrays(g, v, spy_close):
    c = g["c"]; n = len(c); cs = pd.Series(c)
    ret1 = np.r_[np.nan, c[1:] / c[:-1] - 1]
    sd126 = pd.Series(ret1).rolling(126, min_periods=100).std().to_numpy()
    absd = np.r_[np.nan, np.abs(np.diff(c))]
    path126 = pd.Series(absd).rolling(126, min_periods=126).sum().to_numpy()
    up = np.r_[np.nan, (np.diff(c) > 0).astype(float)]
    upsh = pd.Series(up).rolling(126, min_periods=126).mean().to_numpy()
    hi252 = cs.rolling(252, min_periods=200).max().to_numpy()
    ma200 = cs.rolling(200, min_periods=200).mean().to_numpy()
    sc = spy_close[g["s"]]
    spy_r = np.r_[np.nan, sc[1:] / sc[:-1] - 1]
    return dict(ret1=ret1, sd126=sd126, path126=path126, upsh=upsh, hi252=hi252, ma200=ma200, spy_r=spy_r, spy_c=sc)


def clenow(c, t, L=90):
    if t < L:
        return np.nan
    y = np.log(c[t - L + 1:t + 1]); x = np.arange(L, dtype=float)
    xm, ym = x.mean(), y.mean(); sxx = ((x - xm) ** 2).sum(); sxy = ((x - xm) * (y - ym)).sum()
    slope = sxy / sxx; ss_tot = ((y - ym) ** 2).sum()
    if ss_tot <= 0:
        return np.nan
    r2 = (sxy ** 2) / (sxx * ss_tot)
    return (np.exp(slope * 252) - 1.0) * r2


def stock_facts(ctx, R, E20, FEAT, ranks, VOLS, spy_close, mkt, dates):
    SEG, dropped, cal, _ = ctx
    sym, trig = I1.trade_rows(SEG, R)
    n = len(R["d"]); cols = {k: np.full(n, np.nan) for k in FACTS_STOCK}
    by_seg = {}
    for k in range(n):
        by_seg.setdefault(int(sym[k]), []).append(k)
    for i, ks in by_seg.items():
        g = SEG[i]; c, o, h, l, atr, s = g["c"], g["o"], g["h"], g["l"], g["atr"], g["s"]; v = np.asarray(VOLS[i], float)
        A = seg_arrays(g, v, spy_close)
        sm = NV.sig_map(g, q_long(g, *E20[i], 0.50))
        er20 = E20[i][0]
        cand_t = np.array([t for t, _ in g["cand"]])
        dv = c * v
        prev = []                                          # (exit row, result) of this segment's earlier signals in the study
        ksort = sorted(ks, key=lambda q: trig[q])
        exit_rows = {q: int(np.searchsorted(s, R["sess_x"][q])) for q in ksort}
        for q in ksort:
            t = int(trig[q]); st = sm[t]; f = {}
            for L in (63, 126, 252):
                f[f"return_{L}d"] = c[t] / c[t - L] - 1 if t >= L else np.nan
                f[f"rank_{L}d"] = ranks[L][i][t] if L != 126 else g["rank"][t]
            f["return_per_volatility_126d"] = f["return_126d"] / (A["sd126"][t] * np.sqrt(126)) if np.isfinite(A["sd126"][t]) and A["sd126"][t] > 0 else np.nan
            f["trend_slope_times_fit_90d"] = clenow(c, t)
            f["smoothness_126d"] = abs(c[t] - c[t - 126]) / A["path126"][t] if t >= 126 and A["path126"][t] > 0 else np.nan
            f["up_day_share_126d"] = A["upsh"][t]
            if t >= 126:
                w = c[t - 125:t + 1]; f["worst_dip_126d"] = (w / np.maximum.accumulate(w) - 1).min()
            f["below_52w_high"] = c[t] / A["hi252"][t] - 1 if np.isfinite(A["hi252"][t]) else np.nan
            f["above_own_200d"] = c[t] / A["ma200"][t] - 1 if np.isfinite(A["ma200"][t]) else np.nan
            f["er_at_signal"] = er20[st]
            f["run_up_20d_atr"] = (c[st] - c[st - 20]) / atr[st] if st >= 20 else np.nan
            peak = h[st:t + 1].max()
            f["pullback_atr"] = (peak - c[t]) / atr[t]; f["pullback_pct"] = (peak - c[t]) / peak; f["days_signal_to_trigger"] = t - st
            f["trigger_day_return"] = c[t] / c[t - 1] - 1; f["trigger_day_gap"] = o[t] / c[t - 1] - 1
            f["trigger_day_close_position"] = (c[t] - l[t]) / (h[t] - l[t]) if h[t] > l[t] else np.nan
            f["atr_pct_of_price"] = atr[t] / c[t]
            f["atr_now_vs_50d_ago"] = atr[t] / atr[t - 50] if t >= 50 and atr[t - 50] > 0 else np.nan
            f["recent_range_vs_atr"] = (h[t - 4:t + 1] - l[t - 4:t + 1]).mean() / atr[t] if t >= 4 else np.nan
            if t >= 120:
                x = A["ret1"][t - 119:t + 1]; y = A["spy_r"][t - 119:t + 1]; ok = np.isfinite(x) & np.isfinite(y)
                if ok.sum() > 80 and np.var(y[ok]) > 0:
                    b = np.cov(x[ok], y[ok])[0, 1] / np.var(y[ok], ddof=1); f["beta_120d"] = b
                    if t >= 126 and np.isfinite(A["spy_c"][t]) and np.isfinite(A["spy_c"][t - 126]):
                        f["residual_return_126d"] = f["return_126d"] - b * (A["spy_c"][t] / A["spy_c"][t - 126] - 1)
            F = FEAT[(i, t)]
            f["volume_surge_signal_20d"] = F["s20_sig"]; f["volume_surge_signal_50d"] = F["s50_sig"]; f["updown_volume_run_shares"] = F["ud_sig"]; f["updown_volume_run_dollars"] = F["udd_sig"]
            f["volume_surge_trigger_20d"] = F["s20_trg"]; f["updown_volume_trigger_shares"] = F["ud_trg"]
            adv = dv[t - 14:t + 1].mean() if t >= 14 else np.nan
            f["log10_dollar_volume_15d"] = np.log10(adv) if adv > 0 else np.nan; f["log10_price"] = np.log10(c[t])
            if t >= 60:
                gp = o[t - 59:t + 1] / c[t - 60:t] - 1.0; j = int(np.argmax(gp)); kk = t - 59 + j
                f["biggest_gap_up_60d"] = gp[j]; f["days_since_that_gap"] = t - kk
                m20 = v[kk - 20:kk].mean() if kk >= 20 else np.nan
                f["volume_surge_on_that_gap"] = v[kk] / m20 if m20 and m20 > 0 else np.nan
            f["prior_signals_250d"] = float(((cand_t < t) & (cand_t >= t - 250)).sum())
            pv = [(xr, rs) for xr, rs in prev if xr < t]
            if pv:
                xr, rs = max(pv, key=lambda z: z[0]); f["last_trade_result_atr"] = rs; f["days_since_last_exit"] = t - xr
            prev.append((exit_rows[q], R["res"][q]))
            for kx, vx in f.items():
                cols[kx][q] = vx
    D = pd.DataFrame(cols)
    ts = np.array([SEG[int(sym[k])]["s"][int(trig[k])] for k in range(n)])
    for name, arr in mkt.items():
        D[name] = arr[ts]
    D["sess_trigger"] = ts
    return D


def trimmed_mean(x, p=0.01):
    if len(x) < 20:
        return np.nan
    lo, hi = np.quantile(x, [p, 1 - p]); y = x[(x >= lo) & (x <= hi)]
    return y.mean() if len(y) else np.nan


# ---------------------------------------------------------------- part 1
def one_fact_tables(D, facts, ftype):
    res = D["res"].to_numpy(); spy = D["spy_atr"].to_numpy(); yr = D["year"].to_numpy(); month = D["month_id"].to_numpy()
    resw = np.clip(res, *np.quantile(res, [0.01, 0.99]))
    bucket_rows, sum_rows = [], []
    for fx in facts:
        x = D[fx].to_numpy(float); ok = np.isfinite(x)
        if ok.sum() < 500:
            continue
        xs = pd.Series(x[ok]); b = pd.qcut(xs.rank(method="first"), 10, labels=False).to_numpy()
        means = []
        for q in range(10):
            sel = np.flatnonzero(ok)[b == q]
            r = res[sel]; means.append(r.mean())
            bucket_rows.append({"fact": fx, "bucket (1 = lowest values)": q + 1, "signals": len(sel), "fact low": float(x[sel].min()), "fact high": float(x[sel].max()), "mean ATR": r.mean(), "median ATR": np.median(r),
                                "trimmed mean ATR (1% each end)": trimmed_mean(r), "win rate %": (r > 0).mean() * 100, "5-ATR winners %": (r >= 5).mean() * 100, "SPY move over the same holds (ATR)": spy[sel].mean(),
                                "excess over SPY (ATR)": r.mean() - spy[sel].mean()})
        rho = spearmanr(x[ok], resw[ok])[0]
        mono = spearmanr(np.arange(10), means)[0]
        yrs, ics, spreads = [], [], []
        for y in np.unique(yr):
            m = ok & (yr == y)
            if m.sum() < 60:
                continue
            ics.append(spearmanr(x[m], resw[m])[0]); yrs.append(y)
            lo, hi = np.quantile(x[m], [0.3, 0.7]); a = res[m & (x >= hi)]; bb = res[m & (x <= lo)]
            if len(a) >= 10 and len(bb) >= 10:
                spreads.append(a.mean() - bb.mean())
        ics = np.array(ics); spreads = np.array(spreads)
        t_year = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics))) if len(ics) > 2 and ics.std(ddof=1) > 0 else np.nan
        same = int((np.sign(ics) == np.sign(rho)).sum())
        lo, hi = np.quantile(x[ok], [0.3, 0.7]); top = res[ok & (x >= hi)]; bot = res[ok & (x <= lo)]
        # month-level correlation (one point per month: monthly average of the fact and of the outcome)
        mm = pd.DataFrame({"x": x[ok], "r": resw[ok], "m": month[ok]}).groupby("m").agg(x=("x", "mean"), r=("r", "mean"), n=("x", "size")); mm = mm[mm.n >= 5]
        rm = spearmanr(mm.x, mm.r)[0] if len(mm) > 12 else np.nan
        tm = rm * np.sqrt((len(mm) - 2) / max(1e-9, 1 - rm ** 2)) if np.isfinite(rm) else np.nan
        sum_rows.append({"fact": fx, "type": ftype, "signals with a value": int(ok.sum()), "rank correlation with outcome": rho, "year-by-year correlation (average)": ics.mean() if len(ics) else np.nan,
                         "year-by-year t-statistic": t_year, "years with the same sign": f"{same} of {len(ics)}", "top 30% minus bottom 30% (ATR)": top.mean() - bot.mean(),
                         "years top 30% beat bottom 30%": f"{int((spreads > 0).sum())} of {len(spreads)}", "ten-bucket staircase (rank corr of bucket means)": mono, "month-level correlation": rm, "month-level t-statistic": tm})
    return pd.DataFrame(bucket_rows), pd.DataFrame(sum_rows)


def within_month_ic(D, facts, outcome_rank=None, perm=0, seed=1):
    """Fama-MacBeth style: rank correlation inside each month, then average and t-statistic across months; optional permutation of outcomes inside each month."""
    rng = np.random.default_rng(seed)
    res = D["res"].to_numpy(); resw = np.clip(res, *np.quantile(res, [0.01, 0.99]))
    months = D["month_id"].to_numpy(); X = D[facts].to_numpy(float)
    Xs, Ys = [], []
    for mth in np.unique(months):
        idx = np.flatnonzero(months == mth)
        if len(idx) < 20:
            continue
        xr = pd.DataFrame(X[idx]).rank(pct=True).to_numpy()
        mu = np.nanmean(xr, axis=0); sd = np.nanstd(xr, axis=0); sd[sd == 0] = np.nan
        z = (xr - mu) / sd; z = np.where(np.isfinite(z), z, 0.0)
        yr_ = pd.Series(resw[idx]).rank(pct=True).to_numpy(); yz = (yr_ - yr_.mean()) / (yr_.std() if yr_.std() > 0 else 1.0)
        Xs.append(z); Ys.append(yz)
    nm = len(Xs)
    def tstat(ics):
        return ics.mean(0) / (ics.std(0, ddof=1) / np.sqrt(len(ics)) + 1e-12)
    ics = np.array([(Xs[k].T @ Ys[k]) / len(Ys[k]) for k in range(nm)])
    out = pd.DataFrame({"fact": facts, "within-month correlation (average)": ics.mean(0), "within-month t-statistic": tstat(ics), "months": nm, "months positive %": (ics > 0).mean(0) * 100})
    null_max = []
    for p in range(perm):
        icp = np.array([(Xs[k].T @ rng.permutation(Ys[k])) / len(Ys[k]) for k in range(nm)])
        null_max.append(np.abs(tstat(icp)).max())
    return out, np.array(null_max)


# ---------------------------------------------------------------- part 2
def month_rank_matrix(D, facts):
    months = D["month_id"].to_numpy(); out = np.full((len(D), len(facts)), np.nan)
    X = D[facts]
    for mth in np.unique(months):
        idx = np.flatnonzero(months == mth)
        out[idx] = X.iloc[idx].rank(pct=True).to_numpy() - 0.5
    return out


def month_demeaned_target(D):
    res = D["res"].to_numpy(); resw = np.clip(res, *np.quantile(res, [0.01, 0.99]))
    return resw - pd.Series(resw).groupby(D["month_id"].to_numpy()).transform("mean").to_numpy()


def walk_forward(D, facts, models):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    Xr = month_rank_matrix(D, facts); y = month_demeaned_target(D)
    entry = D["entry_date"].to_numpy(); exit_ = D["exit_date"].to_numpy(); yr = D["year"].to_numpy()
    pred = {m: np.full(len(D), np.nan) for m in models}; log = []
    for Y in range(TEST_FIRST_YEAR, 2022):
        cut = np.datetime64(f"{Y}-01-01")
        tr = np.flatnonzero(exit_ < cut); te = np.flatnonzero(yr == Y)
        if len(te) < 30 or len(tr) < MIN_TRAIN:
            continue
        Xtr = np.where(np.isfinite(Xr[tr]), Xr[tr], 0.0); Xte = np.where(np.isfinite(Xr[te]), Xr[te], 0.0)
        if "ridge" in models:
            m = Ridge(alpha=2000.0).fit(Xtr, y[tr]); pred["ridge"][te] = m.predict(Xte)
        if "boosted trees" in models:
            m = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=300, l2_regularization=10.0, random_state=0).fit(Xr[tr], y[tr]); pred["boosted trees"][te] = m.predict(Xr[te])
        log.append((Y, len(tr), len(te)))
    return pred, log


def selection_score(D, score, name):
    """Within each month: mean outcome of the top fifth by score minus the month's average outcome, and the bottom fifth. Returns per-year table."""
    res = D["res"].to_numpy(); months = D["month_id"].to_numpy(); yr = D["year"].to_numpy()
    rows = []
    for mth in np.unique(months):
        idx = np.flatnonzero((months == mth) & np.isfinite(score))
        if len(idx) < 10:
            continue
        sc = score[idx]; r = res[idx]; k = max(1, int(round(len(idx) * 0.2)))
        o = np.argsort(sc); bot = r[o[:k]].mean(); top = r[o[-k:]].mean()
        rows.append({"year": int(yr[idx[0]]), "month": mth, "n": len(idx), "top fifth minus average": top - r.mean(), "bottom fifth minus average": bot - r.mean(),
                     "ic": spearmanr(sc, r)[0] if len(idx) > 5 else np.nan})
    M_ = pd.DataFrame(rows)
    if M_.empty:
        return M_, {}
    Y_ = M_.groupby("year").apply(lambda d: pd.Series({"signals": int(d.n.sum()), "top fifth minus average (ATR)": np.average(d["top fifth minus average"], weights=d.n), "bottom fifth minus average (ATR)": np.average(d["bottom fifth minus average"], weights=d.n)}), include_groups=False)
    summ = {"ranking": name, "top fifth minus average (ATR per trade)": float(np.average(M_["top fifth minus average"], weights=M_.n)), "bottom fifth minus average (ATR per trade)": float(np.average(M_["bottom fifth minus average"], weights=M_.n)),
            "average within-month correlation": float(M_.ic.mean()), "years top fifth beat average": f"{int((Y_.iloc[:, 1] > 0).sum())} of {len(Y_)}", "test-year signals": int(M_.n.sum())}
    return Y_, summ


def account_rows(R, key, cal, dates, label, lo, hi):
    rows = []
    for cap in (2.0, 1.0):
        P = MI.portfolio_gen(R, cal, cap, key)
        st, _ = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
        if not st:
            continue
        dd = abs(st["max drawdown %"])
        rows.append({"ranking when the account is full": label, "cap %": int(cap * 100), "profit per year %": st["profit per year %"], "Sharpe ratio": st["Sharpe ratio"], "max drawdown %": st["max drawdown %"],
                     "profit per year / drawdown": st["profit per year %"] / dd if dd else np.nan, "worst year %": st["worst year %"], "trades taken": int(P["taken"].sum())})
    return rows


def main():
    prices_path, out_dir, spy_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    qqq_path = sys.argv[4] if len(sys.argv) > 4 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 400); pd.set_option("display.max_colwidth", 70)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    R = MI.gen(ctx, mk200)
    n = len(R["d"]); print(f"{n:,} signals in the study set", flush=True)
    FEAT = NV.build_features(ctx, E20)
    qqq = NV.qqq_series(qqq_path, cal) if qqq_path else None
    mkt = market_series(ctx, live, spy_close, qqq)
    ranks = {63: MI.make_rank(ctx, MI.ret_score(63)), 252: MI.make_rank(ctx, MI.ret_score(252))}
    D = stock_facts(ctx, R, E20, FEAT, ranks, MI.VOLS, spy_close, mkt, dates)
    ed = dates[R["sess_e"]]; xd = dates[R["sess_x"]]
    D["res"] = R["res"]; D["held"] = R["held"]; D["how"] = R["how"]; D["entry_date"] = ed.to_numpy(); D["exit_date"] = xd.to_numpy(); D["year"] = ed.year.to_numpy()
    D["month_id"] = (ed.year * 100 + ed.month).to_numpy(); D["month_of_year"] = ed.month.to_numpy()
    D["spy_atr"] = (spy_close[R["sess_x"]] / spy_close[R["sess_e"]] - 1.0) * R["px_e"] / R["a0"]
    D["stock"] = [names[int(i)] for i in R["sym"]]
    D.to_csv(out_dir / "signal_rows.csv.gz", index=False)
    print(f"average result {D.res.mean():+.3f} ATR per signal (median {D.res.median():+.3f}); SPY over the same holds {D.spy_atr.mean():+.3f} ATR; win rate {(D.res > 0).mean()*100:.1f}%; 5-ATR winners {(D.res >= 5).mean()*100:.1f}%; "
          f"the top 1% of signals hold {D.res.nlargest(max(1, n // 100)).sum() / D.res[D.res > 0].sum() * 100:.0f}% of all gains", flush=True)

    # ---- part 1
    facts_all = FACTS_STOCK + [f for f in FACTS_MARKET if f in D.columns]
    B1, S1 = one_fact_tables(D, FACTS_STOCK, "stock"); B2, S2 = one_fact_tables(D, [f for f in FACTS_MARKET if f in D.columns], "market")
    S = pd.concat([S1, S2], ignore_index=True); BK = pd.concat([B1, B2], ignore_index=True)
    ic, null_max = within_month_ic(D, FACTS_STOCK, perm=NPERM)
    S = S.merge(ic[["fact", "within-month correlation (average)", "within-month t-statistic", "months positive %"]], on="fact", how="left")
    thr = float(np.quantile(null_max, 0.95)) if len(null_max) else np.nan
    S["stock fact beats the shuffle benchmark"] = np.where((S.type == "stock") & (S["within-month t-statistic"].abs() > thr), "yes", np.where(S.type == "stock", "no", "n/a"))
    S["abs t"] = S["within-month t-statistic"].abs().fillna(S["month-level t-statistic"].abs()); S = S.sort_values("abs t", ascending=False).drop(columns="abs t")
    S.round(4).to_csv(out_dir / "part1_fact_summary.csv", index=False); BK.round(4).to_csv(out_dir / "part1_fact_buckets.csv", index=False)
    print(f"\n==== PART 1 | one fact at a time | {n:,} signals | shuffle benchmark: the best of the {len(FACTS_STOCK)} stock facts reaches a within-month |t| of {thr:.2f} or more in 5% of shuffles (median {np.median(null_max):.2f}) ====")
    print(S.round(3).to_string(index=False))
    top_facts = S.head(12).fact.tolist()
    print("\n==== ten-bucket tables for the 12 facts at the top of the list (mean ATR, median ATR, win rate %, 5-ATR winners %, SPY same-hold ATR, excess over SPY) ====")
    for fx in top_facts:
        b = BK[BK.fact == fx]
        print(f"\n-- {fx}")
        print(b[["bucket (1 = lowest values)", "signals", "fact low", "fact high", "mean ATR", "median ATR", "trimmed mean ATR (1% each end)", "win rate %", "5-ATR winners %", "SPY move over the same holds (ATR)", "excess over SPY (ATR)"]].round(3).to_string(index=False))

    # ---- part 2
    models = ["ridge", "boosted trees"]
    pred, log = walk_forward(D, FACTS_STOCK, models)
    print("\n==== PART 2 | walk-forward ceiling | test years and training sizes (signals that had exited before 1 January) ====")
    print(" ".join(f"{y}:{a}/{b}" for y, a, b in log))
    summ, yearly = [], {}
    base_score = -(-D["volume_surge_signal_20d"].to_numpy())          # bigger surge = higher score
    test_mask = (D["year"].to_numpy() >= TEST_FIRST_YEAR) & np.isfinite(pred["ridge"])
    Dt = D[test_mask].reset_index(drop=True)
    for nm, sc in [("volume surge on the signal day (current baseline ranking)", base_score[test_mask])] + [(f"{m} (walk-forward)", pred[m][test_mask]) for m in models]:
        Y_, sm = selection_score(Dt, sc, nm)
        yearly[nm] = Y_; summ.append(sm)
    SM = pd.DataFrame(summ)
    print("\nWithin-month selection value on the test years (ATR per trade, net of cost; random choice = 0 by construction):")
    print(SM.round(3).to_string(index=False))
    SM.round(4).to_csv(out_dir / "part2_selection_value.csv", index=False)
    YR = pd.concat({k: v["top fifth minus average (ATR)"] for k, v in yearly.items()}, axis=1)
    print("\nTop fifth minus month average, by test year (ATR per trade):"); print(YR.round(3).to_string())
    YR.round(4).to_csv(out_dir / "part2_selection_value_by_year.csv")
    # account level with the model's order as the ranking
    lo = pd.Timestamp(f"{TEST_FIRST_YEAR}-01-01"); rows = []
    vs = -np.where(np.isfinite(D["volume_surge_signal_20d"]), D["volume_surge_signal_20d"], -1e9)
    tiny = np.random.default_rng(20261118).random(n) * 1e-9
    rows += account_rows(R, vs + tiny, cal, dates, "volume surge on the signal day (current baseline)", lo, END)
    for m in models:
        key = np.where(np.isfinite(pred[m]), -pred[m], vs) + tiny           # years before the first test year keep the volume-surge order
        rows += account_rows(R, key, cal, dates, f"{m}, walk-forward", lo, END)
    rr = []
    for sd in range(MI.KSEEDS):
        rr += account_rows(R, np.random.default_rng(1000 + sd).random(n), cal, dates, "random pick", lo, END)
    RR = pd.DataFrame(rr).groupby(["ranking when the account is full", "cap %"], as_index=False).mean(numeric_only=True)
    A = pd.concat([pd.DataFrame(rows), RR], ignore_index=True)
    A["ranking when the account is full"] = A["ranking when the account is full"].replace({"random pick": "random pick (mean of 8)"})
    A.round(3).to_csv(out_dir / "part2_account_2006_2021.csv", index=False)
    print(f"\n==== PART 2 | account level, {lo.date()} to {END.date()} | ranking used when the account is full ====")
    print(A.round(2).to_string(index=False))

    # ---- part 3 : the gates (all signals of the rule with the strength filter and the SPY condition off)
    Rall = MI.gen(ctx, np.ones(len(cal), bool), top=1.0)
    sa, ta = I1.trade_rows(SEG, Rall)
    rk = Rall["rank"]; spyok = np.array([mk200[SEG[int(sa[k])]["s"][int(ta[k])]] for k in range(len(sa))]); dist = np.array([mkt["spy_above_200d"][SEG[int(sa[k])]["s"][int(ta[k])]] for k in range(len(sa))])
    bm = (spy_close[Rall["sess_x"]] / spy_close[Rall["sess_e"]] - 1.0) * Rall["px_e"] / Rall["a0"]
    G = pd.DataFrame({"res": Rall["res"], "spy_atr": bm, "rank": rk, "spy_ok": spyok, "dist": dist})
    G["strength bucket"] = pd.cut(G["rank"], [0, 0.5, 0.8, 0.9, 1.0001], labels=["bottom half", "50th to 80th", "80th to 90th (in the rule)", "top 10% (in the rule)"], include_lowest=True)
    G["SPY condition"] = np.where(G.spy_ok, "SPY above 200-day (in the rule)", "SPY below 200-day (switched off)")
    T = G.groupby(["SPY condition", "strength bucket"], observed=True).agg(signals=("res", "size"), **{"mean ATR": ("res", "mean"), "median ATR": ("res", "median"), "win rate %": ("res", lambda x: (x > 0).mean() * 100),
                                                                                                          "5-ATR winners %": ("res", lambda x: (x >= 5).mean() * 100), "SPY same-hold ATR": ("spy_atr", "mean")}).reset_index()
    T["excess over SPY (ATR)"] = T["mean ATR"] - T["SPY same-hold ATR"]
    T.round(3).to_csv(out_dir / "part3_gates.csv", index=False)
    print(f"\n==== PART 3 | all {len(G):,} signals with the strength filter and SPY condition off ====")
    print(T.round(3).to_string(index=False))
    off = G[~G.spy_ok].copy(); off["SPY distance below 200-day"] = pd.cut(off["dist"], [-1, -0.10, -0.05, -0.02, 0.0], labels=["more than 10% below", "5 to 10% below", "2 to 5% below", "0 to 2% below"])
    T2 = off[off["rank"] >= 0.8].groupby("SPY distance below 200-day", observed=True).agg(signals=("res", "size"), **{"mean ATR": ("res", "mean"), "median ATR": ("res", "median"), "win rate %": ("res", lambda x: (x > 0).mean() * 100), "SPY same-hold ATR": ("spy_atr", "mean")}).reset_index()
    print("\nSignals in the strongest 20% while SPY is below its 200-day, by how far below:"); print(T2.round(3).to_string(index=False)); T2.round(3).to_csv(out_dir / "part3_gate_off_distance.csv", index=False)
    print("done")


if __name__ == "__main__":
    main()
