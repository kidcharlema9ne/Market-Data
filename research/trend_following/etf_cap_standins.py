"""MYM swap, ETF stand-ins for contracts that are bigger than a chosen per-market volatility budget, and the cash they need.

Usage:
  python etf_cap_standins.py --tickers                      (prints the ETF tickers to fetch, space separated)
  python etf_cap_standins.py micro_first_list.csv etf_recent.parquet OUT_DIR [ACCOUNT]

What it does, in plain words
1. Replaces the Dow mini (YM) with the Dow micro (MYM). MYM is not in the MarketParquet archive. It tracks the same index as YM
   (the Dow Jones Industrial Average) and CME lists its multiplier as $0.50 per index point against $5 for YM, so one MYM is exactly one
   tenth of one YM. Its one-contract 20-day average true range is therefore the YM figure divided by ten. Its daily volume is NOT known
   from the archive and has to be checked at the broker.
2. For every contract in the list, measures one or more US-listed ETFs over the last 20 sessions (20-day average true range per share,
   regular session) and works out how many dollars of the ETF give a position whose 20-day average true range equals a chosen share of the account.
3. For a ladder of per-market volatility budgets (0.05 percent up to 1.00 percent of the account), lists which contracts are bigger than the budget
   (one contract already carries more volatility than the budget allows), whether a US-listed ETF exists for each, and the total cash the ETF
   stand-ins would tie up. Contracts that are at or below the budget are traded as futures in whole contracts and are not counted as cash here.
"""
import sys
import numpy as np
import pandas as pd

# Preferred ETF first. These pairings are PROVISIONAL (Claude's judgement); a ticker that is not in the archive is reported as missing.
ETF_CANDIDATES = {
    "ZT": ["SHY"], "ZF": ["IEI"], "ZN": ["IEF"], "TN": ["IEF"], "US": ["TLT"], "UB": ["EDV", "TLT"],
    "FGBL": ["BWX"], "FGBM": ["BWX"], "FGBX": ["BWX"], "FOAT": ["BWX"], "FBTP": ["BWX"], "G": ["BWX"],
    "MES": ["SPY", "VOO"], "MNQ": ["QQQ", "QQQM"], "M2K": ["IWM"], "MYM": ["DIA"],
    "FCE": ["EWQ"], "FESX": ["FEZ"], "FTUK": ["EWU"], "FTI": ["EWN"], "FXXP": ["VGK"],
    "MFS": ["EFA", "IEFA"], "MME": ["EEM", "IEMG"], "NIY": ["EWJ", "DXJ"],
    "E6": ["FXE"], "E1": ["FXF"], "B6": ["FXB"], "A6": ["FXA"], "AD": ["FXC"], "J1": ["FXY"], "DX": ["UUP"],
    "VX": ["VIXY", "VXX"],
    "NG": ["UNG"], "RB": ["UGA"], "B": ["BNO"], "MCL": ["USO"],
    "ZC": ["CORN"], "ZS": ["SOYB"], "ZW": ["WEAT"], "SB": ["CANE"], "CT": ["BAL"], "KC": ["JO"], "CC": ["NIB"],
    "HG": ["CPER"], "MGC": ["GLD", "IAU"], "SIL": ["SLV", "SIVR"], "PL": ["PPLT"],
}
BUDGETS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]  # percent of the account, 20-day average true range of one position
CAP = 0.25  # the cap Michael named: contracts above this one-contract percent volatility get an ETF stand-in

if len(sys.argv) == 2 and sys.argv[1] == "--tickers":
    print(" ".join(sorted({t for v in ETF_CANDIDATES.values() for t in v})))
    sys.exit(0)

list_path, etf_path, out_dir = sys.argv[1:4]
account = float(sys.argv[4]) if len(sys.argv) > 4 else 300_000.0

lst = pd.read_csv(list_path)
# ---- 1. MYM replaces YM
ym = lst[lst["price_symbol"] == "YM"].iloc[0]
mym = ym.copy()
mym["price_symbol"], mym["name"], mym["contract_desc"] = "MYM", "Dow micro", "$0.50 x Dow (micro)"
mym["contract_value_usd"] = ym["contract_value_usd"] / 10
mym["atr20_usd_per_contract"] = ym["atr20_usd_per_contract"] / 10
mym["percent_volatility"] = ym["percent_volatility"] / 10
mym["avg_volume_60d"] = np.nan  # not in the archive; MYM volume must be checked at the broker
mym["in_original_48"] = "no"
v3 = pd.concat([lst[lst["price_symbol"] != "YM"], pd.DataFrame([mym])], ignore_index=True)
v3["note"] = np.where(v3["price_symbol"] == "MYM", "derived from YM: same index, CME multiplier $0.50 vs $5; volume not in archive", "")
v3.to_csv(f"{out_dir}/micro_first_list_v3.csv", index=False)
print(f"List now has {len(v3)} contracts; sum of percent volatility, one contract each: {v3['percent_volatility'].sum():.3f} "
      f"(was {lst['percent_volatility'].sum():.3f} with YM)")
