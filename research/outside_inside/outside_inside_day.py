"""Outside day followed by an inside day: break of the outside day, stop at the inside day's far side (futures, daily bars).

Setup (all strict, daily bars)
- Outside day: high above the prior day's high AND low below the prior day's low.
- Inside day: the next session; high below the outside day's high AND low above the outside day's low.
- Long trade: buy the break of the outside day's HIGH. Stop (risk) = the inside day's LOW.
- Short trade: sell the break of the outside day's LOW. Stop (risk) = the inside day's HIGH.
- The entry order is live from the session after the inside day for ENTRY_WINDOW sessions (primary 1, variant 5). It is cancelled if
  the stop level trades before the trigger does. A session that opens beyond the trigger fills at the open (gap fill).
- Entry session = session 1. A time exit is at the close of session 5 / 10 / 20.

Daily bars cannot show the order of the high and the low inside one bar. Conservative rules used everywhere:
- Entry bar not a gap and its range touches the stop: counted as stopped out (flagged ambiguous_entry_bar).
- On a later bar that reaches both stop and target, the stop is taken first.
- The bar on which the stop is hit adds no favorable excursion.
- Entry-bar adverse excursion counts the entry bar's whole low (worst case, since the low may have come before the entry).
- Entry-bar high counts toward favorable excursion and targets (the break itself is the high), a mild optimism noted in the output.

Units: risk unit (1.0 = entry to stop), ATR (mean true range of the 14 sessions ending at the inside day) and percent of entry price.
No costs or slippage. Prices are vendor ratio back-adjusted continuous bars. Long and short are separate hypothetical trades.
"""
import sys
import numpy as np
import pandas as pd

PRICE_ROOTS = {"6A": "A6", "6B": "B6", "6C": "AD", "6E": "E6", "6J": "J1", "6L": "BR", "6M": "MP", "6N": "N6",
               "6S": "E1", "ZB": "US", "BRR": "BTC", "LBR": "LBS"}
HORIZONS = (5, 10, 20)
TARGETS = (0.5, 1.0, 1.5, 2.0, 3.0)
MAX_SESSIONS = 20
YEARS = 4
MAX_CALENDAR_GAP = 5          # a hole longer than this between consecutive bars breaks a setup


def load_prices(path):
    px = pd.read_csv(path) if str(path).endswith((".csv", ".csv.gz")) else pd.read_parquet(path)
    px["date"] = pd.to_datetime(px["file_date"])
    n0 = len(px)
    px = px.dropna(subset=["open", "high", "low", "close"])
    px = px[(px["high"] >= px["low"]) & (px["high"] > 0) & (px["low"] > 0)]
    dup = int(px.duplicated(["symbol", "date"], keep=False).sum())
    px = px.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])
    print(f"price rows {n0} -> {len(px)} (duplicate symbol-date rows seen: {dup}); symbols {px['symbol'].nunique()}; "
          f"{px['date'].min().date()} to {px['date'].max().date()}")
    out = {}
    for sym, g in px.groupby("symbol"):
        s = dict(d=g["date"].values.astype("datetime64[D]"), o=g["open"].values.astype(float),
                 h=g["high"].values.astype(float), l=g["low"].values.astype(float), c=g["close"].values.astype(float))
        pc = np.r_[np.nan, s["c"][:-1]]
        s["tr"] = np.maximum.reduce([s["h"] - s["l"], np.abs(s["h"] - pc), np.abs(s["l"] - pc)])
        out[sym] = s
    return out


