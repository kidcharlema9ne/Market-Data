"""The 4 ATR initial / ATR trailing / 0.60 ratio system traded in WHOLE CONTRACTS (micro first) with ETF stand-ins, DEVELOPMENT YEARS ONLY.

Usage: python trend_whole_contracts.py futures_prices.parquet trend_universe.csv market_list.csv OUT_DIR contract_size_atr20.csv

Why this exists: Entries 103 to 107 sized every position as a FRACTION of a contract (shares = risk / ATR). Nobody can trade 0.2 of a contract. Here every position is a
whole number of contracts, or an ETF position, and the ETF cash is checked against the 300,000 account.

Engine: the price loading, unit repair, Kaufman ratio and ATR come from trend_exit_tests.py, loaded unchanged (everything before its list of systems). The trade logic below is a
copy of run_market2 for the one system tested (ratio 0.60 on closes, entry at the next open, initial stop 4 ATR, ATR trailing stop from the best close, no time stop, no minimum
movement, re-entry allowed at once, cost 0.05 ATR per side) with ONE change: the size. A check at the start proves that with fractional sizing the copy reproduces run_market2 to the cent.

Instrument rules (Entry 101, Michael 12 Nov 2026):
- Smallest contract that exists: micro wherever CME lists one (ratio to the full contract in MICRO_RATIO, from CME specifications, PROVISIONAL until checked at the broker), otherwise full size.
- If ONE contract of that size is above the CAP (0.5 percent of the account in 20-day ATR is Michael's rule; 0.35 and 0.25 are also tested, using the 2026-11-06 ATR in contract_size_atr20.csv),
  the market is traded through an ETF stand-in if a US-listed ETF exists (ETF_AVAILABLE, the pairings of etf_cap_standins.py, PROVISIONAL), otherwise it is LEFT OUT.
- Futures: contracts = max(1, round(budget dollars / (ATR as a fraction of price at the signal day x the value of ONE contract at TODAY'S price))). A market whose single contract is bigger than
  the budget is still traded at one contract, so its real risk is above the budget. The count is fixed at entry (no resizing). Profit and loss = contracts x today's contract value x the percent move.
  So this is the portfolio as it would be built at today's prices (Entry 101's basis), tested on the percent moves of 2008 to 2021.
- ETF stand-in: dollars sized so the position's own 20-day ATR equals the budget. The ETF is modelled as moving with the futures percent moves (so the maths equals fractional sizing; real ETFs
  such as BNO, UGA, VXX lose to futures roll costs and tracking error, which is NOT modelled). Cash used = position dollars; shorts are counted the same as longs.
- Futures margin is NOT modelled; gross notional is reported instead.

Why today's prices and not the archive's old prices: the archive is ratio back-adjusted, so old adjusted prices are not real historical price levels, and for markets with heavy roll costs the gap is
enormous (a first run that converted adjusted points to dollars made one micro natural gas contract carry 21 times its budget and 54 percent of all profit; that run was discarded). Percent moves are
unaffected by the adjustment, so only percent moves are used. Not modelled: futures margin, commissions beyond the 0.05 ATR cost, ETF tracking error and roll drag, euro and sterling exchange rates over time.
"""
import os
import sys
import time
import numpy as np
import pandas as pd

size_path = sys.argv[5]
_here = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(_here, "trend_exit_tests.py")).read()
_engine = _src.split("systems = []")[0]
exec(compile(_engine, "trend_exit_tests.py (engine part, unchanged)", "exec"))

MICRO_RATIO = {"ZW": 0.1, "ZC": 0.1, "ZS": 0.1, "ZL": 0.1, "ZM": 0.1, "NG": 0.1, "CL": 0.1, "PL": 0.2, "SI": 0.2, "HG": 0.1, "GC": 0.1,
               "A6": 0.1, "B6": 0.1, "AD": 0.1, "E6": 0.1, "J1": 0.1, "E1": 0.1, "YM": 0.1, "ES": 0.1, "NQ": 0.1, "RTY": 0.1}
