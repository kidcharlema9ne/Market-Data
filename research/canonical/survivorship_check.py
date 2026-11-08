"""Survivorship check for the 12-month-fall lead (C8, Entry 36). Counts and diagnostics only; returns come from
the committed Entry 28 files via factor_decline.load, so the D-068 guard (development years and 2026 pilot) applies.

DECLARED BEFORE RUNNING (so nothing here is chosen after looking):
 A. Census of refined events with no price series: by entry year, by ticker category and by archive status,
    plus the most frequent unmatched tickers in the development years (to see which are my matching errors).
 B. Break-even: the worst-hit fifth by raw 252-session change (Q1, from Entry 36 data) has some mean; if m events
    were missing from it with average excess X (ATR), what would its mean be?  Grid: m in {0, equal-rate, double-rate},
    X in {0,-1,-2,-3,-5}.  Equal-rate m = n * p/(1-p), p = share of refined events with a usable ticker but no series.
 C. Q1 breadth: median, share with excess > 0, mean without the 5 best, trimmed mean (10% each tail),
    count and mean by year, distinct issuers, mean with one event per issuer (earliest).
Status: exploratory diagnostics of an exploratory lead. Nothing here is a tested result.
"""
import json, statistics, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from factor_decline import load, quintile_line, mean, week_of  # noqa: E402

M = 'raw252'


def census(events, year_files):
    from archive_coverage_audit import normalize_ticker
    refined = [e for e in events if e['set'] == 'refined']
    tcat = Counter()
    for e in refined:
        sym, cat = normalize_ticker(e['ticker'])
        e['sym'], e['tcat'] = sym, cat
        tcat[(e['entry'][:4], cat)] += 1
    status = Counter()
    nop = []
    for fn in year_files:
        d = json.loads(Path(fn).read_text())
        for r in d['results']:
            if r['set'] != 'refined':
                continue
            status[(d['year'], r['status'])] += 1
            if r['status'] == 'no_price':
                nop.append(r)
    return refined, tcat, status, nop


def print_census(refined, tcat, status, nop):
    years = sorted({e['entry'][:4] for e in refined})
    cats = sorted({c for _, c in tcat})
    sts = sorted({s for _, s in status})
    print('\n=== A. Census of refined events ===')
    print('year  total | ticker category: ' + ' '.join(cats) + ' | archive status (usable ticker): ' + ' '.join(sts))
    tot = Counter()
    for y in years:
        n = sum(v for (yy, _), v in tcat.items() if yy == y)
        row = f'{y}  {n:5d} | ' + ' '.join(f'{tcat[(y, c)]:4d}' for c in cats) + ' | ' + ' '.join(f'{status[(int(y), s)]:4d}' for s in sts)
        print(row)
        tot['n'] += n
        tot['nop'] += status[(int(y), 'no_price')]
        tot['usable'] += sum(status[(int(y), s)] for s in sts)
    p = tot['nop'] / tot['usable'] if tot['usable'] else float('nan')
    print(f"all years: refined events {tot['n']}; with usable ticker {tot['usable']}; no price series {tot['nop']} ({p:.1%} of usable)")
    dev = [r for r in nop if r['entry'] <= '2020-12-31']
    print(f'no-price events in development years (<=2020): {len(dev)}; most frequent symbols: {Counter(r["sym"] for r in dev).most_common(25)}')
    return p


def breakeven(q1, p):
    n, mu = len(q1), mean(q1)
    eq = round(n * p / (1 - p))
    print(f'\n=== B. Break-even for the worst-hit fifth: n={n}, mean {mu:+.3f} ATR; missing-rate p={p:.3f} ===')
    print('missing m | mean if the missing events averaged X = 0 / -1 / -2 / -3 / -5 ATR')
    for label, m in (('0', 0), (f'equal-rate {eq}', eq), (f'double-rate {2 * eq}', 2 * eq)):
        print(f'{label:>16} | ' + ' / '.join(f'{(n * mu + m * x) / (n + m):+.3f}' for x in (0, -1, -2, -3, -5)))
    base = 0.154
    print('events that would need to be missing, each at X, to pull the fifth down to the all-event +0.154:')
    print('  ' + ', '.join(f'X={x}: {n * (mu - base) / (base - x):.0f}' for x in (-1, -2, -3, -5, -8)))


def trimmed(v, k=0.1):
    v = sorted(v)
    c = int(len(v) * k)
    return statistics.fmean(v[c:len(v) - c])


def breadth(q1):
    v = [r['excess_atr'] for r in q1]
    top5 = sorted(v)[:-5]
    print(f'\n=== C. Q1 breadth: n={len(v)}, {len({week_of(r) for r in q1})} weeks ===')
    print(f'mean {statistics.fmean(v):+.3f}; median {statistics.median(v):+.3f}; share excess>0 {sum(x > 0 for x in v) / len(v):.1%}; '
          f'mean without 5 best {statistics.fmean(top5):+.3f}; 10%-trimmed {trimmed(v):+.3f}; best {max(v):+.2f}, worst {min(v):+.2f}')
    by = {}
    for r in q1:
        by.setdefault(r['entry'][:4], []).append(r)
    print('by year: ' + ', '.join(f'{y} {len(rs)}/{mean(rs):+.2f}' for y, rs in sorted(by.items())))
    first = {}
    for r in sorted(q1, key=lambda r: r['entry']):
        first.setdefault(r['cik'], r)
    per = Counter(r['cik'] for r in q1)
    print(f'distinct issuers {len(first)}; events from issuers with 2+ events {sum(v for v in per.values() if v > 1)}; '
          f'mean with earliest event per issuer {mean(list(first.values())):+.3f} (n={len(first)})')


def run(events_json, year_dir, features, returns):
    import numpy as np
    refined, tcat, status, nop = census(json.loads(Path(events_json).read_text()), sorted(Path(year_dir).glob('year_*.json')))
    p = print_census(refined, tcat, status, nop)
    rows = load(features, returns)
    dev = sorted([r for r in rows if r['entry'] <= '2020-12-31'], key=week_of)
    sub = [r for r in dev if M in r]
    cuts = np.quantile([r[M] for r in sub], [.2, .4, .6, .8])
    q1 = quintile_line(sub, M, cuts)[0]
    print(f'\nQ1 of {M} in development years: n={len(q1)} (Entry 36: n=255, +0.593); cut points {np.round(cuts, 2).tolist()}')
    breakeven(q1, p)
    breadth(q1)


def selftest():
    rows = [{'excess_atr': float(i % 7) - 2, 'cik': str(i % 5), 'entry': f'2010-0{1 + i % 9}-01'} for i in range(60)]
    assert abs(trimmed([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) - 5.5) < 1e-9
    breakeven(rows, 0.165)
    breadth(rows)
    print('selftest ok')


if __name__ == '__main__':
    if sys.argv[1] == '--selftest':
        selftest()
    else:
        run(*sys.argv[1:5])
