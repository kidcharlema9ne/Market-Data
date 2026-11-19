"""Stocks, long only: the WASH-SALE rule added to the compounded, taxed account (Michael, 19 Nov 2026). Follow-up to er_stocks_compound_tax.py (Entry 169).
Usage: python er_stocks_wash_sale.py stock_prices.parquet OUT_DIR spy_prices.parquet nasdaq_etfs.parquet

Everything is the Entry 169 setup (single filer, New Jersey, $300,000 start, $30,000 other income, tax paid out of the account, volume-surge ranking when the account is full, cap 200% with a 4% charge on
borrowed money, and cap 100%), with ONE addition: a loss on a stock is disallowed (deferred) when the account buys the same stock again within 30 days after the losing sale.
THE RULE AS MODELLED (federal and New Jersey both follow the federal treatment of a wash sale):
  - A losing sale of a stock is a wash sale to the extent the account buys more shares of the SAME stock within 30 calendar days AFTER the sale date. The system holds one position per stock at a time, so there is never a purchase
    BEFORE the sale to match; the only case is a re-entry after a loss. (A purchase in the 30 days before a sale would have been a lot that was already sold before the losing lot was bought; those shares are not replacement shares.)
  - Shares are matched in the order the re-entries happen. If the losing lot is bigger than the re-entry, the unmatched part of the loss stays deductible (or is matched by a later re-entry inside the 30 days).
  - The disallowed loss is ADDED to the cost basis of the replacement shares, so it comes back when those shares are sold (a smaller gain or a bigger loss then). It can chain: if the replacement is sold at a loss
    (after the added basis) and the stock is bought again within 30 days, that loss is deferred again.
  - The holding period of the replacement shares includes the holding period of the shares whose loss was deferred (this almost never matters here: 97.5% of gains are short-term).
TIMING. The tax for a calendar year used to be taken out on the last session of that year. A December loss can only be known to be a wash sale after the next 30 days, so with the wash-sale rule the tax for year Y is
taken out on the first session on or after 31 January of Y+1 (the last session of the data for the final year). To separate the effect of the rule from the effect of paying a month later, three tax variants are run:
  (1) last-session payment, no wash-sale rule (reproduces Entry 169 exactly: a self-check),
  (2) end-of-January payment, no wash-sale rule (the control),
  (3) end-of-January payment, WITH the wash-sale rule.
The wash-sale effect is (3) against (2).
NOT modelled (same as Entry 169): Social Security taxation, estimated-payment timing, dividends, margin-interest deductibility. In-sample only (data through 2021-08-06); the sealed years are never read. Post hoc.
"""
import heapq
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks_compound_tax as CT
import er_stocks_many_ideas as MI
import er_stocks_nasdaq_volume as NV
import er_stocks_spy_buffer as SB
import er_stocks_start_years as SY
import er_stocks_common_momentum as M
from er_stocks import CAPITAL, END

KSEEDS = MI.KSEEDS
BASE_COST = CT.BASE_COST
Y0 = CT.Y0
BORROW = CT.BORROW
WINDOW_DAYS = 30


