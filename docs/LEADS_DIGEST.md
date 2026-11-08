# Leads digest (read this first; the log is for going deeper)

Purpose: one page so a new chat does not have to read the 600-line `docs/SHARED_LOG.md`. Every line points to the log entry that holds the script and run link. This page repeats numbers from the log and creates none; if it disagrees with the log, the log governs. Last refreshed: 8 Nov 2026, after Entry 67.

## How to read the log cheaply
- Latest entries only: `tail -n 40 docs/SHARED_LOG.md`, or `grep -n '^## Entry' docs/SHARED_LOG.md | tail -5`.
- One entry: `awk '/^## Entry 52 /{p=1} p{print} /^## Entry 53 /{exit}' docs/SHARED_LOG.md`.
- Deep dives by topic: survivorship = Entries 38, 40, 44, 49, 65; costs = 45; stops = 62, 63; sizing = 64; score = 51; deep fall = 36, 42, 49, 52, 66, 67; Nasdaq lag = 37, 39, 41; basing = 59-61.

## Base rule (Michael's words, D-064/065/066/068)
Four or more distinct officers/directors bought (purchase date) within 15 sessions before entry, all filed; $3M daily dollar volume; enter next open after the filing that makes four; 21-session price-only hold; results in ATR with SPY beside them. Development 2006-2020 n=1,372: +0.154 ATR over SPY gross, about zero after assumed costs (Entries 28, 45). A lead, not an edge. Sealed years 2021-2025 stay closed; Michael is not ready.

## Leads (all post hoc / exploratory; none is an edge)
| Lead | What | Headline (excess over SPY, ATR) | Status | Entries |
|---|---|---|---|---|
| C8 / D1 / F | Deep 12-month fall. D1 = fell-most fifth (cut -15.3 ATR) = the fixed rule F: down 15+ ATR over 12 months | D1 +0.593 (n=255); F +0.599 (n=269, ~1.5 a month); 2011-2020 +0.565 (n=175); pay sits in falls of 50%+ | Lead; survivorship and costs unresolved | 36, 38, 42, 44, 45, 49, 52, 67 |
| C16 / N | Nasdaq lagging SPY over 63 sessions (lowest fifth) | +0.60; one-month effect; no mechanism | Lead; weaker in 2011-2020 | 37, 39, 41, 42, 58 |
| D1 and N together | Both | +1.434 (n=52, 0.29 a month) | Thin | 51, 64 |
| C26 percent drawdown (P) | Down 50%+ from the 252-session closing high | +0.468 (n=444, ~2.5 a month; +0.638 without the 3 episodes); a step at 50%, not a ladder; weaker than F; P and F together +0.662 (n=218), P adds an unproven +0.33 on top of F | Lead (second ruler for C8); graded points not supported | 66, 67 |
| C23 basing | Inside D1, choppy last 2-3 months beats orderly slide | +0.80 (n=170) vs +0.17 (n=85) | Weak lead (best of 12 = 31.8%) | 59-61 |
| Score (Michael's idea) | Points for R1 (no CEO/CFO), N, D1 | 0/1/2/3 points = -0.04/+0.29/+0.63/+1.21 (n=17) | Descriptive only; weights not set | 51, MICHAEL_DETERMINATIONS 1 |

## Not supported (do not re-test)
CEO/CFO as a stand-alone filter, purchase size, director count, officer titles, short look-backs (3 months or less), SPY regime alone, oversold RSI and distance below short averages, bounce off the 12-month low (C20), SPY-200-day gate (C22), "moved up" after a base (C23). Longer holds than 21 sessions (Entry 46). Fixed stops (Entry 63: no gain in excess). 10-session trailing stop (Entry 62): +0.185 excess in 15 sessions, but a few big winners and negative at 0.25 ATR cost.

## Standing caveats
- Survivorship: 16.5% of events have no price series (31% in 2008); bounds in Entries 38 and 44. Entry 65: only 1 of 1,276 trades ended inside the hold, so the archive cannot measure wipe-outs; the D1 lead survives an assumed 1-3% wipe-out rate at -55% and fails at about 5% or more. No survivorship pattern across years or eras. Only a second price source with delisting history can settle it.
- Costs: round-trip 0.10-0.25 ATR wipes out most of the base rule; the deep-fall group trades $14-20M a day, a quarter under $6M (Entries 45, 54, 57).
- Concentration: three large episodes (2008Q4, 2011Q3, 2020Q1) and a few spells; independent sample is tens of market periods.
- Liquidity inverted-U (C21): base rule pays at $5-25M a day, about zero above $25M.

## Open items
1. C27: dd252 >= 50% vs a fixed -15 ATR 12-month fall (not the quintile), alone and both, inside the score (Entry 66 next step).
2. Second price source with delisted history (decision for Michael), then re-price the missing 2011-2020 names.
3. Cost and survivorship by dollar-volume band for D1 and N (Entry 58 next step 1).
4. Michael's open scoring decisions: MICHAEL_DETERMINATIONS item 1.
