"""User-authorized APPROXIMATE continuous-price WR4 study; development sample only."""
import os, json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

OUT=Path('research/wr4_inside/results'); OUT.mkdir(parents=True,exist_ok=True)
HORIZONS=(5,10,21,42)
END=pd.Timestamp('2021-08-06')
ALIASES={'6A':'A6','6B':'B6','6C':'AD','6E':'E6','6J':'J1','6L':'BR','6M':'MP','6N':'N6','6S':'E1','ZB':'US'}
# NOMINAL exchange ticks applied to adjusted prices: explicit approximation, not historical tradable ticks.
TICKS={'ZW':.25,'KE':.25,'ZC':.25,'ZS':.25,'ZL':.01,'ZB':1/32,'UB':1/32,'HO':.0001,'NG':.001,'ZM':.1,'CT':.01,'ZT':1/256,'ZN':1/64,'TN':1/64,'ZF':1/128,'ZQ':.005,'HE':.025,'LE':.025,'GF':.025,'CL':.01,'BZ':.01,'CC':1,'PL':.1,'SB':.01,'KC':.05,'SI':.005,'HG':.0005,'GC':.1,'6C':.00005,'6S':.0001,'6M':.00001,'6B':.0001,'6J':.0000005,'DX':.005,'6E':.00005,'6L':.00005,'RB':.0001,'6N':.0001,'VX':.05,'YM':1,'SR3':.0025,'SR1':.005,'ES':.25,'MES':.25,'NQ':.25,'MNQ':.25,'6A':.0001,'RTY':.1}
METRICS=['mfe','mae_low','mae_high','prestop_mfe_low','prestop_mfe_high','prestop_mae','stop_conservative','entry_stop_ambiguous','return_unstopped','return_stopped']


def publication(dates):
    # Existing repository convention; NOT verified actual release dates.
    hol=set(USFederalHolidayCalendar().holidays(dates.min()-pd.Timedelta(days=7),dates.max()+pd.Timedelta(days=14)))
    out=[]
    for d in dates:
        mon=d-pd.Timedelta(days=d.weekday())
        fri=mon+pd.Timedelta(days=4)
        if any(mon+pd.Timedelta(days=i) in hol for i in range(5)): fri+=pd.Timedelta(days=3)
        out.append(fri)
    return pd.DatetimeIndex(out)


def prepare(g):
    g=g.sort_values('date').copy().reset_index(drop=True)
    pc=g.close.shift(1)
    tr=pd.concat([g.high-g.low,(g.high-pc).abs(),(g.low-pc).abs()],axis=1).max(axis=1)
    tr.iloc[0]=np.nan
    g['atr']=tr.rolling(14,min_periods=14).mean().shift(1)
    return g


def breakout(p,i,d,tick):
    """i is WR4 day. Day 2 must already be strict inside. Only i+2/i+3."""
    threshold=p.high.iloc[i]+tick if d==1 else p.low.iloc[i]-tick
    stop=p.low.iloc[i]-tick if d==1 else p.high.iloc[i]+tick
    for e in (i+2,i+3):
        if e>=len(p): break
        bar=p.iloc[e]
        if (d==1 and bar.high>=threshold) or (d==-1 and bar.low<=threshold):
            fill=max(bar.open,threshold) if d==1 else min(bar.open,threshold)
            return e,fill,stop,(bar.open>=threshold if d==1 else bar.open<=threshold)
    return None


