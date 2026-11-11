# Efficiency-ratio systems: stop width and exit matrix, one ATR = 0.25% of equity (in-sample only)

Written 11 Nov 2026. Code `research/efficiency_trend/exit_matrix.py` (tests `test_exit_matrix.py`), workflow `.github/workflows/efficiency-exit-matrix.yml`, run https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/43109994176, raw results `research/efficiency_trend/results_exit_matrix/` (every cell with about 25 columns, plus the trade lists for the uncapped cells). Branch `claude/outside-inside-day-20261111`. Last 5 years sealed: the last price used is 2021-11-05; no signal after 2021-08-06.

## Setup
- Two systems, 48 report markets, entry at the next open, one position per market, no costs: **20-session efficiency ratio >= 0.6** and **15-session efficiency ratio >= 0.7** (first session the ratio reaches the level in the trend direction).
- **Size: one ATR = 0.25% of equity** (ATR = 14-session average true range at the signal close), added not compounded. The same position size for every initial stop, so only the exit changes between cells.
- Initial stop 2, 3, 4, 5 ATR. Ten exits: fixed stop (never moves) with a 60, 90, 120-session cap or no cap; 40- and 20-session channel trailing stop (lowest low of the last N sessions, highest high for shorts; no cap); 4 ATR and 6 ATR trailing stop below the highest high, each with the 60-session cap and with no cap.
- Same trade filter for every exit; one common calendar (2008-01-30 to 2021-11-05) for every cell. Trades still open at the last in-sample close (2021-11-05) are closed there at that close (only matters for the uncapped cells).
- **Check:** the 3 ATR fixed stop with the 60-session cap reproduces the earlier fixed-risk engine exactly (same trades, same daily returns after scaling by 1.5). It gives 20.6% a year, 28.8% worst drawdown, 11.2% average drawdown for the 20-session system and 22.3%, 31.7%, 12.0% for the 15-session system, the same as the arithmetic scaling predicted in the handoff.

## What the grid says
1. **The 60-session cap with a fixed 3 to 5 ATR stop is still the best or tied for best, even now that trailing stops are allowed to run past 60 sessions.** Among the cells that are not distorted (see 3), the highest Sharpe ratios are the fixed stop with the 60-session cap at 3, 4 and 5 ATR (0.84 to 0.99 across the two systems; the 120-session cap at 3 ATR, 0.95 for the 20-session system, is the one other cell in that range). The differences between those cells are small and are inside the noise of 80 comparisons.
2. **Initial stop width: 2 ATR is clearly worse (Sharpe 0.77 and 0.85 with the 60 cap); 3, 4 and 5 ATR are about the same.** Averaged over all 20 cells at each width the Sharpe is 0.73, 0.76, 0.74, 0.76 for 2, 3, 4, 5 ATR: a flat line. A wider stop does not reduce the drawdown at this fixed position size; the worst drawdown at 3 to 5 ATR is about 29% to 31% for the 20-session system and 32% to 37% for the 15-session system.
3. **No cap with a fixed stop is not a usable result.** At 3 ATR there are only 293 and 330 trades, the win rate is 15% and 13%, the average hold is 400 and 363 sessions, the longest is 3,357 sessions (over 13 years). Forced closes at the cutoff: 45 trades hold +625% of equity of open profit against a total of +439%, so the closed trades together LOST about 186%. All the profit is open positions marked at 2021-11-05, many of them short positions entered in the second half of 2008 whose fixed stop (set from 2008 volatility) was never reached again. Average open positions 33, up to 47; worst drawdown 57% to 58%. The 1.03 Sharpe at 2 ATR (best cell in the grid) is this effect, and depends on the cutoff date.
4. **Trailing stops do not rescue themselves when the cap is removed.** 4 ATR trail: Sharpe 0.57 to 0.76 with the 60 cap and 0.54 to 0.69 without. 6 ATR trail: 0.69 to 0.89 with the cap and 0.52 to 0.76 without. The channel trails: 20-session 0.73 to 0.84 (worst drawdown 27% to 36%, the best of the uncapped exits), 40-session 0.67 to 0.78 (worst drawdown 39% to 51%, average drawdown 19% to 23%). On average all of them sit below the fixed stop with the 60-session cap (Sharpe averaged over the 8 cells: 0.88 against 0.62 to 0.79 for the trailing exits), although a few single cells overlap, such as the 6 ATR trail with the cap at 5 ATR (0.89) against the 15-session fixed stop (0.84). The earlier finding stands: tight trailing exits cut the big winners.
5. **Longer caps raise return and drawdown together, with no gain per unit of risk.** Fixed stop, average over the 8 cells at 60 / 90 / 120 / no cap: Sharpe 0.88 / 0.73 / 0.82 / 0.83, worst drawdown 31% / 39% / 46% / 54%, Calmar 0.66 / 0.48 / 0.50 / 0.54. The 90-session cap being worse than both 60 and 120 is a sign of noise, not of a pattern.
6. **ZQ (30-day fed funds) inflates every cell.** Its ATR is about 0.01% of price, so 0.25% of equity per ATR is a position of roughly 25 times equity. One uncapped ZQ trade made +76% of equity. Without ZQ (47 markets, full grids below): the 3 ATR / 60-session baseline falls to 18.0% a year, Sharpe 0.85, worst drawdown 28.3% (20-session) and 17.3%, 0.77, 32.9% (15-session). The broad ranking is the same: the fixed stop with the 60-session cap still leads the capped exits and the trailing exits still sit below it.

