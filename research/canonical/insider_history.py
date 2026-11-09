"""C41a: insider-level history of the buyers inside each four-buyer cluster (Michael, 9 Nov 2026).

Three features, all computed POINT IN TIME (only filings public before the event's entry, only transactions dated before the
cluster's first counted purchase), development years only (D-068):

  A  PLANNED-BUY PATTERN. A buyer is 'planned' if, at the SAME issuer, he already bought one cycle earlier (weak) or two
     consecutive cycles earlier (strict) at the same calendar slot as his first counted purchase. Cycles: 1, 3, 6 and 12
     months (tolerance +-4, 7, 7, 7 calendar days). Planned buyers are removed from the count (like D-064); the event survives
     only if four non-planned buyers remain. Also shown as a split (any planned buyer vs none).
  B  NET SELLER. Same issuer, the 365 days before the first counted purchase: dollars sold (code S) greater than dollars
     bought (code P). Primary: sales flagged 10b5-1 are ignored (a pre-arranged sale is not a decision); variant: all sales.
     Event flags: at least one such buyer (NS1), at least two (NS2).
  C  RETURN OF EARLIER BUYS. For each buyer, every earlier open-market purchase (any issuer, discretionary, collapsed so that
     one episode per owner and issuer per 21 sessions) is priced exactly like a cluster trade (next open after the filing,
     21 sessions, excess over SPY in ATR, refined_baseline.trade_outcome). Only episodes whose hold had ENDED before the
     event's entry count. Buyer score = mean excess over his earlier episodes (needs >= 2, variant >= 3); event score = mean
     over scored buyers (needs >= 2 scored buyers).

Cohort: entries 2008-04-01 .. 2020-12-31 (the SEC archive starts 2006Q1, so every event has >= 24 months of look-back for
the 12-month pattern). Every comparison is inside that same cohort. EXPLORATORY: declared menu = 14 flags on the whole cohort
(2 any-planned splits + 8 period x level splits + 4 net-seller flags) and 2 prior-return splits on the scored subsets (16).
Gross of cost. The weekly-block chance test shuffles flags inside each entry week (Entry 36 machinery).

Subcommands
  extract   events.json -> history rows (code P and S, Form 4/4A, common stock) for every buyer, filings <= 2020-12-31
  episodes  history rows -> ep_primary.json (input for refined_baseline.py year) and ep_detail.json
  summary   everything -> tables
  --selftest
"""
import argparse, bisect, csv, hashlib, io, json, os, re, statistics, sys, zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refined_baseline import DEV_END, EPISODES, assert_allowed, quarter

COHORT_START = '2008-04-01'
COHORT_MONTHS = 153                         # 2008-04 .. 2020-12
PERIODS = ((1, 30.4375, 4), (3, 91.3125, 7), (6, 182.625, 7), (12, 365.25, 7))   # (months, days, tolerance in days)
NET_DAYS = 365
HOLD_SESSIONS = 21
RATIO_LO, RATIO_HI = 0.5, 2.0               # purchase price / entry open sanity band (archive is split-adjusted)
PREFIX = 'sec/insider-transactions/quarterly-original-zips/'
SEED = 20261109


def d2(s):
    return date.fromisoformat(s)


# ------------------------------------------------------------------ pattern features (pure functions)
def slot_hit(prior_dates, anchor, days, k, tol):
    """prior_dates: sorted list of date objects. True if one lies within tol days of anchor - k cycles."""
    target = anchor - timedelta(days=round(k * days))
    i = bisect.bisect_left(prior_dates, target - timedelta(days=tol))
    return i < len(prior_dates) and prior_dates[i] <= target + timedelta(days=tol)


def planned_flags(prior_dates, anchor):
    """-> {months: (weak, strict)}. weak = a purchase one cycle earlier; strict = one AND two cycles earlier."""
    out = {}
    for m, days, tol in PERIODS:
        h1 = slot_hit(prior_dates, anchor, days, 1, tol)
        out[m] = (h1, h1 and slot_hit(prior_dates, anchor, days, 2, tol))
    return out


def net_seller(buys, sells, start, first_buy, entry, include_planned_sales):
    """buys/sells: lists of history rows of ONE buyer at ONE issuer. Window: start <= trade date < first_buy, filed before entry."""
    def total(rs, skip_planned):
        return sum(r['s'] * r['p'] for r in rs if start <= r['d'] < first_buy and r['f'] < entry and not (skip_planned and r['pl']))
    sold, bought = total(sells, not include_planned_sales), total(buys, False)
    return sold > 0 and sold > bought


