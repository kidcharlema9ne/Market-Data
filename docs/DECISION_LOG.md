# Decision log

## Original v0.9 record

# 18. Numbered decision log — preserved history

| ID    | Topic                                   | Status                            | Decision                                                                                                                                                                                                                   |
|-------|-----------------------------------------|-----------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| D-001 | Research objective and primary unit     | Approved                          | Individual publicly disclosed investor opportunities are primary; episodes are supplementary.                                                                                                                              |
| D-002 | US security universe                    | Approved                          | NYSE, Nasdaq, NYSE American common stocks; all market caps; OTC excluded initially; specified non-common securities excluded.                                                                                              |
| D-003 | Qualifying purchases                    | Approved in principle             | Discretionary open-market insider purchases; exclude grants, exercises, gifts, identifiable automatic/10b5-1 purchases.                                                                                                    |
| D-004 | Investor entry timing                   | Approved                          | Entry at opening price of first eligible session after public disclosure. Late-disclosure case approved: Monday purchase disclosed Friday → entry at next eligible session's open.                                         |
| D-005 | Performance measures                    | Approved                          | Maximum appreciation, maximum adverse excursion, and ending return shown separately; no composite.                                                                                                                         |
| D-006 | ATR methodology                         | Approved                          | ATR(14) from 14 completed sessions before entry; fixed at entry.                                                                                                                                                           |
| D-007 | Horizons                                | Approved                          | 15/30/60/90 calendar days converted to 11/21/43/64 sessions, plus six calendar months.                                                                                                                                     |
| D-008 | Historical depth                        | Approved principle                | Go back as far as reliable data permit; preserve delisted and incomplete observations.                                                                                                                                     |
| D-009 | Benchmarks                              | Approved core mapping             | NYSE S&P 500/SPY; Nasdaq Composite/ONEQ except S&P 500 constituents; NYSE American Russell 2000/IWM; QQQ secondary.                                                                                                        |
| D-010 | Insider career history                  | Approved                          | Track individuals across companies, roles, and careers.                                                                                                                                                                    |
| D-011 | Purchase size/ownership significance    | Approved                          | Dollar value and purchase relative to existing company-stock ownership; not personal net worth.                                                                                                                            |
| D-012 | Filing amendments                       | Approved principles               | Use corrected facts, preserve history, avoid double-counting and look-ahead.                                                                                                                                               |
| D-013 | Five-session episode gap                | Approved 2026-11-05               | Same insider/company/security purchases remain in an episode if gap is no more than five trading sessions; greater gap starts a new episode.                                                                               |
| D-014 | Same-day multiple transactions          | Approved 2026-11-05               | Aggregate same-day same-disclosure purchases using share-weighted average transaction price; one analytical opportunity/path.                                                                                              |
| D-015 | Multi-day transactions in one Form 4    | Approved 2026-11-06               | Preserve each dated transaction; aggregate the filing’s insider transaction price using share weights and aggregate dollars; one public disclosure opportunity, investor entry, and performance path.                      |
| D-016 | Episode-level success reporting         | Approved 2026-11-06               | Report opportunity-level and episode-level success. Count each episode once; an episode meets a criterion if at least one constituent opportunity meets it.                                                                |
| D-017 | Episode-level insider purchase price    | Approved 2026-11-06               | Do not calculate a synthetic average insider purchase price across different purchase dates in an episode; preserve actual transaction prices and dollar values.                                                           |
| D-018 | ATR-based stock success measurement     | Approved principle 2026-11-06     | Use ATR units as the primary stock-performance and stock-based success measure; retain stock percentages as supplementary. Benchmark returns and excess returns remain percentages. Exact success definitions remain open. |
| D-019 | Corporate actions and terminal outcomes | Approved 2026-11-06               | Use actual cash/stock/mixed acquisition consideration, bankruptcy recoveries, and final realizable delisting values where available; unknown outcomes remain incomplete.                                                   |
| D-020 | Purchase significance                   | Approved core approach 2026-11-06 | Emphasize purchase dollar value and its relation to estimated pre-purchase company-stock ownership value; share count is not a headline measure. Ownership denominator details remain open.                                |
| D-021 | Success measures                        | Approved                          | Separate maximum appreciation and ending return success rates; MAE alongside each; working \>0 ATR thresholds, zero convention open.                                                                                       |
| D-022 | Ownership denominator                   | Approved                          | Actual attributable beneficial common shares before purchase; options/unvested awards excluded; missing flagged.                                                                                                           |
| D-023 | Dependence                              | Approved                          | Preserve opportunities; cluster-aware bootstrap with episode, company, and calendar-time dependence as appropriate.                                                                                                        |
| D-024 | Disclosure timestamp                    | Approved                          | EDGAR acceptance proxy; first eligible opening; documented exceptions.                                                                                                                                                     |
| D-025 | Benchmark membership                    | Approved                          | Point-in-time membership and exchange; fixed over horizon; uncertainty flagged.                                                                                                                                            |
| D-026 | Indirect purchases                      | Approved                          | Include attributable common-share purchases; exclude derivatives; flag ambiguous cases.                                                                                                                                    |
| D-027 | Acquisition proceeds                    | Approved                          | Cash held at zero interest; follow replacement shares; mixed consideration tracked.                                                                                                                                        |
| D-028 | Amendments                              | Approved                          | Preserve history, correct facts, prevent double counting, preserve point-in-time knowledge.                                                                                                                                |
| D-029 | Dividend treatment                      | Approved conditional              | Cash dividends without reinvestment for ending returns if reliable; price-only excursions; user prefers omission if free-data burden prohibitive, subject to explicit confirmation.                                        |
| D-030 | Ownership reconstruction                | Approved                          | Use contemporaneous filing evidence; mark unreliable ratios missing; verified zero means new position.                                                                                                                     |
| D-031 | Bootstrap method                        | Approved                          | Cluster-aware episode bootstrap with broader company/time adjustments; flag insufficient independent samples.                                                                                                              |
| D-032 | Primary research focus                  | Approved clarification            | Assess predictive performance of insider purchases across groups; scanner eventual goal; individual career analysis supplementary.                                                                                         |
| D-033 | Multiple comparisons                    | Approved                          | False-discovery-rate adjustment for multiple tested hypotheses; preserve raw statistics.                                                                                                                                   |
| D-034 | Data feasibility                        | Approved process                  | Small free-source feasibility assessment before implementation; consider paid data if needed; purchase requires approval.                                                                                                  |
| D-035 | Incomplete observations                 | Approved                          | Metric- and horizon-specific eligibility; report missing counts; never invent outcomes.                                                                                                                                    |
| D-036 | Insider role groups                     | Approved                          | Separate CEO, CFO, other executives, independent/other directors, and 10% owners; preserve overlapping roles; combined reference sample.                                                                                   |
| D-037 | Supplementary benchmarks                | Approved                          | Primary market benchmark unchanged; add sector and industry comparisons; matched-stock controls optional.                                                                                                                  |
| D-038 | Entry-time conditions                   | Approved                          | Record specified historical momentum, range position, volatility, liquidity, size, and market/industry context; no filters.                                                                                                |
| D-039 | Earnings timing                         | Approved                          | Study actual insider purchase dates before/after earnings; preserve separate disclosure and investor-entry timing; no earnings exclusion.                                                                                  |
| D-040 | Purchase / market cap ratio             | Declined                          | Do not add purchase value divided by company market capitalization as a required measure.                                                                                                                                  |
| D-041 | Out-of-sample validation                | Approved                          | Chronological development and later untouched validation, subject to historical data feasibility; no tuning on validation results.                                                                                         |
| D-042 | Close-only contingency                  | Approved conditional preference   | Preserve OHLCV as primary; if unavailable, investigate separately labeled close-only analysis, with entry convention and estimator still requiring approval.                                                               |
| D-043 | ATR proxy 1.6 multiplier                | Proposed / unresolved             | User suggested 1.6; conversion must distinguish close-to-close standard deviation from mean absolute change, and be empirically calibrated before adoption.                                                                |
| D-044 | TradeStation feasibility                | Planned test                      | User will check discontinued-symbol lookup in TradeStation desktop; no historical coverage conclusion yet.                                                                                                                 |