def excursions(p,e,fill,stop,d,open_entry):
    """Bounds for daily-bar ordering; conservative stop scenario is kept separate."""
    atr=p.atr.iloc[e]
    b=p.iloc[e:e+42]
    fav=np.maximum(0,d*((b.high if d==1 else b.low).to_numpy()-fill))
    adv=np.maximum(0,-d*((b.low if d==1 else b.high).to_numpy()-fill))
    oc=d*(b.open.to_numpy()-fill); cc=d*(b.close.to_numpy()-fill)
    risk=d*(fill-stop)
    hits=adv>=risk
    amb=bool(not open_entry and hits[0])
    first=int(np.flatnonzero(hits)[0]) if hits.any() else 999
    result=[]
    for h in HORIZONS:
        if len(b)<h: continue
        # Favorable entry-bar extreme follows first threshold crossing. Adverse extreme may precede entry.
        al=adv[:h].copy()
        if not open_entry: al[0]=max(0,-cc[0])
        mfe=float(fav[:h].max()); mal=float(al.max()); mau=float(adv[:h].max())
        if first<h:
            k=first
            gap=(k>0 or open_entry) and oc[k]<=-risk
            exit_delta=oc[k] if gap else -risk
            prior=float(fav[:k].max()) if k else 0.
            forced=max(0,oc[k]) if k>0 or open_entry else 0.
            mflo=max(prior,forced)
            mfhi=mflo if gap else max(mflo,float(fav[k]))
            # All prior bars are stop-free; at intraday stop, adverse excursion ends at stop.
            ma=max(float(adv[:k].max()) if k else 0.,-exit_delta)
            sr=exit_delta/atr
        else:
            mflo=mfhi=mfe; ma=mau; sr=cc[h-1]/atr
        result.append([h,mfe/atr,mal/atr,mau/atr,mflo/atr,mfhi/atr,ma/atr,float(first<h),float(amb),cc[h-1]/atr,sr])
    return result


def summary(df):
    rows=[]
    for (sample,side,h),g in df.groupby(['sample','side','horizon']):
        for m in METRICS:
            v=g[m]
            rows.append(dict(sample=sample,side=side,horizon=int(h),metric=m,n=len(g),mean=v.mean(),median=v.median(),sd=v.std(),**{f'p{q}':v.quantile(q/100) for q in [10,25,75,90,95]}))
    return pd.DataFrame(rows)


def selftest():
    # Strict inside day, ties, Day 4 valid, Day 5 invalid, gap and conservative stop fixtures.
    p=pd.DataFrame({'open':[8]*8,'high':[10,10,10,12,11,11,13,14],'low':[6,6,6,6,7,7,5,5],'close':[8]*8,'atr':[2]*8})
    assert (p.high-p.low).iloc[3]==(p.high-p.low).iloc[:4].max()
    assert p.high.iloc[4]<p.high.iloc[3] and p.low.iloc[4]>p.low.iloc[3]
    x=breakout(p,3,1,.25); assert x[0]==6 and x[1]==12.25 and x[2]==5.75
    p.loc[6,'high']=12; assert breakout(p,3,1,.25) is None
    p.loc[5,['open','high']]=[14,15]; x=breakout(p,3,1,.25); assert x[1]==14 and x[3]
    b=pd.DataFrame({'open':[10]*42,'high':[15]*42,'low':[7]*42,'close':[11]*42,'atr':[2]*42})
    a=excursions(b,0,12,8,1,False)[0]; assert a[4]==0 and a[7]==1 and a[8]==1
    b.loc[0,['high','low','close']]=[13,9,12]
    b.loc[1,['open','high','low','close']]=[6,7,5,6]
    a=excursions(b,0,12,8,1,False)[0]; assert a[6]==3 and a[10]==-3
    # Mirror all prices: long and short outputs must match.
    c=b.copy(); c['open']=-b.open; c['close']=-b.close; c['high']=-b.low; c['low']=-b.high
    np.testing.assert_allclose(excursions(b,0,12,8,1,False),excursions(c,0,-12,-8,-1,False))
    print('SELFTEST PASS',flush=True)


