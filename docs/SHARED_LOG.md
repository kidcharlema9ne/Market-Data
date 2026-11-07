# Shared log (ChatGPT + Claude)

This is the one place both assistants read and write. If it is not here, the other assistant cannot see it.

## Rules
1. At the start of a chat, read `AGENTS.md`, this file, `docs/DECISION_LOG.md` and `docs/MASTER_SPECIFICATION.md`.
2. Before ending a chat, add an entry at the bottom: date, who, what was done, results, **script path, branch, and workflow run link**.
3. Never quote a number without its script and run. A number with no script is a claim, not a finding (see Entry 3).
4. Mark every entry `CONFIRMED` (reproduced by running committed code), `REPORTED` (stated but not reproduced), or `PROVISIONAL` (known to use a different method than the approved one).
5. Do not edit old entries. Add a correction entry that points to the old one.

## Standing definitions (user's words, 7 Nov 2026)
- **Cluster window:** 15 trading sessions. Four or more distinct officers/directors must have **bought** (transaction date) inside the 15 completed sessions before entry, and their filings must already be public. A May purchase filed in August does not count. Entry = next regular open after the filing that brings the count to four. *Status: stated by the user in chat; not yet written into `DECISION_LOG.md` as a numbered decision.*
- Other rules unchanged: $3M average daily dollar volume floor, Form 4 code P, 10b5-1 and non-discretionary buys screened out, price-only 21-session hold (entry session = day one), results in the stock's fixed pre-entry ATR(14) with SPY restated on the same scale.

---

## Entry 1 | 7 Nov 2026 | ChatGPT | Original pilot findings | REPORTED
Source: `docs/MASTER_SPECIFICATION.md` section "What we have learned so far"; project doc "Mike research summary". Pilot: Jan-Sep 2026 filings, prices through 5 Nov 2026, 6,604 Form 4 purchase candidates, entry at next regular open after filing, price-only 21-session return in stock ATR. SPY/ONEQ/IWM on the same dates and ATR scale.

| Group | Entries | Stock | SPY | ONEQ | IWM |
|---|---:|---:|---:|---:|---:|
| All screened buys | 4,546 | +0.02 | +0.15 | +0.23 | +0.09 |
| CFO buys | 287 | -0.10 | +0.09 | +0.16 | +0.07 |
| CEO buys | 736 | -0.29 | +0.15 | +0.22 | +0.08 |
| Non-officer directors | 2,050 | +0.09 | +0.14 | +0.22 | +0.08 |
| Four distinct buyers | 101 | +0.79 | +0.05 | +0.05 | +0.18 |
| Five or more distinct buyers | 64 | +0.59 | +0.15 | +0.12 | +0.32 |
| First four-plus entry, CFO among buyers | 57 | +0.97 | +0.07 | +0.11 | +0.08 |
| First four-plus entry, no CFO identified | 80 | +0.59 | +0.13 | +0.12 | +0.27 |
| Stock down 0.5 to <2 ATR, SPY flat (equal weight per date) | 132 | +0.63 | +0.06 | +0.10 | -0.23 |
| Stock down 0.5 to <2 ATR, SPY up (equal weight per date) | 455 | +0.26 | +0.06 | -0.04 | -0.03 |
| Stock down 5+ ATR, SPY down (equal weight per date) | 211 | +0.48 | +0.50 | +0.75 | +0.46 |

Other ChatGPT results: four buyers 21-session excess over SPY +0.74 ATR (95% interval -0.38 to +1.95, raw p=0.196); five-plus +0.44 (-0.51 to +1.40); none passed Holm correction. CFO participation within first four-plus clusters +0.44 ATR more excess (interval -1.30 to +2.42, raw p=0.61). One and two buyers lagged all three references at all five horizons. Broad-market-down bands alone lagged all three references.

