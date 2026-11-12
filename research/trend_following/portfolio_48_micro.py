"""Michael's 48 markets as a micro-first portfolio, every market sized to a 0.25 percent volatility budget.

Usage: python portfolio_48_micro.py contract_size_atr20.csv etf_standins_all.csv OUT_DIR [ACCOUNT] [BUDGET_PERCENT]

Reads only committed outputs (20-day average true range per contract, last session 2026-11-06; ETF stand-in 20-day true range).
No price data is read and no strategy is run. Percent volatility = 20-day ATR in dollars divided by the account, times 100.

Rules (Michael, 12 Nov 2026):
- Every market in the 48 list, micro version wherever CME lists one; natural gas uses Micro Henry Hub; New York cocoa and arabica coffee are replaced
  by London cocoa and Robusta coffee; the 48 list holds ES with MES and NQ with MNQ, so they merge into one market each (46 distinct markets).
- Size each market to the budget (0.25 percent): whole contracts = round(budget / percent volatility of one contract), never fewer than 1,
  so a market whose one contract is already above the budget is still included at one contract.
- If one contract of the micro (or the smallest contract that exists) is above 0.5 percent, use an ETF sized to the budget instead.
  The ETF size is budget dollars divided by the ETF's own 20-day average true range per share.
Micro contracts that are not in the price archive are one tenth (platinum one fifth) of the full contract on the same underlying, so their ATR is the
full-size ATR times that ratio. The ratios come from CME contract specifications and are PROVISIONAL until checked at the broker.
"""
import sys
import numpy as np
import pandas as pd

res_path, etf_path, out_dir = sys.argv[1:4]
account = float(sys.argv[4]) if len(sys.argv) > 4 else 300_000.0
budget_pct = float(sys.argv[5]) if len(sys.argv) > 5 else 0.25
ETF_LIMIT_PCT = 0.5
target_dollars = account * budget_pct / 100.0

