"""Stocks, long only: the system COMPOUNDED and TAXED, against buy and hold QQQ (Michael, 19 Nov 2026).
Usage: python er_stocks_compound_tax.py stock_prices.parquet OUT_DIR spy_prices.parquet nasdaq_etfs.parquet

What this adds to the project baseline (volume-surge ranking when the account is full, 1.5 ATR pullback, 4 ATR initial and 5 ATR trailing stop, SPY above its 200-day, strongest 20% by 126-session return, $3M floor,
0.10% of the account per ATR, cost 0.10 ATR round trip, cap 200% and 100%): the baseline sizes every trade off a FIXED $300,000. Here the account COMPOUNDS.
  continuous      each new position is sized from the account's value at entry (closed trades + open marks - tax paid out), and the cap is a share of that value.
  annual reset    the sizing base is the account value at the first entry of each calendar year (steps up once a year); the cap is still a share of current value.
  continuous + 2% volume limit   as continuous, but a position is at most 2% of the stock's 15-day average dollar volume (a capacity limit; matters once the account is large).
  fixed           the project baseline (reference; reproduced exactly as a self-check).
TAXES (single filer, New Jersey resident; "tax on" runs): at the last session of each calendar year the tax on that year's REALISED gains is taken out of the account (the account sells stock / uses cash to pay it).
  Holding period: more than 365 calendar days between entry and exit date = long-term (federal 0/15/20%); otherwise short-term (federal ordinary rates). Open positions are untaxed until sold (the sample ends with all positions closed).
  Federal: 2026 single brackets and long-term thresholds, indexed by INFL a year from the first year (the backtest year 2000 stands for the first year of the real account); $30,000 of other taxable income (also indexed); gains stack on top.
  Capital losses: net ST/LT netting, $3,000 a year against ordinary income, the rest carried forward by character. 3.8% net investment income tax above $200,000 MAGI (not indexed).
  New Jersey: gains are ordinary income at the NJ single schedule (not indexed), $1,000 exemption, a net loss for the year counts as zero and is NOT carried forward.
  Tax charged = tax WITH the trading result minus tax on the other income alone.
  NOT modelled: wash-sale rules, state/local deductions, Social Security taxation, estimated-payment timing (tax is paid on the last session of the year), tax on interest or dividends, margin-interest deductibility.
BENCHMARKS: QQQ and SPY bought on the first session and sold on the last, price only (no dividends), $300,000, gain taxed once at the end as a long-term gain with the same rules.
Sensitivities on the main case: other income $50,000; brackets not indexed.
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
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
import er_stocks_spy_buffer as SB
import er_stocks_start_years as SY
import er_stocks_throttle_realism as TR
from er_stocks import CAPITAL, END, EPOCH

KSEEDS = MI.KSEEDS
BASE_COST = B.COST_RT
Y0 = 2000
BORROW = 0.04
# ---------------------------------------------------------------- tax rules (single filer)
FED = [(12400, 0.10), (50400, 0.12), (105700, 0.22), (201775, 0.24), (256225, 0.32), (640600, 0.35), (np.inf, 0.37)]   # 2026, taxable income upper bounds
LT_ZERO_TOP, LT_FIFTEEN_TOP = 49450.0, 545500.0                                                                       # 2026 long-term gain thresholds, single
NJ = [(20000, 0.014), (35000, 0.0175), (40000, 0.035), (75000, 0.05525), (500000, 0.0637), (1000000, 0.0897), (np.inf, 0.1075)]
NJ_EXEMPT = 1000.0
NIIT_RATE, NIIT_THRESHOLD, LOSS_LIMIT = 0.038, 200000.0, 3000.0


def bracket_tax(x, table, scale=1.0):
    tax = 0.0; lo = 0.0
    for ub, r in table:
        hi = ub * scale
        if x > lo:
            tax += (min(x, hi) - lo) * r
        lo = hi
        if x <= hi:
            break
    return tax


class TaxState:
    """Carries unused capital losses from year to year (federal) and returns the extra tax caused by the year's realised gains."""

    def __init__(self, other0=30000.0, infl=0.025):
        self.other0, self.infl = other0, infl
        self.cf_st = 0.0; self.cf_lt = 0.0

    def has_carry(self):
        return self.cf_st > 0 or self.cf_lt > 0

    def year(self, yidx, st, lt):
        f = (1.0 + self.infl) ** yidx
        other = self.other0 * f
        st_net = st - self.cf_st; lt_net = lt - self.cf_lt
        ord_gain = pref = 0.0; loss_st = loss_lt = 0.0
        if st_net >= 0 and lt_net >= 0:
            ord_gain, pref = st_net, lt_net
        elif st_net < 0 and lt_net >= 0:
            net = st_net + lt_net
            if net >= 0:
                pref = net
            else:
                loss_st = -net
        elif st_net >= 0 and lt_net < 0:
            net = st_net + lt_net
            if net >= 0:
                ord_gain = net
            else:
                loss_lt = -net
        else:
            loss_st, loss_lt = -st_net, -lt_net
        ded = min(LOSS_LIMIT, loss_st + loss_lt)
        d_st = min(ded, loss_st); d_lt = ded - d_st
        self.cf_st = loss_st - d_st; self.cf_lt = loss_lt - d_lt
        ordinary = max(0.0, other + ord_gain - ded)
        fed_ord = bracket_tax(ordinary, FED, f)
        c0, c15 = LT_ZERO_TOP * f, LT_FIFTEEN_TOP * f
        amt0 = max(0.0, min(pref, c0 - ordinary)); rest = pref - amt0
        amt15 = min(rest, max(0.0, c15 - max(ordinary, c0))); amt20 = rest - amt15
        fed_pref = 0.15 * amt15 + 0.20 * amt20
        magi = other + ord_gain + pref - ded
        niit = NIIT_RATE * min(ord_gain + pref, max(0.0, magi - NIIT_THRESHOLD))
        fed_base = bracket_tax(other, FED, f)
        nj_gain = max(0.0, st + lt)
        nj_with = bracket_tax(max(0.0, other + nj_gain - NJ_EXEMPT), NJ); nj_base = bracket_tax(max(0.0, other - NJ_EXEMPT), NJ)
        fed = fed_ord + fed_pref - fed_base; nj = nj_with - nj_base
        total = fed + niit + nj
        return total, dict(year_index=yidx, realised_short_term=st, realised_long_term=lt, net_ordinary_gain=ord_gain, net_long_term_gain=pref, loss_deduction=ded,
                           federal=fed, niit=niit, new_jersey=nj, total_tax=total, loss_carried_short=self.cf_st, loss_carried_long=self.cf_lt)