## Cautions
- In-sample only; 80 cells compared on one sample, so the best cell is biased upward and gaps of a few hundredths in Sharpe mean nothing.
- No costs. No margin or position limits: up to 23 to 47 correlated positions open at once. Position size is fixed from the ATR at entry and never rebalanced, so very long holds drift far from 0.25% per ATR.
- Back-adjusted continuous prices: very long holds (uncapped cells) rely on the adjustment being faithful across many contract rolls.

## Full grids, all 48 markets

### 20-session ratio 0.6

**Average return per year, % of equity (added, not compounded)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 14.48 | 20.64 | 21.44 | 23.93 |
| fixed stop, 90-session cap | 18.48 | 20.89 | 18.93 | 19.76 |
| fixed stop, 120-session cap | 22.29 | 25.83 | 23.25 | 22.70 |
| fixed stop, no cap | 35.42 | 31.87 | 24.58 | 26.96 |
| 40-session channel trail, no cap | 17.83 | 21.74 | 22.30 | 23.70 |
| 20-session channel trail, no cap | 13.48 | 17.41 | 18.17 | 17.82 |
| 4 ATR trail, 60-session cap | 7.77 | 11.11 | 12.24 | 12.22 |
| 4 ATR trail, no cap | 8.00 | 10.64 | 11.49 | 11.47 |
| 6 ATR trail, 60-session cap | 10.97 | 15.62 | 15.60 | 17.80 |
| 6 ATR trail, no cap | 9.35 | 13.16 | 15.23 | 16.09 |


**Sharpe ratio**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.77 | 0.93 | 0.91 | 0.99 |
| fixed stop, 90-session cap | 0.83 | 0.81 | 0.71 | 0.72 |
| fixed stop, 120-session cap | 0.92 | 0.95 | 0.83 | 0.79 |
| fixed stop, no cap | 1.03 | 0.87 | 0.69 | 0.78 |
| 40-session channel trail, no cap | 0.74 | 0.78 | 0.76 | 0.78 |
| 20-session channel trail, no cap | 0.73 | 0.83 | 0.84 | 0.82 |
| 4 ATR trail, 60-session cap | 0.57 | 0.72 | 0.76 | 0.76 |
| 4 ATR trail, no cap | 0.57 | 0.66 | 0.69 | 0.69 |
| 6 ATR trail, 60-session cap | 0.69 | 0.84 | 0.79 | 0.89 |
| 6 ATR trail, no cap | 0.54 | 0.65 | 0.73 | 0.76 |