def main():
    selftest()
    universe=pd.read_csv('futures_data/report_universe_48_markets.csv',dtype={'code':str})
    cot=pd.read_csv('research/wr4_inside/cot_weekly_full.csv.gz',dtype={'code':str},parse_dates=['date'])
    px=pd.read_parquet('futures_prices.parquet'); px['date']=pd.to_datetime(px.file_date)
    px=px[px.date<=END].copy()  # No sealed outcomes inspected.
    audit=[]; prices={}; signals={}; events=[]; uid=0
    for u in universe.itertuples():
        root=ALIASES.get(u.ibkr,u.ibkr)
        p=px[px.symbol==root].copy()
        dup=int(p.duplicated('date',keep=False).sum())
        finite=np.isfinite(p[['open','high','low','close']]).all(axis=1)
        valid=finite & (p.low<=p[['open','close']].min(axis=1)) & (p.high>=p[['open','close']].max(axis=1)) & (p.high>=p.low)
        bad_dates=set(p.loc[~valid,'date'])
        if dup: raise ValueError(f'Conflicting or duplicate dates: {root}')
        # Keep bad bars as NaN; never bridge them as if a trading session disappeared.
        p.loc[~valid,['open','high','low','close']]=np.nan
        p=prepare(p); prices[u.ibkr]=p
        c=cot[cot.code==u.code].sort_values('date').copy()
        if c.date.duplicated().any(): raise ValueError(f'Duplicate COT {u.code}')
        for col in ['comm','large','small']:
            lo=c[col].rolling(26,min_periods=26).min(); hi=c[col].rolling(26,min_periods=26).max()
            c[col+'_idx']=100*(c[col]-lo)/(hi-lo).replace(0,np.nan)
        c['pub']=publication(pd.DatetimeIndex(c.date))
        if not c.pub.is_monotonic_increasing: raise ValueError('Unordered publication estimates')
        # Most recent estimated publication strictly BEFORE setup date (conservative whole-day convention).
        joined=pd.merge_asof(p[['date']],c[['pub','date','comm_idx','large_idx','small_idx']].rename(columns={'date':'report_date'}),left_on='date',right_on='pub',allow_exact_matches=False)
        long=(joined.comm_idx>=95)&(joined.large_idx<=5)&(joined.small_idx<=5)
        short=(joined.comm_idx<=5)&(joined.large_idx>=95)&(joined.small_idx>=95)
        sig=np.where(long,1,np.where(short,-1,0)); signals[u.ibkr]=sig
        count=0; ranges=p.high-p.low; wr=ranges>=ranges.rolling(4,min_periods=4).max()
        for i in range(3,len(p)-2):
            if not (wr.iloc[i] and p.high.iloc[i+1]<p.high.iloc[i] and p.low.iloc[i+1]>p.low.iloc[i]): continue
            for d in (1,-1):
                x=breakout(p,i,d,TICKS[u.ibkr])
                if x is None: continue
                e,fill,stop,oe=x
                if e<15 or e+42>len(p) or not np.isfinite(p.atr.iloc[e]) or p.atr.iloc[e]<=0: continue
                window=p.iloc[e-15:e+42]
                if window[['open','high','low','close']].isna().any().any() or window.date.diff().dt.days.gt(7).any(): continue
                meta=dict(id=uid,market=u.ibkr,code=u.code,root=root,side=d,wr4_date=str(p.date.iloc[i].date()),setup_date=str(p.date.iloc[i+1].date()),entry_date=str(p.date.iloc[e].date()),entry_session=e,breakout_day=e-i+1,fill=fill,stop=stop,atr=p.atr.iloc[e],open_entry=bool(oe),cot_qualified=bool(sig[i+1]==d),report_date=str(joined.report_date.iloc[i+1]),estimated_pub=str(joined.pub.iloc[i+1]),year=p.date.iloc[e].year)
                for vals in excursions(p,e,fill,stop,d,oe): events.append(dict(**meta,**dict(zip(['horizon']+METRICS,vals))))
                uid+=1; count+=1
        audit.append(dict(market=u.ibkr,code=u.code,root=root,rows=len(p),invalid_bars=len(bad_dates),duplicate_dates=dup,cot_rows=len(c),pattern_events=count,nominal_tick=TICKS[u.ibkr]))
    all_events=pd.DataFrame(events)
    if all_events.empty: raise RuntimeError('No events')
    observed=all_events[all_events.cot_qualified].copy()
    # Primary economic universe excludes duplicate micro index products; also show literal 48-market list.
    primary=observed[~observed.market.isin(['MES','MNQ'])].copy()
    pilot=primary[primary.market.isin(['ES','CL','GC','ZN','6E','ZC'])].copy()
    print('PILOT JOINS AND TRADES',pilot.groupby(['market','horizon']).size().to_string(),flush=True)
    frames=[]
    for label,df in [('pilot',pilot),('economic_universe',primary),('all_48',observed)]:
        for side in [0,1,-1]:
            tmp=df.copy() if side==0 else df[df.side==side].copy()
            tmp['sample']=label; tmp['side']=side; frames.append(tmp)
    sums=summary(pd.concat(frames,ignore_index=True))
    primary.to_csv(OUT/'trades.csv',index=False); observed.to_csv(OUT/'trades_all_48.csv',index=False)
    pd.DataFrame(audit).to_csv(OUT/'data_audit.csv',index=False); sums.to_csv(OUT/'summary.csv',index=False)
    market=primary.groupby(['market','side','horizon'])[METRICS].agg(['count','mean','median']); market.to_csv(OUT/'by_market.csv')
    primary.groupby(['market','horizon'])[METRICS].mean().groupby('horizon').mean().to_csv(OUT/'market_equal_means.csv')
    controls=[]; rng=np.random.default_rng(20261115); B=10000
    control_metrics=['mfe','mae_high','prestop_mfe_low','stop_conservative','return_unstopped','return_stopped']
    for h in HORIZONS:
        obs=primary[primary.horizon==h]
        for kind in ['cot_conditioned_random_open','pattern_without_cot']:
            pools=[]; matched=[]
            for t in obs.itertuples():
                p=prices[t.market]
                if kind=='pattern_without_cot':
                    pool=all_events[(all_events.horizon==h)&(all_events.market==t.market)&(all_events.side==t.side)&(all_events.year==t.year)&(~all_events.cot_qualified)]
                    arr=pool[control_metrics].to_numpy()
                else:
                    # COT known at preceding session close, same market/year/direction, fixed observed risk in ATR.
                    sig=signals[t.market]; eligible=np.where((np.r_[0,sig[:-1]]==t.side)&(p.date.dt.year.to_numpy()==t.year))[0]
                    rows=[]; risk=t.side*(t.fill-t.stop)/t.atr
                    for e in eligible:
                        if e<15 or e+42>len(p) or not np.isfinite(p.atr.iloc[e]) or p.atr.iloc[e]<=0: continue
                        window=p.iloc[e-15:e+42]
                        if window[['open','high','low','close']].isna().any().any() or window.date.diff().dt.days.gt(7).any(): continue
                        fill=p.open.iloc[e]; stop=fill-t.side*risk*p.atr.iloc[e]
                        v=excursions(p,e,fill,stop,t.side,True)[HORIZONS.index(h)]
                        row=dict(zip(['horizon']+METRICS,v)); rows.append([row[m] for m in control_metrics])
                    arr=np.asarray(rows)
                if len(arr): pools.append(arr); matched.append([getattr(t,m) for m in control_metrics])
            if not pools: continue
            actual=np.asarray(matched); draws=np.stack([a[rng.integers(0,len(a),B)] for a in pools],axis=1)
            for stat in ['mean','median']:
                sim=getattr(np,stat)(draws,axis=1); obsstat=getattr(np,stat)(actual,axis=0)
                for j,m in enumerate(control_metrics):
                    greater=(np.sum(sim[:,j]>=obsstat[j])+1)/(B+1); less=(np.sum(sim[:,j]<=obsstat[j])+1)/(B+1)
                    controls.append(dict(control=kind,horizon=h,metric=m,stat=stat,n_matched=len(pools),n_unmatched=len(obs)-len(pools),observed=obsstat[j],random_median=np.median(sim[:,j]),random_p025=np.quantile(sim[:,j],.025),random_p975=np.quantile(sim[:,j],.975),p_two_sided=min(1,2*min(greater,less))))
            print('CONTROL DONE',h,kind,len(pools),flush=True)
    ctrl=pd.DataFrame(controls)
    if len(ctrl):
        ix=np.argsort(ctrl.p_two_sided.to_numpy()); adj=np.maximum.accumulate(ctrl.p_two_sided.to_numpy()[ix]*(len(ctrl)-np.arange(len(ctrl)))); ctrl['p_holm']=np.nan; ctrl.loc[ctrl.index[ix],'p_holm']=np.minimum(1,adj)
    ctrl.to_csv(OUT/'randomized_controls.csv',index=False)
    # Calendar blocks preserve cross-market clustering and overlapping trade dependence approximately.
    boot=[]; rg=np.random.default_rng(20261116)
    for h,g in primary.groupby('horizon'):
        blocks=((pd.to_datetime(g.entry_date)-pd.Timestamp('2000-01-01')).dt.days//90)
        for m in ['return_unstopped','return_stopped','prestop_mfe_low']:
            z=g.assign(block=blocks).groupby('block')[m].agg(['sum','count']); ind=rg.integers(0,len(z),(10000,len(z)))
            vals=z['sum'].to_numpy()[ind].sum(1)/z['count'].to_numpy()[ind].sum(1)
            boot.append(dict(horizon=h,metric=m,blocks=len(z),mean=g[m].mean(),low=np.quantile(vals,.025),high=np.quantile(vals,.975)))
    pd.DataFrame(boot).to_csv(OUT/'calendar_block_bootstrap.csv',index=False)
    run=os.environ.get('GITHUB_RUN_ID','local'); sha=os.environ.get('GITHUB_SHA','local')
    lines=['# Approximate COT + WR4 / inside-day backtest',f'Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/{run}',f'Script commit: {sha}',
    'User authorized using available data despite audit limitations on 2026-11-15.',
    'Development only: prices/outcomes end 2021-08-06; final five years remain sealed. All reported trades have full 42-session outcomes.',
    'Approximations: nominal ticks on ratio-adjusted prices; estimated Friday/holiday publication dates, strict prior-date setup join; no shutdown backlog correction; unknown roll trades and revision vintages; missing sessions screened only by >7-day gaps. No costs/slippage beyond opening gaps.',
    'ATR is simple mean of 14 pre-entry true ranges. Entry is session 1. COT evaluated at completed inside day; WR4 ties qualify, strict inside day, breakout only Day 3/4. Every setup is counted, including overlaps.',
    'Primary universe excludes MES/MNQ duplicates; literal 48-market output is separate. Independent validation of economic contract mappings remains incomplete.',
    'Unstopped MFE follows breakout; entry-bar MAE has lower/upper bounds. Stop-constrained MFE has conservative/optimistic daily-order bounds. Stops touched on intraday entry bars are conservatively charged and separately flagged as ambiguous. Stop-bar MFE is never assumed achievable in the conservative column.',
    'Controls: 10,000 draws, same market/year/direction; conditional random opens match each observed initial stop distance in ATR. Pattern control uses non-COT WR4 events. No volatility matching; control p-values assume independent matched resampling, so serial dependence can make them optimistic. 90-calendar-day clustered bootstrap shown separately. Holm correction spans all reported control tests. Exploratory, not a proof of edge.',
    f'Unique primary trades: {primary.id.nunique()}; pilot: {pilot.id.nunique()}; literal 48: {observed.id.nunique()}.',
    '\n## Pooled means (ATR except rates)',primary.groupby('horizon')[METRICS].mean().to_markdown(),
    '\n## Pooled medians',primary.groupby('horizon')[METRICS].median().to_markdown(),
    '\n## Randomized controls (mean)',ctrl[ctrl.stat=='mean'].to_markdown(index=False),
    '\n## Clustered uncertainty',pd.DataFrame(boot).to_markdown(index=False)]
    (OUT/'REPORT.md').write_text('\n\n'.join(lines))
    provenance={'run':run,'script_commit':sha,'seed':20261115,'draws':B,'end':str(END.date()),'cot_sha256':hashlib.sha256(Path('research/wr4_inside/cot_weekly_full.csv.gz').read_bytes()).hexdigest(),'price_sha256':hashlib.sha256(Path('futures_prices.parquet').read_bytes()).hexdigest()}
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print('\n'.join(lines[:11]),flush=True)
    print(primary.groupby('horizon')[METRICS].mean().to_string(),flush=True)

if __name__=='__main__':
    import sys
    selftest() if '--selftest' in sys.argv else main()