# ------------------------------------------------------------------ extract
def extract(events_path, out):
    from r2_storage import BUCKET, client
    from sec_bulk_importer import rows as tsv_rows, sec_date, number, flag_text
    from cluster_counts_by_year import TITLE
    events = json.loads(Path(events_path).read_text())
    owners = {o[0] for e in events if e['set'] == 'refined' and e['entry'] <= DEV_END for o in e['owners']}
    print(f'buyers (owner CIKs) in development refined events: {len(owners)}')
    s3 = client()
    keys = sorted(obj['Key'] for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BUCKET, Prefix=PREFIX)
                  for obj in page.get('Contents', []) if re.match(r'(20(0[6-9]|1\d|20))q[1-4]_form345\.zip$', obj['Key'].rsplit('/', 1)[-1]))
    print(f'quarterly zips 2006q1-2020q4: {len(keys)}')
    if len(keys) != 60:
        raise SystemExit(f'expected 60 quarterly zips, found {len(keys)}')
    rows, per_code = [], Counter()
    for key in keys:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        payload = obj['Body'].read()
        if hashlib.sha256(payload).hexdigest() != obj.get('Metadata', {}).get('verified-sha256'):
            raise SystemExit(f'checksum mismatch {key}')
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            sub = {r['ACCESSION_NUMBER']: r for r in tsv_rows(z, 'SUBMISSION.tsv') if r.get('DOCUMENT_TYPE', '').upper() in ('4', '4/A')}
            own = defaultdict(list)
            for r in tsv_rows(z, 'REPORTINGOWNER.tsv'):
                if r.get('RPTOWNERCIK') in owners and r['ACCESSION_NUMBER'] in sub:
                    own[r['ACCESSION_NUMBER']].append(r['RPTOWNERCIK'])
            cand = []
            for r in tsv_rows(z, 'NONDERIV_TRANS.tsv'):
                code = r.get('TRANS_CODE', '').upper()
                acc = r['ACCESSION_NUMBER']
                if code in ('P', 'S') and acc in own and TITLE.fullmatch(' '.join((r.get('SECURITY_TITLE') or '').split())):
                    cand.append(r)
            need = {r['ACCESSION_NUMBER'] for r in cand}
            notes = defaultdict(dict)
            for r in tsv_rows(z, 'FOOTNOTES.tsv'):
                if r['ACCESSION_NUMBER'] in need:
                    notes[r['ACCESSION_NUMBER']][r['FOOTNOTE_ID']] = r.get('FOOTNOTE_TXT', '')
        n0 = len(rows)
        for r in cand:
            acc = r['ACCESSION_NUMBER']
            s = sub[acc]
            fdate, tdate = sec_date(s.get('FILING_DATE')), sec_date(r.get('TRANS_DATE'))
            shares, price = number(r.get('TRANS_SHARES')), number(r.get('TRANS_PRICEPERSHARE'))
            if not fdate or not tdate or fdate > DEV_END or shares is None or price is None:
                continue
            ids = set()
            for k, v in r.items():
                if k.endswith('_FN') and v:
                    ids.update(re.findall(r'F\d+|\w+', v))
            text = ' '.join([s.get('REMARKS', ''), *[notes[acc][i] for i in sorted(ids) if i in notes[acc]], r.get('NATURE_OF_OWNERSHIP', '')])
            fl = flag_text(text)
            pl = 'possible_10b5_1' in fl or s.get('AFF10B5ONE', '').strip().upper() in ('1', 'Y', 'YES', 'TRUE')
            nd = 'possible_non_discretionary' in fl
            sh, px = float(shares), float(price)
            if sh <= 0 or px <= 0:
                continue
            for o in set(own[acc]):
                rows.append({'o': o, 'i': s.get('ISSUERCIK'), 't': s.get('ISSUERTRADINGSYMBOL'), 'f': fdate, 'd': tdate,
                             'c': r['TRANS_CODE'].upper(), 'ad': r.get('TRANS_ACQUIRED_DISP_CD', '').upper(), 's': sh, 'p': px,
                             'pl': pl, 'nd': nd, 'ac': acc})
        print(f'{key.rsplit("/", 1)[-1]}: {len(rows) - n0} rows (cumulative {len(rows)})', flush=True)
    for r in rows:
        per_code[r['c']] += 1
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(rows))
    print(f'history rows: {dict(per_code)}; owners with any row: {len({r["o"] for r in rows})} of {len(owners)}')


