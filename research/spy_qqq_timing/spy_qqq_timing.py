"""50% SPY + 50% QQQ: buy and hold versus each fund held only while above its own 200-day average (Michael, 19 Nov 2026).
Usage: python spy_qqq_timing.py PRICES OUT_DIR TBILL_CSV
PRICES is nasdaq_etfs.parquet (symbol, date_i, open, high, low, close, volume) or a csv with columns date, spy, qqq (optional spy_open, qqq_open).

RULES, FROZEN BEFORE THE SEALED YEARS (after 2021-08-06) WERE LOOKED AT. Nothing here is tuned on them.
  Three rules per fund: (a) buy and hold; (b) plain 200-day: in while close > simple 200-session average, else out;
  (c) 200-day with 4% band: enter when close > average x 1.04, leave when close < average x 0.96, otherwise keep the current state.
  Each fund is its own sleeve (half of the money), no rebalancing between funds. Out of a fund = 3-month Treasury bill interest (monthly FRED TB3MS, daily compounded).
  Invested share 100%, 75%, 50%: share w in the system, 1-w in Treasury bills, reset daily. No leverage.
  Timing: next_close = signal at the close, trade at the NEXT session's close (headline); signal_close = trade at the signal close (optimistic);
  next_open = trade at the next session's open (needs open prices; csv input without opens skips it).
  Periods: in-sample start 2000-10-16 to 2021-08-06; sealed 2021-08-09 to end of data; whole = both. Signals are always computed on the full history before each period."""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ANN = 252; SPLIT = pd.Timestamp("2021-08-06"); START = pd.Timestamp("2000-10-16")


def load(path):
    if str(path).endswith(".parquet"):
        import pyarrow.parquet as pq
        d = pq.read_table(path).to_pandas()
        d["date"] = pd.to_datetime(d["date_i"].astype("int64"), unit="D")
        out = {}
        for s in ("SPY", "QQQ"):
            x = d[d.symbol == s].drop_duplicates("date").set_index("date").sort_index()
            out[s.lower()] = x["close"]; out[s.lower() + "_open"] = x["open"]
        return pd.DataFrame(out).dropna(subset=["spy", "qqq"])
    return pd.read_csv(path, index_col=0, parse_dates=True).sort_index()


def band_state(p, n, b):
    a = p.rolling(n).mean(); up = (p > a * (1 + b)).values; dn = (p < a * (1 - b)).values; ok = a.notna().values
    out = np.zeros(len(p), bool); cur = False
    for i in range(len(p)):
        if not ok[i]: cur = False
        elif up[i]: cur = True
        elif dn[i]: cur = False
        out[i] = cur
    return pd.Series(out, index=p.index)


def signal(p, rule):
    if rule == "hold": return pd.Series(True, index=p.index)
    if rule == "plain": a = p.rolling(200).mean(); return (p > a).where(a.notna(), False)
    return band_state(p, 200, 0.04)


def cash_daily(idx, tb):
    m = tb.copy(); m.index = m.index.to_period("M")
    r = pd.Series(idx.to_period("M")).map(m).ffill().values / 100  # months after the last rate (Nov 2026) carry the last rate forward
    return pd.Series((1 + r) ** (1 / ANN) - 1, index=idx)


def sleeve_returns(px, sig, cash, timing, name):
    close = px[name]; ret = close.pct_change().fillna(0.0)
    if timing == "signal_close": pos = sig.shift(1).fillna(False).astype(bool); r = ret.where(pos, cash)
    elif timing == "next_close": pos = sig.shift(2).fillna(False).astype(bool); r = ret.where(pos, cash)
    else:
        op = px[name + "_open"]; pos = sig.shift(1).fillna(False).astype(bool); prev = pos.shift(1).fillna(False).astype(bool)
        full = ret; enter = close / op - 1; leave = op / close.shift(1) - 1
        r = pd.Series(np.where(pos & prev, full, np.where(pos & ~prev, enter, np.where(~pos & prev, leave, cash))), index=close.index)
    return r, pos


def combine(rs, rq):  # two sleeves, each half the money, never rebalanced
    eq = 0.5 * (1 + rs).cumprod() + 0.5 * (1 + rq).cumprod()
    return eq.pct_change().fillna(0.0)


