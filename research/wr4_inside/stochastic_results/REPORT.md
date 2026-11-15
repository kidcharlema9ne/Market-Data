# Reversal stochastic sweep on COT + WR4 / inside-day trades

Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/43742994743

Code commit: 348b17f20469732bb298d1f0450f89c776c19244

All 275 baseline trades and all four outcome horizons independently reproduced against fetched prices before filtering.

Raw, unsmoothed stochastic %K = 100*(inside-day close - N-session lowest low)/(N-session highest high - lowest low). Includes the inside day; no future bars. Buy <= threshold, sell >= 100-threshold. No crossover requirement. Periods 5/10/14/21/42; levels 5/10/20/30 (20 settings).

Primary: stopped return at 21 sessions. Secondary: 5/10/42 sessions. Same original protective stop and no trailing stops. Development only through 2021-08-06. All baseline approximations retained: nominal ticks on ratio-adjusted prices; estimated release dates, not actual delays; no costs except gap fills; overlapping signals.

Inference requires >=30 trades and >=10 in each era. Smaller cells remain descriptive and cannot be selected as an edge. 10,000 joint outcome-vector permutations within market/direction/year; studentized maximum-statistic correction across eligible settings (primary 21 only and all four horizons separately). Conditional filter-placebo test, not a fresh random-entry test. Sparse groups, temporal clustering and selection from already-explored data limit inference; 90-calendar-day block intervals also reported.

Movable trades in permutation strata: 100 / 275; eligible settings: 8 / 20.

Cross-era diagnostic: choose highest 21-session stopped mean among settings with >=15 training trades; hold that choice fixed in the other era. A pass requires >=15 test trades, positive mean, and improvement over test-era unfiltered baseline. This is a robustness diagnostic within development data, not a pristine holdout.


## All 21-session settings (including thin cells)

|   period |   level |   n |   return_stopped_mean |   return_stopped_median |   prestop_mfe_low_mean |   stop_conservative_mean |
|---------:|--------:|----:|----------------------:|------------------------:|-----------------------:|-------------------------:|
|        5 |      10 |   1 |             7.85638   |                 7.85638 |                8.95479 |                 0        |
|       10 |       5 |   1 |             7.85638   |                 7.85638 |                8.95479 |                 0        |
|       14 |       5 |   1 |             7.85638   |                 7.85638 |                8.95479 |                 0        |
|       21 |       5 |   2 |             3.29718   |                 3.29718 |                4.47739 |                 0.5      |
|       10 |      10 |   6 |             2.60678   |                 2.28897 |                3.77928 |                 0.5      |
|       42 |       5 |   8 |             2.40108   |                 1.83254 |                3.35662 |                 0.375    |
|       21 |      10 |  21 |             0.817526  |                -1.21758 |                2.44816 |                 0.52381  |
|       14 |      10 |  11 |             0.794267  |                -1.27844 |                2.50732 |                 0.727273 |
|       10 |      20 |  28 |             0.601717  |                -1.15784 |                2.31994 |                 0.535714 |
|       42 |      10 |  47 |             0.598072  |                -1.17131 |                2.27968 |                 0.510638 |
|        5 |      30 |  37 |             0.246995  |                -1.11071 |                2.02757 |                 0.567568 |
|       14 |      20 |  53 |             0.20246   |                -1.21758 |                1.98798 |                 0.584906 |
|        5 |      20 |  17 |             0.193342  |                -1.26801 |                2.02454 |                 0.705882 |
|       42 |      30 | 174 |             0.170158  |                -1.1334  |                2.01097 |                 0.574713 |
|       10 |      30 |  73 |             0.164226  |                -1.17131 |                1.99422 |                 0.589041 |
|       14 |      30 |  98 |             0.136196  |                -1.12102 |                2.00226 |                 0.581633 |
|       21 |      20 |  84 |             0.0892693 |                -1.18703 |                1.98603 |                 0.571429 |
|       21 |      30 | 129 |             0.069447  |                -1.21639 |                2.00542 |                 0.604651 |
|        0 |       0 | 275 |             0.0606122 |                -1.12    |                1.97361 |                 0.589091 |
|       42 |      20 | 129 |             0.0458939 |                -1.20275 |                1.92949 |                 0.604651 |
|        5 |       5 |   0 |           nan         |               nan       |              nan       |               nan        |


## Multiple-testing results at 21 sessions