# ---------------------------------------------------------------- the wash-sale ledger
class WashLedger:
    """Holds every lot the account has taken (one lot = one trade). settle(year) returns the short-term and long-term gain for the lots SOLD in that calendar year, after the wash-sale rule if it is on."""

    def __init__(self, wash):
        self.wash = wash
        self.by_sym = {}
        self.pending = {}
        self.lots = []
        self.info_by_year = {}

    def add(self, sym, e_day, x_day, x_year, shares, realised):
        lot = dict(sym=sym, e=int(e_day), x=int(x_day), yr=int(x_year), sh=float(shares), real=float(realised), avail=float(shares), carried=0.0, tack_days=0, tack_sh=0.0, pos=0, washed=0.0)
        lst = self.by_sym.setdefault(sym, [])
        lot["pos"] = len(lst); lst.append(lot); self.pending.setdefault(lot["yr"], []).append(lot); self.lots.append(lot)

    def settle(self, year):
        lots = sorted(self.pending.pop(year, []), key=lambda L: (L["x"], L["e"]))
        st = lt = 0.0
        info = dict(lots_sold=len(lots), loss_lots=0, loss_dollars_before_wash=0.0, washed_lots=0, disallowed_dollars=0.0, recovered_dollars=0.0, loss_dollars_after_wash=0.0)
        for A in lots:
            own_days = A["x"] - A["e"]
            frac_t = min(1.0, A["tack_sh"] / A["sh"]) if A["sh"] > 0 else 0.0
            adj_total = A["real"] - A["carried"]
            if A["real"] < 0:
                info["loss_lots"] += 1; info["loss_dollars_before_wash"] += -A["real"]
            if A["carried"] > 0:
                info["recovered_dollars"] += A["carried"]
            d_total = 0.0
            if self.wash and adj_total < 0:
                remaining = A["sh"]; lst = self.by_sym[A["sym"]]
                for j in range(A["pos"] + 1, len(lst)):
                    B = lst[j]
                    if B["e"] - A["x"] > WINDOW_DAYS:
                        break
                    if B["e"] <= A["x"] or B["avail"] <= 0 or remaining <= 0:
                        continue
                    m = min(remaining, B["avail"])
                    d = -adj_total * m / A["sh"]
                    B["avail"] -= m; B["carried"] += d; B["tack_sh"] += m
                    B["tack_days"] = max(B["tack_days"], own_days + (A["tack_days"] if A["tack_sh"] > 0 else 0))
                    remaining -= m; d_total += d
                if d_total > 0:
                    A["washed"] = d_total; info["washed_lots"] += 1; info["disallowed_dollars"] += d_total
            tax_real = adj_total + d_total
            if tax_real < 0:
                info["loss_dollars_after_wash"] += -tax_real
            # split between the tacked (replacement) shares and the others for the one-year test; a disallowed loss scales both parts down in the same proportion
            part_t = A["real"] * frac_t - A["carried"]; part_u = A["real"] * (1.0 - frac_t)
            if d_total > 0 and adj_total != 0:
                scale = tax_real / adj_total
                part_t *= scale; part_u *= scale
            if frac_t > 0 and own_days + A["tack_days"] > 365:
                lt += part_t
            else:
                st += part_t
            if own_days > 365:
                lt += part_u
            else:
                st += part_u
        self.info_by_year[year] = info
        return st, lt, info


def selftest_ledger():
    def mk(wash):
        return WashLedger(wash)
    # 1. a loss re-entered 10 days later: loss deferred into the next lot, which is taxed on a smaller gain
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 110, 130, 2002, 100, 3000.0)
    st, lt, i = L.settle(2001); assert abs(st) < 1e-9 and abs(i["disallowed_dollars"] - 1000.0) < 1e-9, (st, i)
    st, lt, i = L.settle(2002); assert abs(st - 2000.0) < 1e-9 and abs(lt) < 1e-9, (st, lt)
    L = mk(False); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 110, 130, 2002, 100, 3000.0)
    assert abs(L.settle(2001)[0] + 1000.0) < 1e-9 and abs(L.settle(2002)[0] - 3000.0) < 1e-9
    # 2. a re-entry 31 days later is not a wash sale; 30 days later is
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 131, 150, 2001, 100, 500.0)
    assert abs(L.settle(2001)[0] - (-500.0)) < 1e-9
    # direct numbers for the 30-day case: loss 1000 deferred, second lot 500 - 1000 = -500 after added basis, never re-entered -> tax-year total -500
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 130, 150, 2001, 100, 500.0)
    st, _, i = L.settle(2001); assert abs(st - (-500.0)) < 1e-9, st
    # 3. partial: a 100-share loss matched by 40 shares then 100 shares (60 used)
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 105, 108, 2001, 40, 5000.0); L.add("A", 115, 125, 2001, 100, 5000.0)
    st, _, i = L.settle(2001); assert abs(i["disallowed_dollars"] - 1000.0) < 1e-9 and abs(L.lots[1]["carried"] - 400.0) < 1e-9 and abs(L.lots[2]["carried"] - 600.0) < 1e-9, i
    # 3b. only 40 replacement shares: 400 deferred, 600 still a loss this year
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 105, 108, 2001, 40, 5000.0)
    st, _, i = L.settle(2001); assert abs(i["disallowed_dollars"] - 400.0) < 1e-9
    # 4. chain: deferred loss makes the replacement's own loss bigger, which is deferred again into the third lot
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("A", 110, 120, 2001, 100, -500.0); L.add("A", 125, 140, 2002, 100, 4000.0)
    st, _, i = L.settle(2001); assert abs(st) < 1e-9, st                         # first loss deferred; the second (-500 - 1000 = -1500) deferred too
    assert abs(L.lots[2]["carried"] - 1500.0) < 1e-9
    st, _, i = L.settle(2002); assert abs(st - 2500.0) < 1e-9, st
    # 5. holding period of the replacement includes the old holding period: 200 + 200 days > 365 -> the deferred-loss-adjusted gain is long-term
    L = mk(True); L.add("A", 0, 200, 2001, 100, -1000.0); L.add("A", 205, 405, 2002, 100, 3000.0)
    L.settle(2001); st, lt, i = L.settle(2002); assert abs(lt - 2000.0) < 1e-9 and abs(st) < 1e-9, (st, lt)
    # 6. other stocks never match
    L = mk(True); L.add("A", 50, 100, 2001, 100, -1000.0); L.add("B", 110, 120, 2001, 100, 500.0)
    assert abs(L.settle(2001)[0] - (-500.0)) < 1e-9
    print("wash-sale ledger self-test passed", flush=True)


