"""Maximum number of open positions, with larger size each (Michael, 18 Nov 2026; open item from Entry 162, Entry 164).

Usage: python er_stocks_max_positions.py stock_prices.parquet OUT_DIR spy_prices.parquet signal_rows.csv.gz
(signal_rows.csv.gz, from the signal study, supplies the volume-surge value of each signal used to rank when the account is full.)
Same rule, ranking (volume surge when the account is full), account ($300,000 fixed), stops, costs and gross-exposure caps (200% and 100%) as the baseline of Entries 160-163.
New: a limit on how many trades can be open at once. When the limit is reached a new signal is skipped, whatever its rank (so the best-ranked signals of a day are taken first).
For each limit (10, 15, 20, 30 and none) two versions:
  same size       : each position keeps the baseline size (0.1% of the account per ATR), so the limit only removes trades;
  larger size     : each position is scaled by (baseline average number of open positions / the limit), so the average exposure stays about the same as the baseline (size scale shown in the output).
In-sample only (data through 2021-08-06). Post hoc. No random-pick control here (the luck spread of about +/-0.07 Sharpe from Entry 162 applies).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks_ideas_1_2_6 as I1
import er_stocks_many_ideas as MI
from er_stocks import END

LIMITS = [10, 15, 20, 30, None]


def main():
    prices_path, out_dir, spy_path, rows_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = MI.setup(prices_path, spy_path)
    SEG, dropped, cal, (_, _, WIN) = ctx
    MI.check_baseline(ctx, mk200)
    R = MI.gen(ctx, mk200); n = len(R["d"])
    WIN2 = dict(WIN); WIN2["2006 to Aug 2021 (ridge test years)"] = (pd.Timestamp("2006-01-01"), END)
    whole = [k for k in WIN2 if k.startswith("whole")][0]
    tie = np.random.default_rng(20261118).random(n) * 1e-9
    D = pd.read_csv(rows_path, usecols=["res", "entry_date", "volume_surge_signal_20d"])
    assert len(D) == n, (len(D), n)
    assert np.allclose(D["res"].to_numpy(), R["res"], atol=1e-6), "signal table does not line up with a fresh run"
    assert (pd.to_datetime(D["entry_date"]).to_numpy() == dates[R["sess_e"]].to_numpy()).all(), "signal table entry dates differ"
    surge = D["volume_surge_signal_20d"].to_numpy(float)
    key = -np.where(np.isfinite(surge), surge, -1e9) + tie
    rows = []

    def run(label, cap, max_pos, size_scale):
        P = MI.portfolio_gen(R, cal, cap, key, max_pos=max_pos, size_scale=size_scale)
        out = I1.eval_P(R, P, cap, dates, spy_close, WIN2, dict(label))
        for r in out:
            r["max positions"] = max_pos if max_pos else 0; r["size scale"] = size_scale; rows.append(r)
        return [r for r in out if r["period"] == whole][0]

    for cap in (2.0, 1.0):
        print(f"\n===== gross exposure cap {int(cap * 100)}% =====", flush=True)
        b = run({"group": "baseline", "version": "no limit, baseline size"}, cap, None, 1.0)
        avg = b["average open positions"]
        print(f"baseline: +{b['profit per year %']:.1f}% a year / Sharpe {b['Sharpe ratio']:.2f} / drawdown {b['max drawdown %']:.1f}% / worst year {b['worst year %']:.1f}% / trades {b['trades taken']} / average open {avg:.1f} / most open {b.get('most open positions', '')}", flush=True)
        for lim in LIMITS:
            for mode in ("same size", "larger size"):
                if lim is None and mode == "same size":
                    continue
                scale = 1.0 if mode == "same size" else round(float(avg) / lim if lim else 1.0, 2)
                if lim is None:
                    continue
                r = run({"group": "limit", "version": f"max {lim} positions, {mode}"}, cap, lim, scale)
                print(f"max {lim:>2} positions, {mode:<11} (size x{scale:.2f}): +{r['profit per year %']:.1f}% / Sharpe {r['Sharpe ratio']:.2f} / drawdown {r['max drawdown %']:.1f}% / worst year {r['worst year %']:.1f}% / trades {r['trades taken']} / average open {r['average open positions']:.1f} / % sessions at cap {r.get('% of sessions at the cap', float('nan')):.0f}", flush=True)
        pd.DataFrame(rows).round(4).to_csv(out_dir / "max_positions_variants.csv", index=False)
    # window detail for every version
    print("\n=== by window (cap 200% / cap 100%): Sharpe ===", flush=True)
    D = pd.DataFrame(rows)
    for (g, v), grp in D.groupby(["group", "version"], sort=False):
        line = []
        for cap in (200, 100):
            gg = grp[grp["cap %"] == cap]
            line.append(" ".join(f"{str(r['period'])[:16]}={r['Sharpe ratio']:.2f}" for _, r in gg.iterrows()))
        print(f"{v}: 200%: {line[0]} | 100%: {line[1]}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
