"""Read the six-market DEVELOPMENT slice in Actions using existing secrets.

Raw prices stay temporary on the runner. Only audit metadata is uploaded.
"""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import boto3
from botocore.config import Config
import pandas as pd
from run_pilot import PILOT

def main():
    s=boto3.client('s3',endpoint_url=os.environ['R2_ENDPOINT_URL'],aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'],region_name='auto',config=Config(max_pool_connections=16,retries={'max_attempts':6,'mode':'standard'}))
    bucket='insider-research';prefix='marketparquet/futures_daily/'
    pages=s.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix)
    keys=sorted(x['Key'] for page in pages for x in page.get('Contents',[]) if x['Key'].endswith('.parquet') and '2007-12-31'<=x['Key'][len(prefix):-8]<='2021-08-06')
    def read(key):
        obj=s.get_object(Bucket=bucket,Key=key)
        with obj['Body'] as body:b=body.read()
        sha=hashlib.sha256(b).hexdigest()
        if sha!=obj['Metadata'].get('verified-sha256'):raise ValueError('R2 checksum mismatch: '+key)
        p=pd.read_parquet(BytesIO(b));p=p[p.symbol.isin(PILOT)].copy()
        field='date' if 'date' in p else 'timestamp'
        p['embedded']=pd.to_datetime(p[field]).astype(str)
        p['session']=key[len(prefix):-8]
        if 'asset_type' not in p:p['asset_type']='Futures'
        return p[['session','embedded','symbol','asset_type','open','high','low','close','volume']],dict(key=key,sha256=sha)
    with ThreadPoolExecutor(max_workers=16) as pool:result=list(pool.map(read,keys))
    if not result:raise ValueError('No R2 development files')
    pd.concat([x[0] for x in result],ignore_index=True).to_csv('/tmp/reversal_pilot_prices.csv.gz',index=False)
    out=Path(__file__).resolve().parent/'output';out.mkdir(exist_ok=True)
    (out/'r2_verified_objects.json').write_text(json.dumps([x[1] for x in result],indent=2))
    print('Verified R2 objects:',len(keys),'Development cutoff: 2021-08-06. No holdout price files read.')

if __name__=='__main__':main()