**Worst drawdown, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 30.68 | 28.78 | 29.83 | 30.83 |
| fixed stop, 90-session cap | 31.41 | 35.33 | 37.75 | 39.27 |
| fixed stop, 120-session cap | 34.93 | 37.98 | 40.17 | 56.91 |
| fixed stop, no cap | 44.69 | 57.50 | 64.10 | 56.87 |
| 40-session channel trail, no cap | 39.35 | 50.74 | 45.22 | 39.20 |
| 20-session channel trail, no cap | 26.86 | 31.88 | 32.67 | 34.92 |
| 4 ATR trail, 60-session cap | 28.52 | 31.92 | 32.80 | 32.80 |
| 4 ATR trail, no cap | 27.26 | 30.89 | 32.92 | 32.92 |
| 6 ATR trail, 60-session cap | 28.23 | 30.14 | 31.25 | 30.08 |
| 6 ATR trail, no cap | 28.35 | 33.50 | 35.39 | 33.04 |


**Average drawdown over all days, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 11.12 | 11.21 | 10.96 | 9.41 |
| fixed stop, 90-session cap | 13.35 | 13.99 | 14.55 | 14.19 |
| fixed stop, 120-session cap | 11.16 | 11.73 | 12.73 | 16.27 |
| fixed stop, no cap | 12.96 | 19.26 | 18.32 | 18.15 |
| 40-session channel trail, no cap | 18.51 | 21.63 | 21.47 | 20.26 |
| 20-session channel trail, no cap | 13.23 | 13.96 | 14.14 | 14.50 |
| 4 ATR trail, 60-session cap | 9.91 | 11.21 | 10.53 | 10.56 |
| 4 ATR trail, no cap | 10.53 | 11.42 | 11.49 | 11.51 |
| 6 ATR trail, 60-session cap | 10.08 | 11.14 | 11.68 | 10.03 |
| 6 ATR trail, no cap | 12.71 | 14.74 | 14.32 | 12.92 |


**Calmar ratio (return per year / worst drawdown)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.47 | 0.72 | 0.72 | 0.78 |
| fixed stop, 90-session cap | 0.59 | 0.59 | 0.50 | 0.50 |
| fixed stop, 120-session cap | 0.64 | 0.68 | 0.58 | 0.40 |
| fixed stop, no cap | 0.79 | 0.55 | 0.38 | 0.47 |
| 40-session channel trail, no cap | 0.45 | 0.43 | 0.49 | 0.60 |
| 20-session channel trail, no cap | 0.50 | 0.55 | 0.56 | 0.51 |
| 4 ATR trail, 60-session cap | 0.27 | 0.35 | 0.37 | 0.37 |
| 4 ATR trail, no cap | 0.29 | 0.34 | 0.35 | 0.35 |
| 6 ATR trail, 60-session cap | 0.39 | 0.52 | 0.50 | 0.59 |
| 6 ATR trail, no cap | 0.33 | 0.39 | 0.43 | 0.49 |


**Trades**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 1044 | 997 | 969 | 945 |
| fixed stop, 90-session cap | 982 | 920 | 884 | 850 |
| fixed stop, 120-session cap | 938 | 869 | 828 | 791 |
| fixed stop, no cap | 345 | 293 | 227 | 197 |
| 40-session channel trail, no cap | 956 | 898 | 874 | 854 |
| 20-session channel trail, no cap | 1037 | 995 | 985 | 983 |
| 4 ATR trail, 60-session cap | 1077 | 1041 | 1028 | 1028 |
| 4 ATR trail, no cap | 963 | 925 | 913 | 913 |
| 6 ATR trail, 60-session cap | 1055 | 1009 | 991 | 974 |
| 6 ATR trail, no cap | 862 | 781 | 725 | 685 |


### 15-session ratio 0.7

**Average return per year, % of equity (added, not compounded)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 17.10 | 22.30 | 21.68 | 21.71 |
| fixed stop, 90-session cap | 17.17 | 17.29 | 17.66 | 17.42 |
| fixed stop, 120-session cap | 20.36 | 20.20 | 20.43 | 21.67 |
| fixed stop, no cap | 31.71 | 23.46 | 25.80 | 30.07 |
| 40-session channel trail, no cap | 17.01 | 19.28 | 20.56 | 20.92 |
| 20-session channel trail, no cap | 14.42 | 17.96 | 18.21 | 18.41 |
| 4 ATR trail, 60-session cap | 9.03 | 11.61 | 11.98 | 11.94 |
| 4 ATR trail, no cap | 7.73 | 10.87 | 11.51 | 11.50 |
| 6 ATR trail, 60-session cap | 11.81 | 14.68 | 14.14 | 14.72 |
| 6 ATR trail, no cap | 9.36 | 10.76 | 12.29 | 13.90 |


