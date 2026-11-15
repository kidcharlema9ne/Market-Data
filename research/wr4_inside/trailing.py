"""Rolling high/low trailing-stop sweep; fixed entries, no new signal optimization."""
import os,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import run as base
from stochastic import stochastic
WINDOWS=[2,3,5,7,10,14,21,42]
CAP=252
B=10000
SEED=2026111503
OUT=Path('research/wr4_inside/trailing_results')


def arrays(p):
    a={x:p[x].to_numpy(copy=True) for x in ['open','high','low','close','atr','date']}
    for n in WINDOWS:
        # shift(1): today's extrema NEVER influence today's stop.
        a[f'lo{n}']=p.low.rolling(n,min_periods=n).min().shift(1).to_numpy()
        a[f'hi{n}']=p.high.rolling(n,min_periods=n).max().shift(1).to_numpy()
    return a


def simulate(a,e,fill,initial,d,atr,tick,window=0,cap=CAP,open_entry=False):
    stop=initial; mflo=0.; mfhi=0.; mae=0.; amb=False
    for j in range(e,min(e+cap,len(a['close']))):
        if j>e and window:
            candidate=a[f'lo{window}'][j]-tick if d==1 else a[f'hi{window}'][j]+tick
            if np.isfinite(candidate): stop=max(stop,candidate) if d==1 else min(stop,candidate)
        o,h,l,c=(a[x][j] for x in ['open','high','low','close'])
        hit=l<=stop if d==1 else h>=stop
        fav=max(0,d*((h if d==1 else l)-fill))
        adv=max(0,-d*((l if d==1 else h)-fill))
        if hit:
            known_open=j>e or open_entry
            gap=known_open and (o<=stop if d==1 else o>=stop)
            exitprice=o if gap else stop
            forced=max(0,d*(o-fill)) if known_open else 0.
            mflo=max(mflo,forced); mfhi=max(mfhi,forced) if gap else max(mfhi,fav)
            mae=max(mae,max(0,-d*(exitprice-fill)))
            amb=(j==e and not open_entry)
            why='gap_stop' if gap else 'stop'
            break
        mflo=max(mflo,fav); mfhi=max(mfhi,fav); mae=max(mae,adv)
    else:
        j=min(e+cap,len(a['close']))-1; exitprice=a['close'][j]; why='time_cap'
    return dict(ret=d*(exitprice-fill)/atr,hold=j-e+1,exit_session=j,exit_price=exitprice,reason=why,mfe_low=mflo/atr,mfe_high=mfhi/atr,mae_upper=mae/atr,ambiguous_entry_stop=amb)


def selftest():
    p=pd.DataFrame({'open':[10,12,14,15,15,15], 'high':[12,14,16,16,16,16], 'low':[9,11,13,12,11.5,12], 'close':[11,13,15,15,15,15], 'atr':[2]*6,'date':pd.date_range('2000-01-01',periods=6)})
    a=arrays(p)
    x=simulate(a,0,10,8,1,2,.1,window=2,cap=6,open_entry=True)
    # Day 4 low 12 cannot influence day 4 stop, which is based on lows 11/13 =>10.9.
    assert x['exit_session']==4 and abs(x['exit_price']-11.9)<1e-9
    q=p.copy();q['open']=-p.open;q['close']=-p.close;q['high']=-p.low;q['low']=-p.high
    y=simulate(arrays(q),0,-10,-8,-1,2,.1,window=2,cap=6,open_entry=True)
    assert abs(x['ret']-y['ret'])<1e-12 and x['hold']==y['hold']
    p.loc[4,['open','high','low','close']]=[10,11,9,10]
    x=simulate(arrays(p),0,10,8,1,2,.1,window=2,cap=6,open_entry=True)
    assert x['reason']=='gap_stop' and x['exit_price']==10
    a=arrays(p);a['low'][0]=7
    x=simulate(a,0,11,8,1,2,.1,window=2,cap=6,open_entry=False)
    assert x['hold']==1 and x['mfe_low']==0 and x['ambiguous_entry_stop']
    # Ratchet: a lower subsequent rolling low must not widen an already tightened stop.
    a=arrays(p);a['lo2']=np.array([np.nan,9,11,8,7,6]);a['low']=np.array([9,10,12,10.5,10,10]);a['open']=np.array([10,12,13,12,12,12])
    x=simulate(a,0,10,8,1,2,.1,window=2,cap=6,open_entry=True)
    assert x['exit_session']==3 and abs(x['exit_price']-10.9)<1e-9
    print('TRAILING SELFTEST PASS',flush=True)