# 19. Open issues — not approved as methodology changes

- Actual historical source coverage, cost, and feasibility, including delisted securities, SEC filing timestamps, dividends, and point-in-time index membership; paid data selection remains open.

- Operational zero-return convention and any additional appreciation success thresholds; do not infer approval from working \>0 ATR definitions.

- Exact implementation of clustered bootstrap for company/calendar-time dependence, effective sample size diagnostics, and group-level testing design; principle approved.

- Unusual corporate-action mechanics (contingent/fractional consideration, bankruptcy distribution timing, delisting terminal values), timestamp anomalies, and amended filings with newly revealed transactions.

- Historical industry classification and difficult indirect/joint ownership attribution; explicit missing-data flags required.

- Data infrastructure, programming, bulk downloads, and paid purchases are not authorized.

Historical earnings announcement timestamps and dates, historical sector/industry benchmarks, role-classification precedence for mutually exclusive views, and sufficient history for proposed lookbacks.

Exact out-of-sample date split, overlap-aware separation of training/validation observations, and validation protocol after feasibility results.

# 21. November 6, 2026 continuation — data-source research and implementation authorization

## Approved / explicitly authorized

- D-045: User authorizes beginning initial implementation without historical price data, using a provider-agnostic architecture. Authorization covers project structure, schemas, SEC Form 4 ingestion design, historical security identification, calculation specifications and small local tests. It does not authorize paid purchases, mass historical downloads, or large cloud deployments.