**Sharpe ratio**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.85 | 0.93 | 0.85 | 0.84 |
| fixed stop, 90-session cap | 0.74 | 0.68 | 0.67 | 0.64 |
| fixed stop, 120-session cap | 0.83 | 0.75 | 0.72 | 0.75 |
| fixed stop, no cap | 0.94 | 0.71 | 0.76 | 0.87 |
| 40-session channel trail, no cap | 0.68 | 0.67 | 0.67 | 0.68 |
| 20-session channel trail, no cap | 0.74 | 0.81 | 0.78 | 0.78 |
| 4 ATR trail, 60-session cap | 0.63 | 0.72 | 0.71 | 0.71 |
| 4 ATR trail, no cap | 0.54 | 0.66 | 0.67 | 0.67 |
| 6 ATR trail, 60-session cap | 0.71 | 0.76 | 0.69 | 0.71 |
| 6 ATR trail, no cap | 0.52 | 0.54 | 0.57 | 0.64 |


**Worst drawdown, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 25.54 | 31.73 | 37.00 | 35.30 |
| fixed stop, 90-session cap | 35.10 | 41.41 | 46.52 | 43.53 |
| fixed stop, 120-session cap | 34.17 | 48.58 | 59.59 | 56.56 |
| fixed stop, no cap | 50.19 | 58.30 | 55.19 | 48.47 |
| 40-session channel trail, no cap | 48.63 | 45.80 | 44.81 | 44.53 |
| 20-session channel trail, no cap | 34.57 | 36.33 | 35.16 | 33.21 |
| 4 ATR trail, 60-session cap | 32.02 | 35.64 | 36.78 | 36.78 |
| 4 ATR trail, no cap | 33.98 | 34.87 | 31.40 | 31.40 |
| 6 ATR trail, 60-session cap | 26.06 | 32.92 | 38.57 | 40.51 |
| 6 ATR trail, no cap | 43.38 | 44.34 | 33.65 | 33.83 |


**Average drawdown over all days, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 9.76 | 12.01 | 13.15 | 13.15 |
| fixed stop, 90-session cap | 14.54 | 14.50 | 15.12 | 14.50 |
| fixed stop, 120-session cap | 10.58 | 12.83 | 13.37 | 12.48 |
| fixed stop, no cap | 16.64 | 21.53 | 17.91 | 15.31 |
| 40-session channel trail, no cap | 20.91 | 23.04 | 21.49 | 21.15 |
| 20-session channel trail, no cap | 14.36 | 15.30 | 15.76 | 15.45 |
| 4 ATR trail, 60-session cap | 10.37 | 12.44 | 12.48 | 12.56 |
| 4 ATR trail, no cap | 12.47 | 13.14 | 12.78 | 12.83 |
| 6 ATR trail, 60-session cap | 9.60 | 11.56 | 13.67 | 13.77 |
| 6 ATR trail, no cap | 16.37 | 16.94 | 14.70 | 14.05 |


**Calmar ratio (return per year / worst drawdown)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.67 | 0.70 | 0.59 | 0.62 |
| fixed stop, 90-session cap | 0.49 | 0.42 | 0.38 | 0.40 |
| fixed stop, 120-session cap | 0.60 | 0.42 | 0.34 | 0.38 |
| fixed stop, no cap | 0.63 | 0.40 | 0.47 | 0.62 |
| 40-session channel trail, no cap | 0.35 | 0.42 | 0.46 | 0.47 |
| 20-session channel trail, no cap | 0.42 | 0.49 | 0.52 | 0.55 |
| 4 ATR trail, 60-session cap | 0.28 | 0.33 | 0.33 | 0.32 |
| 4 ATR trail, no cap | 0.23 | 0.31 | 0.37 | 0.37 |
| 6 ATR trail, 60-session cap | 0.45 | 0.45 | 0.37 | 0.36 |
| 6 ATR trail, no cap | 0.22 | 0.24 | 0.37 | 0.41 |


