# FUTURES DATA: where Michael's futures live (read this first for ANY futures task)

If Michael says "go to GitHub and find my futures", this is the place. Repo: `kidcharlema9ne/insider-buying-research` (private).

## Daily futures PRICES
- Source: MarketParquet. About 130 of the most active futures contracts as continuous series, **ratio back-adjusted** (scale-free; do not treat old prices as tradable levels). Mini and micro versions of one market (ES / MES, NQ / MNQ, ...) are near duplicates.
- Stored in: Michael's private Cloudflare R2 bucket `insider-research`, key `marketparquet/futures_daily/{YYYY-MM-DD}.parquet`, one file per trading day (4,906 files from 2007-12-31 to 2026-11-06 when last checked, Entry 20 and the 11 Nov 2026 runs).
- Columns: `symbol, open, high, low, close, volume` (plus a date or timestamp column). The trading day is the **file date** in the key (verified: bars carry the file date exactly). Each object has metadata `verified-sha256`; readers check it.
- Loaded into R2 by: workflow `.github/workflows/marketparquet-futures-daily.yml` (script `marketparquet_archive_transfer.py`). A nightly Tue-Sat 06:15 UTC sync exists, but the newest file seen on 11 Nov 2026 was still 2026-11-06 (the vendor lists nightly roll-forward under a paid add-on), so check the newest key before relying on recent data.
- **Access: the R2 keys exist ONLY as GitHub Actions secrets in this repo** (`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`). A chat session cannot read the bucket directly and usually cannot install the R2 library. Do not try. Do not copy the price data somewhere else and do not add new secrets without asking Michael.

## How to use it (the working method)
1. Run the reusable workflow `.github/workflows/futures-prices.yml` (manual run, or `uses:` it from another workflow in this repo). It runs `futures_data/fetch_futures_prices.py`, which stitches every daily file into ONE table `futures_prices.parquet` (columns `symbol, open, high, low, close, volume, file_date`) and uploads it as the artifact `futures_prices`.
2. Or copy the pattern of a research workflow: install `boto3 pyarrow pandas numpy`, run `python futures_data/fetch_futures_prices.py` with the three secrets as environment variables, then run your analysis script on `futures_prices.parquet` and commit the results on a branch.
3. Michael's repo rules: commit the script, report with a workflow run link, push to a **branch** (not main) unless he says otherwise, append an entry to `docs/SHARED_LOG.md`.
- Working examples: `research/outside_inside/` (outside-day / inside-day study, branch `claude/outside-inside-day-20261111`) and `research/cot_exit/` (COT exit tests, branch `claude/cot-commercial50-exit-20261110`).

## Markets
- Michael's COT report universe is 48 markets: `futures_data/report_universe_48_markets.csv` (columns `code, ibkr, name, latest_oi`). Map the `ibkr` symbol to the price symbol with this table, otherwise they are identical: 6A->A6, 6B->B6, 6C->AD, 6E->E6, 6J->J1, 6L->BR, 6M->MP, 6N->N6, 6S->E1, ZB->US, BRR->BTC, LBR->LBS (also `PRICE_ROOTS` in `cot-history/scripts/cot_report.py`). On the 11 Nov 2026 run all 48 had price series.
- `futures_sma20.json` in `cot-history` lists the price symbols that exist.

## COT (Commitments of Traders) data: a different repo
- `kidcharlema9ne/cot-history` (private): raw CFTC zips under `data/raw/` (for example `legacy_fut`), refreshed by GitHub Actions. Michael's plan is to run analysis from OTHER repos that read it. Do not change `scripts/cot_report.py` logic without his approval.
- `research/cot_exit/cot_weekly_full.csv.gz` here is a frozen snapshot (through the 2026-11-03 report) because this repo cannot read `cot-history` without a new access token.

## Standing research rules for futures work (Michael, 11 Nov 2026)
- Keep the last 5 years (outside-day dates from 2021-11-08 on) sealed while developing; develop in-sample (2007-12-31 to 2021-08-06, then a 3-month purge). Unseal only when Michael says so.
- Describe factors and rules in plain words, never letter codes (he does not remember what they stand for).

## Current series through 2026-11-20 (added 21 Nov 2026, branch claude/futures-48-coverage-20261121)
- READ THIS FILE FIRST for current prices: one table, `marketparquet/futures_current/futures_prices_current.parquet` in the R2 bucket (columns symbol, open, high, low, close, volume, file_date, rebase_factor, source). It holds the whole archive (2007-12-31 on) on ONE price level plus the newest days, for all 132 symbols; the original archive prefix is untouched. Built by workflow `futures-current-build.yml` (scripts `build_current_futures.py` then `stitch_current_futures.py`); checks in `futures_data/stitch_validation_report.md`.
- Why it exists: MarketParquet back-adjusts every earlier price by a ratio at each roll, so files stored before a roll sit on an old price level. The vendor's roll file (`/api/v1/meta/futures_rolls` with the API key: root, roll_date, ratio, detected_at; rolls since Sept 2026 only) gives the missing ratios. Rule: a stored file is multiplied by the ratio of every roll with roll_date >= its date that was detected AFTER the file was written to R2.
- Newest days: the vendor's public files 2026-11-16..20 verbatim. Days 2026-11-09..13 are not obtainable on the current plan (nightly updates are the paid Keep Current add-on): filled from free Yahoo bars for 31 markets (exact or offset-scaled, see `current_build_report.md`); the other 17 markets have a 5-session hole there (ZC, ZS, HO, HE, LE, GF, CL, BZ, CC, KC, 6M, DX, 6L, RB, VX, SR3, SR1).
- Rerun the workflow every few days: the vendor's free window is about a week. Coverage of all 48 markets: `futures_data/coverage_48_report.md`.