def selftest_tax():
    t, p = TaxState().year(0, 10000.0, 0.0)           # $10,000 short-term on $30,000 other income: 12% federal + NJ 1.75% on the first 5,000 up to 35k... computed below
    nj = bracket_tax(39000.0, NJ) - bracket_tax(29000.0, NJ)
    assert abs(p["federal"] - 1200.0) < 1e-6 and abs(p["new_jersey"] - nj) < 1e-6 and abs(nj - 245.0) < 1e-6, p
    t, p = TaxState().year(0, 0.0, 10000.0)           # long-term: 0% federal (inside the 0% band), NJ same as above
    assert abs(p["federal"]) < 1e-6 and abs(p["new_jersey"] - 245.0) < 1e-6, p
    t, p = TaxState().year(0, 0.0, 100000.0)          # 49,450 - 30,000 = 19,450 at 0%, the rest at 15%
    assert abs(p["federal"] - 0.15 * (100000 - 19450)) < 1e-6, p
    s = TaxState(); t, p = s.year(0, -20000.0, 0.0)   # loss: 3,000 deducted from income that sits in the 12% band (360 saved), 17,000 carried; NJ counts zero
    assert abs(p["federal"] + 360.0) < 1e-6 and abs(s.cf_st - 17000.0) < 1e-6 and abs(p["new_jersey"]) < 1e-6, p
    t, p = s.year(1, 25000.0, 0.0)                    # next year the carried loss is used against the gain
    assert abs(p["net_ordinary_gain"] - 8000.0) < 1e-6 and s.cf_st == 0.0, p
    t, p = TaxState(other0=0.0, infl=0.0).year(0, 0.0, 1_000_000.0)   # high earner: 3.8% NIIT on 1,000,000 - 200,000
    assert abs(p["niit"] - 0.038 * 800000.0) < 1e-6, p
    print("tax self-test passed", flush=True)