**Trades**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 1124 | 1068 | 1046 | 1013 |
| fixed stop, 90-session cap | 1039 | 971 | 918 | 874 |
| fixed stop, 120-session cap | 1000 | 920 | 865 | 811 |
| fixed stop, no cap | 377 | 330 | 245 | 202 |
| 40-session channel trail, no cap | 1024 | 961 | 930 | 905 |
| 20-session channel trail, no cap | 1121 | 1088 | 1081 | 1077 |
| 4 ATR trail, 60-session cap | 1162 | 1129 | 1122 | 1122 |
| 4 ATR trail, no cap | 1023 | 978 | 967 | 967 |
| 6 ATR trail, 60-session cap | 1132 | 1083 | 1065 | 1043 |
| 6 ATR trail, no cap | 894 | 806 | 764 | 736 |


## Full grids without ZQ (47 markets)

### 20-session ratio 0.6, without ZQ

**Average return per year, % of equity (added, not compounded)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 11.74 | 18.02 | 18.44 | 20.29 |
| fixed stop, 90-session cap | 12.73 | 15.37 | 15.89 | 17.62 |
| fixed stop, 120-session cap | 15.79 | 19.31 | 19.46 | 19.42 |
| fixed stop, no cap | 30.01 | 26.47 | 24.31 | 25.59 |
| 40-session channel trail, no cap | 14.71 | 18.74 | 19.29 | 20.51 |
| 20-session channel trail, no cap | 11.36 | 15.10 | 15.88 | 15.43 |
| 4 ATR trail, 60-session cap | 6.66 | 10.10 | 10.89 | 10.87 |
| 4 ATR trail, no cap | 7.49 | 10.19 | 11.06 | 11.04 |
| 6 ATR trail, 60-session cap | 9.88 | 14.69 | 14.66 | 16.26 |
| 6 ATR trail, no cap | 8.89 | 12.76 | 14.77 | 15.60 |


**Sharpe ratio**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.65 | 0.85 | 0.82 | 0.87 |
| fixed stop, 90-session cap | 0.61 | 0.63 | 0.61 | 0.66 |
| fixed stop, 120-session cap | 0.69 | 0.74 | 0.71 | 0.68 |
| fixed stop, no cap | 0.88 | 0.73 | 0.68 | 0.74 |
| 40-session channel trail, no cap | 0.63 | 0.69 | 0.68 | 0.70 |
| 20-session channel trail, no cap | 0.64 | 0.74 | 0.76 | 0.73 |
| 4 ATR trail, 60-session cap | 0.50 | 0.66 | 0.68 | 0.68 |
| 4 ATR trail, no cap | 0.54 | 0.64 | 0.67 | 0.67 |
| 6 ATR trail, 60-session cap | 0.63 | 0.79 | 0.75 | 0.82 |
| 6 ATR trail, no cap | 0.51 | 0.64 | 0.71 | 0.74 |


**Worst drawdown, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 33.16 | 28.34 | 30.59 | 29.69 |
| fixed stop, 90-session cap | 31.68 | 36.73 | 37.84 | 38.15 |
| fixed stop, 120-session cap | 38.99 | 42.31 | 41.91 | 58.82 |
| fixed stop, no cap | 48.59 | 65.27 | 64.96 | 57.87 |
| 40-session channel trail, no cap | 42.15 | 49.96 | 45.17 | 40.02 |
| 20-session channel trail, no cap | 29.11 | 36.06 | 37.07 | 39.32 |
| 4 ATR trail, 60-session cap | 27.66 | 31.26 | 31.95 | 31.95 |
| 4 ATR trail, no cap | 27.46 | 31.03 | 33.05 | 33.05 |
| 6 ATR trail, 60-session cap | 29.76 | 29.04 | 30.51 | 28.38 |
| 6 ATR trail, no cap | 28.54 | 33.48 | 35.37 | 33.02 |