# (name, group, Michael's code, instrument, ATR source price symbol, ratio of instrument to source, ETF stand-in or None, note)
M = [
    ("Chicago wheat", "grains", "ZW", "MZW micro wheat (500 bu)", "ZW", 0.1, None, ""),
    ("KC wheat", "grains", "KE", "KE full size (no micro exists)", "KE", 1.0, None, ""),
    ("Corn", "grains", "ZC", "MZC micro corn (500 bu)", "ZC", 0.1, None, ""),
    ("Soybeans", "grains", "ZS", "MZS micro soybeans (500 bu)", "ZS", 0.1, None, ""),
    ("Soybean oil", "grains", "ZL", "MZL micro soybean oil (6,000 lb)", "ZL", 0.1, None, ""),
    ("Soybean meal", "grains", "ZM", "MZM micro soybean meal (10 tons)", "ZM", 0.1, None, ""),
    ("Heating oil", "energy", "HO", "HO full size (no micro exists)", "HO", 1.0, None, "no US-listed heating oil ETF"),
    ("Natural gas", "energy", "NG", "Micro Henry Hub, CME code MNG (1,000 mmBtu)", "NG", 0.1, "UNG", ""),
    ("WTI crude", "energy", "CL", "MCL micro WTI (100 bbl)", "MCL", 1.0, "USO", ""),
    ("Brent last-day", "energy", "BZ", "BZ full size (no micro exists)", "BZ", 1.0, "BNO", ""),
    ("RBOB gasoline", "energy", "RB", "RB full size (no micro exists)", "RB", 1.0, "UGA", ""),
    ("Cotton", "softs", "CT", "CT full size (no micro exists)", "CT", 1.0, None, ""),
    ("Cocoa (London replaces New York)", "softs", "CC", "London cocoa C full size (no micro exists)", "C", 1.0, "COCO", "no US-listed cocoa ETF (NIB delisted); COCO is London-listed and its true range is estimated from the futures"),
    ("Sugar", "softs", "SB", "SB full size (no micro exists)", "SB", 1.0, None, ""),
    ("Coffee (Robusta replaces arabica)", "softs", "KC", "RM Robusta full size (no micro exists)", "RM", 1.0, None, ""),
    ("Lean hogs", "meats", "HE", "HE full size (no micro exists)", "HE", 1.0, None, ""),
    ("Live cattle", "meats", "LE", "LE full size (no micro exists)", "LE", 1.0, None, ""),
    ("Feeder cattle", "meats", "GF", "GF full size (no micro exists)", "GF", 1.0, None, "no US-listed cattle ETF"),
    ("Platinum", "metals", "PL", "Micro platinum (10 oz, one fifth of PL)", "PL", 0.2, "PPLT", ""),
    ("Silver", "metals", "SI", "SIL micro silver (1,000 oz)", "SIL", 1.0, "SLV", ""),
    ("Copper", "metals", "HG", "MHG micro copper (2,500 lb)", "HG", 0.1, "CPER", ""),
    ("Gold", "metals", "GC", "MGC micro gold (10 oz)", "MGC", 1.0, "GLD", ""),
    ("Australian dollar", "currencies", "A6", "M6A micro (10,000 AUD)", "A6", 0.1, "FXA", ""),
    ("British pound", "currencies", "B6", "M6B micro (6,250 GBP)", "B6", 0.1, "FXB", ""),
    ("Canadian dollar", "currencies", "AD", "MCD micro (10,000 CAD)", "AD", 0.1, "FXC", ""),
    ("Euro", "currencies", "E6", "M6E micro (12,500 EUR)", "E6", 0.1, "FXE", ""),
    ("Japanese yen", "currencies", "J1", "MJY micro (1,250,000 JPY)", "J1", 0.1, "FXY", ""),
    ("Mexican peso", "currencies", "MP", "MP full size (no micro exists)", "MP", 1.0, None, ""),
    ("Brazilian real", "currencies", "BR", "BR full size (no micro exists)", "BR", 1.0, None, "thin: traded 33 of the last 60 sessions"),
    ("New Zealand dollar", "currencies", "N6", "N6 full size (no micro exists)", "N6", 1.0, None, ""),
    ("Swiss franc", "currencies", "E1", "MSF micro (12,500 CHF)", "E1", 0.1, "FXF", ""),
    ("Dollar index", "currencies", "DX", "DX full size (no micro exists)", "DX", 1.0, "UUP", ""),
    ("VIX", "volatility", "VX", "VX full size (no micro exists)", "VX", 1.0, "VXX", ""),
    ("US 30-year bond", "us rates", "ZB", "US full size (no micro exists)", "US", 1.0, "TLT", ""),
    ("Ultra bond", "us rates", "UB", "UB full size (no micro exists)", "UB", 1.0, "EDV", ""),
    ("10-year note", "us rates", "ZN", "ZN full size (no micro exists)", "ZN", 1.0, "IEF", ""),
    ("Ultra 10-year note", "us rates", "TN", "TN full size (no micro exists)", "TN", 1.0, "IEF", ""),
    ("5-year note", "us rates", "ZF", "ZF full size (no micro exists)", "ZF", 1.0, "IEI", ""),
    ("2-year note", "us rates", "ZT", "ZT full size (no micro exists)", "ZT", 1.0, "SHY", ""),
    ("30-day fed funds", "us rates", "ZQ", "ZQ full size (no micro exists)", "ZQ", 1.0, None, ""),
    ("1-month SOFR", "us rates", "SR1", "SR1 full size (no micro exists)", "SR1", 1.0, None, ""),
    ("3-month SOFR", "us rates", "SR3", "SR3 full size (no micro exists)", "SR3", 1.0, None, ""),
    ("Dow", "stock indexes", "YM", "MYM micro Dow ($0.50 a point)", "YM", 0.1, "DIA", "MYM is not in the price archive"),
    ("S&P 500 (ES and MES merged)", "stock indexes", "ES/MES", "MES micro S&P ($5 a point)", "MES", 1.0, "SPY", ""),
    ("Nasdaq-100 (NQ and MNQ merged)", "stock indexes", "NQ/MNQ", "MNQ micro Nasdaq ($2 a point)", "MNQ", 1.0, "QQQ", ""),
    ("Russell 2000", "stock indexes", "RTY", "M2K micro Russell ($5 a point)", "M2K", 1.0, "IWM", ""),
]

