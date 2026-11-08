"""Read stored futures bars and export reversal events and ATR outcomes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config

from cot_futures_price_panel import BUCKET, PREFIX, read_file
import os

HORIZONS = (10, 21, 63)


def simulate(o, h, l, c, entry, end, fill, stop, side, at_open, hit_on_entry):
    """Return signed exit and excursions in price points, plus stop status."""
    best = worst = 0.0
    for i in range(entry, end):
        adverse_extreme = l[i] if side == 1 else h[i]
        hit = side * (adverse_extreme - stop) <= 0
        if i == entry:
            hit &= hit_on_entry
        if hit:
            gap = i > entry and side * (o[i] - stop) < 0
            exit_price = o[i] if gap else stop
            if i > entry:
                best = max(best, side * (o[i] - fill))
                worst = max(worst, -side * (o[i] - fill))
            pnl = side * (exit_price - fill)
            return pnl, max(worst, -pnl), max(best, pnl), i, gap
        if i == entry and not at_open:
            low = high = c[i]
        else:
            low, high = l[i], h[i]
        best = max(best, side * ((high if side == 1 else low) - fill))
        worst = max(worst, -side * ((low if side == 1 else high) - fill))
    return side * (c[end - 1] - fill), worst, best, None, False


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
    average_200 = close.rolling(200).mean()
    valid_200 = ~pd.Series(gaps).rolling(199).max().fillna(1).astype(bool)
    above_200 = (close > average_200).where(valid_200 & average_200.notna()).shift(1).to_numpy()
    below_200 = (close < average_200).where(valid_200 & average_200.notna()).shift(1).to_numpy()
    avg = close.rolling(100).mean()
    up = ((close > avg) & (avg > avg.shift(20))).shift(1, fill_value=False).to_numpy()
    down = ((close < avg) & (avg < avg.shift(20))).shift(1, fill_value=False).to_numpy()
    move = (close.diff(5).shift(1) / atr).to_numpy()
    triggers = {}
    ranges = h - l
    for setup in range(3, len(bars) - 1):
        if bad[setup - 3:setup + 1].any() or gaps[setup - 2:setup + 1].any():
            continue
        if not np.isfinite(atr[setup]) or atr[setup] <= 0:
            continue
        if ranges[setup] <= ranges[setup - 3:setup].max():
            continue
        for side, level, stop in ((1, h[setup], l[setup]), (-1, l[setup], h[setup])):
            for trigger in range(setup + 1, min(setup + 3, len(bars))):
                if bad[trigger] or gaps[trigger]:
                    break
                crossed = h[trigger] > level if side == 1 else l[trigger] < level
                if crossed:
                    triggers[trigger, side] = setup, level, stop
                    break
    rows = []
    for (entry, side), (setup, level, stop) in sorted(triggers.items()):
        if not np.isfinite(atr[entry]) or atr[entry] <= 0:
            continue
        at_open = side * (o[entry] - level) > 0
        fill = o[entry] if at_open else level
        extreme = l[entry] if side == 1 else h[entry]
        touches = side * (extreme - stop) <= 0
        definite = touches and (at_open or side * (c[entry] - stop) <= 0)
        ambiguous = touches and not definite
        for n in HORIZONS:
            end = entry + n
            if end > len(c) or bad[entry:end].any() or gaps[entry + 1:end].any():
                continue
            record = {
                "root": bars.symbol.iat[0], "direction": "long" if side == 1 else "short",
                "setup": dates[setup], "session": dates[entry], "lag": entry - setup,
                "horizon": n, "gap_entry": at_open, "ambiguous": ambiguous,
                "date_offset": bars.date_offset.iat[entry],
                "initial_risk_atr": side * (fill - stop) / atr[entry],
                "unstopped_atr": side * (c[end - 1] - fill) / atr[entry],
                "move5": move[setup], "range_atr": ranges[setup] / atr[setup],
                "trend_up": up[setup], "trend_down": down[setup],
                "above_200": above_200[entry], "below_200": below_200[entry],
            }
            for scenario, hit in (("stop_after_entry", definite or ambiguous), ("stop_before_entry", definite)):
                pnl, mae, mfe, hit_i, gap = simulate(o, h, l, c, entry, end, fill, stop, side, at_open, hit)
                record.update({
                    f"return_{scenario}": pnl / atr[entry],
                    f"mae_{scenario}": mae / atr[entry],
                    f"mfe_{scenario}": mfe / atr[entry],
                    f"hit_{scenario}": hit_i is not None,
                    f"gap_{scenario}": gap,
                    f"exit_{scenario}": dates[end - 1 if hit_i is None else hit_i],
                })
            rows.append(record)
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
    assert not output.duplicated(["root", "session", "direction", "horizon"]).any()
    for scenario in ("stop_after_entry", "stop_before_entry"):
        assert (output[f"return_{scenario}"] <= output[f"mfe_{scenario}"] + 1e-9).all()
        assert (output[f"return_{scenario}"] >= -output[f"mae_{scenario}"] - 1e-9).all()
    output.to_parquet("cot-wide-range-stop-events.parquet", index=False)
    print(f"{len(keys):,} stored date files, {len(output):,} outcome rows, {output.root.nunique()} markets")


if __name__ == "__main__":
    main()
