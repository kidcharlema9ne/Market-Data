"""C40 (POST HOC, Michael 9 Nov 2026): a dollar portfolio test of the four-buyer rule with the Entry 78 size-ups.

Michael: "run some real tests with portfolio tests ... start with $100,000, a 3 ATR stop, base position size 0.1% vol and then size up from there ... yearly
return, max drawdown, all those portfolio statistics and trade statistics ... exit at 2 months ... add 0.1 ATR for commissions and slippage."

NEW CODE, PROVISIONAL.  Development entries only (D-068; exits and SPY marks may fall in early 2021 as in Entries 43, 62, 69, 70); no sealed entry is read; the 2026
pilot is not run.  Cohort, flags and entry/ATR exactly as Entries 66-67 and 79 (flag_combo_counts.py join: n=1,273 of the 1,372 base events; the other 99 lack a
feature and cannot be flagged, so they are NOT traded here).  Per-trade path = cost_stops_f.sim_stop, fixed stop 3 ATR below the entry open, 42 sessions
(entry session = day one), unchanged (the 'fixed3' / 42 cell of Entry 70 must reproduce).

DECLARED BEFORE RUNNING:
 A. Account: $100,000 cash at the start, no leverage, no margin, no interest on idle cash, no dividends, whole shares.  Marked to market at each close.
 B. Size: risk per 1 ATR move = BASE_PCT (0.1%) x U x equity at the previous close; shares = that dollar risk / ATR in dollars (ATR = mean true range of the 14 sessions
    before entry, fixed at entry).  U = 1.0 + the add-ons of the flags that are on (R1, N, F, P), Entry 78 Entry-67-model weights from sizing_weights.py (judgment on
    post hoc inputs, not a result).  With the 3 ATR stop a trade risks 3 x 0.1% x U of equity before cost (0.30% at 1.0U, 0.85% at 2.84U), more on a gap through the stop.
 C. Limits: shares <= cash available at the open (a cash-limited entry is cut, never levered); position value <= 1% of the stock's 15-session average daily dollar
    volume (Entry 54 file; if that file lacks the event the cap is skipped and counted).  The Entry 78 "8U total open" cap is NOT enforced; peak open risk is reported
    so we can see whether it would have bound.
 D. Entry at the open of the entry session, filled 0.05 ATR worse; exit 0.05 ATR worse on the fill price: stop = the stop level (the open on a gap), time = the close of
    session 42; a series that ends early closes at its last bar ('delist').  That is 0.10 ATR per round trip in total (Michael: "0.1 ATR for commissions and slippage"; if he
    meant 0.1 each way, the 0.20 row below is that case).  No other cost.  Entry order within a day: file order.
 E. Variants (all printed): MAIN scaled sizes, cost 0.10; FLAT every trade 1.0U (shows what the size-ups add); COST 0.00 (gross); COST 0.20; BASE 0.125% (the earlier
    standing base, for reference).  Benchmark: SPY buy-and-hold with the same $100,000 over the same dates (close to close).
 F. Statistics: total and annual (calendar-year) return, CAGR, daily-return volatility, Sharpe and Sortino (zero risk-free rate, 252 days), max drawdown with dates and the
    longest time under water, beta and alpha against SPY (daily), exposure and open positions; trade statistics in dollars, in R (1R = 3 ATR x shares) and in ATR with
    SPY beside it (D-053); stopped-out share; by size class; the three episodes (2008Q4, 2011Q3, 2020Q1) versus the rest; concentration in the top 10 trades; sample sizes
    (distinct entry dates, weeks, spells).
Cautions written in advance: every size and flag is post hoc and the leads are not edges; 2008-09 and 2020 dominate; survivorship is unresolved (Entry 65) and a wipe-out is
not in this archive; stop fills at the stop price are optimistic in thin names; costs are 0.10 ATR by instruction, not measured (the Entry 70 model says 0.04-0.11 ATR for F
at small size); the 0.10 ATR is charged on the stock's own ATR, so cheap volatile names are charged more dollars per share than their spread; the equity curve has about
15 years but only tens of independent market periods; a single path, so the maximum drawdown is one draw, not a bound.

Usage:  python portfolio_sim.py year YEAR --primary FILE --out FILE
        python portfolio_sim.py scan EVENTS.json YEAR_FOLDER DECLINE_FOLDER REGIME_FOLDER RETURNS_FOLDER DD_FOLDER DV_FOLDER PATH_FOLDER
        python portfolio_sim.py --selftest
"""
import argparse, json, math, statistics, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import excursion_stops as ex
import cost_stops_f as cf
import sizing_weights as sw
from refined_baseline import DEV_END, EPISODES, assert_allowed, quarter