Liquid four-plus cluster ($3M floor): 91 trades, stock +0.53, SPY +0.01, excess +0.53, median +0.17, 51 of 91 positive. Below the floor: 46 trades, excess +0.88, median +0.09 (a few thin winners; removing the best under-$1M trade cut +1.56 to +0.69).
Price setup (liquid four-plus, SPY up >= 0.5 of its ATR, stock down 2 to 5 ATR over 15 sessions): 91 -> 39 -> 15 trades, excess +1.42 mean, +1.27 median.
CFO split inside the $3M group: price setup with CFO 7 trades (+1.29 stock, -0.38 SPY, +1.68 excess); price setup no identified CFO 8 trades (+1.31, +0.11, +1.20); outside setup with CFO 25 trades (+0.05, +0.01, +0.04); outside setup no identified CFO 51 trades (+0.55, +0.05, +0.50).
Purchase-size screen: no screen 91 (+0.53); >= $25k 65 (+0.47); >= $50k 43 (+0.76 mean, +0.43 median); >= $100k 23 (+0.42).
Entry timing: filing-day close vs next open can flip the sign of the typical result; next open is the investable rule (D-051).
Caveat on provenance: the script that generated the depth-band rows (132 / 455 / 211) was never committed (see Entry 3).

## Entry 2 | 7 Nov 2026 | Claude | Independent rebuild | PROVISIONAL
Branch `claude/identity-diagnostic-20261107` (scripts `run_current_rules.py`, `snooping_check.py`, `cost_scale.py`, `ownership_score.py`, `decline_regime_test.py`, `reconcile_pilot_rows.py`, `entry_timing_compare.py`). Rebuilt the cohort from the spec instead of running ChatGPT's code. **Its selector counted buyers by when the filing became public, with no purchase-date test**, so it differs from the intended rule above.
Reported then: liquid four-plus 96 trades, +0.47 ATR excess, per-trade SD 2.99, naive 95% range -0.13 to +1.07; price setup 15 trades +1.27 ATR (SD 2.56); ownership tagging no effect; entry at filing-day close has look-ahead; realistic round-trip cost 0.10-0.30 ATR (one ATR is about 5.3% of price for the middle liquid trade, about $1,334 on $25k); McLean-Pontiff decay 26% out of sample, 58% after publication.
Status: **do not rely on these numbers** until rerun on the Entry 4 cohort. The cost and ATR-size facts still broadly apply.

## Entry 3 | 7 Nov 2026 | ChatGPT (via user) | Reconciliation reply | REPORTED
Why depth-table numbers differed from Claude's: the 132 / 455 / 211 rows classify the stock and SPY over the 21 sessions before the **insider's purchase date** (anchor = first session on or after the latest transaction date; stock context = (Close[p-1] - Close[p-22]) / ATR14(p)). The 15-trade price setup uses the 15 sessions before the **investor entry date** ((Close[e-1] - Close[e-16]) / ATR14(e)). Neither applies the D-055 laggard condition. Two weightings exist with identical counts:
| Cell | Entries (dates) | Equal weight per date: stock / SPY | Equal weight per disclosure: stock / SPY |
|---|---|---|---|
| Down 0.5 to <2, SPY flat | 132 (49) | +0.63 / +0.06 | +0.57 / -0.04 |
| Down 0.5 to <2, SPY up | 455 (97) | +0.26 / +0.06 | +0.40 / -0.02 |
| Down 5+, SPY down | 211 (56) | +0.48 / +0.50 | +0.86 / +0.70 |
Final script that assembled and weighted this table: **not recovered** (status of the table: unreproducible).
Other answers: $50k screen = every one of four buyers needed a single qualifying filing >= $50,000, applied before counting buyers, so the 43 trades are not a subset of the 91. ATR14 = simple mean of the 14 true ranges before the anchor bar. Price setup uses the stock's own SPY regime ((SPY close[j-1] - close[j-16]) / SPY ATR14, >= 0.5). Recovered code committed to branch `recovery/nov7-cohort-provenance`: `research/recovered_20261107/{matrix_warm,wider,liquidity_tiers,purchase_size_screen}.py`.
Cluster selector rules (from `wider.py`): group by issuer CIK + ticker at filing + uppercased security title; sole-owner officer/director, no entity-like names; a filing counts only if at least one transaction date lies in [entry - 15 sessions, entry); trigger when the count crosses from below four to four or more; representative filing = prefer outcome_status ok, then earliest filing date and accession.