# ---------------------------------------------------------------- the account
def account_washed(R, cal, dates, cap, key, mode="continuous", tax=None, borrow=0.0, cost_rt=None, y0=Y0, timing="year_end", wash=False, adv_frac=None):
    """Same account as er_stocks_compound_tax.account_scaled, but the realised gains for the tax come from a WashLedger and the tax for year Y is taken out at timing: 'year_end' (last session of Y) or 'late_jan' (first session on or after 31 January of Y+1; the last session for the last year of data)."""
    assert not (wash and timing == "year_end"), "the wash-sale rule needs the January window"
    cost_rt = BASE_COST if cost_rt is None else cost_rt
    n = len(R["d"]); m = len(cal)
    order = np.lexsort((key, R["sess_e"]))
    cnt = np.bincount(R["f_tid"], minlength=n); off = np.r_[0, np.cumsum(cnt)]
    yr = np.asarray(dates.year); dnum = np.asarray(dates.values.astype("datetime64[D]").astype(np.int64))
    settle_year = np.full(m, -1, np.int64)
    years = np.unique(yr)
    for Y in years:
        if timing == "year_end":
            k = int(np.flatnonzero(yr == Y)[-1])
        else:
            if Y == years[-1]:
                k = m - 1
            else:
                k = int(np.searchsorted(dates.values, np.datetime64(f"{int(Y) + 1}-01-31")))
                if k >= m:
                    k = m - 1
        settle_year[k] = int(Y)
    pnl = np.zeros(m); taken = np.zeros(n, bool); shares = np.zeros(n); dv = np.zeros(m + 1)
    rst = np.zeros(m); rlt = np.zeros(m); tax_paid = np.zeros(m)
    heap = []; gross = 0.0; rows = []
    ledger = WashLedger(wash)
    S = {"cum": 0.0, "ptr": 0, "grun": 0.0}

    def advance(upto):
        cum = S["cum"]; grun = S["grun"]
        for k in range(S["ptr"], upto):
            grun += dv[k]
            if borrow > 0:
                b = grun - (CAPITAL if mode == "fixed" else CAPITAL + cum)
                if b > 0:
                    pnl[k] -= b * borrow / 252.0
            cum += pnl[k]
            if settle_year[k] >= 0 and tax is not None:
                Y = int(settle_year[k])
                st, lt, info = ledger.settle(Y)
                if st != 0.0 or lt != 0.0 or tax.has_carry():
                    t, parts = tax.year(Y - y0, st, lt)
                    pnl[k] -= t; cum -= t; tax_paid[k] = t
                    parts["calendar_year"] = Y; parts.update(info); parts["paid_on_session"] = str(dates[k].date()); rows.append(parts)
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
        ledger.add(int(R["sym"][i]), dnum[s], dnum[sx], int(yr[sx]), sh, realised)
        if dnum[sx] - dnum[s] > 365:
            rlt[sx] += realised
        else:
            rst[sx] += realised
    advance(m)
    dn = np.zeros(m + 1); tk = np.flatnonzero(taken)
    np.add.at(dn, R["sess_e"][tk], 1.0); np.add.at(dn, R["sess_x"][tk] + 1, -1.0)
    return dict(pnl=pnl, taken=taken, shares=shares, gross=np.cumsum(dv)[:m], open_n=np.cumsum(dn)[:m], tax_paid=tax_paid, rows=rows, rst=rst, rlt=rlt, ledger=ledger)