# ---------------------------------------------------------------- the compounding account
def account_scaled(R, cal, dates, cap, key, mode="continuous", tax=None, borrow=0.0, adv_frac=None, cost_rt=None, y0=Y0):
    """mode: 'fixed' (project baseline), 'continuous' or 'annual'. tax: a TaxState (tax paid out of the account at each year's last session) or None. borrow: yearly charge on position value above the account value."""
    cost_rt = BASE_COST if cost_rt is None else cost_rt
    n = len(R["d"]); m = len(cal)
    order = np.lexsort((key, R["sess_e"]))
    cnt = np.bincount(R["f_tid"], minlength=n); off = np.r_[0, np.cumsum(cnt)]
    yr = np.asarray(dates.year); dnum = np.asarray(dates.values.astype("datetime64[D]").astype(np.int64))
    ye = np.zeros(m, bool); ye[:-1] = yr[:-1] != yr[1:]; ye[-1] = True
    pnl = np.zeros(m); taken = np.zeros(n, bool); shares = np.zeros(n); dv = np.zeros(m + 1)
    rst = np.zeros(m); rlt = np.zeros(m); tax_paid = np.zeros(m)
    heap = []; gross = 0.0; rows = []
    S = {"cum": 0.0, "ptr": 0, "grun": 0.0, "yst": 0.0, "ylt": 0.0}

    def advance(upto):
        cum = S["cum"]; grun = S["grun"]
        for k in range(S["ptr"], upto):
            grun += dv[k]
            if borrow > 0:
                b = grun - (CAPITAL if mode == "fixed" else CAPITAL + cum)
                if b > 0:
                    pnl[k] -= b * borrow / 252.0
            cum += pnl[k]
            S["yst"] += rst[k]; S["ylt"] += rlt[k]
            if ye[k]:
                if tax is not None and (S["yst"] != 0.0 or S["ylt"] != 0.0 or tax.has_carry()):
                    t, parts = tax.year(int(yr[k]) - y0, S["yst"], S["ylt"])
                    pnl[k] -= t; cum -= t; tax_paid[k] = t
                    parts["calendar_year"] = int(yr[k]); rows.append(parts)
                S["yst"] = 0.0; S["ylt"] = 0.0
        S["cum"] = cum; S["grun"] = grun; S["ptr"] = upto

    cur_year = -1; base_eq = CAPITAL
    for i in order:
        s = int(R["sess_e"][i])
        while heap and heap[0][0] < s:
            _x = heapq.heappop(heap); gross -= _x[1]
        if s > S["ptr"]:
            advance(s)
        if R["parent"][i] >= 0 and not taken[R["parent"][i]]:
            continue
        eq = CAPITAL + S["cum"]
        if mode == "fixed":
            base = CAPITAL; capbase = CAPITAL
        else:
            if eq <= 0:
                continue
            if mode == "annual":
                if yr[s] != cur_year:
                    cur_year = yr[s]; base_eq = eq
                base = base_eq
            else:
                base = eq
            capbase = eq
        sh = np.floor(base * M.SIZE / 100.0 / R["a0"][i])
        if adv_frac is not None and np.isfinite(R["adv"][i]):
            sh = min(sh, np.floor(adv_frac * R["adv"][i] / R["px_e"][i]))
        if sh < 1:
            continue
        notional = sh * R["px_e"][i]
        if gross + notional > cap * capbase:
            continue
        sx = int(R["sess_x"][i])
        taken[i] = True; shares[i] = sh; gross += notional; heapq.heappush(heap, (sx, notional, -1))
        dv[s] += notional; dv[sx + 1] -= notional
        a, b = off[i], off[i + 1]
        inc = R["f_incr"][a:b]
        pnl[R["f_sess"][a:b]] += inc * sh
        c_ps = 0.5 * cost_rt * R["a0"][i]
        pnl[s] -= c_ps * sh; pnl[sx] -= c_ps * sh
        realised = inc.sum() * sh - 2.0 * c_ps * sh
        if dnum[sx] - dnum[s] > 365:
            rlt[sx] += realised
        else:
            rst[sx] += realised
    advance(m)
    dn = np.zeros(m + 1); tk = np.flatnonzero(taken)
    np.add.at(dn, R["sess_e"][tk], 1.0); np.add.at(dn, R["sess_x"][tk] + 1, -1.0)
    return dict(pnl=pnl, taken=taken, shares=shares, gross=np.cumsum(dv)[:m], open_n=np.cumsum(dn)[:m], tax_paid=tax_paid, rows=rows, rst=rst, rlt=rlt)


