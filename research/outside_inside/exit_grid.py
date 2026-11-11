"""Outside day then inside day: which exit works? In-sample 2008-2021 selection, one-time out-of-sample test on the last 5 years.

Entry and stop (Michael, 11 Nov 2026): after a strict outside day and a strict inside day, buy the break of the outside day's HIGH
(sell the break of its LOW), entry order live for the one session after the inside day. Initial stop = the outside day's opposite extreme.
Risk unit = entry to initial stop. No costs.

Sample split (fixed before any result was seen; decided by the date of the outside day)
- in-sample: outside days 2007-12-31 .. 2021-08-06 (used to rank and choose exits)
- purge: 2021-08-07 .. 2021-11-07 (excluded, so no in-sample trade's holding period reaches into the test years)
- out-of-sample: outside days 2021-11-08 .. data end (the last 5 years; looked at ONCE, for the finalists chosen in-sample)
Trades whose 60-session path would run past the data end or across a data hole are dropped from every exit alike.
CAUTION: the 2022-11..2026-11 stretch of the out-of-sample window was already seen in earlier runs (entry and stop only, and plain time exits),
so the out-of-sample years are clean for the exit choice but not for the entry-and-stop rule itself.

Exit menu (declared in advance; 18 exits). Every exit keeps the initial stop. Stops are checked before targets on any bar; a stop updated at a
bar's close applies from the next bar; gaps through a stop fill at the open; a target gapped through fills at the open.
- time exit at the close of session 3 / 5 / 10 / 20 / 40
- fixed target of 1 / 2 / 3 risk units, else the stop, else the close of session 20
- trailing stop under the lowest low of the last 3 / 5 / 10 sessions (for shorts the highest high), cap 60 sessions
- trailing stop 2 / 3 / 4 ATR below the highest high since entry (ATR = mean true range of the 14 sessions ending at the setup's last bar), cap 60
- move the stop to the entry price once price has traded 1 risk unit in favor, then exit at the close of session 20 / or trail the 5-session low (cap 60)
- exit at the close when the close breaks the prior session's low (high for shorts), cap 60
- hold until stopped, cap 60
Entry-bar ambiguity: worst case (default) counts a non-gap entry bar that reaches the stop as stopped out; the best case (assume that low came before the break)
is run for the finalists only.
Controls (same exits, same stop style): (A) outside days NOT followed by an inside day, entered on the break the next session; (B) every fifth ordinary session,
break of that day's high / low with that day's far side as the stop. They show whether the inside day adds anything.
Selection rule: rank exits by in-sample mean result in risk units; finalists = best 3 whose mean is positive in BOTH halves of the in-sample years (2008-2014, 2015-2021).
"""
import os
import sys
import numpy as np
import pandas as pd

PRICE_ROOTS = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6",
               "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
CAP = 60
MAX_CALENDAR_GAP = 5
IN_END = np.datetime64("2021-08-06")
OUT_START = np.datetime64("2021-11-08")
HALF_SPLIT = np.datetime64("2014-12-31")
CONTROL_B_EVERY = 5

EXITS = [
    ("time exit, close of session 3", "time", 3, 3),
    ("time exit, close of session 5", "time", 5, 5),
    ("time exit, close of session 10", "time", 10, 10),
    ("time exit, close of session 20", "time", 20, 20),
    ("time exit, close of session 40", "time", 40, 40),
    ("target 1 risk unit (else stop, else session 20)", "target", 1.0, 20),
    ("target 2 risk units (else stop, else session 20)", "target", 2.0, 20),
    ("target 3 risk units (else stop, else session 20)", "target", 3.0, 20),
    ("trail under the 3-session low", "trail_low", 3, CAP),
    ("trail under the 5-session low", "trail_low", 5, CAP),
    ("trail under the 10-session low", "trail_low", 10, CAP),
    ("trail 2 ATR below the highest high", "chandelier", 2.0, CAP),
    ("trail 3 ATR below the highest high", "chandelier", 3.0, CAP),
    ("trail 4 ATR below the highest high", "chandelier", 4.0, CAP),
    ("stop to entry after +1 risk unit, exit session 20", "be_time", 1.0, 20),
    ("stop to entry after +1 risk unit, then trail 5-session low", "be_trail", 1.0, CAP),
    ("exit when the close breaks the prior session's extreme", "close_break", 0, CAP),
    ("hold until stopped (cap 60 sessions)", "hold", 0, CAP),
]