# US-listed ETF stand-ins (pairings from etf_cap_standins.py; COCO is London-listed). Markets not listed here have no ETF.
ETF_NAME = {"ZT": "SHY", "ZF": "IEI", "ZN": "IEF", "TN": "IEF", "US": "TLT", "UB": "EDV", "FGBL": "BWX", "FBTP": "BWX", "G": "BWX", "ES": "SPY", "NQ": "QQQ", "RTY": "IWM",
            "YM": "DIA", "FESX": "FEZ", "E6": "FXE", "E1": "FXF", "B6": "FXB", "A6": "FXA", "AD": "FXC", "J1": "FXY", "DX": "UUP", "VX": "VXX", "NG": "UNG", "RB": "UGA",
            "BZ": "BNO", "CL": "USO", "ZC": "CORN", "ZS": "SOYB", "ZW": "WEAT", "SB": "CANE", "CT": "BAL", "HG": "CPER", "GC": "GLD", "SI": "SLV", "PL": "PPLT", "C": "COCO (London cocoa ETC)"}
CAPS = [0.5, 0.35, 0.25, 0.20, 0.15]                      # percent of the account: largest one-contract 20-day ATR a market may have before it must use an ETF (or be left out)
TRAILS = [5.0, 8.0]
BUDGETS = [0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30]   # percent of the account, 20-day ATR per market
UNIVERSES = {"all markets": [], "without fed funds": ["ZQ"]}
TARGET_DD = 100_000
years_total = NCAL / 252
syms = list(mk.keys())

size = pd.read_csv(size_path).set_index("price_symbol")


def build_inst(cap):
    out = {}
    for s in syms:
        ratio = MICRO_RATIO.get(s, 1.0)
        full_mult = float(size.loc[s, "dollars_per_point_usd"])
        pct = 100 * float(size.loc[s, "atr20_usd_per_contract"]) * ratio / ACCOUNT
        if pct <= cap:
            vehicle, unit = "futures", float(size.loc[s, "contract_value_usd"]) * ratio
            label = f"{s} micro (x{ratio:g} of full size)" if ratio < 1 else f"{s} full size"
        elif s in ETF_NAME:
            vehicle, unit, label = "ETF", None, f"{ETF_NAME[s]} ETF stand-in"
        else:
            vehicle, unit, label = "none", None, "left out (one contract above the cap, no ETF)"
        out[s] = dict(ratio=ratio, unit=unit, one_unit_pct=pct, vehicle=vehicle, group=group.get(s, "?"), label=label)
    return out


INST = {cap: build_inst(cap) for cap in CAPS}
for cap in CAPS:
    d = INST[cap]
    print(f"\nCAP {cap} percent: futures {sum(v['vehicle'] == 'futures' for v in d.values())}, ETF {[s for s in syms if d[s]['vehicle'] == 'ETF']}, left out {[s for s in syms if d[s]['vehicle'] == 'none']}")
print("\nOne-contract volatility (percent of account, 2026-11-06 ATR) of every market, smallest contract that exists:")
print("  " + ", ".join(f"{s} {INST[0.5][s]['one_unit_pct']:.3f}" for s in syms))


def run_whole(m, trail, risk, unit, init_atr=4.0, er_min=0.60):
    """Copy of run_market2 for one system; unit = value in dollars of ONE traded contract at today's price (None = fractional / ETF sizing)."""
    o, h, l, c, atr = m.o, m.h, m.l, m.c, m.atr
    er, dr = m.er["close"], m.dir
    n = len(c)
    pnl = [0.0] * n
    inpos = [0] * n
    notional = [0.0] * n
    trades = []
    side = pending = 0
    pend_atr = pend_px = atr0 = stop = stop0 = best = prev = entry = shares = tpnl = 0.0
    ncon = 0.0
    eff = 1.0
    start = 0
    for i in range(n):
        if pending:
            side, atr0, entry = pending, pend_atr, o[i]
            if unit:
                ncon = max(1, int(round(risk / (atr0 / pend_px * unit))))
                shares = ncon * unit / entry
            else:
                shares = risk / atr0
                ncon = shares
            eff = shares * atr0 / risk
            stop = stop0 = entry - side * init_atr * atr0
            best = prev = entry
            start = i
            pending = 0
            cst = -COST * atr0 * shares
            pnl[i] += cst
            tpnl = cst
        if side:
            inpos[i] = 1
            hit = (l[i] <= stop) if side == 1 else (h[i] >= stop)
            reason = None
            if hit:
                if side == 1:
                    pxe = stop if o[i] >= stop else o[i]
                else:
                    pxe = stop if o[i] <= stop else o[i]
                d = shares * side * (pxe - prev) - COST * atr0 * shares
                pnl[i] += d
                tpnl += d
                notional[i] = shares * prev
                reason = "stop"
            else:
                d = shares * side * (c[i] - prev)
                pnl[i] += d
                tpnl += d
                prev = c[i]
                notional[i] = shares * c[i]
                if side == 1:
                    if c[i] > best:
                        best = c[i]
                else:
                    if c[i] < best:
                        best = c[i]
                if atr[i] == atr[i]:
                    new = best - side * trail * atr[i]
                    if side == 1:
                        if new > stop:
                            stop = new
                    else:
                        if new < stop:
                            stop = new
                if i == n - 1:
                    reason = "end"
                    d = -COST * atr0 * shares
                    pnl[i] += d
                    tpnl += d
            if reason:
                trades.append((start, i, ncon, eff, tpnl, side))
                side = 0
        if side == 0 and i < n - 1:
            e, a = er[i], atr[i]
            if e == e and a == a:
                if a > 1e-5 * c[i] and e >= er_min and dr[i] != 0:
                    pending, pend_atr, pend_px = dr[i], a, c[i]
    return pnl, inpos, notional, trades