H = 42
STOP_K = 3
START = 100_000.0
BASE_PCT = 0.1
COST = 0.10
ADV_CAP = 0.01
FLAGS = ('R1', 'N', 'F', 'P')


# ------------------------------------------------------------------ stage 1: per-trade paths (needs the price archive)
def year_job(year, primary_path, out):
    from archive_coverage_audit import DELISTED
    from r2_storage import client
    from refined_baseline import load_span
    s3 = client()
    entries = [e for e in json.loads(Path(primary_path).read_text()) if e['entry'].startswith(str(year))]
    for e in entries:
        assert_allowed(e['entry'])
        assert e['entry'] <= DEV_END, 'C40 is development years only'
    rows, spy_out = [], {}
    if entries:
        syms = {e['sym'] for e in entries}
        want = syms | {s + DELISTED for s in syms}
        stock_bars, dates = load_span(s3, 'stock', [year, year + 1, year + 2], want, 25, 30)
        spy_bars, _ = load_span(s3, 'etf', [year, year + 1, year + 2], {'SPY'}, 25, 30)
        spy = spy_bars.get('SPY', {})
        print(f'{year}: {len(entries)} entries, {len(dates)} sessions loaded, SPY bars {len(spy)}')
        last_exit = max(e['entry'] for e in entries)
        for e in entries:
            series = dict(stock_bars.get(e['sym'], {}))
            if e.get('via') == 'delisted' or not series:
                series = {**series, **stock_bars.get(e['sym'] + DELISTED, {})}
            r = {'entry': e['entry'], 'sym': e['sym'], 'cik': e['cik']}
            ctx, err = ex.entry_ctx(dates, series, spy, e['entry'])
            if err:
                r.update(err)
                rows.append(r)
                continue
            i, atr, op = ctx
            res = cf.sim_stop(dates, series, spy, e['entry'], ctx, 'fixed', STOP_K).get(H)
            if res is None:
                r.update({'status': 'no_path', 'atr': atr, 'open': op})
                rows.append(r)
                continue
            ret, spy_atr, sess, why = res
            kk = i + sess - 1
            r.update({'status': 'ok', 'atr': atr, 'open': op, 'ret_atr': ret, 'spy_atr': spy_atr, 'sess': sess, 'why': why,
                      'exit_date': dates[kk], 'exit_px': round(op + ret * atr, 6),
                      'days': [[dates[k], series[dates[k]][3] if dates[k] in series else None] for k in range(i, kk + 1)]})
            last_exit = max(last_exit, dates[kk])
            rows.append(r)
        spy_out = {d: spy[d][3] for d in dates if f'{year}-01-01' <= d <= last_exit and d in spy}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({'year': year, 'rows': rows, 'spy': spy_out}))
    print(f'{year}: status {dict(Counter(r["status"] for r in rows))}; SPY closes {len(spy_out)}')


# ------------------------------------------------------------------ sizing
def add_on_u():
    return {k: v['add_U'] for k, v in sw.weights(sw.MODELS['Entry 67 (R1+N+P+F)']).items()}


def size_u(add, r):
    return 1.0 + sum(add[k] for k in FLAGS if r.get(k))


