"""Read stored futures bars and export reversal events and ATR outcomes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

from cot_futures_price_panel import BUCKET, PREFIX, read_file
import os

HORIZONS = (10, 21)


def outcomes(o, h, l, c, atr, invalid, gaps, session, entry, fill, direction, at_open):
    if not np.isfinite(atr[entry]) or atr[entry] <= 0 or invalid[entry]:
        return {}
    output = {}
    for n in HORIZONS:
        end = entry + n
        if end > len(c) or invalid[entry:end].any() or gaps[entry + 1:end].any():
            continue
        # If crossed intraday, the entry-day extrema can precede the fill.
        first = entry if at_open else entry + 1
        high = max(c[entry], h[first:end].max())
        low = min(c[entry], l[first:end].min())
        adverse = fill - low if direction == 1 else high - fill
        favorable = high - fill if direction == 1 else fill - low
        output[n] = (direction * (c[end - 1] - fill) / atr[entry],
                     max(0, adverse) / atr[entry], max(0, favorable) / atr[entry],
                     session[entry], session[end - 1])
    return output


def market_events(bars):
    bars = bars.sort_values("session").reset_index(drop=True)
    o, h, l, c = (bars[x].to_numpy() for x in ("open", "high", "low", "close"))
    dates = bars.session.to_numpy()
    bad = ~np.isfinite([o, h, l, c]).all(axis=0) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))
    bad |= bars.session.duplicated(keep=False).to_numpy() | ~bars.date_offset.between(0, 3).to_numpy()
    gaps = bars.session.diff().dt.days.fillna(0).gt(7).to_numpy()
    close = pd.Series(c).mask(bad)
    previous = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - previous), abs(l - previous)))
    tr[bad | np.r_[True, bad[:-1]] | gaps] = np.nan
    atr = pd.Series(tr).rolling(20).mean().shift(1).to_numpy()
    avg = close.rolling(100).mean()
    up = ((close > avg) & (avg > avg.shift(20))).shift(1, fill_value=False).to_numpy()
    down = ((close < avg) & (avg < avg.shift(20))).shift(1, fill_value=False).to_numpy()
    move = (close.diff(5).shift(1) / atr).to_numpy()
    # One candidate per trigger date and side. Favor an eligible wide-range
    # setup; when several qualify, select the most recent setup.
    triggers = {}
    ranges = h - l
    for setup in range(3, len(bars) - 1):
        direction = 1 if down[setup] else -1 if up[setup] else 0
        if not direction or bad[setup - 3:setup + 1].any() or gaps[setup - 2:setup + 1].any():
            continue
        if not np.isfinite(atr[setup]) or atr[setup] <= 0:
            continue
        prior_max = ranges[setup - 3:setup].max()
        if ranges[setup] == prior_max:
            continue
        wide = bool(ranges[setup] > prior_max)
        level = h[setup] if direction == 1 else l[setup]
        for trigger in range(setup + 1, min(setup + 3, len(bars))):
            if bad[trigger] or gaps[trigger]:
                break
            crossed = h[trigger] > level if direction == 1 else l[trigger] < level
            if not crossed:
                continue
            old = triggers.get((trigger, direction))
            if old is None or wide or not old[1]:
                triggers[trigger, direction] = setup, wide, level
            break
    rows = []
    for (trigger, direction), (setup, wide, level) in sorted(triggers.items()):
        fill = max(o[trigger], level) if direction == 1 else min(o[trigger], level)
        inputs = [("break", trigger, fill)]
        if trigger + 1 < len(bars) and not gaps[trigger + 1]:
            inputs.append(("next_open", trigger + 1, o[trigger + 1]))
        for mode, entry, fill in inputs:
            result = outcomes(o, h, l, c, atr, bad, gaps, dates, entry, fill, direction, mode == "next_open" or direction * (o[trigger] - level) > 0)
            for horizon, (ret, mae, mfe, entry_day, exit_day) in result.items():
                rows.append({
                    "root": bars.symbol.iat[0], "direction": "long" if direction == 1 else "short",
                    "setup": dates[setup], "session": dates[trigger], "entry": entry_day, "exit": exit_day,
                    "lag": trigger - setup, "wide": wide, "mode": mode, "horizon": horizon,
                    "gap_fill": (direction * (o[trigger] - level)) > 0,
                    "move5": move[setup], "range_atr": ranges[setup] / atr[setup],
                    "exit_atr": ret, "mae_atr": mae, "mfe_atr": mfe,
                })
    return rows


def main():
    storage = boto3.client(
        "s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
        config=Config(max_pool_connections=32, retries={"max_attempts": 8, "mode": "standard"}),
    )
    pages = storage.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=PREFIX)
    keys = sorted(o["Key"] for p in pages for o in p.get("Contents", []) if o["Key"].endswith(".parquet")
                  and date.fromisoformat(o["Key"][len(PREFIX):-8]) <= date(2026, 11, 6))
    with ThreadPoolExecutor(max_workers=24) as pool:
        prices = pd.concat(pool.map(lambda key: read_file(storage, key), keys), ignore_index=True)
    rows = [row for _, bars in prices.groupby("symbol") for row in market_events(bars)]
    output = pd.DataFrame(rows)
    assert output.root.nunique() == 48 and set(output.horizon) == set(HORIZONS)
    assert not output.duplicated(["root", "session", "direction", "mode", "horizon"]).any()
    assert (output.exit_atr <= output.mfe_atr + 1e-9).all()
    assert (output.exit_atr >= -output.mae_atr - 1e-9).all()
    output.to_parquet("cot-wide-range-events.parquet", index=False)
    print(f"{len(keys):,} stored date files, {len(output):,} outcome rows, {output.root.nunique()} markets")


if __name__ == "__main__":
    main()