# ---- check: the copy with fractional sizing reproduces run_market2 (5 ATR trailing, ratio 0.60)
risk_ref = REF / 100 * ACCOUNT
worst = 0.0
ntr_check = 0
for s, m in mk.items():
    a = np.array(run_market2(m, dict(er_min=0.60, init_atr=4.0, trail_atr=5.0), risk_ref)[0])
    b = np.array(run_whole(m, 5.0, risk_ref, None)[0])
    worst = max(worst, float(np.abs(a - b).max()))
print(f"\nCHECK: largest daily difference between this copy (fractional sizing) and run_market2, over all markets: {worst:.6f} dollars")
assert worst < 1e-6, "the copy does not reproduce run_market2"

store = {}
t1 = time.time()
ZERO = np.zeros(NCAL)


def run_all(trail, budget, cap):
    """cap None = fractional sizing of every market (what Entries 103 to 107 assumed)."""
    key = (trail, budget, cap)
    if key in store:
        return store[key]
    risk = budget / 100 * ACCOUNT
    out = {}
    for s, m in mk.items():
        if cap is None:
            unit, veh = None, "fractional"
        else:
            d = INST[cap][s]
            unit, veh = d["unit"], d["vehicle"]
        if veh == "none":
            out[s] = dict(pnl=ZERO, pos=ZERO, notional=ZERO, trades=[])
            continue
        pl, ip, nt, trs = run_whole(m, trail, risk, unit)
        p_ = np.zeros(NCAL); i_ = np.zeros(NCAL); n_ = np.zeros(NCAL)
        p_[m.idx] = pl; i_[m.idx] = ip; n_[m.idx] = nt
        out[s] = dict(pnl=p_, pos=i_, notional=n_, trades=trs)
    store[key] = out
    return out


def book(res, drop):
    keep = [s for s in syms if s not in drop]
    tot = np.sum([res[s]["pnl"] for s in keep], axis=0)
    act = np.sum([res[s]["pos"] for s in keep], axis=0)
    ntrade = sum(len(res[s]["trades"]) for s in keep)
    return tot, act, ntrade, keep


NB, BLK = 2000, 20
idx = np.empty((NB, NCAL), dtype=np.int64)
idx[:, 0] = rng.integers(0, NCAL, NB)
restart = rng.random((NB, NCAL)) < 1 / BLK
fresh = rng.integers(0, NCAL, (NB, NCAL))
for t in range(1, NCAL):
    idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % NCAL)


def boot_dd95(tot):
    x = tot[idx]
    paths = np.cumsum(np.concatenate([np.zeros((NB, 1)), x], axis=1), axis=1)
    return float(np.percentile((np.maximum.accumulate(paths, axis=1) - paths).max(axis=1), 95))


def row(label, cap, trail, uname, b, tot, act, ntr, k=1.0, dd=None, q95=None):
    dd = max_dd(tot) * k if dd is None else dd
    return dict(sizing=label, one_contract_cap_pct=cap, trailing_stop_atr=trail, markets=uname, budget_percent=b, annual_dollars=tot.sum() / years_total * k,
                annual_pct=100 * tot.sum() / years_total * k / ACCOUNT, sharpe=sharpe_of(tot), max_drawdown_dollars=dd, max_drawdown_pct=100 * dd / ACCOUNT,
                resampled_95th_drawdown_dollars=q95, trades=ntr, markets_in_trade_average=float(act.mean()), markets_in_trade_most=int(act.max()),
                sharpe_before_2015=sharpe_of(tot[first_half]), sharpe_2015_on=sharpe_of(tot[~first_half]))