res = pd.read_csv(res_path).set_index("price_symbol")
etf = pd.read_csv(etf_path)
rows = []
for name, group, code, inst, src, ratio, etf_sym, note in M:
    atr_unit = float(res.loc[src, "atr20_usd_per_contract"]) * ratio
    value_unit = float(res.loc[src, "contract_value_usd"]) * ratio
    pct_unit = 100.0 * atr_unit / account
    r = dict(market=name, group=group, michael_code=code, atr_source=src, ratio_to_source=ratio, one_unit_atr_usd=atr_unit,
             one_unit_percent_volatility=pct_unit, one_unit_value_usd=value_unit,
             avg_volume_60d_source=float(res.loc[src, "avg_volume_60d"]), note=note)
    if pct_unit <= ETF_LIMIT_PCT:
        n = max(1, int(round(target_dollars / atr_unit)))
        r.update(vehicle="futures", instrument=inst, quantity=n, unit="contracts", percent_volatility=n * pct_unit,
                 notional_usd=n * value_unit, cash_for_etf_usd=0.0, etf="")
    else:
        cand = etf[etf["etf"] == etf_sym].drop_duplicates("etf") if etf_sym else etf.iloc[0:0]
        if len(cand) and pd.notna(cand.iloc[0]["atr20_per_share"]):
            c = cand.iloc[0]
            shares = target_dollars / float(c["atr20_per_share"])
            r.update(vehicle="ETF", instrument=f"{etf_sym} ETF", quantity=shares, unit="shares", percent_volatility=budget_pct,
                     notional_usd=shares * float(c["last_close"]), cash_for_etf_usd=shares * float(c["last_close"]), etf=etf_sym,
                     etf_percent_of_price=float(c["etf_atr_percent_of_price"]))
        elif etf_sym == "COCO":
            fut_pct_price = float(res.loc[src, "atr20_pct_of_price"])
            dollars = target_dollars / (fut_pct_price / 100.0)
            r.update(vehicle="ETF (estimated)", instrument="WisdomTree Cocoa COCO (London)", quantity=np.nan, unit="dollars",
                     percent_volatility=budget_pct, notional_usd=dollars, cash_for_etf_usd=dollars, etf="COCO",
                     etf_percent_of_price=fut_pct_price)
        else:
            r.update(vehicle="none", instrument="no ETF exists; left out", quantity=0, unit="", percent_volatility=0.0,
                     notional_usd=0.0, cash_for_etf_usd=0.0, etf="")
    rows.append(r)

d = pd.DataFrame(rows)
d.to_csv(f"{out_dir}/portfolio_48_micro.csv", index=False)
pd.set_option("display.width", 250, "display.max_rows", 200, "display.max_colwidth", 52)
show = d[["market", "instrument", "quantity", "unit", "one_unit_percent_volatility", "percent_volatility", "notional_usd", "note"]]
print(f"Account {account:,.0f}; budget {budget_pct} percent = {target_dollars:,.0f} dollars of 20-day ATR per market; {len(d)} markets")
print(show.round(3).to_string(index=False))
inn = d[d["vehicle"] != "none"]
fut = d[d["vehicle"] == "futures"]
etfs = d[d["vehicle"].str.startswith("ETF")]
print(f"\nMarkets in the portfolio: {len(inn)} (futures {len(fut)}, ETF {len(etfs)}, left out {len(d) - len(inn)})")
print(f"Summed percent volatility (stand-alone, all on at once): {inn['percent_volatility'].sum():.2f} percent = {inn['percent_volatility'].sum() * account / 100:,.0f} dollars")
print(f"  futures part {fut['percent_volatility'].sum():.2f}, ETF part {etfs['percent_volatility'].sum():.2f}")
print(f"ETF cash if every ETF were held: {etfs['cash_for_etf_usd'].sum():,.0f} dollars = {100 * etfs['cash_for_etf_usd'].sum() / account:,.0f} percent of the account")
over = d[(d["vehicle"] == "futures") & (d["percent_volatility"] > budget_pct * 1.2)]
print("Futures markets that end up more than 20 percent above the budget because one contract is large:", ", ".join(over["michael_code"]))
print("\nBy group (summed percent volatility):")
print(inn.groupby("group")["percent_volatility"].agg(["count", "sum"]).round(2).to_string())
