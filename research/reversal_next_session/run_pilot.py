"""Auditable DEVELOPMENT diagnostic; fails closed for exact execution.

This diagnostic uses a nominal exchange tick on ratio-adjusted prices. It is NOT
the validated mandatory-rule backtest. Exact mode needs adjusted tick history,
contract roll identifiers, verified publication timestamps and bar provenance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import zipfile
import numpy as np
import pandas as pd
import pandas_market_calendars as mc
from pandas.tseries.holiday import USFederalHolidayCalendar
from engine import entries_and_outcomes, summarize

HERE=Path(__file__).resolve().parent
PILOT={'ES':('CME Globex Equity',.25),'ZN':('CME Globex Fixed Income',1/64),
       'E6':('CMEGlobex_FX',.00005),'CL':('CMEGlobex_EnergyAndMetals',.01),
       'GC':('CMEGlobex_EnergyAndMetals',.1),'ZC':('CMEGlobex_Grains',.25)}
COLUMNS={'As of Date in Form YYYY-MM-DD':'report','CFTC Contract Market Code':'code',
         'Commercial Positions-Long (All)':'longs','Commercial Positions-Short (All)':'shorts'}

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_cot(root, manifest, universe):
    pieces=[]
    for obj in manifest['archives']:
        p=Path(root)/obj['path'];b=p.read_bytes()
        sha=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
        if sha!=obj['sha']: raise ValueError('COT blob hash mismatch: '+str(p))
        with zipfile.ZipFile(p) as z:
            with z.open(z.namelist()[0]) as f:
                d=pd.read_csv(f,encoding='latin1',dtype=str,usecols=lambda x:x.strip() in COLUMNS)
        d.columns=d.columns.str.strip();d=d.rename(columns=COLUMNS)
        d['code']=d.code.str.strip();pieces.append(d[d.code.isin(universe.code)])
    d=pd.concat(pieces).drop_duplicates(['code','report'],keep='last')
    d['report']=pd.to_datetime(d.report)
    d['net']=pd.to_numeric(d.longs)-pd.to_numeric(d.shorts)
    d=d.sort_values(['code','report'])
    d['cot_index']=d.groupby('code').net.transform(lambda x:100*(x-x.rolling(26).min())/(x.rolling(26).max()-x.rolling(26).min()).replace(0,np.nan))
    return d

def releases(cot,path):
    meta=(pd.read_csv(path) if str(path).endswith('.csv') else pd.read_parquet(path)).query("report_type=='legacy'")
    meta['report']=pd.to_datetime(meta.report_date)
    meta=meta[['report','release_at','release_estimated','release_source']].copy()
    meta['release_at']=pd.to_datetime(meta.release_at,utc=True)
    holiday=set(USFederalHolidayCalendar().holidays('2007','2022'))
    rows=[]
    # Explicitly ESTIMATED for audit only. Not asserted to be actual publication.
    for d in sorted(set(cot.report)-set(meta.report)):
        if d<pd.Timestamp('2007-01-01') or d>pd.Timestamp('2021-08-06'):continue
        wed=d+pd.Timedelta(days=2-d.weekday());pub=wed+pd.Timedelta(days=2)
        for _ in range(sum(wed+pd.Timedelta(days=i) in holiday for i in range(3))):
            pub+=pd.Timedelta(days=1)
            while pub.weekday()>=5 or pub in holiday:pub+=pd.Timedelta(days=1)
        stamp=(pub+pd.Timedelta(hours=15,minutes=30)).tz_localize('America/New_York').tz_convert('UTC')
        rows.append(dict(report=d,release_at=stamp,release_estimated=True,release_source='derived'))
    return pd.concat([meta,pd.DataFrame(rows)],ignore_index=True)

def prepare(raw,root,calendar,cot,tick):
    schedule=mc.get_calendar(calendar).schedule('2008-01-01','2021-08-06')
    d=raw[raw.symbol.eq(root)].copy()
    dup=d.session.duplicated(keep=False)
    embedded=pd.to_datetime(d.embedded,format='mixed',errors='coerce').dt.normalize()
    valid=(~dup)&d.session.eq(embedded)&d.volume.gt(0)&d.asset_type.eq('Futures')
    valid &= np.isfinite(d[['open','high','low','close']]).all(axis=1)
    valid &= d.high.ge(d[['open','close']].max(axis=1))&d.low.le(d[['open','close']].min(axis=1))
    clean=d.loc[valid].set_index('session').reindex(schedule.index)
    p=clean[['open','high','low','close']].copy()
    # As-of setup close. Never substitute Tuesday's observation date for release.
    c=cot.sort_values(['release_at','report']).copy()
    c=c[c.report.eq(c.report.cummax())].drop_duplicates('release_at',keep='last')
    joined=pd.merge_asof(schedule.reset_index(names='session').sort_values('market_close'),
        c[['report','release_at','cot_index','release_estimated']],left_on='market_close',right_on='release_at',direction='backward').set_index('session').reindex(p.index)
    p['cot_index']=joined.cot_index;p['cot_report']=joined.report;p['release_at']=joined.release_at
    p['release_estimated']=joined.release_estimated
    p['tick']=tick
    if root=='E6':p.loc[p.index<pd.Timestamp('2016-01-11'),'tick']=.0001
    assert (joined.release_at.dropna()<=joined.market_close[joined.release_at.notna()]).all()
    return p,dict(root=root,raw_rows=len(d),rejected_rows=int((~valid).sum()),
         missing_calendar_rows=int(p.close.isna().sum()),first=str(d.session.min().date()),last=str(d.session.max().date()))

def block_interval(x):
    if not len(x):return [None,None]
    q=x.assign(q=x.entry.dt.to_period('Q')).groupby('q').return_atr.agg(['sum','count'])
    rng=np.random.default_rng(16112026)
    idx=rng.integers(len(q),size=(2000,len(q)))
    samples=q['sum'].to_numpy()[idx].sum(axis=1)/q['count'].to_numpy()[idx].sum(axis=1)
    return np.quantile(samples,[.025,.975]).tolist()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prices',required=True)
    source=ap.add_mutually_exclusive_group(required=True);source.add_argument('--cot-root');source.add_argument('--cot-snapshot')
    ap.add_argument('--releases',required=True);ap.add_argument('--diagnostic-nominal-ticks',action='store_true')
    args=ap.parse_args();out=HERE/'output';out.mkdir(exist_ok=True)
    manifest=json.loads((HERE/'source_manifest.json').read_text())
    universe=pd.read_csv(HERE/'universe.csv',dtype={'code':str});universe['root']=universe.ibkr.replace({'6E':'E6'})
    universe=universe[universe.root.isin(PILOT)]
    if args.cot_root:
        cot=load_cot(args.cot_root,manifest,universe)
    else:
        if digest(args.cot_snapshot)!=manifest['cot_snapshot_sha256']:raise ValueError('Frozen COT snapshot checksum mismatch')
        cot=pd.read_csv(args.cot_snapshot,dtype={'code':str},parse_dates=['report'])
    cot=cot.merge(releases(cot,args.releases),on='report',how='inner')
    # Read local existing extract, never export or copy raw prices into GitHub.
    raw=pd.read_csv(args.prices,parse_dates=['session'])
    coverage=dict(rows=len(raw),first=str(raw.session.min().date()),last=str(raw.session.max().date()),roots=int(raw.symbol.nunique()))
    raw=raw[raw.session.le('2021-08-06')]
    check=raw[raw.symbol.isin(PILOT)][['session','symbol','open','high','low','close','volume']].sort_values(['session','symbol']).copy()
    canonical=check.to_csv(index=False,float_format='%.10g',date_format='%Y-%m-%d').encode()
    canonical_sha=hashlib.sha256(canonical).hexdigest()
    audit=dict(status='DIAGNOSTIC ONLY',cot_commit=manifest['cot_commit'],cot_hashes_verified=len(manifest['archives']),
       price_sha256=digest(args.prices),canonical_pilot_sha256=canonical_sha,release_sha256=digest(args.releases),coverage=coverage,
       cutoff='2021-08-06',sealed_from='2021-11-08',python=platform.python_version(),
       exact_blockers=['No contract identifiers or historical roll factors in price input',
         'No adjusted historical tick sizes; nominal ticks are diagnostic proxies',
         'Development COT publication timestamps are estimated',
         'Historical exchange-session calendar alignment not independently certified'],markets=[])
    if manifest.get('canonical_pilot_sha256') and canonical_sha!=manifest['canonical_pilot_sha256']:
        raise ValueError('Fresh R2 data differs from frozen local pilot; investigate before comparing results')
    all_events=[];all_setups=[]
    for row in universe.itertuples():
        cal,tick=PILOT[row.root]
        p,info=prepare(raw,row.root,cal,cot[cot.code.eq(row.code)],tick);audit['markets'].append(info)
        if not args.diagnostic_nominal_ticks:continue
        e,s=entries_and_outcomes(p,apply_cot=False);e['root']=row.root;s['root']=row.root
        e['release_estimated']=e.setup.map(p.release_estimated)
        all_events.append(e);all_setups.append(s)
    (out/'audit.json').write_text(json.dumps(audit,indent=2))
    if not args.diagnostic_nominal_ticks:
        print('EXACT RUN NOT EXECUTED: '+ '; '.join(audit['exact_blockers']));return
    events=pd.concat(all_events,ignore_index=True);setups=pd.concat(all_setups,ignore_index=True)
    events.to_csv(out/'diagnostic_events.csv',index=False);setups.to_csv(out/'diagnostic_setups.csv',index=False)
    qualified=events[events.cot_qualified].copy()
    summary=summarize(qualified)
    summaries=[]
    for _,r in summary.iterrows():
        x=qualified[qualified.horizon.eq(r.horizon)]
        if r.direction!='combined':x=x[x.side.eq(1 if r.direction=='long' else -1)]
        r['ci_low'],r['ci_high']=block_interval(x)
        summaries.append(r)
    summary=pd.DataFrame(summaries);summary.to_csv(out/'diagnostic_summary.csv',index=False)
    summarize(events).to_csv(out/'diagnostic_no_cot_summary.csv',index=False)
    # Same pattern, market, direction and year; descriptive comparison, not a causal estimate.
    events['year']=events.entry.dt.year
    controls=events[~events.cot_qualified].groupby(['root','side','year','horizon']).return_atr.mean().rename('control')
    matched=events[events.cot_qualified].join(controls,on=['root','side','year','horizon']).dropna(subset=['control'])
    matched['difference']=matched.return_atr-matched.control
    matched.groupby('horizon').agg(n=('difference','size'),actual=('return_atr','mean'),control=('control','mean'),difference=('difference','mean')).to_csv(out/'diagnostic_matched.csv')
    print('DIAGNOSTIC ONLY: nominal ticks on ratio-adjusted prices; estimated publication timestamps.')
    print('Historical strategy not validated. Development only; all outcomes end by 2021-08-06.')
    print(summary.round(5).to_string(index=False))
    print('Setup counts:',setups.groupby(['side','status']).size().to_dict())

if __name__=='__main__':main()
