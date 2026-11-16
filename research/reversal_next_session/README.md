# Next-session reversal breakout: implementation and diagnostic pilot

Status: **PROVISIONAL diagnostic, not the validated mandatory-entry backtest.**

The exact requested entry engine is implemented and covered by deterministic tests.
The cached data allowed work to start locally; GitHub CLI authentication was not
needed for that. No weekly COT report code or rules were modified.

## Frozen strategy

- Core commercial index: 26 weekly Legacy Futures Only observations, using net
  commercial positions and the current report's min-max formula. No speculator filter.
- Long: index >=80 at setup close; higher high and lower close than the prior
  exchange session; buy at reversal high + one tick, on the next exchange session only.
- Short: index <=20; lower low and higher close; sell at reversal low - one tick,
  on the next exchange session only.
- Orders expire at the end of that next session. Missing bars cannot advance an
  order to a later session. Breaks of the opposite extreme do not trigger entry.
- Gaps through the trigger fill at the opening price. All fills assume no extra
  slippage or commissions; these are gross hypothetical outcomes, not real fills.
- ATR is the arithmetic mean of 14 completed true ranges before entry. Reversal
  session is included; entry session is excluded. ATR is fixed for every horizon.
- Forward returns are entry-to-close at 1,2,3,4,5,10 sessions; entry session is day 1.
- No stops or targets. Every qualifying setup is counted, including overlapping
  observations; these are event results, not a capital-constrained portfolio.
- MFE is exact given the assumed fill and valid daily bars. Intraday entry-day MAE
  has lower/upper bounds because the adverse extreme could precede entry. Gap-open
  fills have exact MAE. Both bounds are positive adverse-excursion magnitudes.

## What ran

Six pilot roots: ES, ZN, E6, CL, GC, ZC. Development outcomes end by 2021-08-06.
The purge period and reserved last-five-year outcome sample were not analyzed.
`output/diagnostic_summary.csv` separates longs, shorts and combined and supplies
counts, means and medians. `diagnostic_matched.csv` compares qualified trades with
the same reversal/breakout pattern outside the COT threshold, matched by root,
direction and year. Quarter-block bootstrap intervals resample quarters jointly
across markets; they are exploratory and unadjusted for the six horizons.

**Do not quote these as exact-rule strategy results:**

1. MarketParquet prices are ratio back-adjusted. This diagnostic adds a nominal
   exchange tick in adjusted price units. Historical adjusted tick sizes are not
   available in the extract, so this is not an exact historical one-tick test.
2. Development publication timestamps in the cached metadata are estimated.
   Holidays and known suspension entries are represented, but the dates/times
   have not all been independently verified. Actual release timing is required
   before promoting results. Setup-close as-of joins never use Tuesday directly.
3. Root-only bars have no delivery-month identifiers or historical roll factors.
   Cross-roll triggers and returns cannot be certified as executable contract P&L.
4. Missing exchange-calendar sessions are retained as missing, not compressed
   away. ATR warmups and forward windows crossing them are excluded. Counts thus
   fall with horizon; this is a selected complete-data sample, not all signals.
5. Exchange calendar alignment is from pandas_market_calendars, not a separately
   audited history of each exchange's session changes.

The runner without `--diagnostic-nominal-ticks` writes the audit and does not
calculate strategy returns. It cannot silently upgrade diagnostic results.

## Provenance and reproduction

COT reference commit: `8622f760ab6ef1f8fbc5effdfc37c2f801fa835e` in cot-history.
All eleven CFTC ZIP blobs match that main commit. `source_manifest.json` records
their Git hashes, the frozen pilot COT snapshot checksum, and a canonical checksum
of the existing six-market development price slice. No raw prices are committed.
`cot_pilot_snapshot.csv` was generated from those verified ZIPs, not HTML.

The standalone workflow `reversal-next-session-pilot.yml` uses existing R2 secrets,
verifies each object's stored SHA-256, and compares the fresh pilot price slice to
the cached slice before reproducing the diagnostic. It reads no holdout price files.
Its run log and artifacts are the authoritative remote-run evidence. `run.log` is
the earlier local diagnostic log, not evidence of GitHub Actions execution.

```bash
python research/reversal_next_session/test_engine.py
python research/reversal_next_session/fetch_pilot.py
python research/reversal_next_session/run_pilot.py \
  --prices /tmp/reversal_pilot_prices.csv.gz \
  --cot-snapshot research/reversal_next_session/cot_pilot_snapshot.csv \
  --releases research/reversal_next_session/release_metadata.csv \
  --diagnostic-nominal-ticks
```

Next required audit work: historical adjusted tick/roll mapping and official
publication timestamps. The vendor documents roll metadata only from September
2026 onward, so that alone cannot certify the development history. Do not expand
to all 48 markets or claim a trading edge before the pilot's input audit passes.

Sources checked 2026-11-16:
- https://marketparquet.com/data-quality (ratio adjustment, session and roll metadata)
- https://www.cmegroup.com/tools-information/lookups/advisories/clearing/15-407.html
  (Euro tick reduction effective 2016-01-11)
