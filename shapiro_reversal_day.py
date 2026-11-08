from concurrent.futures import ThreadPoolExecutor
from datetime import date
import os

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

import cot_futures_price_panel as panel

panel.ROOTS.update({"OJ", "LBS", "PA", "BTC", "ETH", "MET", "ZO"})
HORIZON = 21

def market_rows(bars):
    bars = bars.sort_values("session").reset_index(drop=True)
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    dates = bars.session.to_numpy()
    offset = bars.date_offset.to_numpy()
    bad = ~np.isfinite([o, h, l, c]).all(axis=0) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))
    bad |= bars.session.duplicated(keep=False).to_numpy() | ~bars.date_offset.between(0, 3).to_numpy()
    gap = bars.session.diff().dt.days.fillna(0).gt(7).to_numpy()
    prev = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h-l, np.maximum(abs(h-prev), abs(l-prev)))
    tr[bad | np.r_[True, bad[:-1]] | gap] = np.nan
    close = pd.Series(c).mask(bad)
    atr = pd.Series(tr).rolling(20).mean().shift(1).to_numpy()
    avg = close.rolling(100).mean()
    trend = np.select([(close > avg) & (avg > avg.shift(20)), (close < avg) & (avg < avg.shift(20))], [1,-1], default=0)
    move = (close.diff(5).shift(1)/atr).to_numpy()
    rows = []
    for t in range(1,len(c)-HORIZON):
        e = t+1
        end = e+HORIZON
        if bad[t-1:end].any() or gap[t:end].any() or not np.isfinite(atr[e]) or atr[e]<=0:
            continue
        high,low=h[t]>h[t-1],l[t]<l[t-1]
        side = 1 if low and c[t]>c[t-1] else -1 if high and c[t]<c[t-1] else 0
        if not side:
            continue
        stop = l[t] if side==1 else h[t]
        fill = o[e]
        a = atr[e]
        risk = side*(fill-stop)/a
        kind = "outside" if high and low else "one-sided"
        row = dict(root=bars.symbol.iat[0],signal=dates[t],entry=dates[e],exit=dates[end-1],
                   signal_offset=offset[t],entry_offset=offset[e],side=side,pattern=kind,atr=a,
                   initial_risk=risk,trend=int(trend[t-1]),move5=move[t],hit=False,skip=risk<=0)
        if risk<=0:
            rows.append(row)
            continue
        best=worst=0.0
        for i in range(e,end):
            op=side*(o[i]-fill)/a
            best=max(best,op)
            adverse=l[i] if side==1 else h[i]
            favorable=h[i] if side==1 else l[i]
            if side*(adverse-stop)<=0:
                at_open=side*(o[i]-stop)<=0
                pnl=op if at_open else -risk
                row.update(hit=True,stop_date=dates[i],ret=pnl,mfe=best,mae=max(worst,-pnl),
                           mfe_upper=best if at_open else max(best,side*(favorable-fill)/a))
                break
            best=max(best,side*(favorable-fill)/a)
            worst=max(worst,-side*(adverse-fill)/a)
        else:
            row.update(ret=side*(c[end-1]-fill)/a,mfe=best,mae=worst,mfe_upper=best)
        rows.append(row)
    return rows

def main():
    storage=boto3.client("s3",endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],region_name="auto",
        config=Config(max_pool_connections=32,retries={"max_attempts":8,"mode":"standard"}))
    pages=storage.get_paginator("list_objects_v2").paginate(Bucket=panel.BUCKET,Prefix=panel.PREFIX)
    keys=sorted(x["Key"] for page in pages for x in page.get("Contents",[]) if x["Key"].endswith(".parquet")
         and date.fromisoformat(x["Key"][len(panel.PREFIX):-8])<=date(2026,11,6))
    with ThreadPoolExecutor(max_workers=24) as pool:
        prices=pd.concat(pool.map(lambda key:panel.read_file(storage,key),keys),ignore_index=True)
    d=pd.DataFrame([row for _,bars in prices.groupby("symbol") for row in market_rows(bars)])
    assert not d.duplicated(["root","signal"]).any()
    traded=d[~d.skip]
    assert (traded.mfe_upper>=traded.mfe).all()
    assert (traded.ret<=traded.mfe+1e-9).all() and (traded.ret>=-traded.mae-1e-9).all()
    d.to_parquet("shapiro-reversal-day-events.parquet",index=False)
    print(len(keys),len(d),d.root.nunique())

if __name__=="__main__":
    main()
