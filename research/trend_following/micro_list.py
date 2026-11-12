"""Micro-first trend-following futures list, summed percent volatility, and ETF stand-ins for the big contracts.

Usage: python micro_list.py contract_size_atr20.csv trend_universe.csv etf_recent.parquet OUT_DIR [ACCOUNT]

Percent volatility = 20-day average true range per contract, in dollars, divided by the account (default 300,000), times 100.
Selection rule, per family of the same market: keep contracts that are liquid enough (at least 5,000 contracts a day on average over
60 sessions and traded in at least 55 of them; Brazilian real is kept although thin because it is in the original 48),
then keep the smallest size (micro, then mini, then full); a tie between near-duplicates goes to the higher volume.
For any kept contract above 1 percent volatility, find an ETF and size it so that its own 20-day average true range is 0.1 percent of the account.
"""
import sys
import numpy as np
import pandas as pd

res_path, uni_path, etf_path, out_dir = sys.argv[1:5]
account = float(sys.argv[5]) if len(sys.argv) > 5 else 300_000.0
THIN_BUT_KEPT = {"BR"}
ETF_FOR = {"YM": ["DIA"], "FTI": ["EWN"], "NIY": ["EWJ", "DXJ"], "B": ["BNO"], "RB": ["UGA"], "HG": ["CPER"], "KC": ["JO"], "HO": []}

res = pd.read_csv(res_path)
uni = pd.read_csv(uni_path)[["price_symbol", "family", "size_rank", "contract_desc"]]
d = res.merge(uni, on="price_symbol", how="left")
d["percent_volatility"] = d["atr20_pct_of_account"]
d["passes_liquidity"] = (d["liquid_enough"] == "yes") | d["price_symbol"].isin(THIN_BUT_KEPT)
ok = d[d["passes_liquidity"] & (d["status"].str.startswith("ok"))].copy()
ok = ok.sort_values(["family", "size_rank", "avg_volume_60d"], ascending=[True, True, False])
keep = ok.groupby("family", sort=False).head(1).copy()
dropped = d[~d["price_symbol"].isin(keep["price_symbol"])][["price_symbol", "name", "family", "size_rank", "liquid_enough", "avg_volume_60d", "sessions_with_volume_of_60", "status"]]
order = ["us rates", "foreign bonds", "foreign short rates", "stock indexes", "foreign stock indexes", "currencies", "volatility",
         "energy", "foreign commodities", "grains", "softs", "meats", "metals"]
keep["g"] = keep["group"].map({g: i for i, g in enumerate(order)})
keep = keep.sort_values(["g", "price_symbol"]).drop(columns="g")
cols = ["price_symbol", "name", "group", "contract_desc", "last_close", "contract_value_usd", "atr20_usd_per_contract",
        "percent_volatility", "avg_volume_60d", "in_original_48"]
keep[cols].to_csv(f"{out_dir}/micro_first_list.csv", index=False)
dropped.to_csv(f"{out_dir}/micro_first_dropped.csv", index=False)

pd.set_option("display.width", 250, "display.max_rows", 300, "display.max_colwidth", 60)
print(f"KEPT {len(keep)} contracts (account {account:,.0f})")
print(keep[cols].round(3).to_string(index=False))
print("\nSUM of percent volatility, one contract each:", round(keep["percent_volatility"].sum(), 3))
print(keep.groupby("group")["percent_volatility"].agg(["count", "sum"]).round(3).to_string())
print("\nDROPPED (with reason columns)")
print(dropped.round(1).to_string(index=False))

# ---- ETF stand-ins for kept contracts above 1 percent volatility
big = keep[keep["percent_volatility"] > 1.0]
etf = pd.read_parquet(etf_path)
etf["file_date"] = pd.to_datetime(etf["file_date"])
rows = []
for _, r in big.iterrows():
    cands = ETF_FOR.get(r["price_symbol"], None)
    fut_pct = 100 * r["atr20_points"] / r["last_close"]
    if not cands:
        rows.append({"futures": r["price_symbol"], "futures_percent_volatility": r["percent_volatility"], "futures_atr_percent_of_price": fut_pct,
                     "etf": "none found", "note": "no US-listed ETF"})
        continue
    for t in cands:
        g = etf[etf["symbol"] == t].drop_duplicates("file_date", keep="first").sort_values("file_date")
        if len(g) < 21:
            rows.append({"futures": r["price_symbol"], "futures_percent_volatility": r["percent_volatility"], "futures_atr_percent_of_price": fut_pct,
                         "etf": t, "note": f"only {len(g)} sessions in the archive"})
            continue
        g = g.tail(60).reset_index(drop=True)
        h, l, c = g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
        atr = float(tr[-20:].mean())
        last = float(c[-1])
        target = 0.001 * account  # dollars of 20-day average true range that equal 0.1 percent of the account
        shares = target / atr
        rows.append({"futures": r["price_symbol"], "futures_percent_volatility": r["percent_volatility"],
                     "futures_atr_percent_of_price": fut_pct, "etf": t, "feed": g["feed"].iloc[-1],
                     "last_date": g["file_date"].iloc[-1].date(), "last_close": last, "atr20_per_share": atr,
                     "etf_atr_percent_of_price": 100 * atr / last, "shares_for_0.1pct": shares,
                     "dollars_for_0.1pct": shares * last, "avg_dollar_volume_20d": float((g["close"] * g["volume"]).tail(20).mean()),
                     "avg_shares_20d": float(g["volume"].tail(20).mean())})
et = pd.DataFrame(rows)
et.to_csv(f"{out_dir}/etf_standins_0p1pct.csv", index=False)
print("\n=== ETF stand-ins: dollars needed for a 0.1 percent volatility position ===")
print(et.round(3).to_string(index=False))