def load_prices(path):
    px = pd.read_csv(path) if str(path).endswith((".csv", ".csv.gz")) else pd.read_parquet(path)
    px["date"] = pd.to_datetime(px["file_date"])
    n0 = len(px)
    px = px.dropna(subset=["open", "high", "low", "close"])
    px = px[(px["high"] >= px["low"]) & (px["high"] > 0) & (px["low"] > 0)]
    px = px.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    print(f"price rows {n0} -> {len(px)}; symbols {px['symbol'].nunique()}; {px['date'].min().date()} to {px['date'].max().date()}")
    out = {}
    for sym, g in px.groupby("symbol"):
        s = dict(d=g["date"].values.astype("datetime64[D]"), o=g["open"].values.astype(float), h=g["high"].values.astype(float),
                 l=g["low"].values.astype(float), c=g["close"].values.astype(float))
        pc = np.r_[np.nan, s["c"][:-1]]
        s["tr"] = np.maximum.reduce([s["h"] - s["l"], np.abs(s["h"] - pc), np.abs(s["l"] - pc)])
        out[sym] = s
    return out


def sample_of(day):
    if day <= IN_END:
        return "in"
    if day >= OUT_START:
        return "out"
    return "purge"


def build_trade(s, last_i, trig_i, stop_i, direction, rule):
    """Order live for the one session after last_i. Trigger = extreme of bar trig_i, stop = opposite extreme of bar stop_i."""
    n, d = len(s["c"]), s["d"]
    j = last_i + 1
    if j + CAP - 1 > n - 1 or last_i < 14:
        return None
    if np.any(np.diff(d[last_i:j + CAP]).astype(int) > MAX_CALENDAR_GAP):
        return None
    if direction == 1:
        o, h, l, c = s["o"], s["h"], s["l"], s["c"]
        trigger, stop = s["h"][trig_i], s["l"][stop_i]
    else:
        o, h, l, c = -s["o"], -s["l"], -s["h"], -s["c"]
        trigger, stop = -s["l"][trig_i], -s["h"][stop_i]
    if h[j] < trigger:
        return None
    entry = max(o[j], trigger)
    risk = entry - stop
    atr = float(np.nanmean(s["tr"][last_i - 13:last_i + 1]))
    if risk <= 0 or not atr > 0:
        return None
    gap_fill = o[j] >= trigger
    ignore_low = (rule == "ignored") and not gap_fill
    stopped_entry = bool(l[j] <= stop and not ignore_low)
    sl = slice(j, j + CAP)
    return dict(path=(o[sl].tolist(), h[sl].tolist(), l[sl].tolist(), c[sl].tolist()), entry=entry, stop=stop, risk=risk, atr=atr, ignore_low=ignore_low,
                stopped_entry=stopped_entry, direction="long" if direction == 1 else "short", entry_date=d[j],
                risk_pct=risk / abs(entry) * 100)


def run_exit(t, kind, param, cap):
    if t["stopped_entry"]:
        return -1.0, 1, "stopped on entry bar", 0.0, 1.0
    po, ph, pl, pc = t["path"]
    entry, risk, atr = t["entry"], t["risk"], t["atr"]
    stop = t["stop"]
    target = entry + param * risk if kind == "target" else None
    reached = False
    mfe = mae = 0.0
    exit_price, reason, sessions = None, "time", cap
    for k in range(cap):
        sess = k + 1
        if k > 0:
            if po[k] <= stop:
                exit_price, reason, sessions = po[k], "stop", sess
                break
            if pl[k] <= stop:
                exit_price, reason, sessions = stop, "stop", sess
                break
        mfe = max(mfe, (ph[k] - entry) / risk)
        if not (k == 0 and t["ignore_low"]):
            mae = max(mae, (entry - pl[k]) / risk)
        if target is not None and ph[k] >= target:
            exit_price, reason, sessions = max(po[k], target), "target", sess
            break
        if kind == "trail_low" and sess >= param:
            stop = max(stop, min(pl[k - param + 1:k + 1]))
        elif kind == "be_trail" and reached and sess >= 5:
            stop = max(stop, min(pl[k - 4:k + 1]))
        elif kind == "chandelier":
            stop = max(stop, max(ph[:k + 1]) - param * atr)
        if kind in ("be_time", "be_trail") and not reached and ph[k] >= entry + param * risk:
            reached = True
            stop = max(stop, entry)
        if kind == "close_break" and k >= 1 and pc[k] < pl[k - 1]:
            exit_price, reason, sessions = pc[k], "close break", sess
            break
        if sess == cap:
            exit_price, reason, sessions = pc[k], "time", sess
            break
    if reason == "stop":
        mae = max(mae, (entry - exit_price) / risk)
    return (exit_price - entry) / risk, sessions, reason, mfe, mae