# ---------------------------------------------------------------- statistics
def path_stats(eq_path, dates_w):
    eq = np.r_[CAPITAL, eq_path]; W = len(eq_path); yrs = W / 252.0
    peak = np.maximum.accumulate(eq)
    dd = ((eq - peak) / peak).min() * 100 if (peak > 0).all() else -100.0
    end = eq[-1]
    cagr = ((end / CAPITAL) ** (1.0 / yrs) - 1.0) * 100 if end > 0 else -100.0
    s = pd.Series(eq_path, index=dates_w); ye = s.groupby(s.index.year).last().to_numpy()
    prev = np.r_[CAPITAL, ye[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        yret = np.where(prev > 0, ye / prev - 1.0, np.nan) * 100
        r = np.diff(eq) / np.where(eq[:-1] > 0, eq[:-1], np.nan)
    sharpe = np.nanmean(r) / np.nanstd(r) * np.sqrt(252) if np.nanstd(r) > 0 else np.nan
    return {"ending value $": end, "growth per year % (compound)": cagr, "max drawdown % (from peak)": dd, "growth per year / drawdown": cagr / abs(dd) if dd != 0 else np.nan,
            "worst year %": np.nanmin(yret), "best year %": np.nanmax(yret), "Sharpe ratio": sharpe}


def trading_only_drawdown(P, sel):
    """Drawdown of the account's trading returns with the tax payments added back (a tax payment is a withdrawal, not a trading loss)."""
    eq_full = CAPITAL + np.cumsum(P["pnl"]); prev = np.r_[CAPITAL, eq_full[:-1]]
    ok = prev > 0
    r = np.where(ok, (P["pnl"] + P["tax_paid"]) / np.where(ok, prev, 1.0), 0.0)
    idx = np.r_[1.0, np.cumprod(1.0 + r[sel])]
    return float(((idx - np.maximum.accumulate(idx)) / np.maximum.accumulate(idx)).min() * 100)


def run_stats(R, P, dates, sel, label, taxed, fixed=False):
    eq_full = CAPITAL + np.cumsum(P["pnl"])
    eqw = eq_full[sel]
    st = path_stats(eqw, dates[sel])
    tk = P["taken"]
    held = (np.asarray(dates.values.astype("datetime64[D]").astype(np.int64))[R["sess_x"]] - np.asarray(dates.values.astype("datetime64[D]").astype(np.int64))[R["sess_e"]])
    gw = P["gross"][sel]; ew = eqw
    st.update({"trades taken": int(tk.sum()), "average open positions": float(P["open_n"][sel].mean()),
               "average position value % of account": float(np.mean(gw / CAPITAL if fixed else np.where(ew > 0, gw / np.where(ew > 0, ew, np.nan), np.nan)) * 100),
               "total tax paid $": float(P["tax_paid"].sum()), "realised short-term $": float(P["rst"].sum()), "realised long-term $": float(P["rlt"].sum()),
               "trades held over a year": int((tk & (held > 365)).sum())})
    tdd = trading_only_drawdown(P, sel)
    st["max drawdown % (trading only, tax payments added back)"] = tdd
    st["growth per year / trading-only drawdown"] = st["growth per year % (compound)"] / abs(tdd) if tdd != 0 else np.nan
    gain_before_tax = eqw[-1] + P["tax_paid"].sum() - CAPITAL
    st["tax as % of the gain before tax"] = float(P["tax_paid"].sum() / gain_before_tax * 100) if taxed and gain_before_tax > 0 else np.nan
    row = dict(label); row.update(st)
    return row


def benchmark(close, dates, sel, name, infl, other0, y0=Y0):
    c = close[sel]; w = dates[sel]
    path = CAPITAL * c / c[0]
    pre = path_stats(path, w)
    gain = path[-1] - CAPITAL
    t = 0.0
    if gain > 0:
        t, parts = TaxState(other0, infl).year(int(w[-1].year) - y0, 0.0, gain)
    path_at = path.copy(); path_at[-1] -= t
    aft = path_stats(path_at, w)
    return pre, aft, t


def main():
    prices_path, out_dir, spy_path, etf_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 70)
    selftest_tax()
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    R = MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    key_vs = SB.vs_key(R, FEAT, SEG)
    dates = pd.DatetimeIndex(dates)
    lo = pd.Timestamp("2000-01-01"); sel = np.asarray((dates >= lo) & (dates <= END))
    assert dates[-1] <= END, "data run past the in-sample end"

    # self-check 1: the fixed mode reproduces the project account exactly (and its borrowing charge)
    for cap in (2.0, 1.0):
        Pa = account_scaled(R, cal, dates, cap, key_vs, mode="fixed"); Pb = TR.account(R, cal, cap, key_vs)
        assert np.allclose(Pa["pnl"], Pb["pnl"]) and (Pa["taken"] == Pb["taken"]).all() and np.allclose(Pa["gross"], Pb["gross"]), "fixed mode differs from the project account"
    Pa = account_scaled(R, cal, dates, 2.0, key_vs, mode="fixed", borrow=BORROW); Pb = MI.add_interest(MI.portfolio_gen(R, cal, 2.0, key_vs), 0.0, BORROW)
    assert np.allclose(Pa["pnl"], Pb["pnl"]), "borrowing charge differs from the project's"
    print("fixed mode reproduces the project account exactly (cap 200% and 100%, and the 4% borrowing charge)", flush=True)

    # benchmarks
    Q = NV.qqq_series(etf_path, cal)
    bench_rows = []
    for infl, other0, tag in ((0.025, 30000.0, "other income $30,000, brackets indexed 2.5% a year"), (0.025, 50000.0, "other income $50,000, brackets indexed 2.5% a year"), (0.0, 30000.0, "other income $30,000, brackets NOT indexed")):
        for nm, ser in (("QQQ buy and hold (price only)", Q), ("SPY buy and hold (price only)", spy_close)):
            pre, aft, t = benchmark(np.asarray(ser, float), dates, sel, nm, infl, other0)
            r = {"series": nm, "tax assumption": tag, "tax paid at the end $": t}
            r.update({f"pre-tax {k}": v for k, v in pre.items()}); r.update({f"after-tax {k}": v for k, v in aft.items()})
            bench_rows.append(r)
    BR = pd.DataFrame(bench_rows); BR.round(3).to_csv(out_dir / "benchmarks_qqq_spy.csv", index=False)
    print("\n==== BUY AND HOLD (single purchase 2000-01-03, sold at the last session, $300,000, tax once at the end) ====")
    for _, r in BR.iterrows():
        print(f"  {r['series']} | {r['tax assumption']}: ending ${r['pre-tax ending value $']:,.0f} pre-tax / ${r['after-tax ending value $']:,.0f} after tax (tax ${r['tax paid at the end $']:,.0f}); growth {r['pre-tax growth per year % (compound)']:.1f}% / {r['after-tax growth per year % (compound)']:.1f}% a year; "
              f"max drawdown {r['pre-tax max drawdown % (from peak)']:.1f}%; growth÷drawdown {r['pre-tax growth per year / drawdown']:.2f} / {r['after-tax growth per year / drawdown']:.2f}; worst year {r['pre-tax worst year %']:.1f}%; Sharpe {r['pre-tax Sharpe ratio']:.2f}", flush=True)

    cases = [("cap 200%, 4% a year charge on borrowed money", 2.0, BORROW), ("cap 200%, no borrowing charge", 2.0, 0.0), ("cap 100%, no borrowing", 1.0, 0.0)]
    modes = [("fixed $300,000 (project baseline)", "fixed", None), ("compounding, continuous", "continuous", None), ("compounding, base reset once a year", "annual", None),
             ("compounding, continuous, position at most 2% of daily dollar volume", "continuous", 0.02)]
    rows = []; yearly = []
    for cname, cap, bor in cases:
        for mname, mode, advf in modes:
            for taxed in (False, True):
                if mode == "fixed" and taxed:
                    continue
                kws = dict(mode=mode, borrow=bor, adv_frac=advf)
                P = account_scaled(R, cal, dates, cap, key_vs, tax=(TaxState() if taxed else None), **kws)
                r = run_stats(R, P, dates, sel, {"case": cname, "sizing": mname, "tax": "paid out of the account" if taxed else "none", "ranking": "volume surge", "pick": "reference"}, taxed, fixed=(mode == "fixed"))
                rows.append(r)
                if taxed and mode == "continuous" and advf is None:
                    for y in P["rows"]:
                        yearly.append(dict(case=cname, ranking="volume surge", **y))
                allr = []
                for sd in range(KSEEDS):
                    key = np.random.default_rng(1000 + sd).random(len(R["d"]))
                    Pk = account_scaled(R, cal, dates, cap, key, tax=(TaxState() if taxed else None), **kws)
                    allr.append(run_stats(R, Pk, dates, sel, {"case": cname, "sizing": mname, "tax": "paid out of the account" if taxed else "none", "ranking": "random pick (mean of 8)", "pick": sd}, taxed, fixed=(mode == "fixed")))
                D = pd.DataFrame(allr); num = [c for c in D.columns if D[c].dtype.kind in "fi" and c != "pick"]
                m_ = {c: D[c].mean() for c in num}
                m_.update({"case": cname, "sizing": mname, "tax": "paid out of the account" if taxed else "none", "ranking": "random pick (mean of 8)", "pick": "mean",
                           "ratio lowest pick": D["growth per year / drawdown"].min(), "ratio highest pick": D["growth per year / drawdown"].max(), "growth lowest pick": D["growth per year % (compound)"].min(), "growth highest pick": D["growth per year % (compound)"].max()})
                rows.append(m_)
                print(f"  {cname} | {mname} | tax {'on' if taxed else 'off'}: surge {r['growth per year % (compound)']:.1f}% / dd {r['max drawdown % (from peak)']:.1f}% (trading only {r['max drawdown % (trading only, tax payments added back)']:.1f}%) / ratio {r['growth per year / drawdown']:.2f} / end ${r['ending value $']:,.0f};  "
                      f"picks {m_['growth per year % (compound)']:.1f}% / dd {m_['max drawdown % (from peak)']:.1f}% / ratio {m_['growth per year / drawdown']:.2f} (range {m_['ratio lowest pick']:.2f}-{m_['ratio highest pick']:.2f}) / end ${m_['ending value $']:,.0f}", flush=True)
    S = pd.DataFrame(rows); S.round(3).to_csv(out_dir / "compound_tax_variants.csv", index=False)

    # sensitivities on the main case (cap 200% with the 4% charge, continuous compounding, volume surge, tax on)
    sens = []
    for cname, cap, bor in cases[:1] + cases[2:]:
        for tag, other0, infl in (("other income $30,000, indexed 2.5% a year (main)", 30000.0, 0.025), ("other income $50,000, indexed 2.5% a year", 50000.0, 0.025), ("other income $30,000, brackets NOT indexed", 30000.0, 0.0)):
            P = account_scaled(R, cal, dates, cap, key_vs, mode="continuous", tax=TaxState(other0, infl), borrow=bor)
            r = run_stats(R, P, dates, sel, {"case": cname, "tax assumption": tag}, True)
            sens.append(r)
            print(f"  SENS {cname} | {tag}: {r['growth per year % (compound)']:.1f}% a year / dd {r['max drawdown % (from peak)']:.1f}% / ratio {r['growth per year / drawdown']:.2f} / end ${r['ending value $']:,.0f} / tax paid ${r['total tax paid $']:,.0f}", flush=True)
    pd.DataFrame(sens).round(3).to_csv(out_dir / "tax_sensitivity.csv", index=False)
    Y = pd.DataFrame(yearly); Y.round(2).to_csv(out_dir / "yearly_tax_main.csv", index=False)

    # equity paths for the main cases (surge ranking), with SPY and QQQ
    eqs = {}
    for cname, cap, bor in cases[:1] + cases[2:]:
        for taxed in (False, True):
            P = account_scaled(R, cal, dates, cap, key_vs, mode="continuous", tax=(TaxState() if taxed else None), borrow=bor)
            eqs[f"{cname} | compounding | {'after tax' if taxed else 'pre-tax'}"] = (CAPITAL + np.cumsum(P["pnl"]))[sel]
    w = dates[sel]
    eqs["QQQ buy and hold (price only)"] = CAPITAL * Q[sel] / Q[sel][0]; eqs["SPY buy and hold (price only)"] = CAPITAL * spy_close[sel] / spy_close[sel][0]
    pd.DataFrame(eqs, index=w).round(0).to_csv(out_dir / "equity_paths.csv")

    # start years: the account started empty on 1 January of each year, run to the last session; QQQ and SPY bought the same day; tax brackets start indexing from the start year
    sy_rows = []
    ed = dates[R["sess_e"]]
    for cname, cap, bor in (cases[0], cases[2]):
        for y in range(2000, 2017):
            lo_y = pd.Timestamp(f"{y}-01-01")
            mask = np.asarray((ed >= lo_y) & (ed <= END)); sel_y = np.asarray((dates >= lo_y) & (dates <= END))
            Rs = SY.subset(R, mask); ks = key_vs[mask]
            Pa = account_scaled(Rs, cal, dates, cap, ks, mode="continuous", tax=TaxState(), borrow=bor, y0=y)
            Pn = account_scaled(Rs, cal, dates, cap, ks, mode="continuous", tax=None, borrow=bor)
            ra = run_stats(Rs, Pa, dates, sel_y, {}, True); rn = run_stats(Rs, Pn, dates, sel_y, {}, False)
            qpre, qaft, qt = benchmark(np.asarray(Q, float), dates, sel_y, "QQQ", 0.025, 30000.0, y0=y)
            spre, saft, stt = benchmark(np.asarray(spy_close, float), dates, sel_y, "SPY", 0.025, 30000.0, y0=y)
            sy_rows.append({"case": cname, "start year": y, "years": round(sel_y.sum() / 252.0, 1),
                            "system pre-tax growth %": rn["growth per year % (compound)"], "system after-tax growth %": ra["growth per year % (compound)"], "system after-tax ending $": ra["ending value $"],
                            "system drawdown % (balance, after tax)": ra["max drawdown % (from peak)"], "system drawdown % (trading only)": ra["max drawdown % (trading only, tax payments added back)"],
                            "QQQ pre-tax growth %": qpre["growth per year % (compound)"], "QQQ after-tax growth %": qaft["growth per year % (compound)"], "QQQ after-tax ending $": qaft["ending value $"], "QQQ drawdown %": qpre["max drawdown % (from peak)"],
                            "SPY after-tax growth %": saft["growth per year % (compound)"], "SPY drawdown %": spre["max drawdown % (from peak)"]})
    SYT = pd.DataFrame(sy_rows); SYT.round(2).to_csv(out_dir / "start_years_vs_qqq.csv", index=False)
    for cname, _, _ in (cases[0], cases[2]):
        v = SYT[SYT.case == cname]
        print(f"\n==== START YEARS | {cname} | continuous compounding, volume surge, tax paid from the account; QQQ and SPY bought the same day (price only), tax once at the end ====")
        print(v.drop(columns=["case"]).round(1).to_string(index=False))
        print(f"  system after-tax growth beats QQQ after-tax growth in {int((v['system after-tax growth %'] > v['QQQ after-tax growth %']).sum())} of {len(v)} start years; system trading-only drawdown shallower than QQQ's in {int((v['system drawdown % (trading only)'] > v['QQQ drawdown %']).sum())} of {len(v)}")

    # year-end account values, main case after tax, with QQQ
    ykeys = [k for k in eqs if "after tax" in k] + ["QQQ buy and hold (price only)"]
    YE = pd.DataFrame({k: pd.Series(eqs[k], index=w).groupby(w.year).last() for k in ykeys})
    YR = YE.pct_change() * 100; YR.iloc[0] = (YE.iloc[0] / CAPITAL - 1) * 100
    YO = pd.concat([YE.add_suffix(" | year-end value $"), YR.add_suffix(" | year return %")], axis=1); YO.round(1).to_csv(out_dir / "year_end_values.csv")
    print("\n==== year-end account value and return, after tax, 2000-2021 (continuous compounding, volume surge) ====")
    pd.set_option("display.float_format", lambda v: f"{v:,.1f}")
    print(YO.to_string())

    # readable tables
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
    cols = ["sizing", "tax", "ranking", "ending value $", "growth per year % (compound)", "max drawdown % (from peak)", "max drawdown % (trading only, tax payments added back)", "growth per year / drawdown", "growth per year / trading-only drawdown", "worst year %", "Sharpe ratio", "trades taken", "average position value % of account", "total tax paid $", "tax as % of the gain before tax"]
    for cname, _, _ in cases:
        v = S[S.case == cname]
        print(f"\n==== {cname} (volume surge = one run; random pick = mean of 8) ====")
        print(v[[c for c in cols if c in v.columns]].to_string(index=False))
    print("\n==== holding periods of the system's trades (cap 200%, 4% charge, continuous compounding, volume surge, tax on) ====")
    v = S[(S.case == cases[0][0]) & (S.sizing == "compounding, continuous") & (S.tax == "paid out of the account") & (S.ranking == "volume surge")]
    print(v[["trades taken", "trades held over a year", "realised short-term $", "realised long-term $"]].to_string(index=False))
    print("\n==== tax by year, main case (cap 200%, 4% charge, continuous compounding, volume surge) ====")
    if len(Y):
        print(Y[Y.case == cases[0][0]][["calendar_year", "realised_short_term", "realised_long_term", "federal", "niit", "new_jersey", "total_tax", "loss_carried_short", "loss_carried_long"]].round(0).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