|   period |   level |   horizon |   n | eligible_for_inference   |   observed_mean |   matched_random_filter_mean |   incremental_mean |       raw_p |   p_adjusted_21 |   p_adjusted_all_horizons |
|---------:|--------:|----------:|----:|:-------------------------|----------------:|-----------------------------:|-------------------:|------------:|----------------:|--------------------------:|
|        5 |       5 |        21 |   0 | False                    |     nan         |                  nan         |       nan          | nan         |      nan        |                nan        |
|        5 |      10 |        21 |   1 | False                    |       7.85638   |                    7.85638   |         0          | nan         |      nan        |                nan        |
|        5 |      20 |        21 |  17 | False                    |       0.193342  |                    0.232971  |        -0.0396292  | nan         |      nan        |                nan        |
|        5 |      30 |        21 |  37 | False                    |       0.246995  |                    0.16031   |         0.0866852  | nan         |      nan        |                nan        |
|       10 |       5 |        21 |   1 | False                    |       7.85638   |                    7.85638   |         0          | nan         |      nan        |                nan        |
|       10 |      10 |        21 |   6 | False                    |       2.60678   |                    2.64826   |        -0.0414802  | nan         |      nan        |                nan        |
|       10 |      20 |        21 |  28 | False                    |       0.601717  |                    0.432928  |         0.168789   | nan         |      nan        |                nan        |
|       10 |      30 |        21 |  73 | True                     |       0.164226  |                    0.20051   |        -0.0362839  |   0.624638  |        0.940406 |                  0.9951   |
|       14 |       5 |        21 |   1 | False                    |       7.85638   |                    7.85638   |         0          | nan         |      nan        |                nan        |
|       14 |      10 |        21 |  11 | False                    |       0.794267  |                    0.855512  |        -0.0612452  | nan         |      nan        |                nan        |
|       14 |      20 |        21 |  53 | True                     |       0.20246   |                    0.273412  |        -0.0709524  |   0.705529  |        0.967303 |                  0.9978   |
|       14 |      30 |        21 |  98 | True                     |       0.136196  |                    0.149953  |        -0.0137571  |   0.550045  |        0.886811 |                  0.985201 |
|       21 |       5 |        21 |   2 | False                    |       3.29718   |                    3.29718   |         0          | nan         |      nan        |                nan        |
|       21 |      10 |        21 |  21 | False                    |       0.817526  |                    0.710158  |         0.107369   | nan         |      nan        |                nan        |
|       21 |      20 |        21 |  84 | True                     |       0.0892693 |                    0.0953187 |        -0.00604945 |   0.490651  |        0.866013 |                  0.979302 |
|       21 |      30 |        21 | 129 | True                     |       0.069447  |                    0.0399912 |         0.0294558  |   0.339766  |        0.721128 |                  0.919608 |
|       42 |       5 |        21 |   8 | False                    |       2.40108   |                    2.3832    |         0.017873   | nan         |      nan        |                nan        |
|       42 |      10 |        21 |  47 | True                     |       0.598072  |                    0.519795  |         0.0782772  |   0.0824918 |        0.29717  |                  0.542246 |
|       42 |      20 |        21 | 129 | True                     |       0.0458939 |                    0.0323948 |         0.0134991  |   0.426557  |        0.789921 |                  0.951605 |
|       42 |      30 |        21 | 174 | True                     |       0.170158  |                    0.142276  |         0.0278827  |   0.29737   |        0.678532 |                  0.892611 |


## Cross-era selection

| train     | test      |   period |   level |   train_n |   train_mean |   test_n |   test_mean |   test_baseline_mean | passes   |
|:----------|:----------|---------:|--------:|----------:|-------------:|---------:|------------:|---------------------:|:---------|
| 2008-2014 | 2015-2021 |       21 |      10 |        17 |     0.613276 |        4 |   1.68559   |            0.101405  | False    |
| 2015-2021 | 2008-2014 |       10 |      30 |        21 |     0.811384 |       52 |  -0.0971259 |            0.0365609 | False    |


## Return uncertainty

|   period |   level |   horizon |   n |      mean |       low |     high |
|---------:|--------:|----------:|----:|----------:|----------:|---------:|
|        0 |       0 |        21 | 275 | 0.0606122 | -0.206394 | 0.34487  |
|       10 |      30 |        21 |  73 | 0.164226  | -0.393632 | 0.791296 |
|       14 |      20 |        21 |  53 | 0.20246   | -0.50048  | 1.01688  |
|       14 |      30 |        21 |  98 | 0.136196  | -0.332698 | 0.707648 |
|       21 |      20 |        21 |  84 | 0.0892693 | -0.388252 | 0.63111  |
|       21 |      30 |        21 | 129 | 0.069447  | -0.364897 | 0.56367  |
|       42 |      10 |        21 |  47 | 0.598072  | -0.182597 | 1.36901  |
|       42 |      20 |        21 | 129 | 0.0458939 | -0.340733 | 0.483405 |
|       42 |      30 |        21 | 174 | 0.170158  | -0.190262 | 0.570861 |