rows = []
for trail in TRAILS:
    for uname, drop in UNIVERSES.items():
        tot, act, ntr, keep = book(run_all(trail, 0.10, None), drop)
        f95 = boot_dd95(tot)
        for b in BUDGETS:
            k = b / 0.10
            rows.append(row("fractional (not tradable)", None, trail, uname, b, tot, act, ntr, k=k, q95=f95 * k))
        for cap in CAPS:
            for b in BUDGETS:
                tot, act, ntr, keep = book(run_all(trail, b, cap), drop)
                rows.append(row("whole contracts and ETF stand-ins", cap, trail, uname, b, tot, act, ntr, q95=boot_dd95(tot)))
print(f"ran the grid in {time.time() - t1:.0f} seconds")
S = pd.DataFrame(rows)
S.round(3).to_csv(f"{out_dir}/whole_contracts_summary.csv", index=False)
pd.set_option("display.width", 320, "display.max_rows", 900, "display.max_columns", 60, "display.max_colwidth", 70)
cols = ["budget_percent", "annual_pct", "annual_dollars", "sharpe", "max_drawdown_dollars", "max_drawdown_pct", "resampled_95th_drawdown_dollars", "trades", "markets_in_trade_average",
        "sharpe_before_2015", "sharpe_2015_on"]
print("\n=== 1. budget ladders: fractional (what Entries 103 to 107 assumed) against whole contracts and ETF stand-ins, by one-contract cap ===")
for trail in TRAILS:
    for uname in UNIVERSES:
        print(f"\n--- {trail:g} ATR trailing stop, {uname}: fractional ---")
        print(S[(S["trailing_stop_atr"] == trail) & (S["markets"] == uname) & (S["sizing"].str.startswith("fractional"))][cols].round(2).to_string(index=False))
        for cap in CAPS:
            print(f"--- {trail:g} ATR trailing stop, {uname}: whole contracts, cap {cap} percent ---")
            print(S[(S["trailing_stop_atr"] == trail) & (S["markets"] == uname) & (S["one_contract_cap_pct"] == cap)][cols].round(2).to_string(index=False))

# ---- budget for a 100,000 drawdown (interpolated, then re-run exactly)
print(f"\n=== 2. budget per market that holds the drawdown at {TARGET_DD:,} (whole contracts), re-run at the interpolated budget ===")
final_rows = []
for trail in TRAILS:
    for uname, drop in UNIVERSES.items():
        for cap in CAPS:
            d = S[(S["sizing"] == "whole contracts and ETF stand-ins") & (S["trailing_stop_atr"] == trail) & (S["markets"] == uname) & (S["one_contract_cap_pct"] == cap)].sort_values("budget_percent")
            for label, col in (("historical maximum drawdown", "max_drawdown_dollars"), ("95th percentile of resampled drawdowns", "resampled_95th_drawdown_dollars")):
                xs, ys = d["budget_percent"].to_numpy(), d[col].to_numpy()
                base = dict(trailing_stop_atr=trail, markets=uname, one_contract_cap_pct=cap, basis=label)
                if ys.min() > TARGET_DD:
                    final_rows.append(dict(**base, note=f"drawdown already above {TARGET_DD:,} at {xs.min()} percent (the one-contract floor decides); lowest tested {ys.min():,.0f}"))
                    continue
                if ys.max() < TARGET_DD:
                    final_rows.append(dict(**base, note=f"drawdown stays below {TARGET_DD:,} up to {xs.max()} percent (highest tested {ys.max():,.0f})"))
                    continue
                j = int(np.argmax(ys > TARGET_DD))
                if j == 0:
                    final_rows.append(dict(**base, note="first grid point already above the target"))
                    continue
                b_star = round(float(np.interp(TARGET_DD, [ys[j - 1], ys[j]], [xs[j - 1], xs[j]])), 3)
                tot, act, ntr, keep = book(run_all(trail, b_star, cap), drop)
                final_rows.append(dict(**base, budget_percent_per_market=b_star, annual_dollars=tot.sum() / years_total, annual_pct=100 * tot.sum() / years_total / ACCOUNT, sharpe=sharpe_of(tot),
                                       historical_max_drawdown_dollars=max_dd(tot), resampled_95th_drawdown_dollars=boot_dd95(tot), trades=ntr,
                                       note="interpolated between grid points; whole-contract drawdown is not exactly linear in the budget"))