- D-046: Preserve approved investor-entry-at-eligible-open and full daily OHLCV/observed ATR as primary methodology. Do not activate close-only fallback merely for convenience.

- D-047: User prefers a low-maintenance automated system, minimal manual downloads and inexpensive infrastructure; GitHub for code, separate object storage for historical data are proposed architecture, not yet selected services.

## Research findings — not approvals or verified guarantees

- WIKI Prices: approximately 3,199 symbols, OHLCV through March 2018, some delisted; incomplete historical universe and no 2018–2026 coverage. Kaggle Huge Stock Market Dataset: approximately 8,539 stock/ETF files through November 2017; systematic delisted inclusion and point-in-time universe not established. Neither recommended as sole final universe without an audit.

- MarketParquet advertises a \$79 one-time full historical daily OHLCV archive beginning 2000, with delisted stocks, and a free recent-year sample. Public documentation describes one Parquet file per trading date, with date/timestamp, symbol, asset_type, open/high/low/close/volume; split adjusted, dividends not included. Historical 2008 LEH and Washington Mutual WM original common shares and historical issuer mapping have NOT been independently verified.

- MarketParquet documents bulk date-range manifest API, including daily stock files; optional \$15/month updates. Vendor advertises thousands of delisted stocks, but the claim is not an independent completeness audit. Historical ticker reuse (Washington Mutual WM versus current Waste Management WM) illustrates need for point-in-time security mapping, not date-only matching.

- TradeStation desktop discontinued-symbol lookup: Lehman LEH not found in prior user search; WAMUQ Washington Mutual Incorporated appears but historical bars were still loading; availability of pre-failure NYSE daily history unconfirmed. TradeStation not presently selected as main historical source.

- No published MarketParquet telephone opening hours or verified support phone number found in publicly checked website/documentation. Do not claim a specific opening time.

## Unresolved verification and implementation choices

