"""Stocks, long only: many improvement ideas, each tested ALONE against the same baseline (Michael, 18 Nov 2026).
Usage: python er_stocks_many_ideas.py stock_prices.parquet OUT_DIR spy_prices.parquet MODE [sector_etfs.parquet]
Every scenario is run with 8 different random picks (when the account is full the pick among a day's signals is random) and the table shows the MEAN of the 8, plus the lowest and highest Sharpe, so a difference
smaller than the pick-luck range is visibly noise. The baseline is the current best rule (hand-off doc): common stocks, one series per company, $3M floor, 20-session ratio 0.50 with rising close, 20-session watch,
buy the next open after a close 1.5 ATR below the best high since the signal, strongest 20% by 126-session return that day, SPY above its 200-day, 4 ATR initial stop, 5 ATR trailing, no time limit, 0.05 ATR a side,
0.10% of $300k per ATR, caps 200% and 100%. In-sample only (data through 2021-08-06); sealed years are not read. Post hoc: an idea counts only if it helps in both 2000-2007 and 2008-2021 and its neighbours look similar.
MODES
  entry     52-week-high nearness filter; other strength windows (63, 189, 252-skip-month, 126-skip-month, average of three); volume dry-up on the pullback (and its opposite as a control); avoid the likely earnings week;
            turn-up confirmation (buy only after a close above the previous day's high).
  exit      tighten the trailing stop after a big gain; release dead money (exit if no progress after N sessions); add to winners (pyramiding).
  account   graded exposure (cap scales with how far SPY is above its 200-day, or with SPY volatility); drawdown throttle; interest on idle cash; position size limited by liquidity; volume-based trading cost;
            fill-cost stress (a share of the day's range on entry and exit days).
  structure ensembles of neighbouring settings splitting the capital (pullback 1/1.5/2 ATR, ratio 0.4/0.5/0.6, SPY average 150/200/250); a short sleeve that trades the mirror rule only while SPY is below its 200-day.
  sector    stocks mapped to the sector ETF they track most closely (past 120 sessions, market removed); filters on sector strength and on the sector ETF's own trend (needs sector_etfs.parquet).
"""
import heapq
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd

import er_stocks as B
import er_stocks_common_momentum as M
import er_stocks_ideas_1_2_6 as I1
from er_stocks import CAPITAL, END, EPOCH, MAIN_START, FIRST_TRADE
from er_stocks_er_grid import er_dr
from er_stocks_combined_er import q_long, cands_from_q
from er_stocks_market_band import switch

PULL = 1.5
SEED = 20261117
KSEEDS = 8
TOP = 0.20
VOLS = []
_orig_analyze = M.analyze


def _analyze_keep_volume(s, o, h, l, c, v):
    out = _orig_analyze(s, o, h, l, c, v)
    if out[1].any():  # same rule build() uses to keep a segment, so VOLS lines up with SEG
        VOLS.append(v)
    return out


# ---------------------------------------------------------------- exits
def run_v(o, h, l, c, atr, t, d, init=4.0, mm=5.0, tight=None, dead=None):
    """Same as er_stocks.run_trade (long) plus: tight=(gain in ATR, new trail in ATR) once the best close is that far above entry; dead=(sessions, needed gain in ATR): exit at the close of that session if the best close has not gained that much."""
    n = len(c); e = t + 1
    if e >= n:
        return None
    a0 = atr[t]; entry = o[e]; stop = entry - init * a0; best = entry; marks = []; cur = mm
    for j in range(e, n):
        k = j - e
        if l[j] <= stop:
            gap = k > 0 and o[j] <= stop
            return j, (o[j] if gap else stop), marks, "stop"
        marks.append(c[j]); best = max(best, c[j])
        if tight is not None and (best - entry) >= tight[0] * a0:
            cur = tight[1]
        na = atr[j]
        if na == na:
            stop = max(stop, best - cur * na)
        if dead is not None and k == dead[0] - 1 and (best - entry) < dead[1] * a0:
            return j, c[j], marks[:-1], "dead money"
    return n - 1, c[n - 1], marks[:-1], "data end"


def base_runner(o, h, l, c, atr, t, d):
    return B.run_trade(o, h, l, c, atr, t, d, 4.0, 5.0, None)


# ---------------------------------------------------------------- trades
KEYS = ("sess_e", "sess_x", "d", "px_e", "px_x", "a0", "res", "held", "sym", "rank", "adv", "rng_e", "rng_x", "parent")