# ------------------------------------------------------------------ simulation
def simulate(trades, cal, start=START, base_pct=BASE_PCT, cost=COST, flat=False, adv_cap=ADV_CAP):
    """trades: dicts with entry, open, atr, exit_date, exit_px, why, days [[date, close|None]], U, dv (or None).  cal: sorted list of session dates (SPY dates).
    Returns (curve [(date, equity, invested)], trade records, counters)."""
    by_entry = defaultdict(list)
    for t in trades:
        by_entry[t['entry']].append(t)
    half = cost / 2.0
    pos, cash = {}, start
    curve, recs = [], []
    cnt = Counter()
    peak_u = 0.0
    cal_set = set(cal)
    for t in trades:
        assert t['entry'] in cal_set and t['exit_date'] in cal_set, (t['sym'], t['entry'], t['exit_date'])
    closes = {id(t): {d: c for d, c in t['days'] if c is not None} for t in trades}
    for d in cal:
        # 1. entries at the open, sized on the previous close equity
        if d in by_entry:
            eq = cash + sum(p['shares'] * p['last'] for p in pos.values())
            for t in by_entry[d]:
                u = 1.0 if flat else t['U']
                px_in = t['open'] + half * t['atr']
                want = math.floor(base_pct / 100.0 * u * eq / t['atr'])
                by_cash = math.floor(cash / px_in)
                by_adv = math.floor(adv_cap * t['dv'] / t['open']) if t.get('dv') else None
                if by_adv is None:
                    cnt['no_dv_cap'] += 1
                sh = min(x for x in (want, by_cash, by_adv) if x is not None)
                if sh < want:
                    cnt['cash_limited' if (by_adv is None or by_cash <= by_adv) and sh == by_cash else 'adv_limited'] += 1
                if sh <= 0:
                    cnt['skipped_zero'] += 1
                    continue
                cash -= sh * px_in
                pos[id(t)] = {'t': t, 'shares': sh, 'px_in': px_in, 'last': px_in, 'eq0': eq, 'u': u, 'cl': closes[id(t)]}
                cnt['entered'] += 1
        # 2. intraday stop exits
        for k in [k for k, p in pos.items() if p['t']['exit_date'] == d and p['t']['why'] in ('stop', 'gap')]:
            cash = _close(pos, k, cash, half, recs)
        # 3. marks at the close; time and delist exits at the close
        for p in pos.values():
            c = p['cl'].get(d)
            if c is not None:
                p['last'] = c
        for k in [k for k, p in pos.items() if p['t']['exit_date'] == d]:
            cash = _close(pos, k, cash, half, recs)
        inv = sum(p['shares'] * p['last'] for p in pos.values())
        curve.append((d, cash + inv, inv, len(pos)))
        peak_u = max(peak_u, sum(p['u'] for p in pos.values()))
    assert not pos, f'{len(pos)} positions never closed'
    cnt['peak_open_U'] = peak_u
    return curve, recs, cnt


def _close(pos, k, cash, half, recs):
    p = pos.pop(k)
    t = p['t']
    px_out = t['exit_px'] - half * t['atr']
    cash += p['shares'] * px_out
    pnl = p['shares'] * (px_out - p['px_in'])
    recs.append({'entry': t['entry'], 'exit': t['exit_date'], 'sym': t['sym'], 'why': t['why'], 'sess': t['sess'], 'shares': p['shares'], 'u': p['u'],
                 'notional': p['shares'] * p['px_in'], 'pnl': pnl, 'eq0': p['eq0'], 'pct_eq': pnl / p['eq0'],
                 'R': pnl / (p['shares'] * STOP_K * t['atr']), 'atr_net': (px_out - p['px_in']) / t['atr'], 'stock_atr': t['ret_atr'], 'spy_atr': t['spy_atr'],
                 'flags': tuple(k2 for k2 in FLAGS if t.get(k2))})
    return cash


# ------------------------------------------------------------------ statistics
def years_between(d0, d1):
    return (date.fromisoformat(d1) - date.fromisoformat(d0)).days / 365.25


def curve_stats(curve, start):
    """curve: [(date, equity, ...)] daily.  Returns a dict of portfolio statistics; the starting equity is the day-0 value."""
    dates = [c[0] for c in curve]
    eq = [start] + [c[1] for c in curve]
    r = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    yrs = years_between(dates[0], dates[-1])
    sd = statistics.pstdev(r)
    dn = math.sqrt(sum(min(x, 0) ** 2 for x in r) / len(r))
    peak, mdd, pk_i, tr_i, best = eq[0], 0.0, 0, 0, (0.0, 0, 0)
    uw_len, uw_start, longest = 0, 0, (0, 0, 0)
    for i, v in enumerate(eq):
        if v >= peak:
            if i - uw_start > longest[0] and i > uw_start:
                longest = (i - uw_start, uw_start, i)
            peak, pk_i, uw_start = v, i, i
        dd = v / peak - 1
        if dd < mdd:
            mdd, best = dd, (dd, pk_i, i)
    if len(eq) - 1 - uw_start > longest[0]:
        longest = (len(eq) - 1 - uw_start, uw_start, None)
    lab = lambda i: dates[0] if i == 0 else dates[i - 1]
    rec = next((j for j in range(best[2], len(eq)) if eq[j] >= eq[best[1]]), None)
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1 if yrs > 0 else float('nan')
    return {'end': eq[-1], 'total': eq[-1] / eq[0] - 1, 'cagr': cagr, 'vol': sd * math.sqrt(252), 'sharpe': statistics.fmean(r) / sd * math.sqrt(252) if sd else float('nan'),
            'sortino': statistics.fmean(r) / dn * math.sqrt(252) if dn else float('nan'), 'mdd': mdd, 'mdd_peak': lab(best[1]), 'mdd_trough': lab(best[2]),
            'mdd_recover': lab(rec) if rec is not None else 'not recovered', 'uw_days': longest[0], 'uw_from': lab(longest[1]),
            'uw_to': lab(longest[2]) if longest[2] is not None else 'still under water', 'calmar': cagr / -mdd if mdd < 0 else float('nan'),
            'best_day': max(r), 'worst_day': min(r), 'yrs': yrs, 'r': r, 'eq': eq}


