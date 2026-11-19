"""Multi-ETF portfolio that leaves each fund when it falls below its own 200-day average with a 4% band (Michael, 19 Nov 2026).
Usage: python etf_portfolio_timing.py PRICES OUT_DIR TBILL_CSV
PRICES = portfolio_etfs.parquet (symbol, date_i, open, high, low, close, volume).

RULES (same as the SPY/QQQ system, applied to six funds): SPY, QQQ, VEA (developed markets), VWO (emerging markets), IAU (gold), BIV (intermediate bonds).
  Each fund is held only while the price is above its own 200-session average with a 4% band: enter when close > average x 1.04, leave when close < average x 0.96, else keep state.
  Signal at the close, trade at the NEXT session's close. Money not in a fund earns the 3-month Treasury bill rate (FRED TB3MS monthly, daily compounded; stands in for SGOV).
  Each fund is a sleeve with a target weight; the leftover weight is a permanent Treasury bill sleeve. Sleeves are rebalanced to target on the first session of each year. No leverage, no costs, no taxes.
  PRICE ONLY: no dividends (hurts buy and hold of bonds and international funds most). Treasury bill interest is included.
  Common window starts once every fund has 200 sessions of history. In-sample = start to 2021-08-06; later = after 2021-08-06 (the SPY/QQQ rules were already looked at there, so this is NOT a sealed test).
  Equal-risk weights use only in-sample volatility, no returns."""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ANN = 252; SPLIT = pd.Timestamp("2021-08-06")
FUNDS = ["SPY", "QQQ", "VEA", "VWO", "IAU", "BIV"]
NAMES = {"SPY": "US large (SPY)", "QQQ": "Nasdaq 100 (QQQ)", "VEA": "Developed intl (VEA)", "VWO": "Emerging (VWO)", "IAU": "Gold (IAU)", "BIV": "Intermediate bonds (BIV)"}


def load(path):
    if str(path).endswith(".csv"):
        d = pd.read_csv(path)  # testing path: columns symbol, date_i, close
    else:
        import pyarrow.parquet as pq
        d = pq.read_table(path).to_pandas()
    d["date"] = pd.to_datetime(d["date_i"].astype("int64"), unit="D")
    px = d.drop_duplicates(["symbol", "date"]).pivot(index="date", columns="symbol", values="close").sort_index()
    px = px[px["SPY"].notna()]
    return px.ffill(limit=3)


def band_state(p, n=200, b=0.04):
    a = p.rolling(n).mean(); up = (p > a * (1 + b)).values; dn = (p < a * (1 - b)).values; ok = a.notna().values
    out = np.zeros(len(p), bool); cur = False
    for i in range(len(p)):
        if not ok[i]: cur = False
        elif up[i]: cur = True
        elif dn[i]: cur = False
        out[i] = cur
    return pd.Series(out, index=p.index)


def signal(px, f, rule):
    p = px[f].dropna()
    if rule == "hold":
        a = p.rolling(200).mean(); s = a.notna()  # in from the first day a 200-session average exists, so the three rules share a start
    elif rule == "plain":
        a = p.rolling(200).mean(); s = (p > a) & a.notna()
    else:
        s = band_state(p)
    return s.reindex(px.index, fill_value=False).astype(bool)


def first_ok(px, f):
    p = px[f].dropna(); return p.index[199]


def cash_daily(idx, tb):
    m = tb.copy(); m.index = m.index.to_period("M")
    r = pd.Series(idx.to_period("M")).map(m).ffill().values / 100
    return pd.Series((1 + r) ** (1 / ANN) - 1, index=idx)


def sleeve(px, cash, f, rule):
    ret = px[f].pct_change().fillna(0.0); sig = signal(px, f, rule); pos = sig.shift(2, fill_value=False).astype(bool)
    return ret.where(pos, cash), pos


def portfolio(rets, weights):
    cols = list(weights); w = np.array([weights[c] for c in cols], float); R = rets[cols].values; yrs = rets.index.year
    V = w.copy(); out = np.empty(len(R))
    for i in range(len(R)):
        if i > 0 and yrs[i] != yrs[i - 1]: V = V.sum() * w
        V = V * (1 + R[i]); out[i] = V.sum()
    eq = pd.Series(out, index=rets.index)
    return eq / eq.shift(1, fill_value=1.0) - 1


def metrics(r):
    eq = (1 + r).cumprod(); yrs = len(r) / ANN; g = eq.iloc[-1] ** (1 / yrs) - 1
    dd = eq / eq.cummax() - 1; maxdd = dd.min()
    ye = eq.groupby(eq.index.year).last(); yp = ye.shift(1); yp.iloc[0] = 1.0; yr = ye / yp - 1
    return {"years": round(yrs, 1), "profit per year %": round(g * 100, 2), "max drawdown %": round(maxdd * 100, 1),
            "profit / max drawdown": round(g / abs(maxdd), 2) if maxdd < 0 else np.nan, "worst calendar year %": round(yr.min() * 100, 1),
            "Sharpe ratio": round(r.mean() / r.std() * np.sqrt(ANN), 2) if r.std() > 0 else np.nan}, yr