def main():
    selftest();OUT.mkdir(parents=True,exist_ok=True)
    source=pd.read_csv('research/wr4_inside/results/trades.csv')
    one=pd.read_csv('research/wr4_inside/stochastic_results/trade_indicators.csv').sort_values('id').reset_index(drop=True)
    assert len(one)==275
    raw=pd.read_parquet('futures_prices.parquet');raw['date']=pd.to_datetime(raw.file_date);raw=raw[raw.date<=base.END]
    prices={};aa={}
    for root,g in raw.groupby('symbol'):
        g=g.copy();valid=np.isfinite(g[['open','high','low','close']]).all(axis=1)&(g.low<=g[['open','close']].min(axis=1))&(g.high>=g[['open','close']].max(axis=1))&(g.high>=g.low)
        g.loc[~valid,['open','high','low','close']]=np.nan
        p=base.prepare(g);p['k42']=stochastic(p,42);prices[root]=p;aa[root]=arrays(p)
    accepted=[];excluded=[]
    for t in one.itertuples():
        p=prices[t.root];e=int(t.entry_session);setup=int(np.flatnonzero(p.date.to_numpy()==np.datetime64(t.setup_date))[0])
        np.testing.assert_allclose(p.k42.iloc[setup],t.stoch_42,rtol=1e-9,atol=1e-9)
        assert str(p.date.iloc[e].date())==t.entry_date
        np.testing.assert_allclose(p.atr.iloc[e],t.atr,rtol=1e-9,atol=1e-9)
        fresh=base.excursions(p,e,t.fill,t.stop,t.side,bool(t.open_entry))
        old=source[source.id==t.id].sort_values('horizon')
        np.testing.assert_allclose(fresh,old[['horizon']+base.METRICS].to_numpy(),rtol=1e-8,atol=1e-8)
        reason=''
        if e<42: reason='insufficient trailing warmup'
        elif e+CAP>len(p): reason='252-session follow-up crosses development boundary'
        else:
            w=p.iloc[e-42:e+CAP]
            if w[['open','high','low','close']].isna().any().any() or w.date.diff().dt.days.gt(7).any():reason='invalid bar or >7-day gap'
        if reason:excluded.append(dict(id=t.id,market=t.market,entry_date=t.entry_date,reason=reason))
        else:accepted.append(t.id)
    print('REPRODUCED 275 BASELINE TRADES; common 252-session cohort',len(accepted),flush=True)
    cohort=one[one.id.isin(accepted)].copy().reset_index(drop=True)
    cohort['stoch_filter']=np.where(cohort.side==1,cohort.stoch_42<=10,cohort.stoch_42>=90)
    pd.DataFrame(excluded).to_csv(OUT/'exclusions.csv',index=False)
    choices=[('fixed21',0,21),('fixed42',0,42)]+[(f'trail{n}',n,CAP) for n in WINDOWS]
    results=[]
    for t in cohort.itertuples():
        for name,n,cap in choices:
            z=simulate(aa[t.root],int(t.entry_session),t.fill,t.stop,t.side,t.atr,base.TICKS[t.market],n,cap,bool(t.open_entry))
            if n==0:
                val=float(source[(source.id==t.id)&(source.horizon==cap)].return_stopped.iloc[0]);np.testing.assert_allclose(z['ret'],val,rtol=1e-8,atol=1e-8)
            results.append(dict(id=t.id,market=t.market,side=t.side,year=t.year,entry_date=t.entry_date,stoch_filter=t.stoch_filter,exit=name,**z))
    results=pd.DataFrame(results);results.to_csv(OUT/'trades.csv',index=False)
    summaries=[]
    for label,sub in [('all',results),('stoch42_10_90',results[results.stoch_filter])]:
        for split,df in [('all',sub),('2008-2014',sub[sub.year<=2014]),('2015-2021',sub[sub.year>=2015]),('buys',sub[sub.side==1]),('sells',sub[sub.side==-1])]:
            for name,g in df.groupby('exit'):
                summaries.append(dict(sample=label,subset=split,exit=name,n=len(g),markets=g.market.nunique(),mean=g.ret.mean(),median=g.ret.median(),win_rate=(g.ret>0).mean(),mean_hold=g.hold.mean(),median_hold=g.hold.median(),mfe_mean=g.mfe_low.mean(),mae_mean=g.mae_upper.mean(),time_cap=int((g.reason=='time_cap').sum()),gap_stops=int((g.reason=='gap_stop').sum()),**{f'p{q}':g.ret.quantile(q/100) for q in [10,25,75,90,95]}))
    summary=pd.DataFrame(summaries);summary.to_csv(OUT/'summary.csv',index=False)
    # Current conventions for COT-conditioned random OPEN controls; actual publication delays remain unmodeled.
    cot=pd.read_csv('research/wr4_inside/cot_weekly_full.csv.gz',dtype={'code':str},parse_dates=['date'])
    universe=pd.read_csv('futures_data/report_universe_48_markets.csv',dtype={'code':str})
    candidates={}
    for u in universe.itertuples():
        if u.ibkr not in set(cohort.market):continue
        root=base.ALIASES.get(u.ibkr,u.ibkr);p=prices[root];c=cot[cot.code==u.code].sort_values('date').copy()
        for col in ['comm','large','small']:
            lo=c[col].rolling(26,min_periods=26).min();hi=c[col].rolling(26,min_periods=26).max();c[col+'_idx']=100*(c[col]-lo)/(hi-lo).replace(0,np.nan)
        c['pub']=base.publication(pd.DatetimeIndex(c.date))
        join=pd.merge_asof(p[['date']],c[['pub','comm_idx','large_idx','small_idx']],left_on='date',right_on='pub',allow_exact_matches=False)
        long=(join.comm_idx>=95)&(join.large_idx<=5)&(join.small_idx<=5);short=(join.comm_idx<=5)&(join.large_idx>=95)&(join.small_idx>=95)
        signal=np.r_[0,np.where(long,1,np.where(short,-1,0))[:-1]]
        bad=p[['open','high','low','close']].isna().any(axis=1).to_numpy();gaps=p.date.diff().dt.days.gt(7).to_numpy()
        for d in [-1,1]:
            for year in cohort.loc[cohort.market==u.ibkr,'year'].unique():
                inds=np.flatnonzero((signal==d)&(p.date.dt.year.to_numpy()==year))
                inds=[e for e in inds if e>=42 and e+CAP<=len(p) and np.isfinite(p.atr.iloc[e]) and p.atr.iloc[e]>0 and not bad[e-42:e+CAP].any() and not gaps[e-41:e+CAP].any()]
                candidates[(u.ibkr,d,year)]=inds
    rng=np.random.default_rng(SEED);sums={'all':np.zeros((B,len(choices))),'stoch42_10_90':np.zeros((B,len(choices)))};obs={'all':[],'stoch42_10_90':[]};matched=[]
    for t in cohort.itertuples():
        inds=candidates[(t.market,t.side,t.year)];a=aa[t.root];tick=base.TICKS[t.market]
        if not inds:continue
        risk=t.side*(t.fill-t.stop)/t.atr;pool=[]
        for e in inds:
            fill=a['open'][e];atr=a['atr'][e];stop=fill-t.side*risk*atr
            pool.append([simulate(a,e,fill,stop,t.side,atr,tick,n,cap,True)['ret'] for _,n,cap in choices])
        pool=np.asarray(pool);draws=pool[rng.integers(0,len(pool),B)]
        actual=results[results.id==t.id].set_index('exit').loc[[x[0] for x in choices],'ret'].to_numpy()
        labels=['all']+(['stoch42_10_90'] if t.stoch_filter else [])
        for label in labels:sums[label]+=draws;obs[label].append(actual)
        matched.append(dict(id=t.id,candidates=len(pool),stoch_filter=t.stoch_filter))
    pd.DataFrame(matched).to_csv(OUT/'control_matching.csv',index=False)
    tests=[];zsims=[];details=[]
    for label in sums:
        if not obs[label]:continue
        simulated=sums[label]/len(obs[label]);actual=np.asarray(obs[label]).mean(0);null=simulated.mean(0);sd=simulated.std(0,ddof=1)
        z=np.divide(actual-null,sd,out=np.zeros_like(actual),where=sd>1e-12);zs=np.divide(simulated-null,sd,out=np.zeros_like(simulated),where=sd>1e-12)
        zsims.append(zs[:,2:]);details.append((label,simulated,actual,null,z))
    maxnull=np.concatenate(zsims,axis=1).max(axis=1)
    for label,simulated,actual,null,z in details:
        for k,(name,n,cap) in enumerate(choices):
            tests.append(dict(sample=label,exit=name,n_matched=len(obs[label]),observed_mean=actual[k],random_mean=null[k],random_p025=np.quantile(simulated[:,k],.025),random_p975=np.quantile(simulated[:,k],.975),raw_p=(1+(simulated[:,k]>=actual[k]).sum())/(B+1),p_grid_adjusted=(1+(maxnull>=z[k]).sum())/(B+1) if n else np.nan))
    tests=pd.DataFrame(tests);tests.to_csv(OUT/'random_controls.csv',index=False)
    # Shared 90-calendar-day block bootstrap for return and paired improvement over fixed21.
    cis=[];cross=[]
    for label,sub in [('all',results),('stoch42_10_90',results[results.stoch_filter])]:
        pivot=sub.pivot(index='id',columns='exit',values='ret');meta=cohort.set_index('id').loc[pivot.index]
        blocks=((pd.to_datetime(meta.entry_date)-pd.Timestamp('2000-01-01')).dt.days//90).to_numpy();unique=np.unique(blocks);ix=rng.integers(0,len(unique),(B,len(unique)));counts=np.array([(blocks==b).sum() for b in unique]);den=counts[ix].sum(1)
        for name,n,cap in choices:
            vals=pivot[name].to_numpy();diff=vals-pivot.fixed21.to_numpy();totals=np.array([vals[blocks==b].sum() for b in unique]);dt=np.array([diff[blocks==b].sum() for b in unique]);boot=totals[ix].sum(1)/den;db=dt[ix].sum(1)/den
            cis.append(dict(sample=label,exit=name,n=len(vals),mean=vals.mean(),low=np.quantile(boot,.025),high=np.quantile(boot,.975),difference_vs_fixed21=diff.mean(),difference_low=np.quantile(db,.025),difference_high=np.quantile(db,.975)))
        for train,test in [('2008-2014','2015-2021'),('2015-2021','2008-2014')]:
            trainrows=summary[(summary['sample']==label)&(summary.subset==train)&(summary.exit.str.startswith('trail'))&(summary.n>=15)]
            if trainrows.empty:continue
            best=trainrows.sort_values('mean',ascending=False).iloc[0];testrow=summary[(summary['sample']==label)&(summary.subset==test)&(summary.exit==best.exit)]
            if testrow.empty:continue
            t=testrow.iloc[0];ref=summary[(summary['sample']==label)&(summary.subset==test)&(summary.exit=='fixed21')].iloc[0]
            cross.append(dict(sample=label,train=train,test=test,selected=best.exit,train_mean=best['mean'],test_n=int(t.n),test_mean=t['mean'],test_fixed21=ref['mean'],passes=bool(t.n>=15 and t['mean']>0 and t['mean']>ref['mean'])))
    pd.DataFrame(cis).to_csv(OUT/'block_confidence.csv',index=False);pd.DataFrame(cross).to_csv(OUT/'cross_era.csv',index=False)
    run=os.getenv('GITHUB_RUN_ID','local');sha=os.getenv('GITHUB_SHA','local')
    cols=['sample','exit','n','mean','median','win_rate','mean_hold','time_cap']
    report=['# COT WR4 trailing-stop sweep',f'Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/{run}',f'Code commit: {sha}',
    'Windows: 2,3,5,7,10,14,21,42 sessions. Initial WR4 protective stop is retained on entry day. Starting the next session, long stop=max(previous stop, lowest low of preceding N completed market sessions minus nominal tick); short is mirrored using highest high. Rolling windows may include pre-entry sessions. Stop never loosens. Current-bar high/low cannot move its own stop. Opening gaps fill at open. Intraday-entry same-bar stops charged conservatively.',
    'No fixed 21-session exit for trailing variants; maximum 252 sessions. Both fixed21 and fixed42 retain the original protective stop. Same common cohort for every exit, requiring 42-session warmup and full 252-session valid follow-up within development data through 2021-08-06. This avoids differing end-of-sample censoring across exits, but shrinks sample versus original 275 / 47. Exclusions are recorded. No sealed years opened.',
    'Reproduced all 275 baseline outcomes and stochastic42 values before eligibility filtering; fixed exits on retained sample also reproduce the prior run.',
    f'Common cohort: {len(cohort)} unfiltered / {int(cohort.stoch_filter.sum())} stochastic42 <=10 buys or >=90 sells. Excluded {len(excluded)} baseline events.',
    'Random controls: 10,000 draws of eligible opening entries with prior-known COT alignment, same market/year/direction, observed initial risk in ATR, and identical trailing logic. Filtered strategy controls do NOT also require stochastic alignment: comparison tests combined timing package. Match counts reported. Open-entry versus breakout-entry execution differs. Maximum standardized statistic corrects across 8 trailing exits x 2 samples. Serial dependence can make these resampling probabilities optimistic; 90-day calendar-block confidence intervals and cross-era selection are additional diagnostics. No costs beyond gaps. Prior nominal-tick / ratio-adjusted-price / approximate-release-date limitations remain.',
    '\n## Full-sample exit comparison',summary[summary.subset=='all'][cols].to_markdown(index=False),
    '\n## Random controls',tests.to_markdown(index=False),
    '\n## Block confidence and paired comparison',pd.DataFrame(cis).to_markdown(index=False),
    '\n## Cross-era selection',pd.DataFrame(cross).to_markdown(index=False)]
    (OUT/'REPORT.md').write_text('\n\n'.join(report));(OUT/'provenance.json').write_text(json.dumps(dict(run=run,sha=sha,seed=SEED,draws=B,windows=WINDOWS,cap=CAP,prices_sha256=hashlib.sha256(Path('futures_prices.parquet').read_bytes()).hexdigest()),indent=2))
    print('\n'.join(report),flush=True)

if __name__=='__main__':
    import sys
    selftest() if '--selftest' in sys.argv else main()