def dedupe(rows):
    """Original and amendment of one transaction: same owner, issuer, trade date, code, shares, price -> earliest filing."""
    best = {}
    for r in rows:
        k = (r['o'], r['i'], r['d'], r['c'], r['s'], r['p'])
        if k not in best or r['f'] < best[k]['f']:
            best[k] = r
    return list(best.values())


# ------------------------------------------------------------------ episodes (earlier buys to price)
def make_episodes(rows, cal, normalize):
    """One episode per (owner, issuer, filing date) of discretionary purchases; collapsed to one per owner and issuer per 21 sessions."""
    groups = defaultdict(list)
    for r in rows:
        if r['c'] == 'P' and r['ad'] in ('A', '') and not r['pl'] and not r['nd']:
            groups[(r['o'], r['i'], r['f'])].append(r)
    stats = Counter()
    raw = []
    for (o, i, f), rs in groups.items():
        j = bisect.bisect_right(cal, f)
        if j >= len(cal) or cal[j] > DEV_END:
            stats['entry_after_dev_end'] += 1
            continue
        sym, cat = normalize(rs[0]['t'])
        if cat != 'ok':
            stats['ticker_' + cat] += 1
            continue
        px = sum(r['s'] * r['p'] for r in rs) / sum(r['s'] for r in rs)
        raw.append({'o': o, 'cik': i, 'sym': sym, 'f': f, 'entry': cal[j], 'idx': j, 'px': px, 'via': None})
    out, last = [], {}
    for e in sorted(raw, key=lambda e: (e['o'], e['cik'], e['f'])):
        k = (e['o'], e['cik'])
        if k in last and e['idx'] < last[k] + HOLD_SESSIONS:
            stats['collapsed_within_21_sessions'] += 1
            continue
        last[k] = e['idx']
        out.append(e)
    stats['episodes'] = len(out)
    return out, stats


def build_episodes(rows_path, out_dir):
    from archive_coverage_audit import normalize_ticker
    from cluster_counts_by_year import sessions
    rows = dedupe(json.loads(Path(rows_path).read_text()))
    eps, stats = make_episodes(rows, sessions(), normalize_ticker)
    prim = {}
    for e in eps:
        prim[(e['cik'], e['sym'], e['entry'])] = {'entry': e['entry'], 'sym': e['sym'], 'cik': e['cik'], 'via': None}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / 'ep_primary.json').write_text(json.dumps(sorted(prim.values(), key=lambda x: (x['entry'], x['sym']))))
    (Path(out_dir) / 'ep_detail.json').write_text(json.dumps(eps))
    print(f'episodes: {len(eps)}; distinct (issuer, symbol, entry) to price: {len(prim)}; {dict(stats)}')
    print('by entry year: ' + str(sorted(Counter(e['entry'][:4] for e in eps).items())))


# ------------------------------------------------------------------ event features
def buyer_features(b, ev, hist, ep_by_owner, ep_res):
    """b: buyer cik. ev: event with 'purchases', 'entry', 'issuer_cik'. Returns a dict of this buyer's point-in-time features."""
    entry, issuer = ev['entry'], ev['issuer_cik']
    first_buy = min(d for d, _ in ev['purchases'])
    h = hist.get(b, {'P': [], 'S': []})
    # the buyer's own counted purchase dates are rebuilt from his history rows: this issuer, from the cluster's first counted purchase
    # up to (not including) the entry, filed before the entry; falls back to the cluster's first date
    mine = sorted(r['d'] for r in h['P'] if r['i'] == issuer and first_buy <= r['d'] < entry and r['f'] < entry) or [first_buy]
    anchor = d2(mine[0])
    prior = sorted(d2(r['d']) for r in h['P'] if r['i'] == issuer and r['d'] < first_buy and r['f'] < entry)
    pf = planned_flags(prior, anchor)
    start = (d2(first_buy) - timedelta(days=NET_DAYS)).isoformat()
    buys = [r for r in h['P'] if r['i'] == issuer]
    sells = [r for r in h['S'] if r['i'] == issuer and r['ad'] in ('D', '')]
    sold_any = any(start <= r['d'] < first_buy and r['f'] < entry for r in sells)
    vals = []
    for e in ep_by_owner.get(b, []):
        if e['f'] >= first_buy:
            continue
        r = ep_res.get((e['cik'], e['sym'], e['entry']))
        if not r or r['status'] != 'complete' or r['exit'] >= entry:
            continue
        if not (RATIO_LO <= e['px'] / r['entry_open'] <= RATIO_HI):
            continue
        vals.append(r['excess_atr'])
    return {'planned': pf, 'n_prior_same_issuer': len(prior), 'sold_any': sold_any,
            'ns_nodisc': net_seller(buys, sells, start, first_buy, entry, False),
            'ns_all': net_seller(buys, sells, start, first_buy, entry, True),
            'prior_vals': vals}


