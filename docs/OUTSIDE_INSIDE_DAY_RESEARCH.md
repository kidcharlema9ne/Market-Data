# Outside day then inside day: futures research (running write-up)

Owner: Michael. Last updated 11 Nov 2026 (after Entry 103). Branch `claude/outside-inside-day-20261111`. Data: see [FUTURES_DATA.md](../FUTURES_DATA.md). Full numbers live in `research/outside_inside/results*/` and `docs/SHARED_LOG.md` Entries 99-102; this page is the plain-words summary.

## The idea (Michael's rules)
1. Outside day: today's high is above yesterday's high AND today's low is below yesterday's low.
2. The next day is an inside day: its high is below the outside day's high and its low is above the outside day's low (strict both ways).
3. Entry: the session after the inside day, buy the break of the outside day's HIGH (or sell the break of its LOW). A gap open fills at the open. Order live that one session only.
4. Initial stop: the OTHER side of the outside day (long: the outside day's low). One risk unit = entry to that stop. (Michael's first wording used the inside day's far side; he corrected it to the outside day's far side. The inside-day stop is kept in Entries 99 for comparison.)
5. No exit rule was given, so exits are being tested (below). No costs or slippage in any number yet.

## Data and conventions
- Daily futures bars, about 130 contracts, vendor ratio back-adjusted, 2007-12-31 to 2026-11-06. Universe for the main tests: Michael's 48 COT report markets; all ~130 contracts as a robustness check.
- Daily bars cannot order the high and low inside one bar. Worst case (default): a non-gap entry bar that reaches the stop counts as stopped. Best case (assume that low came before the break) is run for finalists. On any later bar the stop is taken before a target.
- Results are in risk units. Errors are clustered by outside-day date (+-2 standard errors).

## Sample protocol (standing)
- In-sample: outside days 2007-12-31 to 2021-08-06. Purge: 2021-08-07 to 2021-11-07 (excluded). **Sealed out-of-sample: outside days from 2021-11-08 (the last 5 years).**
- The sealed years were opened ONCE, for the 18-exit test (Entry 101), so they are no longer pristine for those exits. Everything from the trend filter on (Entry 102) is in-sample only, and `trend_filter.py` is built so it cannot read the sealed years. Unseal only when Michael says so.
- The older workflows are manual-only now so re-pushing a script cannot reopen the sealed years by accident.

## What we found so far
1. **Last 4 years, no exit (Entries 99-100):** with the outside-day stop, about 66% of trades are stopped out within 20 sessions; average results were within noise of zero at fixed time exits. 563 trades on 310 dates in the 48 markets.
2. **18 exits (Entry 101):** in-sample 2008 to mid-2021, the trend-style exits looked positive: hold until stopped +0.22 (+-0.17), close of session 40 +0.18, trail 4 ATR +0.15 (1,834 trades; win rate about 22-26%, median result -1.0: a few big winners pay for many -1 losses). Short exits (3-10 sessions), fixed targets of 1-3 units and tight trails were near zero. **On the sealed last 5 years these did not hold up** (-0.00, -0.07, -0.06; about +0.03 on all contracts). Longs and shorts split in those years (long -0.17, short +0.16) where in-sample they matched.
3. **Controls (Entry 101):** in-sample the pattern beat outside days with no inside day (+0.22 vs +0.10) and ordinary days (+0.02). That gap vanished in the sealed years.
4. **20-day efficiency-ratio trend filter (Entry 102, in-sample only):** trading only in the direction of the 20-day trend lifts the hold-until-stopped result from +0.21 to +0.30 (988 trades, +-0.22). Requiring a higher efficiency ratio raises it further but on fewer trades: ratio >= 0.3 +0.41 (305 trades, +-0.40), >= 0.4 +0.45 (163), >= 0.5 +0.59 (79, +-0.72), >= 0.6 +0.56 (33). Positive in both in-sample halves at every threshold through 0.6. Trend-style exits (hold, trail 4 ATR, session 40) gain; short time exits and 1-unit targets stay near zero. **But**: (a) none of the lifts is distinguishable from the unfiltered +0.21 given the error bands, (b) the same filter lifts the controls even more (outside day with no inside day: +0.10 to +0.29 at ratio >= 0.3 and +0.53 at >= 0.5), so most of the improvement is "outside day with a trend", not the inside day, (c) ordinary days barely move (+0.02 to +0.07), and (d) trades taken against the trend are about flat for the pattern (-0.06 at ratio >= 0.3) and clearly negative for ordinary days.
5. **10-day efficiency ratio (Entry 103, in-sample only):** no trend effect. Hold-until-stopped: no filter +0.22; with the 10-day trend +0.17 (979 trades); ratio >= 0.3 +0.10; >= 0.5 +0.28 (219, +-0.40); >= 0.7 +0.30 (71). Trades AGAINST the 10-day trend did as well or better (+0.27 overall). So the apparent help from the 20-day trend is not confirmed by the 10-day version, which points to noise or a slow-trend effect only.
6. **Portfolio statistics for the 4 ATR trailing stop (Entry 103, in-sample, 0.5% of equity risked per trade, added not compounded, 48 markets, no costs):**