def simulate(s, outside_i, direction, entry_window, entry_bar_rule="stopped"):
    """One hypothetical trade. Returns a dict, or None if the order never filled. direction = +1 long, -1 short."""
    inside_i = outside_i + 1
    sign = direction
    # Work in a long-only frame: for a short, flip prices so that the same code applies.
    if sign == 1:
        o, h, l, c = s["o"], s["h"], s["l"], s["c"]
        trigger, stop = s["h"][outside_i], s["l"][inside_i]
    else:
        o, h, l, c = -s["o"], -s["l"], -s["h"], -s["c"]
        trigger, stop = -s["l"][outside_i], -s["h"][inside_i]
    n = len(c)
    d = s["d"]
    entry_i = None
    for j in range(inside_i + 1, min(inside_i + entry_window, n - 1) + 1):
        if (d[j] - d[j - 1]).astype(int) > MAX_CALENDAR_GAP:
            return None
        if h[j] >= trigger:
            entry_i = j
            break
        if l[j] <= stop:
            return None                                   # stop level traded before the trigger: order cancelled
    if entry_i is None:
        return None
    gap_fill = o[entry_i] >= trigger
    entry = max(o[entry_i], trigger)
    risk = entry - stop
    atr = float(np.nanmean(s["tr"][inside_i - 13: inside_i + 1])) if inside_i >= 14 else np.nan
    rec = dict(outside_date=str(d[outside_i]), inside_date=str(d[inside_i]), entry_date=str(d[entry_i]),
               direction="long" if sign == 1 else "short", sessions_waited=entry_i - inside_i,
               entry_price=sign * entry, stop_price=sign * stop, gap_fill=bool(gap_fill),
               risk_pct_of_price=risk / abs(entry) * 100, risk_in_atr=risk / atr if atr > 0 else np.nan)
    # Stop touched on the entry bar
    # entry_bar_rule "stopped": a non-gap entry bar whose range reaches the stop counts as stopped out (worst case).
    # entry_bar_rule "ignored": that low is assumed to have come BEFORE the break (best case); it is not counted at all.
    ignore_entry_low = (entry_bar_rule == "ignored") and not gap_fill
    if l[entry_i] <= stop and not ignore_entry_low:
        rec.update(ambiguous_entry_bar=bool(not gap_fill), exit_reason="stopped_on_entry_bar", sessions_held=1,
                   worst_dip_risk_units=1.0, best_run_risk_units=0.0)
        for hz in HORIZONS:
            rec[f"result_exit_session_{hz}"] = -1.0
            rec[f"free_worst_dip_{hz}"] = (entry - l[entry_i]) / risk
            rec[f"free_best_run_{hz}"] = (h[entry_i] - entry) / risk
        for t in TARGETS:
            rec[f"result_target_{t}"] = -1.0
        rec.update(_finish(rec, risk, atr, entry))
        return rec
    rec["ambiguous_entry_bar"] = False
    stop_exit_at = None
    exit_reason = f"time_exit_session_{MAX_SESSIONS}"
    worst_dip = best_run = 0.0
    target_hit = {t: False for t in TARGETS}
    result_at = {}
    last_k = min(entry_i + MAX_SESSIONS - 1, n - 1)
    free_dip = free_run = 0.0
    free_at = {}
    for k in range(entry_i, last_k + 1):
        session = k - entry_i + 1
        low_k = entry if (k == entry_i and ignore_entry_low) else l[k]
        free_dip = max(free_dip, (entry - low_k) / risk)
        free_run = max(free_run, (h[k] - entry) / risk)
        for hz in HORIZONS:
            if session == hz:
                free_at[hz] = (free_dip, free_run)
        if stop_exit_at is None:
            if k > entry_i and l[k] <= stop:
                exit_price = o[k] if o[k] <= stop else stop
                stop_exit_at = (exit_price - entry) / risk
                worst_dip = max(worst_dip, (entry - exit_price) / risk)
                exit_reason = "stopped_gap" if o[k] <= stop else "stopped"
                rec["sessions_held"] = session
                for hz in HORIZONS:
                    if session <= hz:
                        result_at.setdefault(hz, stop_exit_at)
                for t in TARGETS:
                    if not target_hit[t]:
                        target_hit[t] = ("stop", stop_exit_at)
                # the stop-out bar adds no favorable excursion; stop tracking while keeping free excursions going
                continue
            worst_dip = max(worst_dip, (entry - low_k) / risk)
            best_run = max(best_run, (h[k] - entry) / risk)
            for t in TARGETS:
                if target_hit[t] is False and (h[k] - entry) / risk >= t:
                    target_hit[t] = ("target", t)
            if session in HORIZONS:
                result_at[session] = (c[k] - entry) / risk
    if stop_exit_at is None:
        rec["sessions_held"] = last_k - entry_i + 1
    rec.update(ambiguous_entry_bar=False, exit_reason=exit_reason, worst_dip_risk_units=worst_dip,
               best_run_risk_units=best_run)
    for hz in HORIZONS:
        rec[f"result_exit_session_{hz}"] = result_at.get(hz, np.nan)
        fd, fr = free_at.get(hz, (np.nan, np.nan))
        rec[f"free_worst_dip_{hz}"], rec[f"free_best_run_{hz}"] = fd, fr
    final_close = (c[last_k] - entry) / risk
    for t in TARGETS:
        hit = target_hit[t]
        rec[f"result_target_{t}"] = hit[1] if hit else final_close
    rec.update(_finish(rec, risk, atr, entry))
    return rec