def event_flags(ev, hist, ep_by_owner, ep_res):
    buyers = sorted({o[0] for o in ev['owners']})
    bf = {b: buyer_features(b, ev, hist, ep_by_owner, ep_res) for b in buyers}
    out = {'n_buyers': len(buyers)}
    for lvl, idx in (('weak', 0), ('strict', 1)):
        for m, _, _ in PERIODS:
            out[f'pl_{lvl}_{m}'] = sum(bf[b]['planned'][m][idx] for b in buyers)
        flagged = {b for b in buyers if any(bf[b]['planned'][m][idx] for m, _, _ in PERIODS)}
        out[f'pl_{lvl}_any'] = len(flagged)
        out[f'kept_{lvl}'] = len(buyers) - len(flagged) >= 4
    out['ns_nodisc'] = sum(bf[b]['ns_nodisc'] for b in buyers)
    out['ns_all'] = sum(bf[b]['ns_all'] for b in buyers)
    for mn in (2, 3):
        sc = [statistics.fmean(bf[b]['prior_vals']) for b in buyers if len(bf[b]['prior_vals']) >= mn]
        out[f'ret_n{mn}'] = len(sc)
        out[f'ret_mean{mn}'] = statistics.fmean(sc) if len(sc) >= 2 else None
    out['any_prior_buy_same_issuer'] = sum(bf[b]['n_prior_same_issuer'] > 0 for b in buyers)
    out['any_sale'] = sum(bf[b]['sold_any'] for b in buyers)
    out['buyers_with_prior_eps2'] = sum(len(bf[b]['prior_vals']) >= 2 for b in buyers)
    return out


# ------------------------------------------------------------------ statistics
def ranks(v):
    import numpy as np
    order = np.argsort(v, kind='mergesort')
    r = np.empty(len(v))
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    import numpy as np
    rx, ry = ranks(np.asarray(x, float)), ranks(np.asarray(y, float))
    return float(np.corrcoef(rx, ry)[0, 1])


def line(label, rows, fr):
    if not rows:
        return f'  {label}: n=0'
    s = f'  {label}: {fr.stats_line(rows)}  | {fr.indep(rows)}  | {len(rows) / COHORT_MONTHS:.2f} a month'
    if len(rows) >= 30:
        lo, hi = fr.week_boot(rows)
        s += f'  | week-block 95% {lo:+.3f} to {hi:+.3f}'
    return s


def no_ep(rows):
    return [r for r in rows if quarter(r['entry']) not in EPISODES]


def pair(label, flagged, rest, fr):
    print(line(f'{label} YES', flagged, fr))
    print(line(f'{label} NO ', rest, fr))
    if flagged and rest:
        d = statistics.fmean(r['excess_atr'] for r in flagged) - statistics.fmean(r['excess_atr'] for r in rest)
        a, b = no_ep(flagged), no_ep(rest)
        dd = (statistics.fmean(r['excess_atr'] for r in a) - statistics.fmean(r['excess_atr'] for r in b)) if a and b else float('nan')
        print(f'    difference YES - NO: {d:+.3f}  (without the three large episodes: {dd:+.3f}; n {len(a)} vs {len(b)})')