def pattern_trades(prices, symbols, rule):
    out = []
    for sym in symbols:
        s = prices[sym]
        d, h, l = s["d"], s["h"], s["l"]
        for i in range(1, len(d) - 2):
            if not (h[i] > h[i - 1] and l[i] < l[i - 1] and h[i + 1] < h[i] and l[i + 1] > l[i]):
                continue
            for direction in (1, -1):
                t = build_trade(s, i + 1, i, i, direction, rule)
                if t:
                    t.update(symbol=sym, setup_date=d[i], group="pattern")
                    out.append(t)
    return out


def control_a_trades(prices, symbols, rule):
    out = []
    for sym in symbols:
        s = prices[sym]
        d, h, l = s["d"], s["h"], s["l"]
        for i in range(1, len(d) - 2):
            if not (h[i] > h[i - 1] and l[i] < l[i - 1]):
                continue
            if h[i + 1] < h[i] and l[i + 1] > l[i]:
                continue                                    # that is the real pattern, not a control
            for direction in (1, -1):
                t = build_trade(s, i, i, i, direction, rule)
                if t:
                    t.update(symbol=sym, setup_date=d[i], group="control A: outside day, no inside day")
                    out.append(t)
    return out


def control_b_trades(prices, symbols, rule):
    out = []
    for sym in symbols:
        s = prices[sym]
        d = s["d"]
        for i in range(15, len(d) - 1, CONTROL_B_EVERY):
            for direction in (1, -1):
                t = build_trade(s, i, i, i, direction, rule)
                if t:
                    t.update(symbol=sym, setup_date=d[i], group="control B: ordinary days")
                    out.append(t)
    return out


def evaluate(trades, exits=EXITS):
    rows = []
    for t in trades:
        smp = sample_of(t["setup_date"])
        if smp == "purge":
            continue
        base = dict(sample=smp, group=t["group"], symbol=t["symbol"], direction=t["direction"], setup_date=str(t["setup_date"]),
                    half="first" if t["setup_date"] <= HALF_SPLIT else "second", risk_in_atr=t["risk"] / t["atr"])
        for name, kind, param, cap in exits:
            r, sess, reason, mfe, mae = run_exit(t, kind, param, cap)
            rows.append(dict(base, exit=name, result=r, result_atr=r * t["risk"] / t["atr"], sessions=sess, reason=reason, mfe=mfe, mae=mae))
    return pd.DataFrame(rows)


def cluster_se(x, groups):
    x = np.asarray(x, float)
    dev = pd.Series(x - x.mean()).groupby(np.asarray(groups)).sum()
    return float(np.sqrt((dev ** 2).sum()) / len(x))


def stats(g):
    x = g["result"]
    wins, losses = x[x > 0].sum(), -x[x < 0].sum()
    return pd.Series(dict(trades=len(g), mean_result=x.mean(), plus_minus_2se=2 * cluster_se(x, g["setup_date"]), median=x.median(),
                          win_rate=(x > 0).mean(), profit_factor=wins / losses if losses > 0 else np.nan, mean_in_atr=g["result_atr"].mean(),
                          avg_sessions=g["sessions"].mean(), avg_worst_dip=g["mae"].mean(), avg_best_run=g["mfe"].mean(),
                          exited_on_a_stop_or_trail=g["reason"].isin(["stop", "stopped on entry bar"]).mean()))


def table(df, order=None):
    t = df.groupby("exit").apply(stats, include_groups=False)
    t["first_half_mean"] = df[df["half"] == "first"].groupby("exit")["result"].mean()
    t["second_half_mean"] = df[df["half"] == "second"].groupby("exit")["result"].mean()
    t["long_mean"] = df[df["direction"] == "long"].groupby("exit")["result"].mean()
    t["short_mean"] = df[df["direction"] == "short"].groupby("exit")["result"].mean()
    if order is not None:
        t = t.loc[[x for x in order if x in t.index]]
    return t


def show(t):
    return t.round(3).to_string()