print(f"MYM one contract: 20-day ATR ${mym['atr20_usd_per_contract']:.1f}, percent volatility {mym['percent_volatility']:.3f}")

# ---- 2. ETF measurements
etf = pd.read_parquet(etf_path) if etf_path.endswith(".parquet") else pd.read_csv(etf_path)
etf["file_date"] = pd.to_datetime(etf["file_date"])
found = sorted(etf["symbol"].unique())
print("ETF tickers found in the archive:", " ".join(found))
etf_stats = {}
for t in found:
    g = etf[etf["symbol"] == t]
    g = g[g["feed"] == "etf_daily"] if (g["feed"] == "etf_daily").any() else g
    g = g.drop_duplicates("file_date", keep="first").sort_values("file_date")
    if len(g) < 21:
        continue
    g = g.tail(60).reset_index(drop=True)
    h, l, c = g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    atr = float(tr[-20:].mean())
    etf_stats[t] = dict(last_date=g["file_date"].iloc[-1].date(), last_close=float(c[-1]), atr20_per_share=atr,
                        etf_atr_percent_of_price=100 * atr / float(c[-1]),
                        dollar_volume_20d=float((g["close"] * g["volume"]).tail(20).mean()))

rows = []
for _, r in v3.iterrows():
    sym = r["price_symbol"]
    fut_atr_pct_price = 100 * r["atr20_usd_per_contract"] / r["contract_value_usd"]
    for t in ETF_CANDIDATES.get(sym, []):
        s = etf_stats.get(t)
        base = {"futures": sym, "futures_name": r["name"], "futures_percent_volatility": r["percent_volatility"],
                "futures_atr_percent_of_price": fut_atr_pct_price, "etf": t}
        if s is None:
            rows.append({**base, "note": "not in the archive (or fewer than 21 sessions)"})
            continue
        dollars_per_pct = (account / 100) / s["atr20_per_share"] * s["last_close"]  # ETF dollars for a position of 1 percent volatility
        rows.append({**base, **s, "etf_over_futures_atr_percent": s["etf_atr_percent_of_price"] / fut_atr_pct_price,
                     "dollars_for_0.1pct": dollars_per_pct * 0.1, "dollars_for_1pct": dollars_per_pct, "note": ""})
tab = pd.DataFrame(rows)
tab.to_csv(f"{out_dir}/etf_standins_all.csv", index=False)

pd.set_option("display.width", 250, "display.max_rows", 500, "display.max_columns", 30)
over = tab[tab["futures_percent_volatility"] > CAP]
print(f"\n=== contracts above the {CAP} percent cap and their ETF measurements (dollars for a 0.10 percent volatility position) ===")
cols = ["futures", "futures_percent_volatility", "etf", "last_date", "etf_atr_percent_of_price", "futures_atr_percent_of_price",
        "etf_over_futures_atr_percent", "dollars_for_0.1pct", "dollar_volume_20d", "note"]
print(over[cols].round(3).to_string(index=False))
no_etf = v3[(v3["percent_volatility"] > CAP) & (~v3["price_symbol"].isin(ETF_CANDIDATES.keys()))]
print("\nAbove the cap with NO ETF candidate at all:", ", ".join(f"{a} ({b:.2f})" for a, b in zip(no_etf["price_symbol"], no_etf["percent_volatility"])))
missing = over[over["note"] != ""]
print("Above the cap, candidate ETF missing from the archive:", ", ".join(f"{a}->{b}" for a, b in zip(missing["futures"], missing["etf"])))

# ---- 3. budget ladder
first_ok = tab[tab["note"] == ""].drop_duplicates("futures", keep="first").set_index("futures")  # preferred ETF that was measured
ladder = []
for v in BUDGETS:
    big = v3[v3["percent_volatility"] > v]
    with_etf = big[big["price_symbol"].isin(first_ok.index)]
    cash = sum(first_ok.loc[s, "dollars_for_1pct"] * v for s in with_etf["price_symbol"])
    without = big[~big["price_symbol"].isin(first_ok.index)]
    small = v3[v3["percent_volatility"] <= v]
    contracts = (v / small["percent_volatility"]).round().clip(lower=1)
    ladder.append({"budget_percent_vol_per_market": v, "contracts_above_budget": len(big), "of_which_with_measured_etf": len(with_etf),
                   "etf_cash_dollars": round(cash), "etf_cash_percent_of_account": round(100 * cash / account, 1),
                   "above_budget_no_etf": ", ".join(f"{s}({p / v:.1f}x)" for s, p in zip(without["price_symbol"], without["percent_volatility"])),
                   "futures_only_markets": len(small), "futures_contracts_total": int(contracts.sum())})
lad = pd.DataFrame(ladder)
lad.to_csv(f"{out_dir}/etf_cash_by_budget.csv", index=False)
print("\n=== per-market volatility budget ladder (budget = 20-day ATR of one position as percent of the account) ===")
print("ETF cash is the full dollar value of the ETF shares (an ETF has no margin leverage here); futures-only markets are traded in whole contracts,")
print("contracts column = sum over those markets of round(budget / one-contract percent volatility), minimum 1.")
print(lad.to_string(index=False))
