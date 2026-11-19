"""Export the futures trend system's daily dollar profit, one column per version and bet size (Michael, 19 Nov 2026: run the stock and futures systems together).

Usage: python futures_daily_export.py futures_prices.parquet report_universe_48_markets.csv OUT_DIR

Executes the checked part of er_candidate_v2.py (engine, simulator and reference checks run first and stop the script on any difference), then writes OUT_DIR/futures_daily_pnl.csv:
one row per futures session, columns = date and the daily mark-to-market profit in dollars on a fixed $300,000 account for
  original rule (1 ATR initial stop, 5 ATR trailing stop, 130-session limit), candidate version 2 (2 ATR initial stop, 5 ATR trailing stop, no time limit),
  each at 0.15% and 0.25% of the account per ATR; whole contracts, short rates capped at 10 contracts per trade, 0.05 ATR a side.
Nothing is tuned here. The whole history is exported; the combining script cuts it to the stock in-sample window.
"""
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "trend_following" / "er_candidate_v2.py"
_T = _SRC.read_text()
_CUT = "GROUP2 = lambda m:"
__file__ = str(_SRC)
assert _T.count(_CUT) == 1, "could not split er_candidate_v2.py"
exec(compile(_T.partition(_CUT)[0], str(_SRC), "exec"), globals())

cols = {"date": ALLD}
for v in ("original rule", "candidate version 2"):
    for tp in SIZES:
        cols[f"{v} | {tp}% per ATR"] = BK[(v, tp)]["pnl"]
df = pd.DataFrame(cols)
df.to_csv(OUT / "futures_daily_pnl.csv", index=False, float_format="%.4f")
print(f"wrote {len(df)} sessions {df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()}")
for c in df.columns[1:]:
    print(f"{c}: total profit ${df[c].sum():,.0f}")