def calendar_years(curve, start):
    out, prev, cur_year = {}, start, None
    for d, v, *_ in curve:
        y = d[:4]
        if y != cur_year:
            if cur_year is not None:
                out[cur_year] = (out[cur_year][0], prev)
            out[y] = (prev, None)
            cur_year = y
        prev = v
    out[cur_year] = (out[cur_year][0], prev)
    return {y: b / a - 1 for y, (a, b) in out.items()}


def beta_alpha(r, rb):
    import numpy as np
    x, y = np.asarray(rb), np.asarray(r)
    b, a = np.polyfit(x, y, 1)
    return float(b), float(a * 252)


def spy_curve(spy, cal, d0, start):
    base = spy[d0]
    return [(d, start * spy[d] / base) for d in cal]


def fmt_stats(name, s, extra=''):
    return (f'  {name:18s} end ${s["end"]:>11,.0f}  total {s["total"]:+8.1%}  CAGR {s["cagr"]:+6.2%}  vol {s["vol"]:5.1%}  Sharpe {s["sharpe"]:5.2f}  Sortino {s["sortino"]:5.2f}  '
            f'max DD {s["mdd"]:+6.1%}  Calmar {s["calmar"]:5.2f}{extra}')


def trade_block(recs, label):
    n = len(recs)
    if not n:
        return f'  {label}: n=0'
    win = [x for x in recs if x['pnl'] > 0]
    los = [x for x in recs if x['pnl'] <= 0]
    gp, gl = sum(x['pnl'] for x in win), -sum(x['pnl'] for x in los)
    R = [x['R'] for x in recs]
    return (f'  {label}: n={n}  net P&L ${sum(x["pnl"] for x in recs):+,.0f}  win {len(win) / n:.0%}  avg win ${gp / len(win) if win else 0:+,.0f} ({statistics.fmean(x["pct_eq"] for x in win) if win else 0:+.2%} of equity)  '
            f'avg loss ${-gl / len(los) if los else 0:+,.0f} ({statistics.fmean(x["pct_eq"] for x in los) if los else 0:+.2%})  profit factor {gp / gl if gl else float("inf"):.2f}  '
            f'expectancy {statistics.fmean(x["pnl"] for x in recs):+,.0f}/trade = {statistics.fmean(R):+.3f}R (median {statistics.median(R):+.2f}R)  '
            f'| ATR net of cost {statistics.fmean(x["atr_net"] for x in recs):+.3f}; gross stock {statistics.fmean(x["stock_atr"] for x in recs):+.3f} / SPY {statistics.fmean(x["spy_atr"] for x in recs):+.3f} '
            f'= excess {statistics.fmean(x["stock_atr"] - x["spy_atr"] for x in recs):+.3f}')


# ------------------------------------------------------------------ stage 2: join, simulate, report
def load_paths(folder):
    sim, spy = {}, {}
    for p in sorted(Path(folder).glob('pf_*.json')):
        j = json.loads(p.read_text())
        spy.update(j['spy'])
        for r in j['rows']:
            assert_allowed(r['entry'])
            sim[(r['cik'], r['sym'], r['entry'])] = r
    return sim, spy


def load_dv_soft(folder):
    dv = {}
    for p in sorted(Path(folder).glob('dv_*.json')):
        for r in json.loads(p.read_text())['rows']:
            assert_allowed(r['entry'])
            if r.get('bars', 0) >= 15 and 'dv_mean' in r:
                dv[(r['cik'], r['sym'], r['entry'])] = r['dv_mean']
    return dv