F = pd.DataFrame(final_rows)
F.round(3).to_csv(f"{out_dir}/whole_contracts_budget_for_100k.csv", index=False)
print(F.drop(columns=["note"]).round(3).to_string(index=False))
print("\nnotes:")
for r in F.itertuples():
    if isinstance(r.note, str) and not r.note.startswith("interpolated"):
        print(f"  {r.trailing_stop_atr:g} ATR, {r.markets}, cap {r.one_contract_cap_pct}, {r.basis}: {r.note}")

# ---- per market at two policies (5 ATR, all markets)
print("\n=== 3. per market, 5 ATR trailing stop: contracts held, how often the one-contract floor decides, real risk against the budget ===")
mrows = []
for cap, b in ((0.5, 0.10), (0.25, 0.10)):
    res = run_all(5.0, b, cap)
    tot, act, ntr, keep = book(res, [])
    for s in syms:
        t = res[s]["trades"]
        nc = np.array([x[2] for x in t]) if t else np.array([])
        ef = np.array([x[3] for x in t]) if t else np.array([])
        d = INST[cap][s]
        mrows.append(dict(cap_pct=cap, budget_percent=b, symbol=s, group=d["group"], vehicle=d["vehicle"], instrument=d["label"], one_contract_pct_of_account_now=d["one_unit_pct"],
                          trades=len(t), median_contracts=float(np.median(nc)) if len(nc) else np.nan, most_contracts=float(nc.max()) if len(nc) else np.nan,
                          entries_at_the_one_contract_floor_pct=100 * float((nc <= 1).mean()) if (len(nc) and d["vehicle"] == "futures") else np.nan,
                          real_risk_over_budget_average=float(ef.mean()) if len(ef) else np.nan, annual_pct_of_account=100 * res[s]["pnl"].sum() / years_total / ACCOUNT,
                          profit_share_pct=100 * res[s]["pnl"].sum() / tot.sum() if tot.sum() else np.nan))
MK = pd.DataFrame(mrows)
MK.round(3).to_csv(f"{out_dir}/whole_contracts_by_market.csv", index=False)
for cap, b in ((0.5, 0.10), (0.25, 0.10)):
    print(f"\n--- cap {cap} percent, budget {b} percent per market ---")
    print(MK[(MK["cap_pct"] == cap) & (MK["budget_percent"] == b)].drop(columns=["cap_pct", "budget_percent", "group"]).round(2).to_string(index=False))

# ---- cash and notional
print("\n=== 4. ETF cash and gross notional against the 300,000 account (all markets, 5 and 8 ATR trailing stop) ===")
crow = []
for trail in TRAILS:
    for cap in CAPS:
        for b in BUDGETS:
            res = run_all(trail, b, cap)
            etf_cash = np.sum([res[s]["notional"] for s in syms if INST[cap][s]["vehicle"] == "ETF"], axis=0)
            fut_notional = np.sum([res[s]["notional"] for s in syms if INST[cap][s]["vehicle"] == "futures"], axis=0)
            gross = etf_cash + fut_notional
            tot, act, ntr, keep = book(res, [])
            crow.append(dict(trailing_stop_atr=trail, one_contract_cap_pct=cap, budget_percent=b, etf_markets=sum(INST[cap][s]["vehicle"] == "ETF" for s in syms),
                             etf_cash_most_dollars=float(etf_cash.max()), etf_cash_average_dollars=float(etf_cash.mean()), etf_cash_99th_percentile_dollars=float(np.percentile(etf_cash, 99)),
                             sessions_etf_cash_above_account=int((etf_cash > ACCOUNT).sum()), gross_notional_most_times_account=float(gross.max() / ACCOUNT),
                             gross_notional_average_times_account=float(gross.mean() / ACCOUNT), markets_in_trade_most=int(act.max())))
C = pd.DataFrame(crow)
C.round(3).to_csv(f"{out_dir}/whole_contracts_cash.csv", index=False)
print(C.round(2).to_string(index=False))
print(f"\nDONE in {time.time() - t0:.0f} seconds")