def summary(events_path, years, returns, decline, hist_path, ep_dir, epret_dir):
    import numpy as np
    import factor_roles as fr
    import factor_decline as fd
    from base_scan import diff_stats
    from archive_coverage_audit import normalize_ticker
    base = fr.load(events_path, years, returns)
    events = json.loads(Path(events_path).read_text())
    ev_by_key = defaultdict(list)
    for e in events:
        if e['set'] == 'refined':
            ev_by_key[(e['issuer_cik'], normalize_ticker(e['ticker'])[0], e['entry'])].append(e)
    hist = defaultdict(lambda: {'P': [], 'S': []})
    for r in dedupe(json.loads(Path(hist_path).read_text())):
        hist[r['o']][r['c']].append(r)
    eps = json.loads((Path(ep_dir) / 'ep_detail.json').read_text())
    ep_by_owner = defaultdict(list)
    for e in eps:
        ep_by_owner[e['o']].append(e)
    ep_res = {}
    for p in sorted(Path(epret_dir).glob('returns_*.json')):
        for r in json.loads(p.read_text())['rows']:
            assert_allowed(r['entry'])
            ep_res[(r['cik'], r['sym'], r['entry'])] = r
    print(f'earlier-buy episodes: {len(eps)}; priced rows: {len(ep_res)}; complete: {sum(r["status"] == "complete" for r in ep_res.values())}; '
          f'status mix: {dict(Counter(r["status"] for r in ep_res.values()))}')
    coh = []
    for r in base:
        if COHORT_START <= r['entry'] <= DEV_END:
            ev = ev_by_key[(r['cik'], r['sym'], r['entry'])][0]
            assert ev['purchases'], 'event without purchase dates'
            coh.append({**r, **event_flags(ev, hist, ep_by_owner, ep_res)})
    coh.sort(key=lambda r: r['entry'])
    print(f'\ncohort: development events entered {COHORT_START} .. {DEV_END}: n={len(coh)}  ({COHORT_MONTHS} months)')
    print(line('WHOLE COHORT (the comparator for everything below)', coh, fr))

    nb = sum(r['n_buyers'] for r in coh)
    print('\n=== 0. Coverage ===')
    print(f'  buyer-slots {nb}; with an earlier purchase at the same issuer: {sum(r["any_prior_buy_same_issuer"] for r in coh)} '
          f'({sum(r["any_prior_buy_same_issuer"] for r in coh) / nb:.1%}); with any sale at the same issuer in the prior 365 days: '
          f'{sum(r["any_sale"] for r in coh)} ({sum(r["any_sale"] for r in coh) / nb:.1%}); with >= 2 priced earlier buys: '
          f'{sum(r["buyers_with_prior_eps2"] for r in coh)} ({sum(r["buyers_with_prior_eps2"] for r in coh) / nb:.1%})')
    print(f'  events with a return score: min 2 earlier buys {sum(r["ret_mean2"] is not None for r in coh)}, min 3 {sum(r["ret_mean3"] is not None for r in coh)}')

    print('\n=== A. Planned-buy pattern (planned buyers removed from the count; event survives if four non-planned remain) ===')
    for lvl in ('weak', 'strict'):
        kept = [r for r in coh if r[f'kept_{lvl}']]
        gone = [r for r in coh if not r[f'kept_{lvl}']]
        print(f'  -- {lvl}: events with at least one planned buyer: {sum(r[f"pl_{lvl}_any"] > 0 for r in coh)}; buyer-slots flagged: {sum(r[f"pl_{lvl}_any"] for r in coh)}')
        pair(f'{lvl} FILTER: event SURVIVES', kept, gone, fr)
        pair(f'{lvl} SPLIT: any planned buyer', [r for r in coh if r[f'pl_{lvl}_any'] > 0], [r for r in coh if r[f'pl_{lvl}_any'] == 0], fr)
        for m, _, _ in PERIODS:
            pair(f'{lvl} {m}-month cycle, any buyer', [r for r in coh if r[f'pl_{lvl}_{m}'] > 0], [r for r in coh if r[f'pl_{lvl}_{m}'] == 0], fr)

    print('\n=== B. Net seller before buying (same issuer, 365 days; sold dollars > bought dollars) ===')
    for key, name in (('ns_nodisc', 'sales ex-10b5-1 (primary)'), ('ns_all', 'all sales')):
        for k in (1, 2):
            pair(f'{name}, at least {k} buyer(s)', [r for r in coh if r[key] >= k], [r for r in coh if r[key] < k], fr)

    print('\n=== C. Average excess of the buyers\' earlier buys (episodes finished before entry) ===')
    for mn in (2, 3):
        sc = [r for r in coh if r[f'ret_mean{mn}'] is not None]
        print(f'  -- min {mn} earlier buys per buyer; scored events {len(sc)} of {len(coh)}')
        if len(sc) >= 30:
            x = [r[f'ret_mean{mn}'] for r in sc]
            y = [r['excess_atr'] for r in sc]
            print(f'    Spearman(score, cluster excess) = {spearman(x, y):+.3f}  (n={len(sc)}; score mean {statistics.fmean(x):+.3f}, median {statistics.median(x):+.3f})')
            med = statistics.median(x)
            pair(f'score above median ({med:+.3f})', [r for r in sc if r[f'ret_mean{mn}'] > med], [r for r in sc if r[f'ret_mean{mn}'] <= med], fr)
            pair('score > 0', [r for r in sc if r[f'ret_mean{mn}'] > 0], [r for r in sc if r[f'ret_mean{mn}'] <= 0], fr)
            srt = sorted(sc, key=lambda r: r[f'ret_mean{mn}'])
            t = len(srt) // 3
            for nm, part in (('lowest third', srt[:t]), ('middle third', srt[t:len(srt) - t]), ('top third', srt[len(srt) - t:])):
                print(line(nm, part, fr))
        print(line('unscored events', [r for r in coh if r[f'ret_mean{mn}'] is None], fr))

    print('\n=== D. All three together (primary definitions: strict planned filter, net seller ex-10b5-1 >= 1 buyer, return score > 0 with min 2) ===')
    for pl in (False, True):
        for ns in (False, True):
            for rs in ('pos', 'nonpos', 'unscored'):
                sel = [r for r in coh if (r['pl_strict_any'] > 0) == pl and (r['ns_nodisc'] >= 1) == ns and
                       ((r['ret_mean2'] is None and rs == 'unscored') or (r['ret_mean2'] is not None and (r['ret_mean2'] > 0) == (rs == 'pos') and rs != 'unscored'))]
                print(line(f'planned buyer {"YES" if pl else "no "} | net seller {"YES" if ns else "no "} | earlier-buy score {rs:8s}', sel, fr))
    clean = [r for r in coh if r['pl_strict_any'] == 0 and (r['ns_nodisc'] >= 1)]
    pair('NO planned buyer AND at least one net seller', clean, [r for r in coh if not (r['pl_strict_any'] == 0 and r['ns_nodisc'] >= 1)], fr)

    print('\n=== E. Chance (entry-week shuffle of the flags, 10,000 draws, two-sided; flag-minus-rest mean difference) ===')
    names, cols = [], []
    for lvl in ('weak', 'strict'):
        names.append(f'any planned buyer ({lvl})'); cols.append([r[f'pl_{lvl}_any'] > 0 for r in coh])
        for m, _, _ in PERIODS:
            names.append(f'{m}-month cycle ({lvl})'); cols.append([r[f'pl_{lvl}_{m}'] > 0 for r in coh])
    for key in ('ns_nodisc', 'ns_all'):
        for k in (1, 2):
            names.append(f'{key} >= {k}'); cols.append([r[key] >= k for r in coh])
    wk = {w: i for i, w in enumerate(sorted({fr.week_of(r) for r in coh}))}
    wi = np.array([wk[fr.week_of(r)] for r in coh])
    ex = np.array([r['excess_atr'] for r in coh])
    obs, p1, best = diff_stats(ex, wi, np.array(cols).T)
    for n_, o_, p_ in zip(names, obs, p1):
        print(f'  {n_:34s} difference {o_:+.3f}  single-question chance {p_:.1%}')
    print(f'  menu A+B = {len(names)} flags; smallest single chance {p1.min():.1%}; chance the best of {len(names)} is at least that small by luck {best:.1%}')
    for mn in (2, 3):
        sc = [r for r in coh if r[f'ret_mean{mn}'] is not None]
        if len(sc) < 60:
            continue
        med = statistics.median(r[f'ret_mean{mn}'] for r in sc)
        wk2 = {w: i for i, w in enumerate(sorted({fr.week_of(r) for r in sc}))}
        o2, q2, b2 = diff_stats(np.array([r['excess_atr'] for r in sc]), np.array([wk2[fr.week_of(r)] for r in sc]),
                                np.array([[r[f'ret_mean{mn}'] > med] for r in sc]))
        print(f'  C: earlier-buy score above median, min {mn} (n={len(sc)}): difference {o2[0]:+.3f}, single-question chance {q2[0]:.1%}')
    print('  Total declared menu: 14 flags (A+B) + 2 return-score splits (C) = 16. The cells overlap heavily, so best-of-menu is conservative; '
          'per-cycle rows are descriptive.')

    if decline:
        drows = {(r['cik'], r['sym'], r['entry']): r for r in fd.load(decline, returns)}
        inside = [r for r in coh if drows.get((r['cik'], r['sym'], r['entry']), {}).get('raw252') is not None
                  and drows[(r['cik'], r['sym'], r['entry'])]['raw252'] <= -15.0]
        print(f'\n=== F. Inside the deep-fall rule F (down 15+ ATR over 12 months), same cohort: n={len(inside)} ===')
        print(line('F, whole', inside, fr))
        pair('F: strict planned filter, event SURVIVES', [r for r in inside if r['kept_strict']], [r for r in inside if not r['kept_strict']], fr)
        pair('F: net seller (ex-10b5-1) >= 1 buyer', [r for r in inside if r['ns_nodisc'] >= 1], [r for r in inside if r['ns_nodisc'] < 1], fr)
        sc = [r for r in inside if r['ret_mean2'] is not None]
        pair('F: earlier-buy score > 0 (min 2)', [r for r in sc if r['ret_mean2'] > 0], [r for r in sc if r['ret_mean2'] <= 0], fr)
    print('\nEXPLORATORY: POST HOC menu declared in the module docstring; gross of cost; cells under 30 are noise; development years only; '
          'history before 2006Q1 is not in the archive (cohort starts 2008-04 for that reason); amendments (4/A) are de-duplicated on '
          'owner, issuer, trade date, code, shares and price, so a corrected row can still count twice.')


