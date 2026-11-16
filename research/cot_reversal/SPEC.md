COT Reversal-Day Breakout Research — Full Backtest Specification

1. Objective

Run a historical backtest across all 48 futures markets in my COT research universe.

The objective is to determine whether a specific reversal-day price pattern, combined with extreme CFTC Commitment of Traders positioning, produces a statistically meaningful directional trading edge.

Test both long and short trades using identical, mirrored rules.

The primary research objective is to measure maximum favorable excursion (MFE) and maximum adverse excursion (MAE) at 1, 2, 3, 4, 5, and 10 trading sessions after entry.

Compare three increasingly restrictive COT positioning thresholds to determine whether more extreme positioning improves subsequent price behavior.

Do not assume the strategy is profitable. Determine whether an edge exists from actual historical results.

2. Data Sources

GitHub repository:
kidcharlema9ne/cot-history

Use the historical CFTC Legacy Futures Only positioning data maintained in this repository.

Futures price data:
MarketParquet historical daily futures OHLC data, accessible through the existing research infrastructure and Cloudflare R2.

R2 bucket: insider-research

Historical futures files:
marketparquet/futures_daily/YYYY-MM-DD.parquet

Use all 48 markets in the established COT reporting universe, not a smaller subset.

Use the maximum reliable historical overlap between COT data and daily futures prices. Report the actual beginning and ending dates.

Do not invent or simulate historical prices, COT readings, trades, or results.

3. Reversal-Day Pattern

LONG SETUP

A valid bullish reversal breakout requires:

1. The commercial COT index meets the required bullish threshold.
2. A bearish reversal day occurs.
3. That reversal day makes a higher high than the previous trading day.
4. The reversal day closes below the previous trading day’s close.
5. On the very next trading session only, place a buy stop one minimum tick above the reversal day’s high.
6. If that price is reached, enter long.
7. If the reversal day’s high is not exceeded sufficiently to trigger the buy stop during that next session, cancel the setup.
8. Never carry the unfilled order into a second or later session.

This is a bearish reversal day followed by an immediate bullish breakout.

Long entry: Reversal-day high + 1 tick.

Initial protective stop: Reversal-day low.

SHORT SETUP — EXACT MIRROR

A valid bearish reversal breakout requires:

1. The commercial COT index meets the required bearish threshold.
2. A bullish reversal day occurs.
3. That reversal day makes a lower low than the previous trading day.
4. The reversal day closes above the previous trading day’s close.
5. On the very next trading session only, place a sell stop one minimum tick below the reversal day’s low.
6. If that price is reached, enter short.
7. Otherwise, cancel the setup at the end of that session.
8. Never carry the order forward.

Short entry: Reversal-day low − 1 tick.

Initial protective stop: Reversal-day high.

The reversal pattern must be defined exactly as above. Do not substitute a conventional candlestick reversal, outside reversal, or inside-day breakout.

4. Three COT Threshold Experiments

Run all three variations separately on the same 48-market universe.

Test A — Commercial Index 80

Long:

* Commercial COT index ≥80.
* No additional large- or small-speculator index restriction.

Short:

* Commercial COT index ≤20.
* No additional speculator restriction.

Test B — Three-Way Extreme Alignment

Long:

* Commercial index ≥95.
* Large speculator index ≤5.
* Small speculator index ≤5.

Short:

* Commercial index ≤5.
* Large speculator index ≥95.
* Small speculator index ≥95.

Test C — Absolute Three-Way Extreme

Long:

* Commercial index =100.
* Large speculator index =0.
* Small speculator index =0.

Short:

* Commercial index =0.
* Large speculator index =100.
* Small speculator index =100.

Use the established COT index calculation from the research repository, with the existing standard 26-week lookback as the primary definition.

Do not optimize the COT lookback separately for individual markets.

The same reversal-day and next-session breakout requirements apply to every test.

5. COT Publication Timing — Critical

CFTC positioning is measured as of Tuesday but ordinarily published on Friday.

A Tuesday observation cannot be used for a trade before the corresponding report has actually been released.

For every setup:

* Use only the latest publicly released COT report available at the time of the reversal day.
* Account for delayed publication and holiday schedules where relevant.
* Never use future COT data.
* Never backdate Friday’s information to Tuesday.
* Report how publication timing is handled.

This is essential to prevent look-ahead bias.

6. Primary Research — MAE and MFE

For every executed trade, calculate maximum favorable excursion and maximum adverse excursion over:

1, 2, 3, 4, 5, and 10 trading sessions after entry.

For longs:

* MFE = Highest high reached during the measurement window − entry price.
* MAE = Entry price − lowest low reached during the measurement window.

For shorts:

* MFE = Entry price − lowest low reached during the measurement window.
* MAE = Highest high reached during the measurement window − entry price.

Normalize both measures by the 14-session ATR measured before entry.

Report excursions in ATR units, with MFE and MAE expressed as nonnegative magnitudes.

For example:

* Entry price: 100
* Pre-entry ATR: 2
* Highest subsequent high: 106
* Lowest subsequent low: 98

Long MFE = +3 ATR.

Long MAE = 1 ATR.

Use the entry session as session 1, counting price movement from the actual entry onward. For a stop-entry triggered during the session, exclude price extremes that occurred before the entry if their sequence is known.

Because daily OHLC does not reveal intraday event ordering, explicitly flag any entry-day excursion that cannot be established reliably. Do not silently treat pre-entry highs or lows as post-entry excursions.

Required statistics

For each of the six measurement horizons, report:

* Number of eligible trades.
* Mean MFE in ATR.
* Median MFE in ATR.
* Mean MAE in ATR.
* Median MAE in ATR.
* Mean and median close-to-entry return in ATR.
* Percentage of trades with MFE ≥1 ATR.
* Percentage of trades with MFE ≥2 ATR.
* Percentage of trades with MAE ≥1 ATR.
* Percentage of trades with MAE ≥2 ATR.

Also report the distribution of excursions where sample size permits.

7. Required Comparison Tables

Produce a separate table for each COT threshold experiment, plus a combined comparison.

Example output format — illustrative only, not actual results:

COT filter	Trades	1D MFE	2D MFE	3D MFE	4D MFE	5D MFE	10D MFE
Commercial ≥80 / ≤20	TBD	TBD	TBD	TBD	TBD	TBD	TBD
Three-way 95/5	TBD	TBD	TBD	TBD	TBD	TBD	TBD
Three-way 100/0	TBD	TBD	TBD	TBD	TBD	TBD	TBD

Create the corresponding table for mean MAE, median MFE, median MAE, and close-to-entry returns.

Separate:

1. Long trades.
2. Short trades.
3. Combined trades.

Also provide per-market trade counts and results.

8. Additional Trade Risk Analysis

For every trade, calculate initial risk:

Long: Entry price − reversal-day low.

Short: Reversal-day high − entry price.

Express initial risk in ATR units.

Investigate whether the reversal-day stop is excessively wide relative to the subsequent favorable excursion.

Report:

* Average and median initial risk in ATR.
* MFE divided by initial risk.
* Percentage reaching +1R.
* Percentage reaching +2R.
* Percentage touching the initial stop.
* Percentage reaching favorable targets before touching the initial stop, where ordering can be determined.

If both the stop and target are touched during the same daily bar and the sequence is unknown, identify the ambiguity and report sensitivity rather than assuming the favorable outcome.

9. Trailing-Stop Research — Secondary Phase

The original strategy also proposed protective and trailing stops:

Long trades:

* Initial stop at reversal-day low.
* Two-day trailing stop based on the lowest low of the previous two completed sessions.

Short trades:

* Initial stop at reversal-day high.
* One-day trailing stop based on the previous completed session’s high.

Evaluate these exits after completing the primary MAE/MFE research.

Do not let the trailing stops truncate the primary excursion measurements.

The purpose is first to establish whether favorable movement follows the setup, then determine how much of that movement a realistic exit strategy could capture.

Report realized trade returns, win rate, median return, average return, and trade duration under the trailing-stop rules.

Clearly distinguish gross returns before transaction costs from any cost-adjusted results.

10. Data Integrity and Backtest Execution

Before presenting results:

1. Confirm that all 48 COT markets are included.
2. Confirm the available historical date ranges.
3. Confirm correct mapping of CFTC market identifiers to futures price series.
4. Confirm continuous-contract construction and any roll adjustments.
5. Verify that daily prices and COT data are chronologically aligned.
6. Verify that the entry can occur only on the session immediately following the reversal day.
7. Use actual tick sizes for stop-entry triggers.
8. Distinguish the stop trigger price from the actual simulated fill price, including gaps through the trigger.
9. Document how ambiguous daily OHLC sequences are treated.
10. Avoid counting unavailable future sessions as completed measurement windows.
11. Identify missing data and exclude invalid observations transparently.
12. Do not substitute fabricated results if data access or execution fails.

Use one consistent trade-counting methodology across all three COT tests.

Where setups overlap, disclose whether multiple simultaneous positions in the same market are permitted. Prefer one active position per market for the executable strategy, and separately disclose any event-study counts that include overlapping signals.

11. What I Want to Learn

The central research questions are:

A. Does this reversal-day breakout produce positive subsequent price movement?

Does MFE consistently exceed MAE, particularly during the first 1–5 sessions?

B. Does more extreme COT positioning improve the setup?

Compare the 80 commercial threshold against three-way 95/5 alignment and the absolute 100/0 extreme.

Do stronger COT extremes produce larger favorable excursions, smaller adverse excursions, or better forward returns?

C. When does the favorable movement occur?

Is most of the favorable excursion achieved within 1–3 sessions, 5 sessions, or only by 10 sessions?

D. Are longs and shorts different?

Report both directions separately.

E. Is there an executable trading edge?

Favorable MFE alone does not prove profitability.

Determine whether favorable moves can realistically be captured after accounting for initial risk, adverse movement, stop execution, and trading costs.

F. Is the result broad or concentrated?

Determine whether any positive result appears across many futures markets or depends on a small number of contracts, trades, or historical periods.

12. Final Deliverables

Provide:

1. A data audit identifying the 48 markets, historical coverage, and any missing data.
2. Trade counts for each of the three COT thresholds.
3. Complete 1/2/3/4/5/10-session MFE and MAE results in ATR units.
4. Mean and median results, separated into long, short, and combined.
5. Close-to-entry forward returns over the same horizons.
6. Comparison of COT 80, three-way 95/5, and absolute 100/0.
7. Initial-stop and risk/reward analysis.
8. Secondary trailing-stop results.
9. Per-market breakdowns and historical-period robustness checks.
10. An evidence-based conclusion about whether the setup has a usable trading edge.

Important: Run the actual backtest using the repository and historical data. Do not provide hypothetical performance numbers or substitute a proposed methodology for executed research.

Report the exact parameters, historical dates, code version or commit SHA, sample sizes, and any unresolved data limitations so the results are reproducible.

Research priority: First establish the complete MAE/MFE profile of the reversal-day breakout at all three COT thresholds across all 48 markets. Then investigate stop-based profitability and robustness.