def reentry_stats(ledger):
    """How often the account bought the same stock again within 30 days of selling it (taken lots only)."""
    gaps_loss = []; gaps_gain = []; n_loss = n_gain = 0; loss_sum = 0.0; loss_sum_re = 0.0
    for lst in ledger.by_sym.values():
        for j, A in enumerate(lst):
            nxt = lst[j + 1] if j + 1 < len(lst) else None
            gap = (nxt["e"] - A["x"]) if nxt is not None else None
            if A["real"] < 0:
                n_loss += 1; loss_sum += -A["real"]
                if gap is not None and gap <= WINDOW_DAYS:
                    gaps_loss.append(gap); loss_sum_re += -A["real"]
            else:
                n_gain += 1
                if gap is not None and gap <= WINDOW_DAYS:
                    gaps_gain.append(gap)
    return dict(losing_sales=n_loss, losing_sales_bought_again_within_30_days=len(gaps_loss), share_of_losing_sales=len(gaps_loss) / n_loss * 100 if n_loss else np.nan,
                loss_dollars=loss_sum, loss_dollars_bought_again=loss_sum_re, share_of_loss_dollars=loss_sum_re / loss_sum * 100 if loss_sum else np.nan,
                median_days_to_reentry=float(np.median(gaps_loss)) if gaps_loss else np.nan, winning_sales=n_gain, winning_sales_bought_again_within_30_days=len(gaps_gain))


VARIANTS = [("tax at last session of year, no wash-sale rule (Entry 169)", "year_end", False), ("tax at end of January, no wash-sale rule (control)", "late_jan", False), ("tax at end of January, WITH wash-sale rule", "late_jan", True)]