def main(path, out, tbill):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    px = load(path); tb = pd.read_csv(tbill, parse_dates=["date"]).set_index("date")["rate"]
    cash = cash_daily(px.index, tb); assert cash.notna().all()
    funds = [f for f in FUNDS if f in px.columns]; assert len(funds) == len(FUNDS), f"missing funds: {set(FUNDS) - set(funds)}"
    print("DATA CHECK (close prices; if bond/intl first-to-last change looks too small they are price only)")
    for s in px.columns:
        p = px[s].dropna(); gaps = int((p.index.to_series().diff().dt.days > 6).sum())
        print(f"  {s}: {p.index[0].date()} to {p.index[-1].date()}, {len(p)} sessions, first close {p.iloc[0]:.2f}, last close {p.iloc[-1]:.2f}, gaps over 6 days: {gaps}")
    start = max(first_ok(px, f) for f in funds)
    periods = {"in-sample": (start, SPLIT), "after 6 Aug 2021": (SPLIT + pd.Timedelta(days=1), px.index[-1]), "whole common window": (start, px.index[-1])}
    print(f"\ncommon window starts {start.date()} (every fund has 200 sessions of history), ends {px.index[-1].date()}")
    rules = {"buy and hold": "hold", "plain 200-day": "plain", "200-day with 4% band": "band"}
    S = {rn: {f: sleeve(px, cash, f, rk) for f in funds} for rn, rk in rules.items()}

    # ---- each fund alone (100% in that fund, rest bills) ----
    rows = []
    for f in funds:
        own = first_ok(px, f)
        for rn in rules:
            r, pos = S[rn][f]
            for pn, (a, b) in {"own full history": (own, px.index[-1]), **periods}.items():
                x = r.loc[a:b]
                if len(x) < 60: continue
                m, _ = metrics(x); ent = int((pos.astype(int).diff() == 1).loc[a:b].sum())
                rows.append({"fund": NAMES[f], "rule": rn, "period": pn, **m, "time invested %": round(float(pos.loc[a:b].mean()) * 100, 1), "entries per year": round(ent / m["years"], 1) if rn != "buy and hold" else 0})
    A = pd.DataFrame(rows); A.to_csv(out / "each_fund.csv", index=False)

    # ---- equal-risk weights from in-sample volatility of buy-and-hold daily returns (no returns used) ----
    vol = {f: S["buy and hold"][f][0].loc[start:SPLIT].std() for f in funds}; inv = {f: 1 / v for f, v in vol.items()}; tot = sum(inv.values())
    equal_risk = {f: inv[f] / tot for f in funds}
    allocs = {
        "Current two-fund system (SPY 37.5, QQQ 37.5, bills 25)": {"SPY": .375, "QQQ": .375, "bills": .25},
        "Equal split of six funds": {f: 1 / 6 for f in funds},
        "Stock-heavy (SPY 25, QQQ 10, VEA 15, VWO 5, gold 10, BIV 25, bills 10)": {"SPY": .25, "QQQ": .10, "VEA": .15, "VWO": .05, "IAU": .10, "BIV": .25, "bills": .10},
        "Balanced (SPY 20, QQQ 5, VEA 10, VWO 5, gold 10, BIV 30, bills 20)": {"SPY": .20, "QQQ": .05, "VEA": .10, "VWO": .05, "IAU": .10, "BIV": .30, "bills": .20},
        "Equal risk (in-sample volatility weights)": equal_risk,
    }
    print("\nEqual-risk weights %:", {f: round(float(w) * 100, 1) for f, w in equal_risk.items()}); print("in-sample daily volatility %:", {f: round(float(v) * 100, 2) for f, v in vol.items()})
    rows = []; yearly = []; curves = {}
    for an, w in allocs.items():
        assert abs(sum(w.values()) - 1) < 1e-9, an
        for rn in rules:
            R = pd.DataFrame({f: S[rn][f][0] for f in funds}); R["bills"] = cash
            r = portfolio(R, w)
            pos = pd.DataFrame({f: S[rn][f][1] for f in funds}); wi = sum(w.get(f, 0) * pos[f].astype(float) for f in funds) / max(sum(w.get(f, 0) for f in funds), 1e-9)
            curves[f"{an} | {rn}"] = (1 + r.loc[start:]).cumprod() * 500000
            for pn, (a, b) in periods.items():
                m, yr = metrics(r.loc[a:b]); ent = sum(int((pos[f].astype(int).diff() == 1).loc[a:b].sum()) for f in funds if w.get(f, 0) > 0)
                rows.append({"allocation": an, "rule": rn, "period": pn, **m, "average share of risk funds held %": round(float(wi.loc[a:b].mean()) * 100, 1), "entries per year (all funds)": round(ent / m["years"], 1) if rn != "buy and hold" else 0})
                if pn == "whole common window":
                    for y, v in yr.items(): yearly.append({"allocation": an, "rule": rn, "year": int(y), "return %": round(v * 100, 1)})
    P = pd.DataFrame(rows); Y = pd.DataFrame(yearly)
    P.to_csv(out / "portfolios.csv", index=False); Y.to_csv(out / "portfolios_yearly.csv", index=False)
    pd.DataFrame(curves).round(0).to_csv(out / "equity_curves_500k.csv")
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 800, "display.max_colwidth", 70)
    print("\n=== EACH FUND ALONE (100% in the fund, otherwise Treasury bills) ===")
    for pn in ["own full history", "whole common window", "in-sample", "after 6 Aug 2021"]:
        print(f"\n-- {pn} --"); print(A[A.period == pn].drop(columns="period").to_string(index=False))
    print("\n=== PORTFOLIOS (annual rebalance) ===")
    for pn in periods:
        print(f"\n-- {pn} --"); print(P[P.period == pn].drop(columns="period").to_string(index=False))
    print("\n=== calendar year returns %, 200-day with 4% band, whole common window ===")
    print(Y[Y.rule == "200-day with 4% band"].pivot(index="year", columns="allocation", values="return %").to_string())
    print("\n=== calendar year returns %, buy and hold, whole common window ===")
    print(Y[Y.rule == "buy and hold"].pivot(index="year", columns="allocation", values="return %").to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
