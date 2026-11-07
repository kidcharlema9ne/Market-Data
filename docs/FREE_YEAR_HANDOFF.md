# Free-year research handoff — November 7, 2026

The authoritative methodology remains in MASTER_SPECIFICATION.md and DECISION_LOG.md.

- Price transfer workflow: [.github/workflows/marketparquet-free-year.yml](../.github/workflows/marketparquet-free-year.yml). [Full-year transfer and rerun](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42205922843) verified 251 files from 2025-11-06 through 2026-11-05 in `insider-research` under `samples/marketparquet/stock_daily/`. The [initial job](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42205922843/job/127852411305) uploaded 248 and reused three. The [rerun job](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42205922843/job/127854257993) uploaded zero and verified all 251 existing files.
- Three-file workflow: [.github/workflows/marketparquet-r2-sample.yml](../.github/workflows/marketparquet-r2-sample.yml). [Successful transfer](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42202562039) and [successful rerun](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42202623792).
- [Smoke test workflow](../.github/workflows/free-year-research-test.yml) and [successful calculation log](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42207587157/job/127857992586). Four original SEC filings verified locally (GME, CRM, LULU, INTC). The GitHub runner received HTTP 403 from SEC, so the successful run used the verified acceptance timestamps and read the original stored OHLC directly from R2. It produced all 20 price-only horizons. The test uses the mean of 14 completed true ranges and counts entry as session one. These are smoke-test conventions. No dividends, benchmarks, or production qualification claims.
- [SEC source downloads](https://chatgpt.com/library?file_id=libfile_09d1f78dd370819183cced7f1250dc5d&account_id=personal) include SEC structured ZIPs for 2025 Q4 through 2026 Q3, the Q4 2026 index filtered to 24,186 Form 4/4-A entries through November 5, the four original submissions, and hashes. The quarterly ZIPs do not contain acceptance timestamps. Full-year raw submissions and their acceptance times remain outstanding.

## 2026 coverage checkpoint

The [candidate integration workflow](../.github/workflows/free-year-universe.yml) has a [successful run with HTML, candidate JSON and coverage JSON](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42299249032#artifacts). It joined 12,083 candidates to the free-year price archive and computed provisional entry and ATR for 6,915. The run uses D-051 from the repository decision log (next regular session open after the actual SEC filing date). Acceptance timestamps are unnecessary for historical entry under D-051. The filing-date close is a descriptive reference under D-052.

Filtering the existing candidate JSON by **2026 SEC filing date** gives 9,671 candidates, January 2 through September 30. The price archive extends through November 5, so later prices can complete some forward windows. The artifact has no October or November filing candidates.

| 2026 coverage | Count |
| --- | ---: |
| Provisional entry and ATR | 6,119 |
| Unmatched security | 2,443 |
| Missing price series | 697 |
| Missing or invalid entry ATR | 322 |
| Missing entry session bar | 90 |
| Complete 11-session price outcomes | 6,078 |
| Complete 21-session price outcomes | 6,043 |
| Complete 43-session price outcomes | 5,432 |
| Complete 64-session price outcomes | 4,512 |
| Complete six-month price outcomes | 2,386 |

These are pipeline counts. The candidate artifact uses provisional ticker joins, includes flagged purchases and has no verified historical security eligibility, benchmark returns, or dividend/terminal adjustments. It cannot establish returns for the approved discretionary common-stock universe. The October–November index lists forms, so transaction detail must be ingested and reconciled separately to extend filing coverage.

The 2,443 identity conflicts split into 606 with multiple issuer CIKs and 1,837 with one CIK and multiple filing security titles. A read-only diagnostic identified 416 of the latter as common-stock or common-share titles differing only in case, whitespace or straightforward par-value wording, with the stated class unchanged. The other 1,421 require closer title review. The diagnostic proposes review candidates and confers no eligibility. For example, TSM's ADR and Taiwan-listed common shares share a CIK but represent distinct securities.

The attached Word v0.10 and repository decision log reuse D-048 and D-049 for different decisions. Word v0.10 records the approved 63-session pullback and 21-session direction fields and provisional subgroup reporting. The repository uses those numbers for episodes and campaigns. Preserve both records and reconcile identifiers before the next specification update. The existing candidate artifact contains the earlier trailing-return fields and does not contain the new 63-session pullback measure.

## Next run

Validate effective-dated issuer/security mappings and discretionary common-stock eligibility for the January–September candidate cohort. Start with the wording-only review queue and keep multi-class, multi-issuer and non-common securities separate. In parallel, reconcile October through November 5 filings against the SEC index and obtain transaction-level source rows. Then rerun the 2026 integration, retain incomplete horizons, and report ATR and benchmark outcomes separately. The free sample is sufficient for this stage.
