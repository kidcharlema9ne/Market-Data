"""Predeclared reversal stochastic sweep on fixed, reproduced WR4 development trades."""
import os,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import run as base
PERIODS=[5,10,14,21,42]
LEVELS=[5,10,20,30]
HS=[5,10,21,42]
B=10000
SEED=2026111502
OUT=Path('research/wr4_inside/stochastic_results')


def stochastic(p,n):
    lo=p.low.rolling(n,min_periods=n).min(); hi=p.high.rolling(n,min_periods=n).max()
    return 100*(p.close-lo)/(hi-lo).replace(0,np.nan)


def selftest():
    p=pd.DataFrame({'high':[10]*50,'low':[0]*50,'close':[1]*50})
    assert stochastic(p,14).iloc[13]==10 and np.isnan(stochastic(p,14).iloc[12])
    p.loc[14:,'close']=9
    assert stochastic(p,14).iloc[13]==10 and stochastic(p,14).iloc[14]==90
    q=p.copy(); q['high']=-p.low; q['low']=-p.high; q['close']=-p.close
    np.testing.assert_allclose(stochastic(p,14).dropna()+stochastic(q,14).dropna(),100)
    q=pd.DataFrame({'high':[1]*20,'low':[1]*20,'close':[1]*20}); assert stochastic(q,14).isna().all()
    print('STOCHASTIC SELFTEST PASS',flush=True)


