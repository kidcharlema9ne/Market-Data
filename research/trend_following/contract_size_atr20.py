"""How big is one contract? 20-day average true range per contract, in dollars and as a percent of an account.

Usage: python contract_size_atr20.py futures_prices.parquet futures_data/trend_universe.csv OUT_DIR [ACCOUNT]

Reads only the last ~80 sessions of each symbol. No strategy test, no returns beyond the true range.
Average true range = simple average of the last 20 true ranges (true range = the largest of high-low,
|high - previous close|, |low - previous close|). The series are ratio back-adjusted, so the newest
prices are real front-contract prices; the last-close sanity range in the universe table catches unit mistakes.
"""
import sys
import numpy as np
import pandas as pd

prices_path, universe_path, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
account = float(sys.argv[4]) if len(sys.argv) > 4 else 300_000.0

px = pd.read_parquet(prices_path)
px["file_date"] = pd.to_datetime(px["file_date"])
px = px.sort_values(["symbol", "file_date"])
last_day = px["file_date"].max()
print("rows", len(px), "symbols", px["symbol"].nunique(), "last file date", last_day.date())

# ---- liquidity for every symbol (volume only; no multipliers needed)
liq = []
for sym, g in px.groupby("symbol"):
    g = g.tail(60)
    liq.append({
        "price_symbol": sym,
        "last_date": g["file_date"].iloc[-1].date(),
        "last_close": g["close"].iloc[-1],
        "avg_volume_60d": float(g["volume"].mean()),
        "sessions_with_volume_of_60": int((g["volume"] > 0).sum()),
    })
liq = pd.DataFrame(liq).sort_values("avg_volume_60d", ascending=False)

# ---- contract size for the universe
uni = pd.read_csv(universe_path)
by = {s: g.reset_index(drop=True) for s, g in px.groupby("symbol")}


def last_close(sym):
    return float(by[sym]["close"].iloc[-1])


fx = {"USD": 1.0, "EUR": last_close("E6"), "GBP": last_close("B6"), "CAD": last_close("AD"), "JPY": last_close("J1")}
print("fx to USD:", fx)

out = []
for _, u in uni.iterrows():
    sym = u["price_symbol"]
    row = {"price_symbol": sym, "name": u["name"], "group": u["group"], "in_original_48": u["in_original_48"],
           "multiplier_confidence": u["multiplier_confidence"], "currency": u["currency"]}
    if sym not in by:
        row["status"] = "NO PRICE DATA"
        out.append(row)
        continue
    g = by[sym].tail(80).reset_index(drop=True)
    h, l, c = g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = float(np.mean(tr[-20:]))
    last = float(c[-1])
    row.update(last_date=g["file_date"].iloc[-1].date(), last_close=last, atr20_points=atr,
               atr20_pct_of_price=100 * atr / last,
               avg_volume_60d=float(g["volume"].tail(60).mean()),
               sessions_with_volume_of_60=int((g["volume"].tail(60) > 0).sum()))
    ok = u["expected_low"] <= last <= u["expected_high"]
    row["status"] = "ok" if ok else f"LAST CLOSE {last:g} OUTSIDE EXPECTED {u['expected_low']:g}-{u['expected_high']:g}"
    if row["last_date"] != last_day.date():
        row["status"] += f" | STALE (last {row['last_date']})"
    mult_usd = u["multiplier"] * fx[u["currency"]]
    row["dollars_per_point_usd"] = mult_usd
    row["atr20_usd_per_contract"] = atr * mult_usd
    row["atr20_pct_of_account"] = 100 * atr * mult_usd / account
    row["contract_value_usd"] = last * mult_usd
    row["contract_value_pct_of_account"] = 100 * last * mult_usd / account
    row["avg_daily_dollar_volume_usd"] = row["avg_volume_60d"] * last * mult_usd
    # liquidity rule: at least 5,000 contracts a day on average and traded in at least 55 of the last 60 sessions
    row["liquid_enough"] = "yes" if (row["avg_volume_60d"] >= 5000 and row["sessions_with_volume_of_60"] >= 55) else "NO"
    out.append(row)

res = pd.DataFrame(out)
res.to_csv(f"{out_dir}/contract_size_atr20.csv", index=False)
liq.to_csv(f"{out_dir}/liquidity_all_symbols.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 30)
cols = ["price_symbol", "name", "last_close", "atr20_points", "atr20_usd_per_contract", "atr20_pct_of_account",
        "contract_value_pct_of_account", "avg_volume_60d", "sessions_with_volume_of_60", "liquid_enough", "status"]
print(f"\n=== one contract, account {account:,.0f}, 20-day ATR ===")
print(res[cols].round(4).to_string(index=False))
print("\n=== liquidity, all symbols (60-session average volume) ===")
print(liq.round(1).to_string(index=False))