**Average drawdown over all days, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 11.60 | 11.34 | 11.53 | 10.41 |
| fixed stop, 90-session cap | 14.60 | 14.61 | 15.47 | 14.85 |
| fixed stop, 120-session cap | 13.01 | 13.66 | 13.60 | 16.82 |
| fixed stop, no cap | 14.05 | 20.15 | 18.41 | 18.35 |
| 40-session channel trail, no cap | 19.52 | 22.32 | 21.83 | 20.80 |
| 20-session channel trail, no cap | 14.02 | 14.88 | 15.13 | 15.70 |
| 4 ATR trail, 60-session cap | 10.36 | 11.04 | 10.94 | 10.95 |
| 4 ATR trail, no cap | 10.67 | 11.56 | 11.63 | 11.65 |
| 6 ATR trail, 60-session cap | 10.44 | 11.07 | 11.70 | 10.41 |
| 6 ATR trail, no cap | 12.85 | 14.86 | 14.44 | 12.98 |


**Calmar ratio (return per year / worst drawdown)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.35 | 0.64 | 0.60 | 0.68 |
| fixed stop, 90-session cap | 0.40 | 0.42 | 0.42 | 0.46 |
| fixed stop, 120-session cap | 0.40 | 0.46 | 0.46 | 0.33 |
| fixed stop, no cap | 0.62 | 0.41 | 0.37 | 0.44 |
| 40-session channel trail, no cap | 0.35 | 0.38 | 0.43 | 0.51 |
| 20-session channel trail, no cap | 0.39 | 0.42 | 0.43 | 0.39 |
| 4 ATR trail, 60-session cap | 0.24 | 0.32 | 0.34 | 0.34 |
| 4 ATR trail, no cap | 0.27 | 0.33 | 0.33 | 0.33 |
| 6 ATR trail, 60-session cap | 0.33 | 0.51 | 0.48 | 0.57 |
| 6 ATR trail, no cap | 0.31 | 0.38 | 0.42 | 0.47 |


**Trades**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 984 | 944 | 924 | 903 |
| fixed stop, 90-session cap | 931 | 876 | 846 | 815 |
| fixed stop, 120-session cap | 894 | 832 | 798 | 764 |
| fixed stop, no cap | 341 | 290 | 224 | 195 |
| 40-session channel trail, no cap | 907 | 854 | 833 | 814 |
| 20-session channel trail, no cap | 969 | 933 | 924 | 923 |
| 4 ATR trail, 60-session cap | 1013 | 981 | 973 | 973 |
| 4 ATR trail, no cap | 957 | 919 | 907 | 907 |
| 6 ATR trail, 60-session cap | 992 | 951 | 937 | 923 |
| 6 ATR trail, no cap | 856 | 775 | 719 | 679 |


### 15-session ratio 0.7, without ZQ

**Average return per year, % of equity (added, not compounded)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 14.17 | 17.28 | 16.98 | 16.86 |
| fixed stop, 90-session cap | 11.02 | 13.34 | 14.91 | 14.86 |
| fixed stop, 120-session cap | 13.49 | 15.46 | 16.91 | 18.09 |
| fixed stop, no cap | 26.48 | 20.87 | 23.23 | 27.52 |
| 40-session channel trail, no cap | 13.62 | 15.75 | 16.95 | 17.35 |
| 20-session channel trail, no cap | 11.73 | 15.34 | 15.64 | 15.85 |
| 4 ATR trail, 60-session cap | 7.27 | 9.86 | 10.28 | 10.25 |
| 4 ATR trail, no cap | 7.21 | 10.41 | 11.06 | 11.04 |
| 6 ATR trail, 60-session cap | 10.03 | 12.91 | 12.72 | 13.38 |
| 6 ATR trail, no cap | 8.87 | 10.34 | 11.89 | 13.50 |


**Sharpe ratio**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.73 | 0.77 | 0.70 | 0.69 |
| fixed stop, 90-session cap | 0.51 | 0.54 | 0.57 | 0.56 |
| fixed stop, 120-session cap | 0.58 | 0.59 | 0.62 | 0.65 |
| fixed stop, no cap | 0.80 | 0.64 | 0.69 | 0.80 |
| 40-session channel trail, no cap | 0.56 | 0.57 | 0.57 | 0.58 |
| 20-session channel trail, no cap | 0.63 | 0.71 | 0.69 | 0.70 |
| 4 ATR trail, 60-session cap | 0.52 | 0.61 | 0.62 | 0.62 |
| 4 ATR trail, no cap | 0.50 | 0.63 | 0.65 | 0.65 |
| 6 ATR trail, 60-session cap | 0.61 | 0.68 | 0.62 | 0.65 |
| 6 ATR trail, no cap | 0.50 | 0.52 | 0.56 | 0.62 |