def main():
    selftest(); OUT.mkdir(parents=True,exist_ok=True)
    trades=pd.read_csv('research/wr4_inside/results/trades.csv')
    one=trades[trades.horizon==21].sort_values('id').reset_index(drop=True)
    assert len(one)==275 and one.id.nunique()==275
    px=pd.read_parquet('futures_prices.parquet'); px['date']=pd.to_datetime(px.file_date); px=px[px.date<=base.END]
    prices={}
    for root,g in px.groupby('symbol'):
        g=g.copy(); finite=np.isfinite(g[['open','high','low','close']]).all(axis=1)
        valid=finite&(g.low<=g[['open','close']].min(axis=1))&(g.high>=g[['open','close']].max(axis=1))&(g.high>=g.low)
        g.loc[~valid,['open','high','low','close']]=np.nan
        p=base.prepare(g)
        for n in PERIODS: p[f'k{n}']=stochastic(p,n)
        prices[root]=p
    ks=[]
    for t in one.itertuples():
        p=prices[t.root]; setup=np.flatnonzero(p.date.to_numpy()==np.datetime64(t.setup_date))
        assert len(setup)==1
        e=int(t.entry_session); assert str(p.date.iloc[e].date())==t.entry_date
        np.testing.assert_allclose(p.atr.iloc[e],t.atr,rtol=1e-9,atol=1e-9)
        i=int(setup[0])-1
        entry=base.breakout(p,i,t.side,base.TICKS[t.market]); assert entry is not None and entry[0]==e
        np.testing.assert_allclose(entry[1:3],[t.fill,t.stop],rtol=1e-9,atol=1e-9)
        fresh=base.excursions(p,e,t.fill,t.stop,t.side,bool(t.open_entry))
        old=trades[trades.id==t.id].sort_values('horizon')
        np.testing.assert_allclose(np.array(fresh),old[['horizon']+base.METRICS].to_numpy(),rtol=1e-8,atol=1e-8)
        ks.append([p[f'k{n}'].iloc[int(setup[0])] for n in PERIODS])
    print('REPRODUCED ALL 275 BASELINE TRADES AND FOUR HORIZONS',flush=True)
    kval=np.asarray(ks)
    for j,n in enumerate(PERIODS): one[f'stoch_{n}']=kval[:,j]
    one.to_csv(OUT/'trade_indicators.csv',index=False)
    choices=[(n,l) for n in PERIODS for l in LEVELS]
    masks=np.array([np.where(one.side.to_numpy()==1,kval[:,PERIODS.index(n)]<=l,kval[:,PERIODS.index(n)]>=100-l)&np.isfinite(kval[:,PERIODS.index(n)]) for n,l in choices])
    era=np.where(one.year.to_numpy()<=2014,'2008-2014','2015-2021')
    rows=[]; dist=[]; Ys=[]
    for h in HS:
        d=trades[trades.horizon==h].set_index('id').loc[one.id]
        Ys.append(d.return_stopped.to_numpy())
        for label,n,l,m in [('baseline',0,0,np.ones(len(one),dtype=bool))]+[(f'{n}-session / {l}-{100-l}',n,l,masks[j]) for j,(n,l) in enumerate(choices)]:
            for subset,subsetmask in [('all',np.ones(len(one),bool)),('2008-2014',era=='2008-2014'),('2015-2021',era=='2015-2021'),('buys',one.side.to_numpy()==1),('sells',one.side.to_numpy()==-1)]:
                selected=m&subsetmask; g=d.iloc[np.flatnonzero(selected)]
                row=dict(filter=label,period=n,level=l,horizon=h,subset=subset,n=len(g),markets=one.loc[selected,'market'].nunique())
                for metric in ['return_stopped','return_unstopped','prestop_mfe_low','mfe','mae_high','prestop_mae','stop_conservative']:
                    row[metric+'_mean']=g[metric].mean(); row[metric+'_median']=g[metric].median()
                row['win_rate']=(g.return_stopped>0).mean() if len(g) else np.nan
                rows.append(row)
                if subset=='all':
                    for metric in ['return_stopped','prestop_mfe_low','mae_high']:
                        dist.append(dict(filter=label,horizon=h,metric=metric,n=len(g),**{f'p{q}':g[metric].quantile(q/100) for q in [10,25,50,75,90,95]}))
    grid=pd.DataFrame(rows);grid.to_csv(OUT/'grid.csv',index=False);pd.DataFrame(dist).to_csv(OUT/'distributions.csv',index=False)
    # Joint permutation: shuffle entire four-horizon outcome vector within market/direction/year.
    # Masks fixed; preserve subgroup counts and cross-horizon dependence. This tests the incremental filter,
    # not unconditional profitability or realistic random-entry execution.
    y=np.array(Ys).T
    groups=list(one.groupby(['market','side','year']).indices.values())
    count=masks.sum(1)
    eligible=(count>=30)&((masks[:,era=='2008-2014'].sum(1))>=10)&((masks[:,era=='2015-2021'].sum(1))>=10)
    expected=y.copy()
    for ids in groups: expected[ids]=y[ids].mean(0)
    denom=np.maximum(1,count)[:,None]
    nullmean=masks.astype(float)@expected/denom; observed=masks.astype(float)@y/denom
    rng=np.random.default_rng(SEED); sims=np.empty((B,len(choices),len(HS)))
    for b in range(B):
        perm=np.arange(len(one))
        for ids in groups: perm[ids]=rng.permutation(ids)
        sims[b]=masks.astype(float)@y[perm]/denom
    sd=sims.std(axis=0,ddof=1); z=np.divide(observed-nullmean,sd,out=np.zeros_like(observed),where=sd>1e-12)
    zsim=np.divide(sims-nullmean,sd,out=np.zeros_like(sims),where=sd>1e-12)
    family21=zsim[:,eligible,2].max(axis=1) if eligible.any() else np.full(B,np.nan)
    familyall=zsim[:,eligible,:].max(axis=(1,2)) if eligible.any() else np.full(B,np.nan)
    tests=[]
    for j,(n,l) in enumerate(choices):
        for k,h in enumerate(HS):
            testable=bool(eligible[j] and sd[j,k]>1e-12)
            tests.append(dict(period=n,level=l,horizon=h,n=int(count[j]),eligible_for_inference=testable,observed_mean=observed[j,k] if count[j] else np.nan,matched_random_filter_mean=nullmean[j,k] if count[j] else np.nan,incremental_mean=(observed-nullmean)[j,k] if count[j] else np.nan,raw_p=(1+(sims[:,j,k]>=observed[j,k]).sum())/(B+1) if testable else np.nan,p_adjusted_21=(1+(family21>=z[j,k]).sum())/(B+1) if testable and h==21 else np.nan,p_adjusted_all_horizons=(1+(familyall>=z[j,k]).sum())/(B+1) if testable else np.nan))
    tests=pd.DataFrame(tests); tests.to_csv(OUT/'multiple_testing.csv',index=False)
    # Baseline and filtered return confidence intervals, resampling shared 90-calendar-day blocks.
    block=((pd.to_datetime(one.entry_date)-pd.Timestamp('2000-01-01')).dt.days//90).to_numpy(); unique=np.unique(block)
    blockdraws=rng.integers(0,len(unique),(B,len(unique))); ci=[]
    for j,m in [(-1,np.ones(len(one),bool))]+[(j,masks[j]) for j in range(len(choices)) if eligible[j]]:
        n,l=(0,0) if j==-1 else choices[j]
        ns=np.array([sum(m&(block==b)) for b in unique]); den=ns[blockdraws].sum(1)
        for k,h in enumerate(HS):
            totals=np.array([y[m&(block==b),k].sum() for b in unique]); vals=np.divide(totals[blockdraws].sum(1),den,out=np.full(B,np.nan),where=den>0)
            ci.append(dict(period=n,level=l,horizon=h,n=int(m.sum()),mean=y[m,k].mean(),low=np.nanquantile(vals,.025),high=np.nanquantile(vals,.975)))
    pd.DataFrame(ci).to_csv(OUT/'block_confidence.csv',index=False)
    # Select on one era only, evaluate selected setting on the other. 21 sessions predeclared primary.
    cross=[]
    for train,test in [('2008-2014','2015-2021'),('2015-2021','2008-2014')]:
        a=grid[(grid.horizon==21)&(grid.subset==train)&(grid.period>0)&(grid.n>=15)].sort_values(['return_stopped_mean','n'],ascending=False)
        if a.empty: continue
        best=a.iloc[0]; b=grid[(grid.period==best.period)&(grid.level==best.level)&(grid.horizon==21)&(grid.subset==test)].iloc[0]
        ref=grid[(grid.period==0)&(grid.horizon==21)&(grid.subset==test)].iloc[0]
        cross.append(dict(train=train,test=test,period=int(best.period),level=int(best.level),train_n=int(best.n),train_mean=best.return_stopped_mean,test_n=int(b.n),test_mean=b.return_stopped_mean,test_baseline_mean=ref.return_stopped_mean,passes=bool(b.n>=15 and b.return_stopped_mean>0 and b.return_stopped_mean>ref.return_stopped_mean)))
    pd.DataFrame(cross).to_csv(OUT/'cross_era.csv',index=False)
    ranked=grid[(grid.horizon==21)&(grid.subset=='all')].sort_values('return_stopped_mean',ascending=False)
    show=['period','level','n','return_stopped_mean','return_stopped_median','prestop_mfe_low_mean','stop_conservative_mean']
    run=os.getenv('GITHUB_RUN_ID','local'); sha=os.getenv('GITHUB_SHA','local')
    report=['# Reversal stochastic sweep on COT + WR4 / inside-day trades',f'Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/{run}',f'Code commit: {sha}',
    'All 275 baseline trades and all four outcome horizons independently reproduced against fetched prices before filtering.',
    'Raw, unsmoothed stochastic %K = 100*(inside-day close - N-session lowest low)/(N-session highest high - lowest low). Includes the inside day; no future bars. Buy <= threshold, sell >= 100-threshold. No crossover requirement. Periods 5/10/14/21/42; levels 5/10/20/30 (20 settings).',
    'Primary: stopped return at 21 sessions. Secondary: 5/10/42 sessions. Same original protective stop and no trailing stops. Development only through 2021-08-06. All baseline approximations retained: nominal ticks on ratio-adjusted prices; estimated release dates, not actual delays; no costs except gap fills; overlapping signals.',
    'Inference requires >=30 trades and >=10 in each era. Smaller cells remain descriptive and cannot be selected as an edge. 10,000 joint outcome-vector permutations within market/direction/year; studentized maximum-statistic correction across eligible settings (primary 21 only and all four horizons separately). Conditional filter-placebo test, not a fresh random-entry test. Sparse groups, temporal clustering and selection from already-explored data limit inference; 90-calendar-day block intervals also reported.',
    f'Movable trades in permutation strata: {sum(len(g) for g in groups if len(g)>1)} / {len(one)}; eligible settings: {int(eligible.sum())} / 20.',
    'Cross-era diagnostic: choose highest 21-session stopped mean among settings with >=15 training trades; hold that choice fixed in the other era. A pass requires >=15 test trades, positive mean, and improvement over test-era unfiltered baseline. This is a robustness diagnostic within development data, not a pristine holdout.',
    '\n## All 21-session settings (including thin cells)',ranked[show].to_markdown(index=False),
    '\n## Multiple-testing results at 21 sessions',tests[tests.horizon==21].to_markdown(index=False),
    '\n## Cross-era selection',pd.DataFrame(cross).to_markdown(index=False),
    '\n## Return uncertainty',pd.DataFrame(ci).query('horizon==21').to_markdown(index=False)]
    (OUT/'REPORT.md').write_text('\n\n'.join(report))
    (OUT/'provenance.json').write_text(json.dumps(dict(run=run,sha=sha,seed=SEED,draws=B,periods=PERIODS,thresholds=LEVELS,baseline_trades_sha256=hashlib.sha256(Path('research/wr4_inside/results/trades.csv').read_bytes()).hexdigest(),prices_sha256=hashlib.sha256(Path('futures_prices.parquet').read_bytes()).hexdigest()),indent=2))
    print('\n'.join(report),flush=True)

if __name__=='__main__':
    import sys
    selftest() if '--selftest' in sys.argv else main()