## Entry 4 | 7 Nov 2026 | Claude | ChatGPT's recovered code run unchanged | CONFIRMED
Branch `claude/run-chatgpt-code-unchanged-20261107`, workflow `.github/workflows/run-chatgpt-code-unchanged.yml`, run **42418333424** (earlier run 42418211582 failed to find matching inputs). The workflow first checks the four scripts are identical to `recovery/nov7-cohort-provenance` tip c4fb693. Inputs (Actions artifacts from ChatGPT's runs): original candidates `13578539048`, current candidates with 15-session dollar volume `13582058667`, benchmark bars `13577375610`, zero-buyer control file from `13581190927`. The scripts' own assertions passed on that combination only.
| Item | ChatGPT reported | Rerun |
|---|---|---|
| Completed four-plus trades | 137 | 137 |
| Liquid (>= $3M) | 91 | 91 |
| Liquid stock / SPY / excess | +0.53 / +0.01 / +0.53 | +0.5337 / +0.0080 / +0.5257 |
| Liquid median excess | +0.17 | +0.1651 |
| Below floor | 46 | 46 |
| $50k screen | 43; +0.60 / -0.16 / +0.76; median +0.43 | 43; +0.5978 / -0.1634 / +0.7613; median +0.4312 |
| Price setup (15 trades) | +1.42 mean, +1.27 median | CONFIRMED in Entry 5 self-check: n=15, +1.422 mean, +1.269 median |
Tier output (liquid, 21 sessions, excess): CFO + price setup 7 trades +1.677; CFO outside setup 25 trades +0.04; no CFO 59 trades +0.59. Mean excess without the single best trade: 91 liquid +0.3184 (full +0.5257); 14 price-setup trades +1.0593 (full +1.4332); 43 trades +0.6093 (full +0.7613). Window comparison on all four-plus entries (21-session excess vs SPY, no liquidity floor): 15-session window 137 completed trades +0.644; 30-session window 144 trades +0.331. Selector variants give 181 to 190 events depending on small definition changes (grid in the run log).

## Entry 5 | 7 Nov 2026 | Claude | Chance (data-snooping) test | CONFIRMED
Script `research/claude_tests/chance_test.py` (imports ChatGPT code unchanged), run **42419094111**. Self-check reproduced +1.422 / +1.269 (15 trades) and +1.677 (7 trades). Shuffled the excess among the 91 liquid trades (all, and within calendar week), repeated the best-slice hunt 5,000 times. Share of shuffles where chance matched the real best slice:
| Menu | Measure | Real best | All shuffled | Within-week |
|---|---|---|---|---|
| Small (12 slices) | best mean, n>=15 | +1.473 (no CFO, SPY>=0.5, n=23) | 25.5% | 58.3% |
| Small | best t, n>=8 | 2.14 (SPY>=0.5, decline 2-5, n=15) | 24.8% | 17.6% |
| Wide (702 slices) | best mean | +1.473 | 64.8% | 68.0% |
| Wide | best t | 2.74 (SPY>=0, decline>=2, n=25) | 28.1% | 5.3% |
Reading: a hunt over these slices finds results this good by luck often. CFO is not the driver (CFO + SPY up: 16 trades +0.94; no CFO + SPY up: 23 trades +1.47). Not evidence of no edge: 91 trades with SD near 3 ATR cannot detect a modest edge.

## Entry 6 | 7 Nov 2026 | Claude | Stand-alone SPY-rising test | CONFIRMED (single-question p is optimistic)
Script `research/claude_tests/spy_rising_test.py`, run **42419781207**. Question: after SPY rose >= 0.5 of its own ATR over the prior 15 sessions (D-055 cut-off), is excess higher? Rising: 39 trades, +1.25. Not rising: 52 trades, -0.02. Difference +1.27. Shuffle across trades: chance 1.8% of 20,000. Shuffle by entry date: 3.7%. Week-block bootstrap 95% range for the difference: +0.08 to +2.96. Neighbouring cut-offs (0, 0.25, 0.75, 1.0): rising group +1.03 to +1.25, so 0.5 is not a lucky spot.
Concentration: 23 entry dates, 12 calendar weeks. Four consecutive weeks (11 May - 7 Jun 2026; ISO weeks 20-23; 25 trades) hold about 93% of the total gain (about +1.8 ATR per trade); the other 14 rising-market trades average about +0.24. Without the best week (ISO week 22) the mean is +0.69; without the best trade +0.78; without the best three +0.45; median +0.56. 67% of rising-market trades positive vs 48% of the rest.
Caveat: the question was chosen after looking at this same data, so the 2-4% understates the real chance of luck; the best-of-menu figure in Entry 5 (about 25%) overstates it. Treat as an out-of-sample candidate, not an edge.

## Entry 7 | 7 Nov 2026 | Claude | Decisions recorded, pull request merged | CONFIRMED
Michael approved two rules in chat; both are now in `docs/DECISION_LOG.md` as D-057 (cluster window counts by purchase date, filing already public) and D-058 (decline and SPY regime measured before the entry date, per D-055). Pull request #1 (this log plus the `AGENTS.md` rule) was merged into `main` at Michael's request (commit 7e9a5c8).
Which code runs: ChatGPT's recovered selector (`research/recovered_20261107/wider.py` logic) is the cluster definition. Claude's `run_current_rules.py` is retired for that job and stays PROVISIONAL. Claude's overfitting, cost and entry-timing scripts are to be re-pointed to the 91-trade cohort. Planned next: one canonical selector module in the repo that all later tests import. Where code and spec disagree, the spec and decision log decide; if silent, Michael decides and the answer is recorded here.
Unapproved choices inside ChatGPT's selector, for Michael to review: sole-owner filings only (joint filings dropped), entity-like owner names excluded by a name pattern, one representative filing per cluster (prefers outcome_status ok, then earliest filing date and accession), filings before 1 Jan 2026 used only for building the count.

---

## Open items (as of Entry 7)
1. Add D-056 (extra buyers) to the repo and fix the D-048/D-049 numbering clash with Word v0.10. (Cluster window and entry-date anchor are now D-057 and D-058.)
2. Rerun the overfitting checks, costs and ownership tests from Entry 2 on the Entry 4 cohort (ChatGPT's selector).
3. List the top trades behind the +0.53 average (the single best trade appears worth about 19 ATR by arithmetic from printed means; verify).
4. Recover or retire the depth-table generator (132 / 455 / 211); do not quote those rows until reproduced with committed code.
5. Freeze rule (suggested: four-plus buyers by purchase date, 15 sessions, $3M floor, 21-session hold, SPY up >= 0.5 ATR) in a commit before any out-of-sample run. Keep the decline band and CFO as separate candidate factors.
6. Decision for Michael: buy the $79 MarketParquet archive (first confirm pre-2008 coverage for LEH and WM). No purchase authorized.
7. 578 price-contradicted identity matches; effective-dated security and benchmark mapping.
8. Optional: pull request of `claude/identity-diagnostic-20261107` and the two branches above into `main`; rewrite commit 4a4394a to remove the user's Gmail address from a run's user-agent (offered, not done).

## Entry 8 | 7 Nov 2026 | Claude | Canonical selector module + top trades behind +0.53 | CONFIRMED
Branch `claude/canonical-selector-20261107`, workflow `.github/workflows/canonical-selector-check.yml`, run **42421461026**. New: `research/canonical/cluster_selector.py` (`load_cohort()`), which imports ChatGPT's recovered selector unchanged (recovered scripts verified identical to `recovery/nov7-cohort-provenance` c4fb693 in the run) instead of re-implementing it, and `research/canonical/check_canonical.py`. Later tests should `from cluster_selector import load_cohort`. Same inputs as Entry 4 (artifacts 13578539048, 13581190927, 13582058667, 13577375610). The three unapproved selector choices from Entry 7 remain inside the code and are listed in the module docstring.
Reproduced: 137 completed, 91 liquid, liquid stock +0.5337 / SPY +0.0080 / excess +0.5257, median +0.1651.
Top trades (open-to-close 21 sessions, excess over SPY in the stock's ATR; total excess 47.84 ATR over 91 trades): 1 OTLK 28 May +19.19 (stock +18.86, SPY -0.33; 40.1% of the total); 2 XRAY 16 Jun +7.15; 3 NCLH 20 May +6.29; 4 SPG 6 Jan +6.05; 5 HROW 20 May +5.25; 6 GSHD 1 Jun +4.83; 7 GPGI 29 May +4.69; 8 RYAN 12 Jun +3.49; 9 ALT 6 Jan +2.87; 10 NSP 20 Mar +2.75. Top 10 = 130.8% of the total.
Mean excess without the top 1 / 3 / 5 / 10 trades: +0.318 / +0.173 / +0.046 / -0.182. Bottom five: RWT -4.21, CSGP -3.84, GRNT -3.83, UAMY -3.29, FSBC -2.56. 83 distinct tickers, 62 entry dates, 51 of 91 beat SPY. The earlier "about 19 ATR" estimate for the best trade is confirmed (+19.19).
Reading: the +0.53 average depends on a handful of winners; without the best five it is about zero. OTLK was not in the price setup (stock had risen about 6 ATR over the prior 15 sessions).
Next: re-point `snooping_check`, cost conversion and entry-timing scripts to `load_cohort`; then freeze the rule.

## Entry 9 | 7 Nov 2026 | Claude | Step 2A: outlier-robust and week-clustered checks on the 91 liquid trades | CONFIRMED
Script `research/canonical/robustness_check.py` (imports the canonical selector, ChatGPT's code unchanged), branch `claude/canonical-selector-20261107`, run **42421864891**. Self-check reproduced 91 trades, mean excess +0.5257 (stock +0.5337, SPY +0.0080). Independent units: 62 entry dates, 30 ISO weeks, 83 tickers. Week-block bootstrap, 10,000 draws, seed 20261107.
| Statistic (excess over SPY, ATR) | Value | 95% range | Share of draws <= 0 |
|---|---:|---|---:|
| Mean | +0.526 | -0.067 to +1.195 | 4.4% |
| Median | +0.165 | -0.151 to +0.588 | 17.5% |
| Trimmed mean (5% each tail) | +0.267 | -0.207 to +0.742 | 12.2% |
| Capped mean (each trade +-5 ATR) | +0.318 | -0.144 to +0.727 | 8.4% |
| Capped mean (+-3 ATR) | +0.199 | -0.192 to +0.537 | 15.3% |
Concentration: ISO week 2026-W22 alone holds 24.14 of the 47.84 total ATR (50%); weeks 22, 25, 20, 21 together hold about 102%. Dropping W22 leaves a mean of +0.269. Only 15 of 30 weeks have positive total excess. Sign test: 51 of 91 beat SPY, one-sided chance under a coin flip 14.7%.
Selector sensitivity (only the options exposed by the recovered `select()`; sole-owner and one-filing-per-cluster are hard-coded and were not varied): entity-name exclusion and same-title matching make no difference to the liquid cohort (91 trades, +0.526). The "previous" count rule gives 89 trades, +0.517. Keeping only the first cluster per issuer gives 81 trades, +0.640 (median +0.256). Capped means +0.30 to +0.41. The cohort is not fragile to these options.
Variants counted so far: 12 selector variants here, 5 summary statistics, 714 slices in Entry 5, 5 cut-offs in Entry 6.
Reading: the unadjusted mean is borderline (4.4% one-sided), and every outlier-robust version is weaker and its range includes zero. Not an edge; a candidate that needs older years. Steps 2B (costs) and 2C (entry timing) still to do.

## Entry 10 | 7 Nov 2026 | Claude | Step 2D: is a CEO among the four buyers? | CONFIRMED (exploratory question, asked after seeing the data)
Script `research/canonical/ceo_and_schema.py` (imports the canonical selector, ChatGPT's code unchanged), branch `claude/canonical-selector-20261107`, run **42422472063**. Self-check: buyer sets rebuilt from the selector's own data match its buyer count and CFO flag on 137 of 137 trades. CEO = any of the four buyers is an officer whose title matches CEO / chief executive officer. Caveat: directors and some officers have no title on file (81 of 91 trades have at least one untitled buyer), so "no identified CEO" can hide a CEO we cannot see.
| Group (91 liquid trades, 21 sessions) | n | dates / weeks | Stock | SPY | Excess | Median | Capped +-5 | Beat SPY |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| All | 91 | 62 / 30 | +0.534 | +0.008 | +0.526 | +0.165 | +0.318 | 51 |
| CEO among buyers | 47 | 38 / 24 | -0.179 | -0.066 | -0.113 | -0.157 | -0.118 | 22 |
| No identified CEO | 44 | 36 / 23 | +1.295 | +0.087 | +1.208 | +0.528 | +0.784 | 29 |
Difference (CEO minus no CEO), week-block bootstrap 10,000 draws seed 20261107: mean -1.321 (95% range -2.617 to -0.221, share of draws >= 0: 0.7%); median -0.685 (-1.398 to -0.137); capped mean -0.902 (-1.724 to -0.127).
CEO x CFO cells: CEO and CFO 24 trades +0.360; CEO no CFO 23 trades -0.607; CFO no CEO 8 trades +0.518; neither 36 trades +1.362 (SPY +0.142; median +0.643).
Reading: the whole cohort average sits in clusters without an identified CEO. Not a CFO effect (CEO+CFO beats CEO alone, but neither-CEO-nor-CFO is best). EXPLORATORY: this is one more question after several earlier ones, the group sizes are small, the title field is incomplete, and it has not been checked against the top-trade list or the four-week concentration. Needs the frozen-rule treatment on older years.
Ownership size (purchase vs existing holding): NOT computed. The candidate file (`free_year_candidates.json`) has `aggregate_dollars` and `prior_disclosures_by_owner` but no shares-owned-after field. The earlier PROVISIONAL `ownership_score.py` got `shares_after` from the SEC bulk database in R2 (needs R2 credentials in the workflow and a join by accession). Next step if wanted: join the 91 canonical trades to that database.

## Entry 11 | 7 Nov 2026 | Claude | Step 2E: chance test on "neither a CEO nor a CFO among the buyers" | CONFIRMED (exploratory; read the correction)
Script `research/canonical/chance_roles.py` (imports the canonical selector, ChatGPT's code unchanged; `add_roles` in `cluster_selector.py` is new and self-checked against the selector on 137 of 137 trades), branch `claude/canonical-selector-20261107`, run **42422870313**. Permutations shuffle outcomes only among trades of the same ISO week (10,000 draws, seed 20261107), so a week's market backdrop cannot create the result.
**Correction to the script text:** it labels Test 1 "the one pre-stated question". That is wrong. The group was picked after seeing the Entry 10 role table, so Test 1's chance figures are optimistic.
Group "neither CEO nor CFO": 36 trades, excess +1.362 (rest -0.021), difference +1.383 ATR, median +0.633 higher than rest. Chance figures: Test 1, same-week shuffle 3.7% (mean), 5.0% (capped +-5), 2.7% (median); shuffle-all 1.2%. Test 2, best of the 8 role groups that have >= 8 trades (the family examined so far): 40.1% chance a best group is at least this good. That family includes an 8-trade group, which inflates it; a version limited to groups of 20+ trades was NOT run.
Concentration: the group holds 102% of the cohort's total gain from 40% of trades. Six of the top 10 trades are in it (OTLK, XRAY, NCLH, SPG, GPGI, ALT); the other four are CEO+CFO (HROW, GSHD, NSP) and CFO-only (RYAN). Group minus rest without the top 1 / 3 / 5 trades: +0.87 / +0.52 / +0.44. Without week 2026-W22: +0.77. Hot weeks (20-23, 25): group +2.68 vs rest +0.78 (16 / 15 trades); all other weeks: +0.31 vs -0.32 (20 / 40 trades). The sign is the same in both regimes; the size is not.
Director count (second question, descriptive): pure directors (director, not officer) among the four buyers vs mean excess: 0 -> +0.40 (n=10); 1 -> -0.21 (14); 2 -> -0.23 (25); 3 -> +0.68 (21); 4 -> +2.89 (13, median +0.92); 5+ -> mixed, tiny groups. Not monotonic. Spearman +0.156, same-week chance 7.6%.
Reading: a candidate, not a result. The single-question figure is optimistic, the best-of-family figure is pessimistic, and the effect rides on a few trades from director-heavy clusters. Keep "no CEO / no CFO among buyers" as a separate candidate factor for the frozen-rule test on older years; do not size or trade on it.

## Entry 12 | 7 Nov 2026 | Claude | Candidate factors register created | CONFIRMED (documentation only)
Added `docs/CANDIDATES.md` (and a pointer in `AGENTS.md`) so both assistants see the same leads. Michael asked that **C3, no CEO and no CFO among the four buyers**, be recorded as a candidate for testing; it is there with its evidence (36 trades +1.362 vs rest -0.021; runs 42422472063 and 42422870313 cited in the register) and its caveats (exploratory, 102% of the cohort's gain, incomplete title data). The register also lists C1, C2, C4, C5, C6 (PROVISIONAL, retired cohort) and C7. No approved rule changed. Branch `claude/canonical-selector-20261107`, merged to `main` by pull request at Michael's request so ChatGPT can read it.

## Entry 13 | 7 Nov 2026 | Claude | Validation design and archive plan recorded | CONFIRMED (documentation only; no code run, no workflow run, no numbers)
Branch `claude/validation-design-20261107`. Changed files: `docs/DECISION_LOG.md` (D-059, D-060), `docs/CANDIDATES.md` (C8, C9 registered, not run). No script.
Decided with Michael in chat: (1) split by trade count, about two thirds development and one third sealed, three-month gap, cut date fixed from filing-only cluster counts by year before any returns are viewed (D-059); (2) the pilot and development years are open for exploration, and Michael will try many definitions on purpose (D-060); (3) look-back menu 5, 15, 21, 63, 126, 252 sessions, with the 15-session C2 kept as the reproduction row. Correction noted: D-055 says 21 sessions but C1/C2 were tested with 15.
Not yet done: the pre-registration file (menu, bands, SPY conditions, shuffle design, pass criteria); the cluster counts by year; Michael reading the MarketParquet refund and license terms; the purchase. No purchase is authorized.
Archive transfer plan (REPORTED from the vendor's documentation, nothing run): the existing workflow `.github/workflows/marketparquet-free-year.yml` already reads `MARKETPARQUET_API_KEY` and the three `R2_*` secrets and verifies each file with a hash. For the full history it needs one job per year, the ETF daily dataset added (SPY, ONEQ, IWM sit in the etf_* files), the 8 MB per-file cap checked against manifest sizes, and handling of the legacy timestamp column in daily files dated before 2026-03-27. After the purchase, call `/api/v1/assets` to confirm the key's plan, then check LEH and WM pre-2008 coverage. Vendor: https://marketparquet.com/faq and /documentation.
Why the archive comes before the long-window fits: the free sample starts 2025-11-06, so a 126-session stock look-back exists only for pilot entries from about May 2026. The earlier "3 weeks by 6 months, +1.88 ATR on 7 trades" note is REPORTED (no script in the repo) and is consistent with that limit.
Rough power arithmetic (my estimate, not a run): with a per-trade standard deviation near 3 ATR, a mean of +0.35 to +0.5 ATR needs roughly 160 to 330 independent trades at a bar of t = 2.1 (about three pre-declared sealed tests). Trades from the same weeks are not independent, so the true requirement is higher. The price-setup cell was about 16% of the pilot trades, so it will be thin even in a sealed third.
Next: Michael decides on purchase after reading refund and license terms; Claude then drafts the pre-registration and counts clusters by year.

## Entry 14 | 7 Nov 2026 | Claude | Filings-only cluster counting script written, NOT yet run | PROVISIONAL (self-test only; no results)
Branch `claude/validation-design-20261107`, commit 04aa6c0. New: `research/canonical/cluster_counts_by_year.py` and `.github/workflows/cluster-counts-by-year.yml`. Purpose: choose the sealed-period cut date (D-059) from counts of four-plus-buyer clusters by entry year, using SEC filings only and no returns. It reads the verified SEC candidate database in R2 (`sec/insider-transactions/derived/purchase_candidates.sqlite3`; no MarketParquet data needed) and applies the recovered selector's filters and its 15-session, purchase-date, already-public logic. It differs from the approved selector in that it uses an NYSE trading calendar, has no $3M liquidity floor and no ticker-to-security check, so its counts are an upper bound and the method is PROVISIONAL.
Self-test (4 synthetic cases: count reaches four, old purchase filed late is excluded, repeat buyer counts once, entity-named owner excluded) passed locally. No workflow run exists yet: GitHub will only dispatch a workflow that is on `main`, and this branch is not merged. Blocker: Michael's OK to merge the branch (or a pull request) into `main`.

## Entry 15 | 7 Nov 2026 | Claude | Four-buyer clusters by year, filings only; proposed cut date | PROVISIONAL (committed code ran, but the method differs from the approved selector)
Script `research/canonical/cluster_counts_by_year.py`, branch `main` (merged by pull requests #4 and #5 at Michael's OK), workflow `.github/workflows/cluster-counts-by-year.yml`, run **42426427553** (success; run 42426329913 failed with a KeyError and was fixed by using the repo's own `disclosure_opportunities` grouping). No prices and no returns were read. Differences from the approved selector: NYSE calendar, no $3M floor, no ticker-to-security check, every crossing from fewer than four to four-plus distinct buyers counted. Counts are therefore an upper bound on tradable trades. The workflow artifact could not be downloaded from this sandbox (network allowlist), so the figures below are copied from the run log.
Raw four-plus-buyer events by entry year (total 9,282 across 3,402 issuers): 2006 496; 2007 723; 2008 911; 2009 606; 2010 452; 2011 562; 2012 457; 2013 380; 2014 431; 2015 468; 2016 375; 2017 292; 2018 358; 2019 380; 2020 564; 2021 337; 2022 385; 2023 389; 2024 259; 2025 270; 2026 (partial) 187. Early-2006 may be slightly low because the archive starts with 2006 Q1 filings.
Reading: events are NOT even across years (2008 had 911, 2024 had 259), so a calendar split would have misplaced the one-third mark. By count, the latest third of events begins after entry date 2018-03-02 (latest half: after 2014-03-11; latest quarter: after 2020-03-09). Whether the $3M floor falls evenly across years is unknown until prices are loaded.
Proposed cut, for Michael to approve (D-059 says the cut date is fixed from these counts): development = entries through about 2017-11-30; gap = 2017-12-01 to 2018-03-02 (about three months, entries dropped from both sides); sealed = entries after 2018-03-02 through 2025 (about 8 years), which contains the Q4 2018 sell-off, the 2020 crash and the 2022 bear market. Sealed run still happens once, with 1 to 3 hypotheses declared in advance.
Sanity check: the 2026 partial-year count (187) is above the pilot's 137 completed trades, as expected since the pilot required complete outcomes and the $3M floor.
Next: Michael approves or changes the cut; he reads the MarketParquet refund and license terms and decides on the purchase; Claude drafts the pre-registration.