def main():
    prices_path, out_dir, spy_path, etf_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 70)
    CT.selftest_tax(); selftest_ledger()
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    R = MI.check_baseline(ctx, mk200)
    FEAT = NV.build_features(ctx, E20)
    key_vs = SB.vs_key(R, FEAT, SEG)
    dates = pd.DatetimeIndex(dates)
    lo = pd.Timestamp("2000-01-01"); sel = np.asarray((dates >= lo) & (dates <= END))
    assert dates[-1] <= END, "data run past the in-sample end"

    # self-check: with the rule off and payment at the last session, the new account is the Entry 169 account exactly (both caps, with and without tax)
    for cap, bor in ((2.0, BORROW), (1.0, 0.0)):
        for taxed in (False, True):
            Pa = CT.account_scaled(R, cal, dates, cap, key_vs, mode="continuous", tax=(CT.TaxState() if taxed else None), borrow=bor)
            Pb = account_washed(R, cal, dates, cap, key_vs, mode="continuous", tax=(CT.TaxState() if taxed else None), borrow=bor, timing="year_end", wash=False)
            assert np.allclose(Pa["pnl"], Pb["pnl"]) and (Pa["taken"] == Pb["taken"]).all() and np.allclose(Pa["tax_paid"], Pb["tax_paid"]), f"new account differs from Entry 169 (cap {cap}, taxed {taxed})"
    print("self-check passed: rule off + payment at the last session reproduces Entry 169 exactly (cap 200% with the 4% charge, and cap 100%, with and without tax)", flush=True)

    Q = NV.qqq_series(etf_path, cal)
    qpre, qaft, qt = CT.benchmark(np.asarray(Q, float), dates, sel, "QQQ", 0.025, 30000.0)
    spre, saft, st_ = CT.benchmark(np.asarray(spy_close, float), dates, sel, "SPY", 0.025, 30000.0)
    print(f"\nQQQ buy and hold: ${qpre['ending value $']:,.0f} pre-tax ({qpre['growth per year % (compound)']:.1f}% a year), ${qaft['ending value $']:,.0f} after tax ({qaft['growth per year % (compound)']:.1f}% a year); "
          f"SPY after tax {saft['growth per year % (compound)']:.1f}% a year", flush=True)

    cases = [("cap 200%, 4% a year charge on borrowed money", 2.0, BORROW), ("cap 100%, no borrowing", 1.0, 0.0)]
    rows = []; yearly = []; wstats = []
    for cname, cap, bor in cases:
        P = account_washed(R, cal, dates, cap, key_vs, mode="continuous", tax=None, borrow=bor)
        r = CT.run_stats(R, P, dates, sel, {"case": cname, "tax": "none (pre-tax)", "ranking": "volume surge"}, False); rows.append(r)
        print(f"  {cname} | pre-tax: {r['growth per year % (compound)']:.1f}% a year / dd {r['max drawdown % (from peak)']:.1f}% / end ${r['ending value $']:,.0f}", flush=True)
        for vname, timing, wash in VARIANTS:
            P = account_washed(R, cal, dates, cap, key_vs, mode="continuous", tax=CT.TaxState(), borrow=bor, timing=timing, wash=wash)
            r = CT.run_stats(R, P, dates, sel, {"case": cname, "tax": vname, "ranking": "volume surge"}, True)
            r["loss_dollars_deferred_in_total"] = float(sum(x.get("disallowed_dollars", 0.0) for x in P["rows"]))
            rows.append(r)
            for y in P["rows"]:
                yearly.append(dict(case=cname, tax=vname, **y))
            re = reentry_stats(P["ledger"]); re.update({"case": cname, "tax": vname}); wstats.append(re)
            allr = []
            for sd in range(KSEEDS):
                key = np.random.default_rng(1000 + sd).random(len(R["d"]))
                Pk = account_washed(R, cal, dates, cap, key, mode="continuous", tax=CT.TaxState(), borrow=bor, timing=timing, wash=wash)
                allr.append(CT.run_stats(R, Pk, dates, sel, {"case": cname, "tax": vname, "ranking": "random pick", "pick": sd}, True))
            D = pd.DataFrame(allr); num = [c for c in D.columns if D[c].dtype.kind in "fi" and c != "pick"]
            m_ = {c: D[c].mean() for c in num}; m_.update({"case": cname, "tax": vname, "ranking": "random pick (mean of 8)", "pick": "mean",
                                                       "growth lowest pick": D["growth per year % (compound)"].min(), "growth highest pick": D["growth per year % (compound)"].max()})
            rows.append(m_)
            print(f"  {cname} | {vname}: surge {r['growth per year % (compound)']:.2f}% a year / dd {r['max drawdown % (from peak)']:.1f}% (trading only {r['max drawdown % (trading only, tax payments added back)']:.1f}%) / end ${r['ending value $']:,.0f} / tax ${r['total tax paid $']:,.0f} ({r['tax as % of the gain before tax']:.1f}% of gain);  "
                  f"picks {m_['growth per year % (compound)']:.2f}% (range {m_['growth lowest pick']:.2f} to {m_['growth highest pick']:.2f}) / end ${m_['ending value $']:,.0f} / tax ${m_['total tax paid $']:,.0f}", flush=True)
    S = pd.DataFrame(rows); S.round(3).to_csv(out_dir / "wash_sale_variants.csv", index=False)
    Y = pd.DataFrame(yearly); Y.round(2).to_csv(out_dir / "wash_sale_yearly_tax.csv", index=False)
    W = pd.DataFrame(wstats); W.round(2).to_csv(out_dir / "wash_sale_reentry_stats.csv", index=False)

    # readable summary
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
    cols = ["tax", "ranking", "ending value $", "growth per year % (compound)", "max drawdown % (from peak)", "max drawdown % (trading only, tax payments added back)", "growth per year / trading-only drawdown", "worst year %", "Sharpe ratio", "total tax paid $", "tax as % of the gain before tax"]
    for cname, _, _ in cases:
        v = S[S.case == cname]
        print(f"\n==== {cname} (volume surge = one run; random pick = mean of 8) ====")
        print(v[[c for c in cols if c in v.columns]].to_string(index=False))
    print("\n==== how often the account bought the same stock again within 30 days of SELLING it (taken trades only) ====")
    print(W[W.tax.str.contains("WITH")].to_string(index=False))
    print("\n==== wash-sale effect by year, main case (cap 200%, 4% charge): tax with the rule minus tax without it (both paid end of January), loss dollars deferred that year ====")
    for cname, _, _ in cases:
        a = Y[(Y.case == cname) & Y.tax.str.contains("control")].set_index("calendar_year"); b = Y[(Y.case == cname) & Y.tax.str.contains("WITH")].set_index("calendar_year")
        j = pd.DataFrame({"tax without rule": a["total_tax"], "tax with rule": b["total_tax"], "loss lots": b["loss_lots"], "loss $ before rule": b["loss_dollars_before_wash"], "loss $ deferred (disallowed)": b["disallowed_dollars"], "deferred loss recovered this year $": b["recovered_dollars"],
                          "short-term gain taxed, without": a["realised_short_term"], "short-term gain taxed, with": b["realised_short_term"]})
        j["extra tax"] = j["tax with rule"] - j["tax without rule"]
        print(f"\n-- {cname}")
        print(j.round(0).to_string())
        j.round(0).to_csv(out_dir / f"wash_sale_by_year_{'200' if '200' in cname else '100'}.csv")

    # start years: the account started empty on 1 January of each year; QQQ and SPY bought the same day
    sy_rows = []; ed = dates[R["sess_e"]]
    for cname, cap, bor in cases:
        for y in range(2000, 2017):
            lo_y = pd.Timestamp(f"{y}-01-01")
            mask = np.asarray((ed >= lo_y) & (ed <= END)); sel_y = np.asarray((dates >= lo_y) & (dates <= END))
            Rs = SY.subset(R, mask); ks = key_vs[mask]
            P0 = account_washed(Rs, cal, dates, cap, ks, mode="continuous", tax=CT.TaxState(), borrow=bor, y0=y, timing="late_jan", wash=False)
            P1 = account_washed(Rs, cal, dates, cap, ks, mode="continuous", tax=CT.TaxState(), borrow=bor, y0=y, timing="late_jan", wash=True)
            r0 = CT.run_stats(Rs, P0, dates, sel_y, {}, True); r1 = CT.run_stats(Rs, P1, dates, sel_y, {}, True)
            qp, qa, _ = CT.benchmark(np.asarray(Q, float), dates, sel_y, "QQQ", 0.025, 30000.0, y0=y)
            sy_rows.append({"case": cname, "start year": y, "system after-tax growth %, no rule": r0["growth per year % (compound)"], "system after-tax growth %, with wash-sale rule": r1["growth per year % (compound)"],
                            "difference (points)": r1["growth per year % (compound)"] - r0["growth per year % (compound)"], "system after-tax ending $, no rule": r0["ending value $"], "system after-tax ending $, with rule": r1["ending value $"],
                            "tax paid $, no rule": r0["total tax paid $"], "tax paid $, with rule": r1["total tax paid $"], "QQQ after-tax growth %": qa["growth per year % (compound)"]})
    SYT = pd.DataFrame(sy_rows); SYT.round(2).to_csv(out_dir / "wash_sale_start_years.csv", index=False)
    for cname, _, _ in cases:
        v = SYT[SYT.case == cname]
        print(f"\n==== START YEARS | {cname} | after-tax growth, wash-sale rule off vs on (both paid end of January); QQQ after tax ====")
        print(v.drop(columns=["case"]).round(1).to_string(index=False))
        print(f"  with the rule the system beats QQQ after tax in {int((v['system after-tax growth %, with wash-sale rule'] > v['QQQ after-tax growth %']).sum())} of {len(v)} start years (without the rule: {int((v['system after-tax growth %, no rule'] > v['QQQ after-tax growth %']).sum())}); "
              f"the rule lowers the growth rate in {int((v['difference (points)'] < 0).sum())} of {len(v)}, mean difference {v['difference (points)'].mean():.2f} points")
    print("done")


if __name__ == "__main__":
    main()
