# COT + WR4 / inside-day breakout: pre-run audit and locked specification
Date: 2026-11-15
Status: BLOCKED BEFORE BACKTEST. No trades, outcome statistics or random-control results produced.

## Sources inspected
- cot-history main tree SHA: 64f8cfcce1c4414c931fa2f78827067211f958b3.
- insider-buying-research main tree SHA: 805a8670524e5d98541fcc42af55986042dcd086.
- Existing report script blob: 45eac3d0a5ca735de004f690067075213d785043. Not modified.
- FUTURES_DATA.md; futures_data/fetch_futures_prices.py (blob bf134ec6dae55854d5077b69e3b885634bd37b27); futures_data/report_universe_48_markets.csv (blob 311eeff9e820009492a92593c3fbe233c7c265fc).
- Prior data-fetch run https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42911620581 , job 130163442640, script research/cot_exit/fetch_futures_prices.py with identical blob to the current loader.
- Prior COT helper: branch claude/outside-inside-day-20261111, research/cot_exit/cot_exit_test.py, blob 624ae0c06c0bafbae83a608838a9646b0ec771d6.
- https://marketparquet.com/data/futures/continuous
- https://marketparquet.com/data-quality
- https://marketparquet.com/documentation
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm
- https://www.cftc.gov/PressRoom/PressReleases/6745-13
- https://www.cftc.gov/PressRoom/PressReleases/7864-19

## What was verified, and what was not
The prior fetch job logs show 4,906 daily objects, 2007-12-31 through 2026-11-06, and 526,297 rows. These are historical run facts, NOT a new inventory of R2.
The first raw schema printed by that job is timestamp[us], symbol:string, asset_type:string, open/high/low/close/volume:double.
The current loader validates each object's verified-sha256 metadata, retains symbol/OHLCV, and substitutes the filename date. It drops asset_type and timestamp/date and does not validate the underlying date against the key. It has no contract, roll-factor, or exchange-session fields. Only the FIRST raw schema was logged; do not claim every raw file has been audited.
Vendor documentation describes a date field from 2026-03-27 and timestamp before that. Futures daily bars use the official trading day, which can start the prior calendar evening. This session-label convention matters for publication joins.
The 48-market mapping file exists; zero-padded and alphanumeric CFTC codes must remain strings. Price aliases include 6E -> E6 and ZB -> US. This is a mapping proposal, not proof of historical economic identity.
The main cot-history tree has Legacy Futures Only compressed annual data, but no separately identified actual-publication calendar. The existing frozen extract includes net positions and report dates, not verified publication timestamps.
No new R2 read, price join, pilot, full-universe backtest, or randomized control was run.

## Blocking integrity findings
1. Tick and roll execution: prices are ratio back-adjusted continuous root series. The vendor describes multiplying prior prices by new-contract open / expiring-contract close. An exchange tick cannot simply be added to adjusted historical levels. If adjusted_price = factor * raw_price, adjusted_tick = factor * raw_tick. Need the historical factor, underlying contract, applicable tick schedule and roll dates. Cross-roll setups and outcomes also need a stated executable contract policy. Current public documentation guarantees the roll ledger only since September 2026; older cached search text mentions a contract calendar, but its current availability and historical coverage were NOT established. Do not infer factors from rounded OHLC differences.
2. Actual releases: existing pub_dates() assumes Friday, shifting to Monday if any US federal holiday occurs that week. This is not an actual-release calendar and does not handle shutdown catch-up schedules. The CFTC FAQ says no comprehensive historical release list is maintained; report dates are observation dates. Reconstruct from dated official releases/calendars with per-row provenance; unresolved periods must be excluded and counted, never quietly assigned Friday.
3. Point-in-time history: annual bulk files can reflect later corrections. Investigate vintages/revisions; do not label a revised-position test fully point-in-time without evidence.
4. Price integrity: checksum validation proves byte identity with the archive, not that different daily objects share a compatible adjustment basis. Vendor documentation describes rebasing; stored object vintage and revision consistency still need auditing.

## Locked signal rules from Michael
- Legacy Futures Only; each group's net = long minus short. Separate rolling 26-report indices including current report: 100*(net-min)/(max-min). Require 26 valid weekly observations; zero denominator -> unavailable. Inspect missing/duplicate weeks rather than silently taking 26 arbitrary records.
- Long: commercial >=95 AND large <=5 AND small <=5. Short: commercial <=5 AND large >=95 AND small >=95.
- Evaluate the latest publicly available report at completion of Day 2, when the two-bar setup becomes known. Join by actual publication timestamp and actual exchange-session close, not Tuesday or a calendar-date shortcut.
- Day 1 range high-low >= each of the previous three session ranges. Ties qualify.
- Day 2 is the next exchange trading session, strictly lower high AND strictly higher low.
- Live order only on the next two exchange sessions, Days 3 and 4. First qualifying breakout wins; expire after Day 4. Missing data is not a session to skip.
- Buy one tick above Day 1 high; sell one tick below Day 1 low, on the correct underlying tick grid.
- Long fill=max(open, threshold), short fill=min(open, threshold), when the threshold is reached. These are daily-bar model fills; liquidity/slippage beyond gaps remains unmeasured.
- Protective stop: long one tick below Day 1 low; short one tick above Day 1 high.
- COT qualifies at setup; do not add an unrequested fresh-extreme or continuing-COT-at-entry filter.
- No trailing-stop optimization.