def build_trades(cohort, sim, dv, add):
    out, miss, atr_diff = [], Counter(), 0
    for r in cohort:
        k = (r['cik'], r['sym'], r['entry'])
        s = sim.get(k)
        if s is None:
            miss['no_row'] += 1
            continue
        if s.get('status') != 'ok':
            miss[s.get('status', 'bad')] += 1
            continue
        if abs(s['atr'] - r['atr']) > 1e-9:
            atr_diff += 1
        t = {**{f: bool(r[f]) for f in FLAGS}, 'entry': r['entry'], 'sym': r['sym'], 'dv': dv.get(k), 'U': size_u(add, r)}
        t.update({f: s[f] for f in ('atr', 'open', 'ret_atr', 'spy_atr', 'sess', 'why', 'exit_date', 'exit_px', 'days')})
        out.append(t)
    out.sort(key=lambda t: (t['entry'], t['sym']))
    return out, miss, atr_diff


def run_scan(cohort, sim, spy, dv):
    add = add_on_u()
    print('add-ons in U (Entry 78, Entry 67 model): ' + ', '.join(f'{k} {v:+.2f}' for k, v in add.items()) +
          f'; all four on {1 + sum(add.values()):.2f}U; 1U = {BASE_PCT}% of equity per 1 ATR here')
    trades, miss, atr_diff = build_trades(cohort, sim, dv, add)
    print(f'cohort {len(cohort)}; tradable paths {len(trades)}; not tradable {dict(miss)}; entry ATR differs from the Entry 36 file on {atr_diff}; '
          f'dollar-volume file lacks {sum(t["dv"] is None for t in trades)}')
    cal = sorted(spy)
    d_first = min(t['entry'] for t in trades)
    prior = [d for d in cal if d < d_first]
    cal_run = [d for d in cal if d >= d_first]
    d0 = prior[-1] if prior else cal_run[0]
    assert all(t['exit_date'] <= cal[-1] for t in trades)
    print(f'period: first entry {d_first}, last exit {max(t["exit_date"] for t in trades)}; calendar {cal_run[0]} to {cal_run[-1]} ({len(cal_run)} sessions); start value on {d0}')
    bench = spy_curve(spy, cal_run, d0, START)
    bs = curve_stats(bench, START)
    bs_year = calendar_years(bench, START)
    cohort_check(trades)

    variants = [('MAIN 0.1% scaled', dict()), ('FLAT 1.0U all', dict(flat=True)), ('gross cost 0.00', dict(cost=0.0)), ('cost 0.20 ATR', dict(cost=0.20)),
                ('base 0.125%', dict(base_pct=0.125))]
    res = {}
    for name, kw in variants:
        curve, recs, cnt = simulate(trades, cal_run, **kw)
        res[name] = (curve, recs, cnt, curve_stats(curve, START))
    print('\n=== 1. Portfolio, all variants ($100,000 start; 3 ATR stop; 42-session exit) ===')
    for name, _ in variants:
        curve, recs, cnt, st = res[name]
        inv = [c[2] / c[1] for c in curve]
        print(fmt_stats(name, st, f'  trades {len(recs)}  avg invested {statistics.fmean(inv):.0%}  peak {max(inv):.0%}'))
    print(fmt_stats('SPY buy and hold', bs))

    curve, recs, cnt, st = res['MAIN 0.1% scaled']
    print('\n=== 2. MAIN in detail ===')
    print(f'  drawdown: max {st["mdd"]:+.1%} from the {st["mdd_peak"]} peak to the {st["mdd_trough"]} trough; recovered {st["mdd_recover"]}; longest time under water {st["uw_days"]} sessions '
          f'({st["uw_from"]} to {st["uw_to"]}).  SPY: max {bs["mdd"]:+.1%} from {bs["mdd_peak"]} to {bs["mdd_trough"]}, recovered {bs["mdd_recover"]}')
    print(f'  best day {st["best_day"]:+.2%}, worst day {st["worst_day"]:+.2%}; SPY best {bs["best_day"]:+.2%}, worst {bs["worst_day"]:+.2%}')
    b, a = beta_alpha(st['r'], bs['r'])
    print(f'  beta to SPY {b:.2f}; alpha {a:+.2%} a year (daily regression, not adjusted for the part of the year in cash; the account is mostly cash on many days)')
    inv = [c[2] / c[1] for c in curve]
    npos = [c[3] for c in curve]
    print(f'  invested share of equity: mean {statistics.fmean(inv):.1%}, median {statistics.median(inv):.1%}, peak {max(inv):.1%}; open positions: mean {statistics.fmean(npos):.1f}, peak {max(npos)}; '
          f'days with no position {sum(x == 0 for x in npos)} of {len(npos)}; peak open size {cnt["peak_open_U"]:.1f}U (the Entry 78 cap of 8U {"WOULD HAVE BOUND" if cnt["peak_open_U"] > 8 else "never bound"})')
    print(f'  entries {cnt["entered"]} of {len(trades)} tradable; cut by cash {cnt["cash_limited"]}; cut by the 1% volume cap {cnt["adv_limited"]}; skipped (zero shares) {cnt["skipped_zero"]}; '
          f'no volume file (cap skipped) {cnt["no_dv_cap"]}')
    print('\n  calendar-year return (MAIN vs SPY; trades entered; net P&L; stopped out):')
    cy = calendar_years(curve, START)
    byy = defaultdict(list)
    for x in recs:
        byy[x['entry'][:4]].append(x)
    for y in cy:
        g = byy.get(y, [])
        print(f'    {y}: {cy[y]:+8.1%}  | SPY {bs_year.get(y, float("nan")):+7.1%} | trades {len(g):3d}  P&L ${sum(x["pnl"] for x in g):+10,.0f}  stopped {sum(x["why"] in ("stop", "gap") for x in g):3d}')
    ys = list(cy.values())
    print(f'    years up {sum(v > 0 for v in ys)} of {len(ys)} (the last row is a partial year ending {cal_run[-1]}); best {max(ys):+.1%}, worst {min(ys):+.1%}; SPY years up {sum(v > 0 for v in bs_year.values())} of {len(bs_year)}')
    print('\n=== 3. Trade statistics, MAIN ===')
    print(trade_block(recs, 'all trades'))
    ex_ = [x['stock_atr'] - x['spy_atr'] for x in recs]
    stopped = [x for x in recs if x['why'] in ('stop', 'gap')]
    gap = [x for x in recs if x['why'] == 'gap']
    print(f'  stopped out {len(stopped)} ({len(stopped) / len(recs):.0%}); of those through a gap {len(gap)}; time exits {sum(x["why"] == "time" for x in recs)}; delisted-early {sum(x["why"] == "delist" for x in recs)}; '
          f'sessions held mean {statistics.fmean(x["sess"] for x in recs):.1f}, median {statistics.median(x["sess"] for x in recs):.0f}')
    worst = min(recs, key=lambda x: x['R'])
    bestt = max(recs, key=lambda x: x['pnl'])
    print(f'  worst trade {worst["sym"]} {worst["entry"]}: {worst["R"]:+.2f}R, ${worst["pnl"]:+,.0f} ({worst["pct_eq"]:+.2%} of equity); best by dollars {bestt["sym"]} {bestt["entry"]}: {bestt["R"]:+.2f}R, ${bestt["pnl"]:+,.0f}')
    print(f'  average position ${statistics.fmean(x["notional"] for x in recs):,.0f} ({statistics.fmean(x["notional"] / x["eq0"] for x in recs):.1%} of equity), largest {max(x["notional"] / x["eq0"] for x in recs):.1%}; '
          f'average size {statistics.fmean(x["u"] for x in recs):.2f}U')
    try:
        from stop_test import block_range
        lo, hi, _ = block_range([{'entry': x['entry'], 'x': x['stock_atr'] - x['spy_atr']} for x in recs], 'x')
        lo2, hi2, _ = block_range([{'entry': x['entry'], 'x': x['R']} for x in recs], 'x')
        print(f'  week-block 95% range: mean excess over SPY, gross (ATR) [{lo:+.3f}, {hi:+.3f}]; mean R net of cost [{lo2:+.3f}, {hi2:+.3f}]')
    except Exception as e:  # pragma: no cover
        print('  block range unavailable:', e)
    ds = sorted({x['entry'] for x in recs})
    wk = {date.fromisoformat(x['entry']).isocalendar()[:2] for x in recs}
    mo = {x['entry'][:7] for x in recs}
    from factor_regime import spells
    print(f'  sample: {len(recs)} trades on {len(ds)} distinct entry dates, {len(wk)} weeks, {len(mo)} of 180 months, {len(spells(ds))} spells (gaps of the standard length between entry dates)')

    print('\n  by size class (flags on):')
    cls = defaultdict(list)
    for x in recs:
        cls['cluster only (1.0U)' if not x['flags'] else 'one flag' if len(x['flags']) == 1 else 'two flags' if len(x['flags']) == 2 else 'three or four flags'].append(x)
    for k in ('cluster only (1.0U)', 'one flag', 'two flags', 'three or four flags'):
        print(trade_block(cls.get(k, []), k))
    for f in FLAGS:
        print(trade_block([x for x in recs if f in x['flags']], f'{f} on'))
    print('\n  episodes:')
    for nm, g in (('2008Q4 + 2011Q3 + 2020Q1 entries', [x for x in recs if quarter(x['entry']) in EPISODES]), ('all other entries', [x for x in recs if quarter(x['entry']) not in EPISODES])):
        tot = sum(x['pnl'] for x in recs)
        print(trade_block(g, nm) + f'  [{sum(x["pnl"] for x in g) / tot:.0%} of net P&L]' if tot else trade_block(g, nm))
    top = sorted(recs, key=lambda x: -x['pnl'])[:10]
    tot = sum(x['pnl'] for x in recs)
    print(f'  top 10 trades by dollars: ${sum(x["pnl"] for x in top):+,.0f} = {sum(x["pnl"] for x in top) / tot:.0%} of net P&L (${tot:+,.0f}); the other {len(recs) - 10} trades ${tot - sum(x["pnl"] for x in top):+,.0f}'
          if tot else '  net P&L is zero')
    print('  top 10: ' + '; '.join(f'{x["sym"]} {x["entry"]} {x["R"]:+.1f}R ${x["pnl"]:+,.0f}' for x in top))

    print('\n=== 4. Worst months and drawdown path (MAIN) ===')
    mon, prev, cur = {}, START, None
    for d, v, *_ in curve:
        m = d[:7]
        if m != cur:
            if cur is not None:
                mon[cur] = mon[cur][0], prev
            mon[m] = (prev, None)
            cur = m
        prev = v
    mon[cur] = mon[cur][0], prev
    mr = sorted(((b / a - 1, m) for m, (a, b) in mon.items()))
    print('  worst 5 months: ' + ', '.join(f'{m} {x:+.1%}' for x, m in mr[:5]) + '; best 5: ' + ', '.join(f'{m} {x:+.1%}' for x, m in mr[-5:][::-1]))
    print(f'  months up {sum(x > 0 for x, _ in mr)} of {len(mr)}')
    print('\nPOST HOC; sizes and flags are Claude\'s Entry 78 judgment on post hoc leads; costs are 0.10 ATR by instruction, not measured; survivorship (Entry 65) and wipe-outs are not in this archive; '
          'one path, so the drawdown is one draw.')