def gen(ctx, mk, cond=None, cands=None, runner=base_runner, rankfn=None, direction=1, addon=None, top=TOP):
    SEG, dropped, cal, _ = ctx
    first_i = (FIRST_TRADE - EPOCH).days
    R = {k: [] for k in KEYS}; R.update(how=[], f_sess=[], f_incr=[], f_tid=[])

    def add(i, g, t, d, res, parent):
        s, so, sh, sl, sc, atr = g["s"], g["o"], g["h"], g["l"], g["c"], g["atr"]
        x, xpx, marks, how = res; e = t + 1; entry, a0 = so[e], atr[t]
        tid = len(R["d"]); incr = d * np.diff(np.r_[entry, np.asarray(marks, float), xpx])
        v = VOLS[i]; adv = float(np.mean(sc[t - 14:t + 1] * v[t - 14:t + 1])) if t >= 14 else np.nan
        R["sess_e"].append(int(s[e])); R["sess_x"].append(int(s[x])); R["d"].append(d); R["px_e"].append(entry); R["px_x"].append(xpx); R["a0"].append(a0)
        R["res"].append(d * (xpx - entry) / a0 - B.COST_RT); R["held"].append(x - e + 1); R["how"].append(how); R["sym"].append(i); R["rank"].append(rk_cur[0])
        R["adv"].append(adv); R["rng_e"].append(sh[e] - sl[e]); R["rng_x"].append(sh[x] - sl[x]); R["parent"].append(parent)
        R["f_sess"].append(s[e:x + 1]); R["f_incr"].append(incr); R["f_tid"].append(np.full(len(incr), tid))
        return tid, x, e, entry, a0

    rk_cur = [np.nan]
    for i, g in enumerate(SEG):
        if i in dropped:
            continue
        cl = cands(i, g) if cands is not None else g["cand"]
        if not cl:
            continue
        s, so, sh, sl, sc, atr = g["s"], g["o"], g["h"], g["l"], g["c"], g["atr"]
        rka = g["rank"] if rankfn is None else rankfn(i, g)
        last_exit = -1
        for t, d in cl:
            rk = rka[t]
            if t < last_exit or not np.isfinite(rk) or g["spac"][t] or not g["liq"][t] or t + 1 >= len(sc) or cal[s[t + 1]] < first_i:
                continue
            if direction > 0:
                if rk < 1.0 - top or not mk[s[t]]:
                    continue
            else:
                if rk > top or mk[s[t]]:
                    continue
            if cond is not None and not cond(i, g, t):
                continue
            res = runner(so, sh, sl, sc, atr, t, direction)
            if res is None:
                continue
            rk_cur[0] = rk
            tid, x, e, entry, a0 = add(i, g, t, direction, res, -1)
            last_exit = x
            if addon is not None:
                G, _ = addon
                for j in range(e + 1, x - 1):
                    if sc[j] - entry >= G * a0 and mk[s[j]] and np.isfinite(atr[j]) and atr[j] > 0 and j + 1 < x:
                        r2 = runner(so, sh, sl, sc, atr, j, 1)
                        if r2 is not None:
                            add(i, g, j, 1, r2, tid)
                        break
    for k in ("sess_e", "sess_x", "d", "sym", "parent"):
        R[k] = np.asarray(R[k], dtype=np.int64)
    for k in ("px_e", "px_x", "a0", "res", "held", "rank", "adv", "rng_e", "rng_x"):
        R[k] = np.asarray(R[k], dtype=float)
    R["how"] = np.asarray(R["how"])
    for k in ("f_sess", "f_incr", "f_tid"):
        R[k] = np.concatenate(R[k]) if R[k] else np.array([])
    return R


def concat(Rs):
    out = {}; n0 = 0
    for k in KEYS + ("how", "f_sess", "f_incr"):
        out[k] = np.concatenate([R[k] for R in Rs])
    tid = []; par = []
    for R in Rs:
        tid.append(R["f_tid"] + n0); par.append(np.where(R["parent"] >= 0, R["parent"] + n0, -1)); n0 += len(R["d"])
    out["f_tid"] = np.concatenate(tid); out["parent"] = np.concatenate(par)
    return out


# ---------------------------------------------------------------- account simulation
def portfolio_gen(R, cal, cap, key, cap_t=None, mult_fn=None, adv_frac=None, impact=None, slip_frac=None, size_scale=1.0, sector_cap=None, max_pos=None):
    n = len(R["d"]); m = len(cal); tgt = CAPITAL * M.SIZE / 100.0 * size_scale
    base_sh = np.floor(tgt / R["a0"])
    idx = np.where(base_sh >= 1)[0]
    order = idx[np.lexsort((key[idx], R["sess_e"][idx]))]
    cnt = np.bincount(R["f_tid"], minlength=n); off = np.r_[0, np.cumsum(cnt)]
    pnl = np.zeros(m); taken = np.zeros(n, bool); shares = np.zeros(n); heap = []; gross = 0.0; gg = {}
    ptr = 0; cum = 0.0; peak = 0.0
    par = R["parent"]
    for i in order:
        s = R["sess_e"][i]
        while heap and heap[0][0] < s:
            _x = heapq.heappop(heap); gross -= _x[1]
            if _x[2] >= 0:
                gg[_x[2]] -= _x[1]
        if par[i] >= 0 and not taken[par[i]]:
            continue
        sh = base_sh[i]
        if mult_fn is not None:
            if s > ptr:
                cs = cum + np.cumsum(pnl[ptr:s]); peak = max(peak, cs.max()); cum = cs[-1]; ptr = s
            sh = np.floor(tgt * mult_fn(CAPITAL + cum, CAPITAL + peak) / R["a0"][i])
        if adv_frac is not None and np.isfinite(R["adv"][i]):
            sh = min(sh, np.floor(adv_frac * R["adv"][i] / R["px_e"][i]))
        if sh < 1:
            continue
        if max_pos is not None and len(heap) >= max_pos:   # maximum number of open positions (Entry 164); expired trades were already popped above
            continue
        notional = sh * R["px_e"][i]
        capi = cap if cap_t is None else cap_t[s]
        if gross + notional > capi * CAPITAL:
            continue
        gi = int(sector_cap[0][i]) if sector_cap is not None else -1
        if sector_cap is not None and gi >= 0 and gg.get(gi, 0.0) + notional > sector_cap[1] * CAPITAL:
            continue
        taken[i] = True; shares[i] = sh; gross += notional; heapq.heappush(heap, (R["sess_x"][i], notional, gi))
        if gi >= 0:
            gg[gi] = gg.get(gi, 0.0) + notional
        a, b = off[i], off[i + 1]
        pnl[R["f_sess"][a:b]] += R["f_incr"][a:b] * sh
        c_ps = 0.5 * B.COST_RT * R["a0"][i]; ee = ex = 0.0
        if slip_frac:
            ee += slip_frac * R["rng_e"][i]; ex += slip_frac * R["rng_x"][i]
        if impact and np.isfinite(R["adv"][i]):
            ii = impact * R["a0"][i] * np.sqrt(notional / max(R["adv"][i], 1.0)); ee += ii; ex += ii
        pnl[s] -= (c_ps + ee) * sh; pnl[R["sess_x"][i]] -= (c_ps + ex) * sh
    notional = shares * R["px_e"]
    dn = np.zeros(m + 1); dv = np.zeros(m + 1)
    tk = np.flatnonzero(taken)
    np.add.at(dn, R["sess_e"][tk], 1.0); np.add.at(dn, R["sess_x"][tk] + 1, -1.0)
    np.add.at(dv, R["sess_e"][tk], notional[tk]); np.add.at(dv, R["sess_x"][tk] + 1, -notional[tk])
    return dict(pnl=pnl, taken=taken, shares=shares, open_n=np.cumsum(dn)[:m], gross=np.cumsum(dv)[:m])


