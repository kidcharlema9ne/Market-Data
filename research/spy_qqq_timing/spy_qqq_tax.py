"""SPY + QQQ 200-day 4% band system versus buy and hold, AFTER TAX, in a taxable account (Michael, 19 Nov 2026).
Usage: python spy_qqq_tax.py PRICES OUT_DIR TBILL_CSV
Reuses the frozen signal rules from spy_qqq_timing.py (200-day average, 4% band, trade at the NEXT session's close). Nothing about the rules is changed here.

ACCOUNT MODEL (real shares, real tax lots, not the daily-reset percentages of the pre-tax study):
  Start $500,000 on 2000-10-16, end at the last session in the data, then everything is sold and the last tax is paid ("liquidated after tax").
  Share invested w (75% or 50%): each fund gets w/2 of the whole account value when it is bought; no daily rebalancing; cash sits in Treasury bills (TB3MS rate).
  System: a fund is bought when its signal turns on, sold when it turns off (next close). Buy and hold: bought on day one, either left alone ("drift")
  or brought back to w at each year end ("annual reset", which sells some shares and realises a long-term gain).
  Tax is worked out on the last session of each year and paid out of the account's cash (Treasury bills).
  Federal: gains on lots held 365 days or less taxed at the short-term rate (24%), longer at the long-term rate (15%); Treasury bill interest taxed as ordinary income at 24%;
  short and long losses net against each other, net loss up to $3,000 a year against interest, the rest carried forward. Flat rates, as Michael asked (24%); no brackets, no 3.8% surtax.
  New Jersey scenario: flat 6.37% on net gains in the year plus dividends (no carry-forward); Treasury bill interest treated as New Jersey exempt (an assumption, flagged).
  Wash sales: a loss sale followed by a re-buy of the SAME fund within 30 calendar days is disallowed and added to the cost of the new purchase.
  Dividends: the price data has no dividends. Default is price only. A sensitivity adds an ASSUMED constant yield (SPY 1.8%, QQQ 0.7% a year; assumption, not data), paid as cash and taxed at the long-term rate.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spy_qqq_timing as T

F = ("spy", "qqq"); START_VALUE = 500000.0
YIELD_ASSUMED = {"spy": 0.018, "qqq": 0.007}; NO_YIELD = {"spy": 0.0, "qqq": 0.0}
SCEN = {"no tax (IRA-like)": (0.0, 0.0, 0.0), "federal 24% / 15%": (0.24, 0.15, 0.0), "federal 24% / 15% + New Jersey 6.37%": (0.24, 0.15, 0.0637)}


def positions(px, rule):
    n = len(px)
    if rule == "hold": return {f: np.ones(n, bool) for f in F}
    return {f: T.signal(px[f], rule).shift(2).fillna(False).astype(bool).values for f in F}  # same timing as the pre-tax study (next close)


def year_tax(acc, state, rates):
    """acc: st, lt, intr, div for the year. Returns (federal, new jersey). state carries loss carry-forwards."""
    rs, rl, rn = rates
    st = acc["st"] - state["st_cf"]; lt = acc["lt"] - state["lt_cf"]; state["st_cf"] = state["lt_cf"] = 0.0
    if st < 0 < lt: lt += st; st = 0.0
    elif lt < 0 < st: st += lt; lt = 0.0
    ordinary = acc["intr"]
    if st <= 0 and lt <= 0:
        loss = -(st + lt); ded = min(3000.0, loss, ordinary); state["st_cf"] = loss - ded; ordinary -= ded; st = lt = 0.0
    fed = rs * max(ordinary + st, 0.0) + rl * max(lt, 0.0) + rl * acc["div"]
    nj = rn * (max(acc["st"] + acc["lt"], 0.0) + acc["div"]) if rn else 0.0
    return fed, nj


def run(px, cash_r, pos, w, reset, rates, yld, label=""):
    idx = px.index; n = len(idx); i0 = int(idx.searchsorted(T.START)); close = {f: px[f].values for f in F}
    entries = {f: [i for i in range(i0, n - 1) if pos[f][i + 1] and not pos[f][i]] for f in F}
    lots = {f: [] for f in F}; pending = {f: 0.0 for f in F}; cash = START_VALUE
    acc = dict(st=0.0, lt=0.0, intr=0.0, div=0.0); state = dict(st_cf=0.0, lt_cf=0.0)
    eq = np.full(n, np.nan); trades = []; yearly = []; total_tax = 0.0; washes = 0; wash_amt = 0.0; neg_cash = 0
    st_gain_total = lt_gain_total = 0.0

    def value(i): return cash + sum(sum(l[0] for l in lots[f]) * close[f][i] for f in F)

    def sell(f, i, shares_to_sell=None, final=False):
        nonlocal cash, washes, wash_amt, st_gain_total, lt_gain_total
        left = shares_to_sell if shares_to_sell is not None else 1e18; keep = []
        for lot in lots[f]:
            if left <= 1e-12: keep.append(lot); continue
            take = min(lot[0], left); frac = take / lot[0]; basis = lot[1] * frac; proceeds = take * close[f][i]; gain = proceeds - basis
            days = (idx[i] - lot[2]).days; cash += proceeds; left -= take
            nxt = [j for j in entries[f] if j > i]
            if gain < 0 and not final and shares_to_sell is None and nxt and (idx[nxt[0]] - idx[i]).days <= 30:
                pending[f] += -gain; washes += 1; wash_amt += -gain; kind = "loss disallowed (wash sale)"
            else:
                if days > 365: acc["lt"] += gain; lt_gain_total += gain; kind = "long"
                else: acc["st"] += gain; st_gain_total += gain; kind = "short"
            trades.append(dict(fund=f.upper(), entry=lot[2].date(), exit=idx[i].date(), days=days, entry_price=round(lot[3], 2), exit_price=round(close[f][i], 2), gain=round(gain), kind=kind))
            if take < lot[0]: keep.append([lot[0] - take, lot[1] - basis, lot[2], lot[3]])
        lots[f] = keep

    def buy(f, i, amount):
        nonlocal cash
        amount = min(amount, cash)
        if amount <= 0: return
        lots[f].append([amount / close[f][i], amount + pending[f], idx[i], close[f][i]]); pending[f] = 0.0; cash -= amount

    for i in range(i0, n):
        if i > i0:
            ii = cash * cash_r[i]; cash += ii; acc["intr"] += ii
            for f in F:
                d = sum(l[0] for l in lots[f]) * close[f][i] * yld[f] / T.ANN; cash += d; acc["div"] += d
        last = i == n - 1
        for f in F:
            cur = pos[f][i]; nxt = pos[f][i + 1] if not last else cur
            if (i == i0 and cur) or ((not cur) and nxt and not lots[f]): buy(f, i, w / 2 * value(i))
            if lots[f] and cur and not nxt and not last: sell(f, i)
        year_end = last or idx[i + 1].year != idx[i].year
        if last:
            eq[i] = value(i)
            for f in F: sell(f, i, final=True)
        if year_end:
            if reset and not last:
                for f in F:
                    tgt = w / 2 * value(i); cur_v = sum(l[0] for l in lots[f]) * close[f][i]
                    if cur_v > tgt: sell(f, i, shares_to_sell=(cur_v - tgt) / close[f][i])
                    else: buy(f, i, tgt - cur_v)
            fed, nj = year_tax(acc, state, rates); cash -= fed + nj; total_tax += fed + nj
            if cash < 0: neg_cash += 1
            yearly.append(dict(year=idx[i].year, short_term_gain=round(acc["st"]), long_term_gain=round(acc["lt"]), interest=round(acc["intr"]), dividends=round(acc["div"]), federal_tax=round(fed), nj_tax=round(nj), account_after_tax=round(value(i))))
            acc = dict(st=0.0, lt=0.0, intr=0.0, div=0.0)
        if not last: eq[i] = value(i)
    s = pd.Series(eq[i0:], index=idx[i0:]); final = cash; yrs = (idx[-1] - idx[i0]).days / 365.25
    dd = (s / s.cummax() - 1).min(); g = (final / START_VALUE) ** (1 / yrs) - 1
    ye = pd.Series([y["account_after_tax"] for y in yearly], index=[y["year"] for y in yearly]); yr = ye / ye.shift(1).fillna(START_VALUE) - 1
    T_ = pd.DataFrame(trades); closed = T_[T_.kind.isin(["short", "long"])] if len(T_) else T_
    return dict(label=label, final_value=round(final), growth_per_year_pct=round(g * 100, 2), max_drawdown_pct=round(dd * 100, 1), profit_per_year_over_drawdown=round(g / abs(dd), 2),
                worst_year_pct=round(yr.min() * 100, 1), total_tax=round(total_tax), tax_share_of_gain_pct=round(100 * total_tax / max(final - START_VALUE + total_tax, 1), 1),
                closed_trades=len(closed), long_term_trades=int((closed.kind == "long").sum()) if len(closed) else 0, short_term_gain=round(st_gain_total), long_term_gain=round(lt_gain_total),
                wash_sales=washes, wash_loss_deferred=round(wash_amt), years_cash_negative=neg_cash), T_, pd.DataFrame(yearly)


def main(path, out, tbill):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    px = T.load(path); tb = pd.read_csv(tbill, parse_dates=["date"]).set_index("date")["rate"]; cash_r = T.cash_daily(px.index, tb).values
    print(f"data {px.index[0].date()} to {px.index[-1].date()}, {len(px)} sessions")
    configs = [("buy and hold 50% (left alone)", "hold", 0.50, False), ("buy and hold 50% (reset to 50% each year end)", "hold", 0.50, True),
               ("4% band system 75%", "band", 0.75, False), ("4% band system 50%", "band", 0.50, False),
               ("buy and hold 75% (reset to 75% each year end)", "hold", 0.75, True), ("plain 200-day system 75%", "plain", 0.75, False)]
    rows = []; keep = {}
    for dname, yld in (("price only", NO_YIELD), ("with assumed dividends", YIELD_ASSUMED)):
        for sname, rates in SCEN.items():
            for cname, rule, w, reset in configs:
                r, tr, yy = run(px, cash_r, positions(px, rule), w, reset, rates, yld, cname)
                rows.append({"dividends": dname, "tax": sname, **r})
                if dname == "price only" and sname.startswith("federal 24% / 15% + New"): keep[cname] = (tr, yy)
    R = pd.DataFrame(rows); R.to_csv(out / "after_tax_results.csv", index=False)
    for cname, (tr, yy) in keep.items():
        tag = cname.replace(" ", "_").replace("%", "").replace("(", "").replace(")", "").replace(",", "")
        tr.to_csv(out / f"trades_{tag}.csv", index=False); yy.to_csv(out / f"yearly_tax_{tag}.csv", index=False)
    pd.set_option("display.width", 300, "display.max_columns", 40, "display.max_rows", 500, "display.max_colwidth", 60)
    show = ["label", "final_value", "growth_per_year_pct", "max_drawdown_pct", "profit_per_year_over_drawdown", "worst_year_pct", "total_tax", "tax_share_of_gain_pct", "closed_trades", "long_term_trades", "wash_sales"]
    for dname in R.dividends.unique():
        for sname in SCEN:
            print(f"\n=== {dname} | {sname} ==="); print(R[(R.dividends == dname) & (R.tax == sname)][show].to_string(index=False))
    bt, by = keep["4% band system 75%"]
    print("\n=== 4% band 75% trade list summary (price only, with New Jersey) ==="); print(bt.groupby(["fund", "kind"]).agg(trades=("gain", "size"), gain=("gain", "sum"), avg_days=("days", "mean")).round(0).to_string())
    print("\n=== 4% band 75% yearly tax (price only, with New Jersey) ==="); print(by.to_string(index=False))
    print("\n=== buy and hold 50% (left alone) yearly (price only, with New Jersey) ==="); print(keep["buy and hold 50% (left alone)"][1].to_string(index=False))


if __name__ == "__main__":
    main(*sys.argv[1:4])