- Before purchase: confirm pre-September-2008 daily OHLCV for original Lehman Brothers LEH and Washington Mutual WM, and issuer/ticker identity mapping; obtain response through vendor contact if possible. No purchase authorized.

- Choose storage host, GitHub integration and credentials strategy after user approval; do not commit secrets or paid licensed raw data to a public repository.

- Design importer for daily date-partitioned Parquet with date/timestamp schema normalization and independent security master. Plan reconciliation of CIK, filing issuer, ticker, security class, exchange, listing dates and corporate actions; flag ambiguous matches.

- Design reproducible SEC Form 4 ingestion with acceptance timestamp and individual purchase/disclosure opportunity, retaining same-day weighted aggregations and five-session episodes per existing rules.

- Design modular OHLCV/ATR and benchmark calculations; postpone full historical execution until data validated. Any code or tests must not silently redefine approved metrics.

- Historical source selection, archive completeness, dividends/corporate actions, earnings data, point-in-time benchmarks and sample coverage remain unresolved.

## Infrastructure decisions approved November 6, 2026

- I-001 — Use private Cloudflare R2 Standard storage with the intended bucket `insider-research` and Parquet historical price files.
- I-002 — Plan a one-time acquisition of approximately 20 years of daily OHLCV, including delisted securities and historical identifiers where available. Provider, coverage, size, and cost remain open.
- I-003 — The historical archive may be frozen after the study. The ongoing SEC scanner is separate and fetches its own current price and volume information.
- I-004 — Use Python and GitHub Actions for automation and Pushover for scanner notifications. Google Drive is a candidate for human-readable reports.
- I-005 — Maintain authoritative documentation in Git. Log explicit approvals and preserve prior versions through descriptive commits.
- I-006 — Restrict R2 credentials to the project bucket and store them in GitHub Actions secrets. Verify with a small temporary object. Paid services, data purchases, and bulk downloads await separate approval.

## November 6, 2026 — approved episode/campaign revisions

- **D-048 (approved):** Replace the five-trading-session buying-episode gap with **10 trading sessions** for consecutive qualifying purchases by the same insider in the same security. Prior five-session decision is superseded, not erased.
- **D-049 (approved in principle):** Introduce a **separate three-month (~90-calendar-day) signal-campaign grouping**, alongside disclosure-level opportunities and 10-session episodes, to study repeated buying and campaign profitability without inflating evidence of insider skill from correlated entries. Do not collapse individual disclosures or episode observations. User also used the phrase 'three-month trading session separation'; 90 trading sessions is longer than three months, so the exact calendar/trading-day operational threshold is **pending confirmation**. Campaign-level success aggregation remains unresolved; preserve existing per-disclosure and per-episode rules until separately specified.

- **D-050 (approved clarification):** Signal-campaign separation is definitively **90 calendar days**, not 90 trading sessions. Consecutive qualifying purchases by the same insider in the same security with gaps of 90 calendar days or fewer remain in one campaign; gaps greater than 90 calendar days begin a new campaign. Supersedes the unresolved threshold in D-049. Campaign success aggregation remains open.

- **D-051 (approved November 6, 2026):** Historical investor entry is the **next regular trading session's open after the actual SEC Form 4/4-A filing date**, obtained from the SEC quarterly insider-transactions bulk dataset. This replaces the earlier acceptance-time-based same-day/next-day entry logic **for the historical study**. No acceptance timestamp lookup is required for historical entry. Do not substitute transaction date, presumed two-day reporting lag, or quarterly ZIP publication date for the actual filing date. Verify dataset coverage/fields on a sample before large-scale ingestion; retain all other approved outcome and eligibility rules.

- **D-052 (approved November 6, 2026):** In addition to the primary tradable next-session-open outcomes (D-051), calculate filing-date-close-based reference returns over corresponding research horizons and the filing-close-to-next-open gap. Compare the two return series explicitly. Filing-date close is a descriptive benchmark and may precede actual public disclosure; do not present it as necessarily executable. Preserve approved ATR and percentage outcome reporting and document horizon alignment.


