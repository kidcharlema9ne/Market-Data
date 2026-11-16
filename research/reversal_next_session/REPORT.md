# Six-market development diagnostic

**PROVISIONAL: this is not yet the validated mandatory one-tick backtest.**

Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/43827290082

Code commit: `0bb3d59791a5a7c0bc5f34a1244c6c6f1f97cf45`. GitHub Actions completed successfully, verified 3,541 R2 objects, passed all ten entry tests and reproduced the tables below. The fresh R2 pilot slice matched the frozen local checksum.

Markets: ES, ZN, E6 (Euro FX), CL, GC, ZC. Outcomes end by August 6, 2021. No reserved last-five-year results were examined. All returns and excursions are ATR units, gross of costs.

The diagnostic uses nominal ticks on ratio-adjusted prices and estimated COT release timestamps. Historical tick factors, contract rolls and actual publication dates remain unresolved. Full method and limitations: [README](README.md).

Each excursion cell is mean / median. MAE lower and upper columns bound the unknown entry-day ordering. Counts decline when a later horizon crosses a missing session or the cutoff.

## Long

| Sessions | N | Return mean / median | MFE mean / median | MAE lower mean / median | MAE upper mean / median |
|---:|---:|---:|---:|---:|---:|
| 1 | 136 | +0.032 / +0.042 | +0.392 / +0.329 | +0.185 / +0.000 | +0.802 / +0.747 |
| 2 | 131 | +0.066 / +0.008 | +0.649 / +0.484 | +0.560 / +0.451 | +0.903 / +0.828 |
| 3 | 125 | +0.056 / -0.058 | +0.819 / +0.640 | +0.731 / +0.616 | +0.998 / +0.926 |
| 4 | 120 | +0.077 / +0.056 | +0.962 / +0.749 | +0.902 / +0.745 | +1.139 / +0.968 |
| 5 | 117 | +0.064 / +0.228 | +1.060 / +0.839 | +1.053 / +0.856 | +1.273 / +1.067 |
| 10 | 99 | +0.005 / -0.204 | +1.587 / +1.245 | +1.667 / +1.408 | +1.823 / +1.451 |

## Short

| Sessions | N | Return mean / median | MFE mean / median | MAE lower mean / median | MAE upper mean / median |
|---:|---:|---:|---:|---:|---:|
| 1 | 111 | -0.050 / +0.000 | +0.353 / +0.246 | +0.191 / +0.000 | +0.913 / +0.849 |
| 2 | 108 | +0.102 / +0.176 | +0.687 / +0.548 | +0.518 / +0.425 | +0.984 / +0.935 |
| 3 | 107 | +0.029 / +0.148 | +0.854 / +0.816 | +0.682 / +0.565 | +1.069 / +0.976 |
| 4 | 103 | +0.025 / -0.035 | +0.967 / +0.870 | +0.834 / +0.707 | +1.160 / +1.033 |
| 5 | 100 | +0.027 / +0.027 | +1.132 / +0.882 | +0.963 / +0.756 | +1.266 / +1.051 |
| 10 | 90 | +0.060 / -0.423 | +1.592 / +1.137 | +1.551 / +1.410 | +1.705 / +1.449 |

## Combined

| Sessions | N | Return mean / median | MFE mean / median | MAE lower mean / median | MAE upper mean / median |
|---:|---:|---:|---:|---:|---:|
| 1 | 247 | -0.005 / +0.020 | +0.375 / +0.276 | +0.188 / +0.000 | +0.852 / +0.789 |
| 2 | 239 | +0.082 / +0.037 | +0.666 / +0.519 | +0.541 / +0.432 | +0.939 / +0.877 |
| 3 | 232 | +0.044 / +0.021 | +0.835 / +0.720 | +0.709 / +0.589 | +1.031 / +0.947 |
| 4 | 223 | +0.053 / +0.006 | +0.964 / +0.793 | +0.870 / +0.714 | +1.148 / +0.985 |
| 5 | 217 | +0.047 / +0.098 | +1.093 / +0.868 | +1.011 / +0.815 | +1.270 / +1.060 |
| 10 | 189 | +0.031 / -0.256 | +1.589 / +1.222 | +1.612 / +1.408 | +1.767 / +1.451 |

## Statistical check

Every quarter-block 95% confidence interval for the mean return includes zero, in longs, shorts and combined. This diagnostic does not establish an edge. These are exploratory intervals, with correlated/overlapping trades and six horizons; they are not proof that the strategy is random.

## Same-pattern comparison

Controls: reversal/breakout entries outside the COT threshold, matched by market, side and calendar year. This is a descriptive comparison; it is not randomized and does not fix data limitations.

| Sessions | Matched N | COT mean | Control mean | Difference |
|---:|---:|---:|---:|---:|
| 1 | 231 | -0.010 | +0.008 | -0.018 |
| 2 | 223 | +0.086 | -0.063 | +0.150 |
| 3 | 213 | +0.045 | -0.092 | +0.137 |
| 4 | 204 | +0.060 | -0.074 | +0.134 |
| 5 | 197 | +0.067 | -0.065 | +0.131 |
| 10 | 152 | +0.053 | -0.214 | +0.266 |