def add_interest(P, credit, borrow):
    """Interest on idle cash (credit rate) and charge on borrowed money (borrow rate), flat annual rates on the account value."""
    net = CAPITAL - P["gross"]          # the account is a fixed $300,000 (profits are not added to it), so idle cash = 300,000 minus position value
    extra = np.where(net > 0, net * credit, net * borrow) / 252.0
    Q = dict(P); Q["pnl"] = P["pnl"] + extra
    return Q


NUM = ["profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "trades taken", "average open positions", "% of sessions at the cap", "average ATR per trade", "excess over SPY (ATR units)"]


def scen(ctx, R, label, K=KSEEDS, on=None, cap_t_fn=None, post=None, **kw):
    """Run one scenario for both caps and K random picks; return rows averaged over the picks."""
    SEG, dropped, cal, (dates, spy_close, WIN) = ctx
    rows = []
    if len(R["d"]) == 0:
        print("  (no trades for this scenario)", flush=True)
        return rows
    for cap in (2.0, 1.0):
        allr = []
        for s in range(K):
            key = np.random.default_rng(1000 + s).random(len(R["d"]))
            P = portfolio_gen(R, cal, cap, key, cap_t=(cap_t_fn(cap) if cap_t_fn else None), **kw)
            if post is not None:
                P = post(P)
            for r in I1.eval_P(R, P, cap, dates, spy_close, WIN, dict(label), on=on):
                r["seed"] = s; allr.append(r)
        D = pd.DataFrame(allr)
        for per, v in D.groupby("period"):
            r = dict(label); r.update({"cap %": int(cap * 100), "period": per, "Sharpe lowest pick": v["Sharpe ratio"].min(), "Sharpe highest pick": v["Sharpe ratio"].max(), "signals": len(R["d"])})
            for c in NUM:
                r[c] = v[c].mean()
            rows.append(r)
    return rows


def line(rows, name):
    w = [r for r in rows if r["period"].startswith("whole") and r["cap %"] == 200]
    if w:
        r = w[-1]
        print(f"  {name}: +{r['profit per year %']:.1f}% / Sharpe {r['Sharpe ratio']:.2f} ({r['Sharpe lowest pick']:.2f} to {r['Sharpe highest pick']:.2f}) / {r['max drawdown %']:.0f}% / worst year {r['worst year %']:.0f}% / trades {r['trades taken']:.0f}", flush=True)


# ---------------------------------------------------------------- setup
def setup(prices_path, spy_path):
    M.analyze = _analyze_keep_volume
    SEG, names, dropped, cal, live, E20, dates, spy_close, mk200 = I1.setup(prices_path, spy_path)
    assert len(VOLS) == len(SEG), (len(VOLS), len(SEG))
    WIN = {"2000 to 2007": (pd.Timestamp("2000-01-01"), MAIN_START - pd.Timedelta(days=1)), "2008 to Aug 2021": (MAIN_START, END), "whole 2000 to Aug 2021": (pd.Timestamp("2000-01-01"), END)}
    ctx = (SEG, dropped, cal, (dates, spy_close, WIN))
    return ctx, names, live, E20, dates, spy_close, mk200


def check_baseline(ctx, mk200):
    SEG, dropped, cal, _ = ctx
    R = gen(ctx, mk200)
    Rm = M.trades_for(SEG, dropped, cal, TOP, I1.VNAME, market_ok=mk200, long_only=True)
    assert len(R["d"]) == len(Rm["d"]) and np.allclose(R["res"], Rm["res"]) and (R["sess_e"] == Rm["sess_e"]).all(), "trade generator differs from the standard one"
    key = np.random.default_rng(SEED).random(len(R["d"]))
    P1 = B.portfolio(Rm, cal, (1,), M.SIZE, 2.0, key); P2 = portfolio_gen(R, cal, 2.0, key)
    assert np.allclose(P1["pnl"], P2["pnl"]) and (P1["taken"] == P2["taken"]).all(), "account simulator differs from the standard one"
    st, _ = B.wstats(P2["pnl"], ctx[3][0], pd.Timestamp("2000-01-01"), END, P2["open_n"], P2["gross"])
    print(f"baseline: {len(R['d']):,} signals; reference pick, whole period cap 200%: {st['profit per year %']:+.1f}% / Sharpe {st['Sharpe ratio']:.2f} / {st['max drawdown %']:.0f}% (documented +22.9% / 0.64 / -22%); generator and account simulator match the standard ones", flush=True)
    return R


def selftest_exits(ctx, mk200):
    SEG, dropped, cal, _ = ctx; n = 0
    for i, g in enumerate(SEG):
        if i in dropped or not g["cand"]:
            continue
        for t, d in g["cand"][:3]:
            a = B.run_trade(g["o"], g["h"], g["l"], g["c"], g["atr"], t, 1, 4.0, 5.0, None); b = run_v(g["o"], g["h"], g["l"], g["c"], g["atr"], t, 1)
            if a is None:
                assert b is None
                continue
            assert a[0] == b[0] and a[1] == b[1] and np.allclose(a[2], b[2]), (i, t)
            n += 1
        if n > 300:
            break
    print(f"exit routine with no extras matches the standard one on {n} trades", flush=True)


# ---------------------------------------------------------------- mode: entry
def make_rank(ctx, scorefn):
    """Percentile rank by session of a per-stock score (same universe rule as the standard 126-session ranking)."""
    SEG, dropped, cal, _ = ctx
    ids, rows_, sess_, vals = [], [], [], []
    for i, g in enumerate(SEG):
        if i in dropped:
            continue
        sc = scorefn(i, g)
        m = g["liq"] & ~g["spac"] & np.isfinite(sc)
        if m.any():
            idx = np.where(m)[0]; ids.append(np.full(len(idx), i)); rows_.append(idx); sess_.append(g["s"][idx]); vals.append(sc[idx])
    ids, rows_, sess_, vals = (np.concatenate(x) for x in (ids, rows_, sess_, vals))
    pct = pd.Series(vals).groupby(sess_).rank(pct=True, method="average").to_numpy()
    out = {i: np.full(len(SEG[i]["c"]), np.nan) for i in range(len(SEG)) if i not in dropped}
    o = np.argsort(ids, kind="stable"); ids, rows_, pct = ids[o], rows_[o], pct[o]
    cuts = np.r_[0, np.flatnonzero(np.diff(ids)) + 1, len(ids)]
    for a, b in zip(cuts[:-1], cuts[1:]):
        out[ids[a]][rows_[a:b]] = pct[a:b]
    return out


def ret_score(L, skip=0):
    def f(i, g):
        c = g["c"]; n = len(c); r = np.full(n, np.nan)
        if n > L:
            r[L:] = c[L - skip:n - skip] / c[:n - L] - 1.0
        return r
    return f


def run_entry(ctx, mk200, names, live, E20, rows):
    SEG, dropped, cal, _ = ctx
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    # 5: nearness to the 52-week high
    near = {}
    def nr(i, g):
        if i not in near:
            near[i] = g["c"] / pd.Series(g["c"]).rolling(252, min_periods=200).max().to_numpy()
        return near[i]
    for x in (0.95, 0.90, 0.80, 0.70):
        R = gen(ctx, mk200, cond=lambda i, g, t, x=x: np.isfinite(nr(i, g)[t]) and nr(i, g)[t] >= x)
        r = scen(ctx, R, {"idea": "5 nearness to 52-week high", "scenario": f"close within {int(round((1-x)*100))}% of its 252-session high"}); rows += r; line(r, f"52w high within {int(round((1-x)*100))}%")
    # 4/5: other strength windows
    variants = {"63-session return": ret_score(63), "189-session return": ret_score(189), "252-session return skipping the latest 21": ret_score(252, 21), "126-session return skipping the latest 21": ret_score(126, 21)}
    ranks = {}
    for name, fn in variants.items():
        ranks[name] = make_rank(ctx, fn)
    r63, r126, r252 = ranks["63-session return"], {i: SEG[i]["rank"] for i in range(len(SEG)) if i not in dropped}, make_rank(ctx, ret_score(252))
    comb = {i: (r63[i] + r126[i] + r252[i]) / 3.0 for i in r63}
    ranks["average of the 63, 126 and 252-session rankings (ranked again)"] = make_rank(ctx, lambda i, g: comb[i])
    for name, rk in ranks.items():
        R = gen(ctx, mk200, rankfn=lambda i, g, rk=rk: rk[i])
        r = scen(ctx, R, {"idea": "4 other strength windows (top 20% each)", "scenario": name}); rows += r; line(r, name)
    # 12: volume dry-up on the pullback
    def vr(i, t):
        v = VOLS[i]
        if t < 20:
            return np.nan
        return float(v[t - 2:t + 1].mean() / max(v[t - 19:t + 1].mean(), 1.0))
    for name, fn in {"pullback volume (last 3 sessions) at most 0.8 of the 20-session average": lambda x: x <= 0.8, "at most 1.0": lambda x: x <= 1.0,
                     "at least 1.2 (control: loud pullbacks)": lambda x: x >= 1.2}.items():
        R = gen(ctx, mk200, cond=lambda i, g, t, fn=fn: (lambda x: np.isfinite(x) and fn(x))(vr(i, t)))
        r = scen(ctx, R, {"idea": "12 volume dry-up", "scenario": name}); rows += r; line(r, name)
    # 13: earnings-week avoidance inferred from volume spikes about every 63 sessions
    spk = {}
    def due(i, t):
        if i not in spk:
            v = pd.Series(VOLS[i]); spk[i] = (v > 2.5 * v.rolling(60, min_periods=40).median().shift(1)).to_numpy()
        a = spk[i][max(0, t - 67):max(0, t - 57)]
        return bool(a.any())
    for name, cnd in {"skip entries when the last volume spike was 58 to 67 sessions ago (next one likely due)": lambda i, g, t: not due(i, t),
                      "only entries in that window (control)": lambda i, g, t: due(i, t)}.items():
        R = gen(ctx, mk200, cond=cnd)
        r = scen(ctx, R, {"idea": "13 earnings-cycle avoidance", "scenario": name}); rows += r; line(r, name)
    # 11: turn-up confirmation
    for W in (3, 5, 10):
        def cf(i, g, W=W):
            c, h = g["c"], g["h"]; out = []
            for t, d in g["cand"]:
                for u in range(t + 1, min(t + 1 + W, len(c) - 1)):
                    if c[u] > h[u - 1]:
                        out.append((u, 1)); break
            return sorted(set(out))
        R = gen(ctx, mk200, cands=cf)
        r = scen(ctx, R, {"idea": "11 turn-up confirmation", "scenario": f"after the trigger, buy after the first close above the previous day's high (within {W} sessions)"}); rows += r; line(r, f"turn-up {W}")
    return rows


# ---------------------------------------------------------------- mode: exit
def run_exit(ctx, mk200, names, live, E20, rows):
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    for gain, tr in ((8, 3.0), (12, 3.0), (12, 4.0), (20, 3.0), (20, 2.0)):
        R = gen(ctx, mk200, runner=lambda o, h, l, c, a, t, d, gain=gain, tr=tr: run_v(o, h, l, c, a, t, d, tight=(gain, tr)))
        r = scen(ctx, R, {"idea": "14 tighten trail after a big gain", "scenario": f"after a gain of {gain} ATR, trail {tr:g} ATR instead of 5"}); rows += r; line(r, f"tighten after {gain} to {tr:g}")
    for N, need in ((40, 1.0), (60, 0.0), (60, 2.0), (90, 2.0), (120, 3.0)):
        R = gen(ctx, mk200, runner=lambda o, h, l, c, a, t, d, N=N, need=need: run_v(o, h, l, c, a, t, d, dead=(N, need)))
        r = scen(ctx, R, {"idea": "17 release dead money", "scenario": f"exit after {N} sessions if the best close is not at least {need:g} ATR above entry"}); rows += r; line(r, f"dead money {N}/{need:g}")
    for G in (5, 10, 15):
        R = gen(ctx, mk200, addon=(G, 1.0))
        r = scen(ctx, R, {"idea": "15 add to winners", "scenario": f"one extra position (same size, same stops) bought after a gain of {G} ATR, if SPY is still above its 200-day"}); rows += r; line(r, f"add-on at {G} ATR")
    return rows


# ---------------------------------------------------------------- mode: account
def run_account(ctx, mk200, names, live, E20, rows, spy_close):
    SEG, dropped, cal, (dates, _, _) = ctx
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    s = pd.Series(spy_close); sma = s.rolling(200, min_periods=200).mean(); dist = (s / sma - 1.0).to_numpy()
    vol = (np.log(s).diff().rolling(20).std() * np.sqrt(252)).to_numpy()
    def mk_cap(fn):
        return lambda cap: np.nan_to_num(fn(cap), nan=cap)
    graded = {
        "cap full only when SPY is 5%+ above its 200-day, half of it between 0 and 5%": lambda cap: np.where(dist >= 0.05, cap, cap * 0.5),
        "cap grows with the distance above the 200-day (full at 10%+, at least a quarter)": lambda cap: np.clip(cap * dist / 0.10, cap * 0.25, cap),
        "cap scaled by SPY volatility (target 16% a year, between a quarter and full)": lambda cap: np.clip(cap * 0.16 / vol, cap * 0.25, cap),
        "cap full when SPY 20-session volatility is under 20%, half otherwise": lambda cap: np.where(vol < 0.20, cap, cap * 0.5),
        "cap 1.5x the usual when SPY is 5%+ above its 200-day and volatility under 15% (leverage up)": lambda cap: np.where((dist >= 0.05) & (vol < 0.15), cap * 1.5, cap),
    }
    for name, fn in graded.items():
        r = scen(ctx, base, {"idea": "7 graded exposure", "scenario": name}, cap_t_fn=mk_cap(fn)); rows += r; line(r, name)
    for dd, mult in ((0.10, 0.5), (0.15, 0.5), (0.10, 0.25), (0.20, 0.5)):
        r = scen(ctx, base, {"idea": "8 drawdown throttle", "scenario": f"risk per trade x{mult:g} while the account is {int(dd*100)}% or more below its peak"},
                 mult_fn=lambda eq, pk, dd=dd, mult=mult: mult if eq < pk * (1 - dd) else 1.0); rows += r; line(r, f"throttle {dd}/{mult}")
    for cr, bo in ((0.0, 0.04), (0.02, 0.04), (0.03, 0.05), (0.04, 0.06)):
        r = scen(ctx, base, {"idea": "9 interest on idle cash", "scenario": f"{cr*100:g}% earned on idle cash, {bo*100:g}% charged on borrowed money (flat rates, not the real history)"}, post=lambda P, cr=cr, bo=bo: add_interest(P, cr, bo)); rows += r; line(r, f"interest {cr}/{bo}")
    for f in (0.01, 0.02, 0.05):
        r = scen(ctx, base, {"idea": "16 liquidity-limited size", "scenario": f"position at most {f*100:g}% of the 15-day average dollar volume"}, adv_frac=f); rows += r; line(r, f"liquidity {f}")
    for k in (0.5, 1.0, 2.0):
        r = scen(ctx, base, {"idea": "16 liquidity-scaled cost", "scenario": f"extra cost per side = {k:g} x ATR x square root of (position / average dollar volume)"}, impact=k); rows += r; line(r, f"impact {k}")
    for f in (0.05, 0.10, 0.20):
        r = scen(ctx, base, {"idea": "20 fill-cost stress", "scenario": f"extra cost per side = {int(f*100)}% of the high-to-low range of the fill day (entry and exit)"}, slip_frac=f); rows += r; line(r, f"slip {f}")
    return rows


# ---------------------------------------------------------------- mode: structure
def combine_scen(ctx, parts, label, K=KSEEDS):
    """parts: list of (R, size_scale). Each part gets cap/len(parts) and size/len(parts) of the account; results are summed."""
    SEG, dropped, cal, (dates, spy_close, WIN) = ctx
    rows = []; nparts = len(parts)
    for cap in (2.0, 1.0):
        allr = []
        for s in range(K):
            Ps = [portfolio_gen(R, cal, cap / nparts, np.random.default_rng(1000 + s).random(len(R["d"])), size_scale=1.0 / nparts) for R, _ in parts]
            P = dict(pnl=sum(p["pnl"] for p in Ps), open_n=sum(p["open_n"] for p in Ps), gross=sum(p["gross"] for p in Ps))
            for wn, (lo, hi) in WIN.items():
                st, _ = B.wstats(P["pnl"], dates, lo, hi, P["open_n"], P["gross"])
                if not st:
                    continue
                sel = np.asarray((dates >= max(lo, FIRST_TRADE)) & (dates <= hi))
                full = P["gross"][sel] / CAPITAL * 100 >= cap * 100 * 0.95
                allr.append(dict(period=wn, seed=s, **{k: st[k] for k in ("profit per year %", "Sharpe ratio", "max drawdown %", "worst year %")}, **{"trades taken": sum(int(p["taken"].sum()) for p in Ps), "average open positions": st["average open positions"], "% of sessions at the cap": float(full.mean() * 100)}))
        D = pd.DataFrame(allr)
        for per, v in D.groupby("period"):
            r = dict(label); r.update({"cap %": int(cap * 100), "period": per, "Sharpe lowest pick": v["Sharpe ratio"].min(), "Sharpe highest pick": v["Sharpe ratio"].max()})
            for c in ("profit per year %", "Sharpe ratio", "max drawdown %", "worst year %", "trades taken", "average open positions", "% of sessions at the cap"):
                r[c] = v[c].mean()
            rows.append(r)
    return rows


def cands_pull(E20, live, SEG, pull, thr):
    for i in live:
        g = SEG[i]; g["cand"] = cands_from_q(g, q_long(g, *E20[i], thr), pull)


def run_structure(ctx, mk200, names, live, E20, rows, spy_close):
    SEG, dropped, cal, (dates, _, _) = ctx
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    # 19: ensembles
    sets = {}
    for pull in (1.0, 1.5, 2.0):
        cands_pull(E20, live, SEG, pull, 0.50); sets[("pull", pull)] = gen(ctx, mk200)
    for thr in (0.4, 0.6):
        cands_pull(E20, live, SEG, PULL, thr); sets[("thr", thr)] = gen(ctx, mk200)
    cands_pull(E20, live, SEG, PULL, 0.50); sets[("thr", 0.5)] = gen(ctx, mk200)
    s = pd.Series(spy_close)
    for n in (150, 250):
        sma = s.rolling(n, min_periods=n).mean(); sets[("spy", n)] = gen(ctx, switch(((s / sma - 1.0) * 100).to_numpy(), 0, 0))
    sets[("spy", 200)] = sets[("thr", 0.5)]
    for lab, parts in (("pullback 1 / 1.5 / 2 ATR", [("pull", 1.0), ("pull", 1.5), ("pull", 2.0)]), ("efficiency ratio 0.4 / 0.5 / 0.6", [("thr", 0.4), ("thr", 0.5), ("thr", 0.6)]),
                       ("SPY average 150 / 200 / 250 days", [("spy", 150), ("spy", 200), ("spy", 250)])):
        r = combine_scen(ctx, [(sets[p], 1) for p in parts], {"idea": "19 ensemble", "scenario": f"capital split in three: {lab}"}); rows += r; line(r, lab)
    # 10: short sleeve (mirror rule only while SPY is below its 200-day; no borrowing fee on shorts, so optimistic)
    def short_cands(i, g):
        er, dr = E20[i]; c, l, atr = g["c"], g["l"], g["atr"]; n = len(c)
        q = np.isfinite(er) & (er >= 0.50) & (dr < 0) & np.isfinite(atr) & (atr > 1e-6 * c)
        qprev = np.r_[False, q[:-1]]; out = []
        for st in np.where(q & ~qprev)[0]:
            tr_ = l[st]
            for t in range(st + 1, min(st + M.WATCH, n - 2) + 1):
                tr_ = min(tr_, l[t]); a = atr[t]
                if a == a and a > 0 and (c[t] - tr_) / a >= PULL:
                    out.append((t, -1)); break
        return out
    Rs = gen(ctx, mk200, cands=short_cands, direction=-1)
    r = scen(ctx, Rs, {"idea": "10 short sleeve", "scenario": "shorts only (SPY below its 200-day, weakest 20%, mirror rule), no long book"}); rows += r; line(r, "shorts alone")
    r = scen(ctx, concat([base, Rs]), {"idea": "10 short sleeve", "scenario": "long book plus short sleeve sharing one account and one cap (no borrow fee on shorts: optimistic)"}); rows += r; line(r, "long + short")
    return rows


# ---------------------------------------------------------------- mode: sector
def run_sector(ctx, mk200, names, live, E20, rows, spy_close, etf_path):
    SEG, dropped, cal, (dates, _, _) = ctx
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    df = (pd.read_csv(etf_path) if etf_path.endswith(".csv") else pd.read_parquet(etf_path)); df = df[df["date_i"] <= (END - EPOCH).days]
    syms = sorted(df["symbol"].unique()); print("sector ETF symbols found:", syms, flush=True)
    ns = len(cal); E = {}
    for sy in syms:
        d = df[df.symbol == sy].sort_values("date_i").drop_duplicates("date_i")
        ser = pd.Series(d["close"].to_numpy(float), index=np.searchsorted(cal, d["date_i"].to_numpy())); ser = ser[ser.index < ns]
        E[sy] = ser.reindex(range(ns)).ffill().to_numpy().copy()
        first = np.searchsorted(cal, d["date_i"].min()); E[sy][:first] = np.nan
    core = [x for x in ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC", "XLRE") if x in E]
    allsec = [x for x in syms if x != "SPY"]
    spy = pd.Series(spy_close)
    rspy = spy.pct_change().to_numpy()
    for cfg_name, sec in (("9 core SPDR sectors", core), (f"all {len(allsec)} sector and industry ETFs found", allsec)):
        if len(sec) < 5:
            continue
        RET = np.vstack([pd.Series(E[x]).pct_change().to_numpy() - rspy for x in sec]).T      # session x sector, market removed
        R126 = np.vstack([pd.Series(E[x]).pct_change(126).to_numpy() for x in sec]).T
        SMA = np.vstack([(pd.Series(E[x]) / pd.Series(E[x]).rolling(200, min_periods=200).mean() - 1.0).to_numpy() for x in sec]).T
        pos = np.full(R126.shape, np.nan)
        for t_ in range(ns):
            v = R126[t_]; ok = np.isfinite(v)
            if ok.sum() >= 4:
                pos[t_, ok] = (-v[ok]).argsort().argsort() + 1
        navail = np.isfinite(R126).sum(1)
        cache = {}
        def sector_of(i, g, t):
            key = (i, t)
            if key in cache:
                return cache[key]
            res = -1
            if t >= 121:
                s_ = g["s"][t - 120:t + 1]; c_ = g["c"][t - 120:t + 1]
                contig = np.diff(s_) == 1
                rs = (c_[1:] / c_[:-1] - 1.0)[contig] - rspy[s_[1:]][contig]
                if len(rs) >= 80:
                    sess = s_[1:][contig]; best = -2.0
                    for k in range(len(sec)):
                        re = RET[sess, k]; ok = np.isfinite(re) & np.isfinite(rs)
                        if ok.sum() >= 80:
                            cc = np.corrcoef(rs[ok], re[ok])[0, 1]
                            if np.isfinite(cc) and cc > best:
                                best, res = cc, k
            cache[key] = res
            return res
        def mkcond(fn):
            def cond(i, g, t):
                k = sector_of(i, g, t)
                if k < 0:
                    return False
                return fn(g["s"][t], k)
            return cond
        nsec = len(sec)
        tests = {}
        for frac in (0.3, 0.5, 0.7):
            tests[f"sector among the strongest {int(frac*100)}% of the sectors by 126-session return"] = lambda s_, k, frac=frac: np.isfinite(pos[s_, k]) and pos[s_, k] <= max(1, round(frac * navail[s_]))
        tests["sector among the weakest half (control)"] = lambda s_, k: np.isfinite(pos[s_, k]) and pos[s_, k] > navail[s_] / 2
        tests["sector ETF above its own 200-day average"] = lambda s_, k: np.isfinite(SMA[s_, k]) and SMA[s_, k] > 0
        for name, fn in tests.items():
            R = gen(ctx, mk200, cond=mkcond(fn))
            r = scen(ctx, R, {"idea": "3 sector information", "scenario": f"[{cfg_name}] {name}"}); rows += r; line(r, f"{cfg_name[:22]}: {name[:60]}")
        # 2b: cap of the position value per sector ETF group (same style as the cluster cap test)
        for gf in (0.15, 0.25):
            R = gen(ctx, mk200)
            sym = R["sym"]; t_dec = np.array([int(np.searchsorted(SEG[sym[k]]["s"], R["sess_e"][k])) - 1 for k in range(len(sym))])
            grp = np.array([sector_of(int(sym[k]), SEG[int(sym[k])], int(t_dec[k])) for k in range(len(sym))])
            r = scen(ctx, R, {"idea": "3 sector information", "scenario": f"[{cfg_name}] cap per sector group {int(gf*100)}% of the account"}, sector_cap=(grp, gf)); rows += r; line(r, f"sector cap {gf}")
    return rows


# ---------------------------------------------------------------- mode: followup
def run_followup(ctx, mk200, names, live, E20, rows, spy_close):
    SEG, dropped, cal, (dates, _, _) = ctx
    base = gen(ctx, mk200)
    rows += scen(ctx, base, {"idea": "baseline", "scenario": "current best rule"}); line(rows, "baseline")
    RK = {L: make_rank(ctx, ret_score(L)) for L in (63, 189, 252)}
    RK[126] = {i: SEG[i]["rank"] for i in range(len(SEG)) if i not in dropped}
    def avg(Ls):
        return {i: np.mean([RK[L][i] for L in Ls], axis=0) for i in RK[63]}
    combos = {"63+126": (63, 126), "126+252": (126, 252), "63+189": (63, 189), "63+126+252": (63, 126, 252), "63+126+189+252": (63, 126, 189, 252)}
    reranked = {}
    for name, Ls in combos.items():
        sc = avg(Ls); rk = make_rank(ctx, lambda i, g, sc=sc: sc[i]); reranked[name] = rk
        for top in (0.10, 0.20, 0.30):
            R = gen(ctx, mk200, rankfn=lambda i, g, rk=rk: rk[i], top=top)
            r = scen(ctx, R, {"idea": "4 average of strength rankings", "scenario": f"average rank of the {name}-session returns, top {int(top*100)}%"}); rows += r; line(r, f"avg {name} top {int(top*100)}%")
    for name, Ls in (("63, 126 and 252", (63, 126, 252)), ("63, 126, 189 and 252", (63, 126, 189, 252))):
        mn = {i: np.min([RK[L][i] for L in Ls], axis=0) for i in RK[63]}
        for top in (0.30, 0.40):
            R = gen(ctx, mk200, rankfn=lambda i, g, mn=mn: mn[i], top=top)
            r = scen(ctx, R, {"idea": "4 every ranking strong", "scenario": f"in the top {int(top*100)}% on each of the {name}-session returns"}); rows += r; line(r, f"all of {name} top {int(top*100)}%")
    # graded exposure neighbours
    s = pd.Series(spy_close); sma = s.rolling(200, min_periods=200).mean(); dist = (s / sma - 1.0).to_numpy()
    def gcap(thr, frac):
        return lambda cap: np.nan_to_num(np.where(dist >= thr, cap, cap * frac), nan=cap)
    for thr in (0.03, 0.05, 0.08):
        for frac in (0.5, 0.25, 0.0):
            r = scen(ctx, base, {"idea": "7 graded exposure (neighbours)", "scenario": f"cap full when SPY is {int(thr*100)}%+ above its 200-day, {frac:g} of it between 0 and {int(thr*100)}%"}, cap_t_fn=gcap(thr, frac)); rows += r; line(r, f"graded {thr}/{frac}")
    # stacked (not independent: each piece was picked from the tests above)
    rk = reranked["63+126+252"]
    Rc = gen(ctx, mk200, rankfn=lambda i, g: rk[i])
    r = scen(ctx, Rc, {"idea": "stacked", "scenario": "average of 63/126/252 rankings (top 20%) + graded exposure (full cap only when SPY is 5%+ above its 200-day, half between 0 and 5%)"}, cap_t_fn=gcap(0.05, 0.5)); rows += r; line(r, "stacked rank+graded")
    r = scen(ctx, Rc, {"idea": "stacked", "scenario": "average of 63/126/252 rankings (top 20%) + 2% interest on idle cash and 4% charge on borrowing"}, post=lambda P: add_interest(P, 0.02, 0.04)); rows += r; line(r, "stacked rank+interest")
    return rows


def main():
    prices_path, out_dir, spy_path, mode = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx, names, live, E20, dates, spy_close, mk200 = setup(prices_path, spy_path)
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 900); pd.set_option("display.max_colwidth", 110)
    check_baseline(ctx, mk200)
    selftest_exits(ctx, mk200)
    rows = []
    if mode == "entry":
        run_entry(ctx, mk200, names, live, E20, rows)
    elif mode == "exit":
        run_exit(ctx, mk200, names, live, E20, rows)
    elif mode == "account":
        run_account(ctx, mk200, names, live, E20, rows, spy_close)
    elif mode == "structure":
        run_structure(ctx, mk200, names, live, E20, rows, spy_close)
    elif mode == "followup":
        run_followup(ctx, mk200, names, live, E20, rows, spy_close)
    elif mode == "sector":
        run_sector(ctx, mk200, names, live, E20, rows, spy_close, sys.argv[5])
    S = pd.DataFrame(rows)
    S.to_csv(out_dir / f"many_{mode}.csv", index=False)
    cols = ["idea", "scenario", "profit per year %", "Sharpe ratio", "Sharpe lowest pick", "Sharpe highest pick", "max drawdown %", "worst year %", "trades taken", "average open positions", "% of sessions at the cap"]
    for wn in ctx[3][2]:
        for cap in (200, 100):
            print(f"\n==== {mode} | {wn} | cap {cap}% | mean of {KSEEDS} random picks ====")
            v = S[(S.period == wn) & (S["cap %"] == cap)]
            print(v[[c for c in cols if c in v.columns]].round(2).to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