# ------------------------------------------------------------------ selftest
def selftest():
    # 1. slot hits: annual buyer (Mar 2019, Mar 2018) before an anchor in Mar 2020
    prior = sorted([date(2018, 3, 12), date(2019, 3, 14)])
    pf = planned_flags(prior, date(2020, 3, 13))
    assert pf[12] == (True, True), pf
    assert pf[6] == (False, False) and pf[1] == (False, False) and pf[3] == (False, False), pf
    pf = planned_flags([date(2019, 3, 14)], date(2020, 3, 13))
    assert pf[12] == (True, False), pf                                   # one cycle only: weak yes, strict no
    pf = planned_flags([date(2019, 3, 30)], date(2020, 3, 13))
    assert pf[12] == (False, False), pf                                  # 16 days off the slot: outside the 7-day tolerance
    # monthly buyer: purchases on the 10th of the three months before an anchor on the 10th
    pf = planned_flags([date(2020, 1, 10), date(2020, 2, 10)], date(2020, 3, 10))
    assert pf[1] == (True, True), pf
    # 2. net seller
    S = lambda d, f, s, p, pl=False: {'d': d, 'f': f, 's': s, 'p': p, 'pl': pl}
    sells = [S('2019-06-01', '2019-06-03', 1000, 10.0), S('2019-07-01', '2019-07-02', 5000, 10.0, True)]
    buys = [S('2019-08-01', '2019-08-02', 100, 10.0)]
    assert net_seller(buys, sells, '2019-03-01', '2020-03-01', '2020-03-20', False) is True          # 10,000 sold (plan sale ignored) vs 1,000 bought
    assert net_seller(buys, [sells[1]], '2019-03-01', '2020-03-01', '2020-03-20', False) is False   # only a 10b5-1 sale: ignored
    assert net_seller(buys, [sells[1]], '2019-03-01', '2020-03-01', '2020-03-20', True) is True      # variant: all sales
    assert net_seller([S('2019-08-01', '2019-08-02', 5000, 10.0)], sells[:1], '2019-03-01', '2020-03-01', '2020-03-20', False) is False   # bought more than sold
    assert net_seller([], [S('2019-06-01', '2020-03-25', 1000, 10.0)], '2019-03-01', '2020-03-01', '2020-03-20', False) is False         # filed after entry: not public
    assert net_seller([], [S('2020-03-02', '2020-03-03', 1000, 10.0)], '2019-03-01', '2020-03-01', '2020-03-20', False) is False         # traded inside the cluster window
    # 3. dedupe keeps the earliest filing
    rows = [{'o': 'a', 'i': '1', 'd': '2019-01-02', 'c': 'P', 's': 10.0, 'p': 5.0, 'f': '2019-01-04'},
            {'o': 'a', 'i': '1', 'd': '2019-01-02', 'c': 'P', 's': 10.0, 'p': 5.0, 'f': '2019-01-03'}]
    assert [r['f'] for r in dedupe(rows)] == ['2019-01-03']
    # 4. episodes: same-filing rows merge, a second filing inside 21 sessions collapses, 10b5-1 rows are skipped, OTC tickers dropped
    os.environ['ALLOW_WEEKDAY_CALENDAR'] = '1'
    from cluster_counts_by_year import sessions
    cal = [d for d in sessions() if d >= '2019-01-01'][:120]
    P = lambda o, f, t='ABC', pl=False, s=100, p=10.0: {'o': o, 'i': '9', 't': t, 'f': f, 'd': f, 'c': 'P', 'ad': 'A', 's': s, 'p': p, 'pl': pl, 'nd': False}
    norm = lambda t: (t.upper(), 'otc' if t.endswith('.OB') else 'ok')
    eps, st = make_episodes([P('a', cal[10]), P('a', cal[10], s=300, p=12.0), P('a', cal[20]), P('a', cal[40]), P('a', cal[50], pl=True),
                             P('b', cal[10], t='XYZ.OB')], cal, norm)
    assert [(e['o'], e['entry']) for e in eps] == [('a', cal[11]), ('a', cal[41])], eps
    assert abs(eps[0]['px'] - (1000 + 3600) / 400) < 1e-9 and st['collapsed_within_21_sessions'] == 1 and st['ticker_otc'] == 1, (eps, st)
    # 5. buyer features: earlier episode counted only if its hold ended before entry and it was filed before the first purchase
    ev = {'issuer_cik': '9', 'entry': '2019-06-20', 'owners': [['a', 'Director', ''], ['b', 'Director', ''], ['c', 'Officer', 'CFO'], ['d', 'Director', '']],
          'purchases': [['2019-06-05', 10.0], ['2019-06-07', 10.0]]}
    hist = {'a': {'P': [{'o': 'a', 'i': '9', 'd': '2018-06-06', 'f': '2018-06-08', 's': 1.0, 'p': 1.0, 'pl': False},
                        {'o': 'a', 'i': '9', 'd': '2017-06-07', 'f': '2017-06-09', 's': 1.0, 'p': 1.0, 'pl': False}], 'S': []}}
    ep = {'a': [{'o': 'a', 'cik': '9', 'sym': 'ABC', 'f': '2018-06-08', 'entry': '2018-06-11', 'px': 10.0},
                {'o': 'a', 'cik': '8', 'sym': 'ZZZ', 'f': '2019-05-30', 'entry': '2019-05-31', 'px': 10.0},     # exit after entry -> not usable
                {'o': 'a', 'cik': '7', 'sym': 'QQQ', 'f': '2019-06-10', 'entry': '2019-06-11', 'px': 10.0}]}    # filed after the first purchase
    res = {('9', 'ABC', '2018-06-11'): {'status': 'complete', 'exit': '2018-07-10', 'excess_atr': 1.5, 'entry_open': 10.5},
           ('8', 'ZZZ', '2019-05-31'): {'status': 'complete', 'exit': '2019-06-28', 'excess_atr': 9.0, 'entry_open': 10.0},
           ('7', 'QQQ', '2019-06-11'): {'status': 'complete', 'exit': '2019-07-10', 'excess_atr': 9.0, 'entry_open': 10.0}}
    f = event_flags(ev, hist, ep, res)
    assert f['pl_strict_12'] == 1 and f['pl_strict_any'] == 1 and f['kept_strict'] is False and f['n_buyers'] == 4, f
    assert f['kept_weak'] is False and f['ns_nodisc'] == 0, f
    assert f['ret_n2'] == 0 and f['ret_mean2'] is None, f                 # only one usable earlier buy -> buyer not scored (needs 2)
    # 6. ranks / spearman
    assert abs(spearman([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-12 and abs(spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-12
    print('insider_history selftest passed')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', nargs='?', choices=['extract', 'episodes', 'summary'])
    ap.add_argument('--events')
    ap.add_argument('--rows')
    ap.add_argument('--out')
    ap.add_argument('--years')
    ap.add_argument('--returns')
    ap.add_argument('--decline')
    ap.add_argument('--ep-dir')
    ap.add_argument('--epret-dir')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.cmd == 'extract':
        extract(a.events, a.out)
    elif a.cmd == 'episodes':
        build_episodes(a.rows, a.out)
    elif a.cmd == 'summary':
        summary(a.events, a.years, a.returns, a.decline, a.rows, a.ep_dir, a.epret_dir)
    else:
        ap.error('give a subcommand or --selftest')
