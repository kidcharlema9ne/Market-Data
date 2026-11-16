"""Next-session-only reversal breakouts. No stops, targets, or delayed entries."""
import numpy as np
import pandas as pd

HORIZONS = (1, 2, 3, 4, 5, 10)

def entries_and_outcomes(bars, apply_cot=True):
    """One row per exchange session, including missing sessions as NaN.

    Required: open/high/low/close, tick (in THIS price series' units),
    cot_index (public at setup close), optional cot_report/release_at.
    Caller verifies scale, contract continuity, publication timestamps and calendar.
    MAE is positive. Intraday entry-day MAE is an interval, not a point estimate.
    """
    p = bars.copy()
    previous = p.close.shift()
    tr = pd.concat([p.high-p.low, (p.high-previous).abs(),
                    (p.low-previous).abs()], axis=1).max(axis=1, skipna=False)
    atr = tr.rolling(14, min_periods=14).mean().shift()
    valid = np.isfinite(p[['open','high','low','close']]).all(axis=1)
    valid &= p.high.ge(p[['open','close']].max(axis=1))
    valid &= p.low.le(p[['open','close']].min(axis=1))
    rows, setups = [], []
    for t in range(1, len(p)-1):
        e = t+1
        if not valid.iloc[t-1:t+1].all():
            continue
        for side in (1, -1):
            pattern = (p.high.iloc[t] > p.high.iloc[t-1] and p.close.iloc[t] < p.close.iloc[t-1]) if side == 1 else (p.low.iloc[t] < p.low.iloc[t-1] and p.close.iloc[t] > p.close.iloc[t-1])
            ci = p.cot_index.iloc[t]
            cot_ok = np.isfinite(ci) and (ci >= 80 if side == 1 else ci <= 20)
            if not pattern or (apply_cot and not cot_ok):
                continue
            tick = p.tick.iloc[t]
            audit = dict(setup=p.index[t], entry=p.index[e], side=side,
                         cot_index=ci, status='expired')
            if not valid.iloc[e] or not np.isfinite(atr.iloc[e]) or atr.iloc[e] <= 0 or not np.isfinite(tick) or tick <= 0:
                audit['status'] = 'unusable_data'
                setups.append(audit)
                continue
            trigger = p.high.iloc[t]+tick if side == 1 else p.low.iloc[t]-tick
            touched = p.high.iloc[e] >= trigger if side == 1 else p.low.iloc[e] <= trigger
            if not touched:
                setups.append(audit)
                continue
            audit['status'] = 'entered'
            setups.append(audit)
            at_open = side*(p.open.iloc[e]-trigger) >= 0
            fill = p.open.iloc[e] if at_open else trigger
            a = atr.iloc[e]
            for h in HORIZONS:
                end = e+h-1
                if end >= len(p) or not valid.iloc[e:end+1].all():
                    continue
                w = p.iloc[e:end+1]
                favorable = w.high.max()-fill if side == 1 else fill-w.low.min()
                adverse = fill-w.low.min() if side == 1 else w.high.max()-fill
                known = max(0., -side*(p.close.iloc[e]-fill))
                if h > 1:
                    later = p.iloc[e+1:end+1]
                    known = max(known, fill-later.low.min() if side == 1 else later.high.max()-fill)
                upper = max(0., adverse)/a
                rows.append(dict(setup=p.index[t], entry=p.index[e], end=p.index[end],
                    side=side, horizon=h, trigger=trigger, fill=fill, gap_fill=at_open,
                    atr=a, tick=tick, cot_index=ci, cot_qualified=cot_ok,
                    return_atr=side*(p.close.iloc[end]-fill)/a,
                    mfe_atr=max(0.,favorable)/a,
                    mae_lower_atr=upper if at_open else known/a, mae_upper_atr=upper,
                    cot_report=p.cot_report.iloc[t] if 'cot_report' in p else None,
                    release_at=p.release_at.iloc[t] if 'release_at' in p else None))
    columns = ['setup','entry','end','side','horizon','trigger','fill','gap_fill','atr','tick','cot_index','cot_qualified','return_atr','mfe_atr','mae_lower_atr','mae_upper_atr','cot_report','release_at']
    return pd.DataFrame(rows, columns=columns), pd.DataFrame(setups, columns=['setup','entry','side','cot_index','status'])

def summarize(events):
    output = []
    if events.empty:
        return pd.DataFrame()
    for label, group in [('long', events[events.side.eq(1)]), ('short', events[events.side.eq(-1)]), ('combined',events)]:
        for h, g in group.groupby('horizon'):
            row = dict(direction=label, horizon=h, n=len(g))
            for metric in ['return_atr','mfe_atr','mae_lower_atr','mae_upper_atr']:
                row[metric+'_mean'] = g[metric].mean()
                row[metric+'_median'] = g[metric].median()
            output.append(row)
    return pd.DataFrame(output)