## Approved — November 6, 2026: Live scanner vs daily prices

- Detect and notify qualifying SEC Form 4 purchase disclosures promptly, independent of the stock-price data refresh schedule.
- Do not delay Pushover filing alerts when the latest available daily OHLCV bar is one or more sessions old. Always label the last completed price session and never present stale prices as current quotes.
- Update historical research outcomes and ATR-normalized statistics when newly completed daily bars become available. Real-time market-price subscriptions are not required for the initial research/scanner architecture.
- A live/premarket quote or intraday price-based alert is an optional later enhancement, not a prerequisite for initial SEC filing alerts.
- Preserve the previously approved primary next-session-open historical entry methodology; an alert is not an execution fill.


## Research hypotheses proposed — November 6, 2026 (not established findings)

- Test whether CFO open-market purchases predict superior forward outcomes relative to CEO, COO/president, director, and other-officer purchases. Role classification must reflect the insider's role at the filing date, allow multiple roles, and distinguish officer/director overlap.
- Independently test prior price weakness versus strength, including trailing 21/63/126-session returns measured in ATRs, relative returns versus market/sector, and distance from 52-week high/low.
- Explicitly test role × prior-trend interactions, especially CFO buying dips versus CFO buying strength and corresponding CEO comparisons. Do not presuppose dip buying wins.
- Compare win rates, maximum favorable excursion, maximum adverse excursion, end returns, benchmark-relative returns, distributions, sample sizes and uncertainty at existing approved horizons. Preserve ATR-first presentation.
- Control for firm size, liquidity, sector, market regime, calendar era, and repeated observations; assess out-of-sample robustness and post-Sarbanes–Oxley subperiods. Distinguish evidence for contrarian purchase frequency from evidence of superior subsequent performance.
- Literature motivation: Wang/Shin/Francis (2012), CFO purchases exceeded CEO purchases by about five percentage points in 12-month abnormal return during 1992–2002; Knewtson/Nofsinger (2014) reports CFO advantage attenuated post-SOX; Lakonishok/Lee (2001) finds insiders contrarian with incremental predictive information. These are hypotheses to validate in our own 2006 onward universe, not accepted findings.


## November 7, 2026 — benchmark display and entry context

- **D-053 (approved):** Whenever reporting a stock ATR return, show the relevant named entry-date benchmark beside it over the same dates, including subgroup and progress summaries. Use the stock’s fixed pre-entry ATR to put both on a common scale, and display paired excess. Retain percentage inputs and excess for audit. Flag missing classifications or prices beside the stock return. The earlier percentage-only presentation in D-018 is superseded for display. Benchmark selection remains governed by D-009 and D-025.
- **D-054 (previously approved measurements carried forward):** Record the 63-session pullback depth and signed 21-session price change in stock ATR units at investor entry, as specified in Word v0.10 D-048. This repository number avoids the existing episode decision’s D-048. The Word D-049 reporting bands and any down-versus-up subgroup comparisons remain open for discussion before implementation.

- **D-055 (approved November 7, 2026):** Compare pre-entry falling stocks that lagged their assigned benchmark, stratified by SPY’s 21-session regime. Use the same 21 close-to-close intervals ending before entry. SPY is flat strictly inside ±0.5 of its own pre-entry ATR(14), down at or below −0.5, and up at or above +0.5. Report forward outcomes and applicable benchmarks under D-053. This authorizes the first regime test. Additional pullback-depth, role, and cluster splits remain proposals.


## November 7, 2026 — pilot evidence and future scoring proposal