def _finish(rec, risk, atr, entry):
    out = {}
    out["worst_dip_in_atr"] = rec["worst_dip_risk_units"] * rec["risk_in_atr"]
    out["best_run_in_atr"] = rec["best_run_risk_units"] * rec["risk_in_atr"]
    out["worst_dip_pct"] = rec["worst_dip_risk_units"] * rec["risk_pct_of_price"]
    out["best_run_pct"] = rec["best_run_risk_units"] * rec["risk_pct_of_price"]
    return out


def find_trades(prices, symbols, start_date, entry_window, entry_bar_rule="stopped"):
    rows = []
    for sym in symbols:
        s = prices.get(sym)
        if s is None:
            continue
        d, h, l = s["d"], s["h"], s["l"]
        for i in range(1, len(d) - 2):          # i = outside day; i+1 = inside day
            if d[i] < start_date:
                continue
            if not (h[i] > h[i - 1] and l[i] < l[i - 1]):
                continue
            if not (h[i + 1] < h[i] and l[i + 1] > l[i]):
                continue
            if max((d[i] - d[i - 1]).astype(int), (d[i + 1] - d[i]).astype(int)) > MAX_CALENDAR_GAP:
                continue
            for direction in (1, -1):
                rec = simulate(s, i, direction, entry_window, entry_bar_rule)
                if rec:
                    rec["symbol"] = sym
                    rows.append(rec)
    return pd.DataFrame(rows)


def cluster_se(values, groups):
    values = np.asarray(values, float)
    m = np.nanmean(values)
    dev = pd.Series(values - m).groupby(np.asarray(groups)).sum()
    return float(np.sqrt((dev ** 2).sum()) / len(values))


def summarize(df, label):
    if df.empty:
        return f"{label}: no trades\n"
    lines = [f"=== {label} ===", f"trades {len(df)} | distinct outside-day dates {df['outside_date'].nunique()} | markets {df['symbol'].nunique()}"]
    lines.append(f"gap fills {df['gap_fill'].mean():.1%} | stopped on the entry bar {(df['exit_reason'] == 'stopped_on_entry_bar').mean():.1%} "
                 f"(ambiguous same-bar {df['ambiguous_entry_bar'].mean():.1%}) | stopped later {df['exit_reason'].isin(['stopped', 'stopped_gap']).mean():.1%} | "
                 f"survived all {MAX_SESSIONS} sessions {df['exit_reason'].str.startswith('time').mean():.1%}")
    lines.append(f"risk per trade: median {df['risk_in_atr'].median():.2f} ATR, {df['risk_pct_of_price'].median():.2f}% of price "
                 f"(10th pct {df['risk_in_atr'].quantile(.1):.2f} ATR, 90th pct {df['risk_in_atr'].quantile(.9):.2f} ATR)")
    q = lambda col: " / ".join(f"{df[col].quantile(p):.2f}" for p in (.5, .75, .9))
    lines.append(f"with the stop in place, worst dip median/75th/90th pct: {q('worst_dip_risk_units')} risk units | {q('worst_dip_in_atr')} ATR | {q('worst_dip_pct')} %")
    lines.append(f"with the stop in place, best run  median/75th/90th pct: {q('best_run_risk_units')} risk units | {q('best_run_in_atr')} ATR | {q('best_run_pct')} %")
    lines.append("exit at close of session N, stop honored (result in risk units; +-2 standard errors clustered by outside-day date):")
    for hz in HORIZONS:
        col = f"result_exit_session_{hz}"
        x = df[col].dropna()
        g = df.loc[x.index, "outside_date"]
        lines.append(f"  session {hz:>2}: mean {x.mean():+.3f} (+-{2 * cluster_se(x, g):.3f}) | median {x.median():+.2f} | win rate {(x > 0).mean():.1%} | "
                     f"in ATR mean {(x * df.loc[x.index, 'risk_in_atr']).mean():+.3f}")
    lines.append("fixed target with the 1-unit stop, time exit at the close of session 20 (reach = target before stop):")
    for t in TARGETS:
        col = f"result_target_{t}"
        reach = (df[col] == t).mean()
        lines.append(f"  target {t:>3} risk units: reached {reach:.1%} | mean result {df[col].mean():+.3f}")
    lines.append("ignoring the stop (what the market did anyway), median/90th pct worst dip | best run in risk units:")
    for hz in HORIZONS:
        lines.append(f"  within {hz:>2} sessions: dip {df[f'free_worst_dip_{hz}'].median():.2f} / {df[f'free_worst_dip_{hz}'].quantile(.9):.2f} | "
                     f"run {df[f'free_best_run_{hz}'].median():.2f} / {df[f'free_best_run_{hz}'].quantile(.9):.2f}")
    return "\n".join(lines) + "\n"