def metrics(r, invested):
    eq = (1 + r).cumprod(); yrs = len(r) / ANN
    g = eq.iloc[-1] ** (1 / yrs) - 1
    dd = eq / eq.cummax() - 1; maxdd = dd.min()
    ye = eq.groupby(eq.index.year).last(); yp = ye.shift(1); yp.iloc[0] = 1.0; yr = ye / yp - 1
    me = eq.resample("ME").last(); mo = pd.concat([pd.Series([1.0]), me.reset_index(drop=True)]).pct_change().dropna()
    return {"years": round(yrs, 2), "average yearly return %": round(yr.mean() * 100, 2), "growth per year %": round(g * 100, 2),
            "best year %": round(yr.max() * 100, 1), "worst year %": round(yr.min() * 100, 1), "worst month %": round(mo.min() * 100, 1),
            "worst drawdown %": round(maxdd * 100, 1), "growth per year / worst drawdown": round(g / abs(maxdd), 2),
            "Sharpe (0% cash)": round(r.mean() / r.std() * np.sqrt(ANN), 2), "time invested %": round(float(invested.mean()) * 100, 1)}, yr


def main(path, out, tbill):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    px = load(path); tb = pd.read_csv(tbill, parse_dates=["date"]).set_index("date")["rate"]
    cash = cash_daily(px.index, tb); assert cash.notna().all(); have_open = "spy_open" in px and px["spy_open"].notna().mean() > 0.9
    print(f"data {px.index[0].date()} to {px.index[-1].date()}, {len(px)} sessions; opens: {have_open}")
    periods = {"in-sample": (START, SPLIT), "sealed": (SPLIT + pd.Timedelta(days=1), px.index[-1]), "whole": (START, px.index[-1])}
    rows = []; yearly = []; curves = {}
    for timing in ("next_close", "signal_close") + (("next_open",) if have_open else ()):
        for rule in ("hold", "plain", "band"):
            sigs, poss, rets = {}, {}, {}
            for f in ("spy", "qqq"):
                sg = signal(px[f], rule); rets[f], poss[f] = sleeve_returns(px, sg, cash, timing, f)
            base = combine(rets["spy"], rets["qqq"]); inv = (poss["spy"].astype(float) + poss["qqq"].astype(float)) / 2
            ent = {f: int((poss[f].astype(int).diff() == 1).sum()) for f in ("spy", "qqq")}
            for w in (1.0, 0.75, 0.5):
                r = w * base + (1 - w) * cash
                if timing == "next_close": curves[f"{rule}_{int(w*100)}"] = (1 + r.loc[START:]).cumprod() * 500000  # output only, no rule change
                for pn, (a, b) in periods.items():
                    if len(r.loc[a:b]) < 20: continue
                    m, yr = metrics(r.loc[a:b], inv.loc[a:b])
                    e = {f: int(((poss[f].astype(int).diff() == 1).loc[a:b]).sum()) for f in ("spy", "qqq")}
                    m["entries per year (both funds)"] = round((e["spy"] + e["qqq"]) / m["years"], 1) if rule != "hold" else 0
                    rows.append({"timing": timing, "rule": rule, "invested": int(w * 100), "period": pn, **m})
                    if pn != "whole":
                        for y, v in yr.items(): yearly.append({"timing": timing, "rule": rule, "invested": int(w * 100), "period": pn, "year": int(y), "return %": round(v * 100, 1)})
    R = pd.DataFrame(rows); Y = pd.DataFrame(yearly)
    pd.DataFrame(curves).round(0).to_csv(out / "equity_curves_500k.csv")
    R.to_csv(out / "results.csv", index=False); Y.to_csv(out / "yearly.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 500)
    key = ["timing", "rule", "invested", "period", "average yearly return %", "growth per year %", "best year %", "worst year %", "worst month %", "worst drawdown %", "growth per year / worst drawdown", "entries per year (both funds)", "years"]
    for t in R.timing.unique():
        print(f"\n=== timing {t} ==="); print(R[R.timing == t][key].to_string(index=False))
    print("\n=== calendar years, next_close, 50% invested, sealed period ===")
    if "sealed" not in set(R.period): return
    s = Y[(Y.timing == "next_close") & (Y.invested == 50) & (Y.period == "sealed")].pivot(index="year", columns="rule", values="return %"); print(s.to_string())
    print("\n=== calendar years, next_close, 100% invested, sealed period ===")
    s = Y[(Y.timing == "next_close") & (Y.invested == 100) & (Y.period == "sealed")].pivot(index="year", columns="rule", values="return %"); print(s.to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