| Strategy | Trades/yr | Win rate | Profit factor | Annual return | Volatility | Sharpe | Max drawdown | Longest time under a peak |
|---|---|---|---|---|---|---|---|---|
| All pattern trades | 133 | 26% | 1.21 | 9.9% | 17.2% | 0.58 | 37% | 3.2 yrs |
| With the 20-day trend | 72 | 26% | 1.31 | 7.7% | 13.4% | 0.57 | 28% | 2.3 yrs |
| 20-day trend, ratio >= 0.3 | 22 | 29% | 1.56 | 4.1% | 6.5% | 0.63 | 13% | 3.5 yrs |
| 20-day trend, ratio >= 0.5 | 6 | 33% | 1.76 | 1.4% | 3.1% | 0.47 | 6% | 3.4 yrs |
| With the 10-day trend | 71 | 26% | 1.23 | 5.8% | 13.0% | 0.45 | 24% | 2.1 yrs |
| 10-day trend, ratio >= 0.5 | 16 | 26% | 1.38 | 2.1% | 5.4% | 0.40 | 14% | 4.2 yrs |

The filter mostly shrinks the book: Sharpe stays about 0.45-0.63 whatever the filter, so risk-adjusted performance is about the same, with fewer trades and smaller drawdowns (a 20-day-trend, ratio >= 0.3 book scaled to the unfiltered volatility would earn about 10.8% with about a 33% drawdown versus 9.9% and 37%: no meaningful difference). An assumed cost of 0.05 risk units per trade cuts the Sharpe of the unfiltered book from 0.58 to 0.38 and the 20-day-trend, ratio >= 0.3 book from 0.63 to 0.54. Drawdowns are large because up to 29 trades can be open at once and they are correlated. Both halves of the in-sample years are positive but the second half is weaker (unfiltered Sharpe 0.77 in 2008-2014 vs 0.36 in 2015-mid 2021). Years: unfiltered-style books lose in 2009 and have long flat stretches; one year (2014) supplies a big share of the 20-day-trend, ratio >= 0.3 book's return (+25%).

## Honest status
Nothing here is an edge yet. In-sample selection among 18 exits and now 10 trend filters carries a multiple-testing haircut, and the one look at the sealed years for exits showed the in-sample result fading. The trend filter is the first idea since then that was developed without touching the sealed years.

## Next steps (open; Michael to choose)
- Break the in-sample years down by market group (rates, currencies, energy, metals, grains, indices) and by year to see where the trend-filtered result comes from.
- Try a 40-session trend lookback and a trend-slope or moving-average version, in-sample only (10 sessions did not help).
- Test whether the inside day adds anything once the trend filter is on (pattern vs outside-day-only at the same filter), with matched trade counts.
- Add costs and slippage (a rough per-contract cost in risk units) before believing any small positive.
- Condition on COT positioning (separate question; COT data in `cot-history`).
- Only when a rule is frozen in-sample: unseal the last 5 years once and record the result.

## How to reproduce
Workflows (manual or branch push): `outside-inside-trend-filter.yml` (in-sample only), `outside-inside-exit-grid.yml` (opens the sealed years; manual only), `futures-prices.yml` (fetch prices). Scripts and tests in `research/outside_inside/`.

## Addendum (11 Nov 2026): efficiency ratio alone, no pattern (Entry 104)
Dropping the outside/inside day and trading only "20-session efficiency ratio >= 0.5, in the trend direction, 2 ATR stop" gives +0.29 risk units per trade for hold until stopped (1,815 trades, +-0.15), Sharpe 0.76, max drawdown 34%, positive in both halves. Against the trend loses (-0.14). The earlier pattern results were therefore mostly the trend, not the inside day. Costs of 0.05 per trade cut the Sharpe to 0.63; trail 4 ATR becomes about zero. Returns are concentrated in 2008, 2014, 2020. Still in-sample only; the last 5 years remain sealed. Full tables: `research/efficiency_trend/results/efficiency_trend_results.txt`.