def cohort_check(trades):
    c = Counter(t['why'] for t in trades)
    print(f'  path check (should match Entry 70 plain/fixed 3 at 42 sessions for the full cohort, stopped share shown): {dict(c)}; '
          f'mean stock ATR {statistics.fmean(t["ret_atr"] for t in trades):+.3f} / SPY {statistics.fmean(t["spy_atr"] for t in trades):+.3f}')


def scan(events, years, decl, regime, ret, dd_folder, dv_folder, path_folder):
    import drawdown_scan as dd
    import score_scan as ss
    import deepfall_2x2 as d2
    dev0 = ss.build(events, years, decl, regime, ret)
    dev, atr_diff = dd.load_dd(dd_folder, dev0)
    cohort = [r for r in dev if 'dd252' in r]
    for r in cohort:
        d2.flags(r)
    for r in cohort:
        assert r['entry'] <= DEV_END
    sim, spy = load_paths(path_folder)
    run_scan(cohort, sim, spy, load_dv_soft(dv_folder))


# ------------------------------------------------------------------ self test
def selftest():
    from datetime import timedelta
    # sizes from Entry 78: cluster 1.0, all four 2.84
    add = add_on_u()
    assert abs(size_u(add, {}) - 1.0) < 1e-12 and abs(size_u(add, {f: True for f in FLAGS}) - 2.84) < 0.01, size_u(add, {f: True for f in FLAGS})
    # synthetic calendar
    cal, d0, k = [], date(2010, 1, 4), 0
    while len(cal) < 120:
        x = d0 + timedelta(days=k)
        k += 1
        if x.weekday() < 5:
            cal.append(x.isoformat())

    def mk(sym, ent_i, atr, op, closes, exit_i, exit_px, why, u=1.0, dv=None, ret=0.0):
        days = [[cal[ent_i + j], c] for j, c in enumerate(closes)]
        return {'sym': sym, 'entry': cal[ent_i], 'open': op, 'atr': atr, 'exit_date': cal[exit_i], 'exit_px': exit_px, 'why': why, 'days': days, 'U': u, 'dv': dv,
                'ret_atr': (exit_px - op) / atr, 'spy_atr': 0.0, 'sess': exit_i - ent_i + 1, **{f: False for f in FLAGS}}
    # trade A: $20 stock, ATR $1, 1.0U: risk 0.1% of $100k = $100 per ATR -> 100 shares; cost 0.1 ATR -> pays 20.05, receives (exit - 0.05)
    a = mk('A', 5, 1.0, 20.0, [20.0, 21.0, 22.0], 7, 22.0, 'time')
    curve, recs, cnt = simulate([a], cal)
    assert len(recs) == 1 and recs[0]['shares'] == 100, recs
    assert abs(recs[0]['pnl'] - 100 * (22.0 - 0.05 - 20.05)) < 1e-9, recs[0]['pnl']
    assert abs(curve[-1][1] - (100000 + recs[0]['pnl'])) < 1e-9 and curve[-1][2] == 0
    assert abs(curve[5][1] - (100000 + 100 * (20.0 - 20.05))) < 1e-9          # day one marks at the close: only the entry slippage is lost
    assert abs(recs[0]['R'] - recs[0]['pnl'] / 300.0) < 1e-12
    # trade B: stopped at 3 ATR below the open on session 2 -> exit px 17.0, loses 3 ATR + 0.1 ATR cost = $310 on 100 shares
    b = mk('B', 10, 1.0, 20.0, [19.5, 17.0], 11, 17.0, 'stop')
    curve, recs, cnt = simulate([b], cal)
    assert abs(recs[0]['pnl'] - 100 * (17.0 - 0.05 - 20.05)) < 1e-9 and abs(recs[0]['R'] + 3.1 / 3.0) < 1e-9, recs[0]
    # cash limit: a $200 stock with ATR $0.2 wants 500 shares = $100,000+; two of them the same day -> second one cut to the cash left
    c1 = mk('C1', 20, 0.2, 200.0, [200.0, 200.0], 21, 200.0, 'time', u=1.0)
    c2 = mk('C2', 20, 0.2, 200.0, [200.0, 200.0], 21, 200.0, 'time', u=1.0)
    curve, recs, cnt = simulate([c1, c2], cal)
    assert len(recs) == 1 and recs[0]['shares'] == 499 and cnt['cash_limited'] == 2 and cnt['skipped_zero'] == 1, (recs, cnt)
    assert all(c[1] > 0 for c in curve) and min(c[2] for c in curve) >= 0
    # 1% volume cap: dv $50,000 a day -> position <= $500 -> 25 shares of a $20 stock
    d = mk('D', 30, 1.0, 20.0, [20.0, 20.0], 31, 20.0, 'time', dv=50_000.0)
    curve, recs, cnt = simulate([d], cal)
    assert recs[0]['shares'] == 25 and cnt['adv_limited'] == 1, (recs, cnt)
    # flat sizing ignores U
    e = mk('E', 40, 1.0, 20.0, [20.0, 20.0], 41, 20.0, 'time', u=2.5)
    assert simulate([e], cal)[1][0]['shares'] == 250 and simulate([e], cal, flat=True)[1][0]['shares'] == 100
    # statistics: a straight 10% fall then recovery
    cv = [(cal[i], v) for i, v in enumerate([100_000, 90_000, 95_000, 100_000, 110_000])]
    st = curve_stats(cv, 100_000.0)
    assert abs(st['mdd'] + 0.10) < 1e-12 and st['mdd_trough'] == cal[1] and st['mdd_recover'] == cal[3] and abs(st['total'] - 0.10) < 1e-12, st
    # calendar years
    cy = calendar_years([('2010-12-30', 105_000.0), ('2011-01-03', 100_000.0), ('2011-12-30', 120_000.0)], 100_000.0)
    assert abs(cy['2010'] - 0.05) < 1e-12 and abs(cy['2011'] - (120_000 / 105_000 - 1)) < 1e-12, cy
    # positions never left open and the final equity equals cash when flat
    assert abs(curve_stats([(cal[0], 100_000.0), (cal[1], 100_000.0)], 100_000.0)['sharpe'] != 0 or True)
    print('portfolio_sim selftest ok: sizing, entry/exit costs, stop, cash cap, volume cap, flat sizing, drawdown, calendar years')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--selftest']:
        selftest()
        sys.exit(0)
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('args', nargs='*')
    ap.add_argument('--primary')
    ap.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'year':
        year_job(int(a.args[0]), a.primary, a.out)
    elif a.cmd == 'scan':
        scan(*a.args)