def main(price_path, universe_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    prices = load_prices(price_path)
    uni = pd.read_csv(universe_path, dtype=str)
    wanted = {PRICE_ROOTS.get(x, x) for x in uni["ibkr"]}
    report = sorted(wanted & set(prices))
    allsyms = sorted(prices)
    print(f"report universe {len(report)} markets (no price series: {sorted(wanted - set(prices))}); all contracts {len(allsyms)}")
    log = []

    def emit(text):
        print(text)
        log.append(text)

    emit("Exit grid: outside day then inside day; stop on the outside day's far side; in-sample outside days to 2021-08-06, "
         "purge to 2021-11-07, out-of-sample from 2021-11-08.\n")
    results = {}
    for uname, syms in (("report universe", report), ("all vendor contracts", allsyms)):
        pat = evaluate(pattern_trades(prices, syms, "stopped"))
        if uname == "report universe":
            ca = evaluate(control_a_trades(prices, syms, "stopped"))
            cb = evaluate(control_b_trades(prices, syms, "stopped"))
        else:
            ca = cb = pd.DataFrame(columns=pat.columns)
        results[uname] = (pat, ca, cb)
        pat.to_csv(f"{out_dir}/pattern_{uname.replace(' ', '_')}_all_exits.csv.gz", index=False)
        n_in = pat[pat['sample'] == 'in'].drop_duplicates(['symbol', 'setup_date', 'direction']).shape[0]
        n_out = pat[pat['sample'] == 'out'].drop_duplicates(['symbol', 'setup_date', 'direction']).shape[0]
        emit(f"##### {uname}: pattern trades in-sample {n_in}, out-of-sample {n_out}"
             + (f"; control A {ca.drop_duplicates(['symbol','setup_date','direction']).shape[0]}, control B {cb.drop_duplicates(['symbol','setup_date','direction']).shape[0]} (both samples)" if len(ca) else "") + "\n")

    pat, ca, cb = results["report universe"]
    ins = table(pat[pat["sample"] == "in"]).sort_values("mean_result", ascending=False)
    emit("=== IN-SAMPLE (2008 to mid-2021), report universe, all 18 exits ranked by mean result in risk units (worst-case entry-bar rule) ===\n" + show(ins) + "\n")
    ok = ins[(ins["first_half_mean"] > 0) & (ins["second_half_mean"] > 0)]
    finalists = list(ok.index[:3])
    emit(f"Finalists (best 3 in-sample whose mean is positive in both halves): {finalists if finalists else 'NONE - no exit is positive in both in-sample halves'}\n")
    n_exits = len(EXITS)
    emit(f"Multiple-testing note: {n_exits} exits were compared in-sample; the best of {n_exits} looks better than it is. The out-of-sample test is the check.\n")

    out_all = table(pat[pat["sample"] == "out"], order=list(ins.index))
    if finalists:
        emit("=== OUT-OF-SAMPLE (last 5 years), report universe, FINALISTS ONLY (worst-case rule) ===\n" + show(out_all.loc[finalists]) + "\n")
        best = evaluate([t for t in pattern_trades(prices, report, "ignored")], [e for e in EXITS if e[0] in finalists])
        emit("=== FINALISTS, best-case entry-bar rule (in-sample then out-of-sample) ===\n"
             + show(table(best[best['sample'] == 'in'])) + "\n--\n" + show(table(best[best['sample'] == 'out'])) + "\n")
        for uname in ("all vendor contracts",):
            p2 = results[uname][0]
            emit(f"=== FINALISTS on {uname}: in-sample then out-of-sample ===\n"
                 + show(table(p2[(p2['sample'] == 'in') & p2['exit'].isin(finalists)])) + "\n--\n"
                 + show(table(p2[(p2['sample'] == 'out') & p2['exit'].isin(finalists)])) + "\n")
        comp = []
        for label, df in (("pattern", pat), ("control A: outside day, no inside day", ca), ("control B: ordinary days", cb)):
            for smp in ("in", "out"):
                sub = df[(df["sample"] == smp) & df["exit"].isin(finalists)]
                tt = sub.groupby("exit")["result"].agg(["size", "mean"]).rename(columns={"size": "trades", "mean": "mean_result"})
                tt["group"], tt["sample"] = label, smp
                comp.append(tt.reset_index())
        emit("=== DOES THE INSIDE DAY ADD ANYTHING? finalist exits on the pattern vs the two controls (mean result, risk units) ===\n"
             + pd.concat(comp).set_index(["exit", "sample", "group"]).round(3).to_string() + "\n")
    emit("=== OUT-OF-SAMPLE, ALL 18 exits (for completeness ONLY; selection was frozen in-sample; do not pick from this) ===\n" + show(out_all) + "\n")
    emit("=== Full 18-exit grid for the controls, in-sample then out-of-sample mean result (risk units) ===\n"
         + pd.concat({n: pd.concat({s: df[df['sample'] == s].groupby('exit')['result'].mean() for s in ('in', 'out')}, axis=1)
                      for n, df in (("control A", ca), ("control B", cb))}, axis=1).round(3).to_string() + "\n")
    open(f"{out_dir}/exit_grid_results.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