**Worst drawdown, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 24.89 | 32.89 | 41.60 | 39.65 |
| fixed stop, 90-session cap | 48.75 | 41.27 | 49.03 | 44.95 |
| fixed stop, 120-session cap | 36.50 | 52.95 | 60.19 | 57.16 |
| fixed stop, no cap | 53.39 | 59.87 | 59.56 | 51.18 |
| 40-session channel trail, no cap | 50.56 | 51.00 | 48.02 | 47.37 |
| 20-session channel trail, no cap | 35.68 | 40.55 | 38.04 | 36.87 |
| 4 ATR trail, 60-session cap | 33.58 | 38.41 | 36.03 | 36.03 |
| 4 ATR trail, no cap | 34.05 | 34.95 | 31.76 | 31.76 |
| 6 ATR trail, 60-session cap | 30.38 | 36.18 | 36.99 | 38.93 |
| 6 ATR trail, no cap | 43.30 | 44.31 | 33.73 | 33.91 |


**Average drawdown over all days, % of equity**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 11.08 | 13.35 | 14.47 | 14.33 |
| fixed stop, 90-session cap | 18.18 | 17.04 | 16.33 | 16.22 |
| fixed stop, 120-session cap | 12.87 | 15.12 | 15.05 | 14.10 |
| fixed stop, no cap | 17.73 | 22.15 | 18.49 | 15.88 |
| 40-session channel trail, no cap | 23.27 | 25.62 | 23.94 | 22.59 |
| 20-session channel trail, no cap | 15.82 | 17.08 | 17.27 | 16.81 |
| 4 ATR trail, 60-session cap | 12.49 | 14.40 | 14.53 | 14.61 |
| 4 ATR trail, no cap | 12.61 | 13.31 | 12.95 | 13.00 |
| 6 ATR trail, 60-session cap | 11.21 | 13.19 | 14.23 | 14.36 |
| 6 ATR trail, no cap | 16.49 | 17.07 | 14.79 | 14.20 |


**Calmar ratio (return per year / worst drawdown)**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 0.57 | 0.53 | 0.41 | 0.43 |
| fixed stop, 90-session cap | 0.23 | 0.32 | 0.30 | 0.33 |
| fixed stop, 120-session cap | 0.37 | 0.29 | 0.28 | 0.32 |
| fixed stop, no cap | 0.50 | 0.35 | 0.39 | 0.54 |
| 40-session channel trail, no cap | 0.27 | 0.31 | 0.35 | 0.37 |
| 20-session channel trail, no cap | 0.33 | 0.38 | 0.41 | 0.43 |
| 4 ATR trail, 60-session cap | 0.22 | 0.26 | 0.29 | 0.28 |
| 4 ATR trail, no cap | 0.21 | 0.30 | 0.35 | 0.35 |
| 6 ATR trail, 60-session cap | 0.33 | 0.36 | 0.34 | 0.34 |
| 6 ATR trail, no cap | 0.20 | 0.23 | 0.35 | 0.40 |


**Trades**

| Exit | 2 ATR initial stop | 3 ATR | 4 ATR | 5 ATR |
|---|---|---|---|---|
| fixed stop, 60-session cap | 1064 | 1019 | 998 | 967 |
| fixed stop, 90-session cap | 990 | 929 | 879 | 839 |
| fixed stop, 120-session cap | 957 | 884 | 834 | 782 |
| fixed stop, no cap | 373 | 328 | 243 | 200 |
| 40-session channel trail, no cap | 976 | 923 | 893 | 868 |
| 20-session channel trail, no cap | 1052 | 1023 | 1016 | 1012 |
| 4 ATR trail, 60-session cap | 1099 | 1073 | 1066 | 1066 |
| 4 ATR trail, no cap | 1018 | 975 | 964 | 964 |
| 6 ATR trail, 60-session cap | 1072 | 1032 | 1013 | 992 |
| 6 ATR trail, no cap | 889 | 803 | 761 | 733 |