def breakdowns(df, label):
    if df.empty:
        return ""
    col = "result_exit_session_10"
    by_year = df.assign(year=df["entry_date"].str[:4]).groupby(["year", "direction"]).agg(
        trades=("symbol", "size"), mean_result_session_10=(col, "mean"), stopped_share=("exit_reason", lambda x: x.str.startswith("stopped").mean()))
    by_market = df.groupby("symbol").agg(trades=("symbol", "size"), mean_result_session_10=(col, "mean"),
                                         median_worst_dip=("worst_dip_risk_units", "median"),
                                         median_best_run=("best_run_risk_units", "median")).sort_values("trades", ascending=False)
    return f"--- {label}: by year and direction ---\n{by_year.round(3).to_string()}\n--- {label}: by market ---\n{by_market.round(3).to_string()}\n"


def main(price_path, universe_path, out_dir):
    import os
    os.makedirs(out_dir, exist_ok=True)
    prices = load_prices(price_path)
    last = max(s["d"][-1] for s in prices.values())
    start = (pd.Timestamp(last) - pd.DateOffset(years=YEARS)).to_datetime64().astype("datetime64[D]")
    print(f"sample: outside days from {start} to {last} ({YEARS} years)")
    uni = pd.read_csv(universe_path, dtype=str)
    report_symbols = sorted({PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} & set(prices))
    missing = sorted({PRICE_ROOTS.get(x, x) for x in uni["ibkr"]} - set(prices))
    print(f"report universe: {len(report_symbols)} markets with prices; no price series: {missing}")
    universes = {"report universe": report_symbols, "all vendor contracts": sorted(prices)}
    text = []
    for window, rule in ((1, "stopped"), (1, "ignored"), (5, "stopped")):
        for name, syms in universes.items():
            df = find_trades(prices, syms, start, window, rule)
            tag = f"{name.replace(' ', '_')}_wait{window}_{rule}"
            df.to_csv(f"{out_dir}/trades_{tag}.csv", index=False)
            rule_text = ("same-bar stop-or-entry ambiguity counted as STOPPED (worst case)" if rule == "stopped"
                         else "same-bar ambiguity: low assumed BEFORE the break (best case)")
            title = f"{name}; entry order live {window} session(s); {rule_text}"
            block = [summarize(df, title)]
            for d in ("long", "short"):
                block.append(summarize(df[df["direction"] == d], f"{title}; {d} only"))
            if not df.empty:
                block.append(summarize(df[df["risk_in_atr"] >= 0.25], f"{title}; only trades whose risk is at least 0.25 ATR"))
            if window == 1 and rule == "stopped" and name == "report universe":
                block.append(breakdowns(df, title))
            text.append("\n".join(block))
    result = "\n".join(text)
    print(result)
    open(f"{out_dir}/outside_inside_results.txt", "w").write(result)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