## Predeclared measurement conventions
- ATR14 = arithmetic mean of the 14 true ranges strictly before entry, consistent with existing futures research. TR=max(high-low, abs(high-prev_close), abs(low-prev_close)); require adequate prior close and valid bars. Fixed at entry.
- Horizons 5/10/21/42 trading sessions; entry session counts as session 1.
- Nonnegative MFE and MAE magnitudes, divided by fixed pre-entry ATR.
- Report complete-horizon counts separately; do not truncate incomplete observations and call them full horizons. Also show a common 42-session-complete cohort for comparability.
- Report unrestricted path excursions separately from stop-limited excursions. Unrestricted means ignoring the protective stop, not including pre-entry prices.
- Intraday-entry adverse extreme can precede entry. Return lower/upper bounds rather than asserting the day's whole range occurred after entry.
- If entry and stop are both touched on an intraday-entry bar, flag sequencing ambiguity. A conservative scenario counts the stop; also report feasible bounds. Do not call a merely possible hit certain.
- On a later stop bar, exclude unproven favorable movement from the conservative pre-stop MFE; include only information forced before stop (such as the open). Report the upper bound separately. Opening gaps through stop execute at the opening price, not at the stop.
- Stop-hit rates: definite, possible, and conservative-scenario rates, with ambiguous counts.
- Means, medians, SD, 10th/25th/75th/90th/95th percentiles, and full trade-level distribution files. Split long/short and market; report pooled trade-weighted and market-equal summaries.
- Each unique setup is an event for excursion research. Flag overlapping events; this is not a portfolio with independent trades. Cluster inference to account for overlapping horizons and cross-market co-movement.
- Existing futures holdout instruction retained: develop before 2021-08-07, purge thereafter, sealed period from 2021-11-08 remains unopened for new analysis. Require development outcomes to end before the purge boundary.

## Pilot and expansion gates
Proposed pilot: ES, CL, GC, ZN, 6E (vendor E6), ZC. This choice spans asset classes and includes a symbol alias.
For each: verify code/root identity, units, tick history, exchange calendar, contract/roll record, duplicate bars, OHLC consistency, missing sessions, warm-up, and publication timestamps. Inspect manually reconstructed long/short triggers and synthetic boundary fixtures (ties, equality inside day, Day 4 vs Day 5, gaps, same-bar stops, delayed release).
Reject ambiguous mapping or missing metadata with an explicit reason. Do not count mini/micro duplicates as independent economic markets. Report the 48-list universe with separate duplicate-family sensitivity. Expand only after the pilot gates pass.
Contract policy must be recorded before results: preferably reconstruct executable contract-specific paths and rolls. If only adjusted series are available, any no-tick approximation is a different study and must not replace this exact request.

## Randomized controls (not yet executed)
Use a fixed recorded seed and 10,000 repetitions.
1. COT-conditioned random eligible entry sessions, matched within market, direction, calendar year and pre-entry volatility stratum. Match observed initial stop distance in ATR; execute at session open and apply the identical horizon/stop engine. Explicitly label the open-entry difference from the breakout execution.
2. WR4/inside-day breakout events without the COT filter, matched by market/direction/year and pre-entry volatility, to test whether COT adds information to the price trigger.
Keep all pools within audited development dates with complete outcome horizons. Report unmatched counts; never silently relax matching.
Report observed-minus-control means/medians and empirical tail probabilities, uncertainty clustered in time blocks long enough for 42-session overlap, and cross-market calendar-block sensitivity. Adjust across the four horizons and declared outcomes (Holm); retain raw probabilities too.
MFE alone is positive even for random entries. Include fixed-horizon signed close return, with/without the initial stop, as secondary diagnostics so large excursions are not mistaken for profitability. No claims of an edge from MFE alone.

## Concrete next step
Establish access to a historical contract/factor/roll dataset covering the development years, and build a source-backed publication calendar. A new run using the present loader would not resolve either missing input. Do not pay for new data, expose secrets, or silently relax the test. Once inputs exist, implement a standalone research/wr4_inside runner and execute the pilot before expansion.
