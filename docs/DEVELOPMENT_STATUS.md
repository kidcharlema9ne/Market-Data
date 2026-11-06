# Development status

Updated November 6, 2026. The decision log and master specification govern research methodology. The tests below are local unless explicitly linked to a GitHub Actions run.

## A. SEC data integrity

- [x] Baseline snapshot reviewed and local suite passed (27 tests). Source archive scope is 2006 Q1 through 2026 Q3 (83 published quarters).
- [ ] Verify all archived ZIPs and the derived SQLite database in R2. [Archive run](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42288337419) was in progress at first check. The archive job writes ZIPs. The downstream SEC-to-prices workflow builds the database.
- [x] Implement exact quarter-name validation, database readback hashing, row reconciliation and indexed-column versus payload checks in `sec_archive_scope.py`, `build_historical_sec_database.py` and `validate_historical_candidates.py`. See the commit introducing this checkpoint. Live R2 validation remains pending.
- [ ] Reconcile archive filings to SEC indexes, including the unpublished-quarter gap. Quantify unmatched records and investigate source duplicate rows.
- [x] Normalize ISO and SEC day-month-name dates while preserving raw source values. Disclosure aggregation now carries form, transaction dates and original submission date when present. Local test suite passed (31 tests).
- [ ] Connect amendment handling to ingestion and opportunity construction. Verify original and corrected facts, filing dates, ambiguous amendments, duplicate prevention, insider identities, roles and ownership with real filing examples.

## B. Historical security master

- [x] Wire the existing dated resolver into `integrated_research_dataset.py` with explicit matched, ambiguous and unresolved evidence. Local integration regression covers expired symbols, ticker reuse by another issuer and overlapping IDs. Production mapping data, alias histories and terminal events still require validation.

- [ ] Add effective-dated issuer/security/identifier mappings and provenance. Cover renamed and reused tickers, share classes, mergers, delistings and ambiguous matches. Test each case. Static mapping support in `integrated_research_dataset.py` is scaffolding.

## C. Price-data integration

- [x] Implement calendar-aware D-051 entry, fixed ATR using 14 true ranges, optional D-052 filing-close reference, explicit bar gaps and six-calendar-month price-only outcomes in `price_outcomes.py`. Regression suite passed locally (29 tests). Both baselines use identical forward sessions beginning at the next open. The six-month endpoint is the last regular session on or before the six-month anniversary. Production must supply an independent exchange calendar. Live sample verification remains open.

- [ ] Revalidate the 251 free-year R2 partitions, schema, dates, OHLCV and adjustment conventions. Use the exchange session calendar to reject missing entry bars and mark forward-window gaps. Implement liquidity and corporate action handling or explicit flags. Audit D-051 entries, D-052 descriptive baselines and fixed pre-entry ATR against independently calculated real cases. The existing free-year smoke workflow uses the older entry rule.

## D. Benchmark and sector research

- [ ] Add effective-dated membership, exchange, sector and industry data contracts with provenance and missing-data flags. Implement D-009/D-025 selection, benchmark percentage and excess percentage returns, and reliable supplementary comparisons. Test point-in-time behavior.

## E. Insider research features

- [ ] Implement ownership significance, overlapping roles and CFO/CEO cohorts, earnings timing, cluster buying, and matured prior performance by insider across issuers. Add pre-entry liquidity, momentum, volatility, 52-week range and market/industry context. Test the information cutoff.
- [ ] Replace legacy seven-calendar-day filing grouping with D-048 purchase-date ten-session episodes and D-050 90-calendar-day campaigns. Preserve independent entries and multi-owner/multi-security membership. Campaign success criterion remains unspecified.

## F. Statistical analysis

- [ ] Verify metric-specific eligibility, success, denominators, descriptive distributions and missingness for all horizons. Add dependence-aware uncertainty and false-discovery controls, chronological development/validation separation, and bias regression checks. Existing `research_statistics.py` provides descriptive scaffolding.

## G. Findings report

- [ ] Wire `research_html_report.py` to actual integrated data. Cover all requested findings, diagnostics, assumptions, reproducibility metadata and data limitations. Review the generated real-data artifact.

## H. End-to-end validation

- [x] Commit the narrow real-data smoke workflow and trigger [run 42295939875](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42295939875). This run uses the pinned original GME filing, R2 price partitions and an independent XNYS calendar. Check its result before counting it as verified.
- [x] GitHub Actions passed integrated and historical outcomes tests on `35ff7dba43a3e47989d6dd2cd6bd4f8b8b89a015` ([integration](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42295756410), [outcomes](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42295756399)). The subsequent dated mapping and SEC date changes passed the 31-test suite locally.

- [ ] Connect verified SEC and free-year R2 inputs through identity, outcomes, research statistics and report generation. Publish report and diagnostics in Actions, verify representative calculations and record run/commit references. A database-only pass does not establish readiness.
- [ ] Update infrastructure and recovery instructions against live workflow behavior and storage state. Keep paid-data acquisition gated on separate authorization.

## Resume point

Check the archive run and downstream job, then verify R2 audit artifacts. Continue implementing independent price and identity work while long jobs run. The real-data report and successful end-to-end run are still outstanding.
