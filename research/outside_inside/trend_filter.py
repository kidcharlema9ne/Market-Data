"""Outside day then inside day + 20-day efficiency-ratio trend filter. IN-SAMPLE ONLY (outside days 2007-12-31 .. 2021-08-06).

THE LAST 5 YEARS (outside days from 2021-11-08) ARE SEALED. This script never builds or evaluates a trade whose setup date is after 2021-08-06, and
an in-sample trade's 60-session path ends before 2021-11-08, so no sealed price bar is used. Unsealing needs a deliberate code change plus
Michael's say-so. (The window was opened once, for the 18-exit test in Entry 101, so it is no longer pristine for those exits.)

Efficiency ratio (Kaufman), 20 sessions by default (10 via the optional 4th argument), measured at the close of the inside day (known before the entry order):
    efficiency ratio = |close_today - close_20_sessions_ago| / sum of |daily close-to-close changes| over those 20 sessions   (0 = pure chop, 1 = straight line)
Trend direction = sign of close_today - close_20_sessions_ago. A trade is WITH the trend if a long has a positive 20-session change or a short a negative one.
Filters tested: no filter; with the trend at any efficiency; with the trend and efficiency >= 0.1 ... 0.7; and, as a diagnostic, AGAINST the trend at
efficiency >= 0.0 / 0.3 / 0.5 (if only the trend mattered, against-trend trades would do the opposite of with-trend trades).
Entry, stop, exits: as in exit_grid.py (outside-day break, stop at the outside day's far side, worst-case entry-bar rule). Six exits are used (the best
three in-sample from Entry 101 plus three reference exits). Controls get the same filters: A = outside days without an inside day; B = every fifth ordinary session.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import exit_grid as eg

ER_LOOKBACK = 20
LOOKBACKS = (10, 20)
THRESHOLDS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
AGAINST_THRESHOLDS = [0.0, 0.3, 0.5]
KEY_EXITS = [e for e in eg.EXITS if e[0] in (
    "hold until stopped (cap 60 sessions)", "time exit, close of session 40", "trail 4 ATR below the highest high",
    "time exit, close of session 20", "time exit, close of session 5", "target 1 risk unit (else stop, else session 20)")]
MAIN_EXIT = "hold until stopped (cap 60 sessions)"


def efficiency_arrays(close, n=ER_LOOKBACK):
    """Returns (efficiency ratio, signed net change) aligned to each bar; NaN until n sessions exist."""
    c = pd.Series(close)
    net = c - c.shift(n)
    path = c.diff().abs().rolling(n).sum()
    er = (net.abs() / path.replace(0, np.nan))
    return er.values, net.values


def add_trend(prices, lookbacks=LOOKBACKS):
    for s in prices.values():
        for n in lookbacks:
            s[f"er{n}"], s[f"net{n}"] = efficiency_arrays(s["c"], n)


def gen_trades(prices, symbols, kind, lookback=ER_LOOKBACK):
    out = []
    for sym in symbols:
        s = prices[sym]
        d, h, l = s["d"], s["h"], s["l"]
        for i in range(max(1, lookback), len(d) - 2):
            if d[i] > eg.IN_END:                       # SEALED: nothing after 2021-08-06 is ever built
                break
            if kind == "pattern":
                if not (h[i] > h[i - 1] and l[i] < l[i - 1] and h[i + 1] < h[i] and l[i + 1] > l[i]):
                    continue
                last_i, label = i + 1, "pattern"
            elif kind == "control A":
                if not (h[i] > h[i - 1] and l[i] < l[i - 1]) or (h[i + 1] < h[i] and l[i + 1] > l[i]):
                    continue
                last_i, label = i, "control A: outside day, no inside day"
            else:
                if i % eg.CONTROL_B_EVERY:
                    continue
                last_i, label = i, "control B: ordinary days"
            for direction in (1, -1):
                t = eg.build_trade(s, last_i, i, i, direction, "stopped")
                if t:
                    net = s[f"net{lookback}"][last_i]
                    if np.isnan(s[f"er{lookback}"][last_i]):
                        continue
                    t.update(symbol=sym, setup_date=d[i], group=label, er=s[f"er{lookback}"][last_i], entry_idx=last_i + 1,
                             with_trend=bool((direction == 1 and net > 0) or (direction == -1 and net < 0)))
                    out.append(t)
    return out


def evaluate(trades):
    rows = []
    for t in trades:
        base = dict(group=t["group"], symbol=t["symbol"], direction=t["direction"], setup_date=str(t["setup_date"]), er=t["er"],
                    with_trend=t["with_trend"], half="first" if t["setup_date"] <= eg.HALF_SPLIT else "second")
        for name, kind, param, cap in KEY_EXITS:
            r, sess, reason, mfe, mae = eg.run_exit(t, kind, param, cap)
            rows.append(dict(base, exit=name, result=r, sessions=sess))
    return pd.DataFrame(rows)


def filters(lookback=ER_LOOKBACK):
    f = [("no filter", lambda d: d["er"] >= 0)]
    f.append((f"with the {lookback}-day trend, any efficiency", lambda d: d["with_trend"]))
    for x in THRESHOLDS:
        f.append((f"with the trend, efficiency ratio >= {x}", (lambda x: lambda d: d["with_trend"] & (d["er"] >= x))(x)))
    for x in AGAINST_THRESHOLDS:
        f.append((f"AGAINST the trend, efficiency ratio >= {x} (diagnostic)", (lambda x: lambda d: ~d["with_trend"] & (d["er"] >= x))(x)))
    return f


def grid(df, lookback=ER_LOOKBACK):
    names = [e[0] for e in KEY_EXITS]
    rows = []
    for label, fn in filters(lookback):
        sub = df[fn(df)]
        if sub.empty:
            continue
        piv = sub.groupby("exit")["result"].mean()
        main = sub[sub["exit"] == MAIN_EXIT]
        row = dict(filter=label, trades=len(main), share_of_all=len(main) / (len(df) / len(names)),
                   main_exit_plus_minus_2se=2 * eg.cluster_se(main["result"], main["setup_date"]),
                   main_first_half=main[main["half"] == "first"]["result"].mean(), main_second_half=main[main["half"] == "second"]["result"].mean(),
                   win_rate_main=(main["result"] > 0).mean())
        for n in names:
            row[n] = piv.get(n, np.nan)
        rows.append(row)
    return pd.DataFrame(rows).set_index("filter")


def er_buckets(df):
    main = df[df["exit"] == MAIN_EXIT].copy()
    main["efficiency bucket"] = pd.cut(main["er"], [0, 0.2, 0.4, 0.6, 1.01], labels=["0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-1.0"], include_lowest=True)
    main["direction vs trend"] = np.where(main["with_trend"], "with trend", "against trend")
    t = main.groupby(["efficiency bucket", "direction vs trend"], observed=True)["result"].agg(trades="size", mean_result="mean")
    return t


def main(price_path, universe_path, out_dir, lookback=ER_LOOKBACK):
    os.makedirs(out_dir, exist_ok=True)
    prices = eg.load_prices(price_path)
    add_trend(prices)
    uni = pd.read_csv(universe_path, dtype=str)
    wanted = {eg.PRICE_ROOTS.get(x, x) for x in uni["ibkr"]}
    report = sorted(wanted & set(prices))
    log = []

    def emit(x):
        print(x)
        log.append(x)

    emit(f"Trend filter ({lookback}-day efficiency ratio), in-sample only: outside days 2007-12-31 to 2021-08-06. Last 5 years sealed.\n"
         "Results are mean result in risk units (1.0 = entry to the outside day's far-side stop), worst-case entry-bar rule, no costs.\n")
    res = {}
    for label, kind, syms in (("pattern", "pattern", report), ("control A", "control A", report), ("control B", "control B", report),
                              ("pattern, all vendor contracts", "pattern", sorted(prices))):
        df = evaluate(gen_trades(prices, syms, kind, lookback))
        res[label] = df
        if label == "pattern":
            df.to_csv(f"{out_dir}/pattern_report_universe_key_exits.csv.gz", index=False)
        n = len(df) // len(KEY_EXITS)
        emit(f"##### {label}: {n} trades (in-sample)")
    pd.set_option("display.width", 250)
    for label in res:
        g = grid(res[label], lookback)
        emit(f"\n=== {label.upper()}: mean result by filter and exit (in-sample); main exit = hold until stopped ===\n" + g.round(3).to_string())
    emit("\n=== PATTERN: hold-until-stopped mean result by efficiency bucket, with vs against the trend ===\n" + er_buckets(res["pattern"]).round(3).to_string())
    open(f"{out_dir}/trend_filter_results.txt", "w").write("\n".join(log))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else ER_LOOKBACK)