- Added the [pilot findings](MASTER_SPECIFICATION.md#what-we-have-learned-so-far) to the master specification. The user asked to retain evidence that could eventually inform a score. Buyer count, mild stock decline in a flat or rising market, and CFO participation within four-plus clusters are candidates for validation. A combined score, weights, and scanner rules remain proposals. The current reporting methodology continues to present the underlying measures separately.


## November 7, 2026 — cluster window and context anchor (user decisions, recorded from chat)

Numbering note: D-056 (extra buyers after the count reaches four) exists in Word v0.10 but is not yet in this repository. These two entries use D-057 and D-058 to avoid reusing it; reconcile numbering when D-056 is added.

- **D-057 (approved by Michael, November 7, 2026):** The four-plus buyer cluster counts a distinct officer or director only if at least one of their **purchase (transaction) dates** falls inside the 15 completed trading sessions before the investor entry open **and** their filing is already public. A purchase made earlier and filed late does not count. Entry is the next regular open after the filing that brings the count to four. This matches the logic in ChatGPT's recovered selector (`research/recovered_20261107/wider.py`) and supersedes the filing-date-only counting used in Claude's earlier rebuild (`run_current_rules.py`), which is marked provisional. The recovered selector's undocumented choices (sole-owner filings only, entity-like names excluded, one representative filing per cluster) are listed in `docs/SHARED_LOG.md` for review and are not yet approved.
- **D-058 (approved by Michael, November 7, 2026):** Stock decline and SPY regime used as study strata are measured over the completed sessions ending **before the investor entry date**, the information available when placing the trade, not before the insider's purchase date. This is consistent with D-055. The earlier depth-band table (132 / 455 / 211) anchored on the purchase date and is therefore not a D-055 test; it remains unreproduced because its generating script was never committed.

## November 7, 2026 - validation design (approved by Michael in chat)

Numbering note: D-056 is still missing from this repository (see the note above D-057); these entries continue with D-059 and D-060.

- **D-059 (approved by Michael, November 7, 2026):** Split by trade count, not by calendar. About two thirds of qualifying trades (the earlier years, expected to be roughly 2006 to 2018/2019) are the development sample and the most recent third (expected to be roughly 2019/2020 to 2025) is sealed, with a gap of about three months at the boundary so overlapping look-back and hold windows do not straddle it. The exact cut date is set from counts of qualifying four-buyer clusters by year, using filings only, before any returns are viewed. The sealed period is run once, with one to three hypotheses declared in advance, and nothing is changed afterward. This is the first concrete split under D-041. Usable history starts in 2006 (the SEC bulk Form 4 archive) because the pre-August-2002 monthly filing regime and the paper-to-electronic transition make earlier filings incomparable.
- **D-060 (approved by Michael, November 7, 2026):** The 2026 pilot and the development years are open for exploration, including many decline, drawdown and look-back definitions. Michael does this on purpose to build hypotheses. Every variant tried is added to the tally of questions asked (`docs/CANDIDATES.md`) and shuffle tests report best-of-menu chances. The look-back menu is 5, 15, 21, 63, 126 and 252 completed sessions. D-055 says 21 sessions, but the tests run so far (C1, C2, `research/claude_tests/spy_rising_test.py`) used 15; this is recorded as a correction, not a change, and C2 stays as a 15-session reference row so the pilot result can be reproduced.

- **D-061 (approved by Michael as PRELIMINARY, November 7, 2026):** Preliminary sealed-period cut under D-059. Development = entries through 2019-09-30; gap = 2019-10-01 to 2019-12-31 (entries dropped from both sides); sealed = entries 2020-01-01 through 2025-12-31. The 2026 pilot is in-sample and is never part of the sealed set. Basis: filing-only cluster counts by entry year (SHARED_LOG Entry 15, run 42426427553), about 24% of 2006-2025 raw events fall in the sealed period. Condition: once MarketParquet prices are loaded, apply the $3M liquidity floor and count liquid events per period, WITHOUT reading any returns. If the sealed period holds less than 20% or more than 30% of 2006-2025 liquid events, move the cut to the nearest quarter boundary that brings it into that range. The decision is made from counts only and is then final. The sealed run is still done once, with 1 to 3 hypotheses declared in advance.
