# Approximate COT + WR4 / inside-day backtest

Run: https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/43741855157

Script commit: bcafe916c5153c6d8505beebe10a2da809d66105

User authorized using available data despite audit limitations on 2026-11-15.

Development only: prices/outcomes end 2021-08-06; final five years remain sealed. All reported trades have full 42-session outcomes.

Approximations: nominal ticks on ratio-adjusted prices; estimated Friday/holiday publication dates, strict prior-date setup join; no shutdown backlog correction; unknown roll trades and revision vintages; missing sessions screened only by >7-day gaps. No costs/slippage beyond opening gaps.

ATR is simple mean of 14 pre-entry true ranges. Entry is session 1. COT evaluated at completed inside day; WR4 ties qualify, strict inside day, breakout only Day 3/4. Every setup is counted, including overlaps.

Primary universe excludes MES/MNQ duplicates; literal 48-market output is separate. Independent validation of economic contract mappings remains incomplete.

Unstopped MFE follows breakout; entry-bar MAE has lower/upper bounds. Stop-constrained MFE has conservative/optimistic daily-order bounds. Stops touched on intraday entry bars are conservatively charged and separately flagged as ambiguous. Stop-bar MFE is never assumed achievable in the conservative column.

Controls: 10,000 draws, same market/year/direction; conditional random opens match each observed initial stop distance in ATR. Pattern control uses non-COT WR4 events. No volatility matching; control p-values assume independent matched resampling, so serial dependence can make them optimistic. 90-calendar-day clustered bootstrap shown separately. Holm correction spans all reported control tests. Exploratory, not a proof of edge.

Unique primary trades: 275; pilot: 25; literal 48: 275.


## Pooled means (ATR except rates)

|   horizon |     mfe |   mae_low |   mae_high |   prestop_mfe_low |   prestop_mfe_high |   prestop_mae |   stop_conservative |   entry_stop_ambiguous |   return_unstopped |   return_stopped |
|----------:|--------:|----------:|-----------:|------------------:|-------------------:|--------------:|--------------------:|-----------------------:|-------------------:|-----------------:|
|         5 | 1.16747 |   1.00574 |    1.21397 |           1.09455 |            1.11304 |       1.00155 |            0.276364 |              0.0436364 |          0.0579531 |        0.0260027 |
|        10 | 1.64432 |   1.60869 |    1.73512 |           1.47539 |            1.49389 |       1.13983 |            0.461818 |              0.0436364 |         -0.0570313 |       -0.0375091 |
|        21 | 2.44812 |   2.37601 |    2.46619 |           1.97361 |            1.99211 |       1.21579 |            0.589091 |              0.0436364 |          0.0735282 |        0.0606122 |
|        42 | 3.63514 |   3.40795 |    3.48243 |           2.58221 |            2.6007  |       1.28875 |            0.712727 |              0.0436364 |          0.137676  |        0.107262  |


## Pooled medians

|   horizon |      mfe |   mae_low |   mae_high |   prestop_mfe_low |   prestop_mfe_high |   prestop_mae |   stop_conservative |   entry_stop_ambiguous |   return_unstopped |   return_stopped |
|----------:|---------:|----------:|-----------:|------------------:|-------------------:|--------------:|--------------------:|-----------------------:|-------------------:|-----------------:|
|         5 | 0.974254 |  0.791298 |    1.00538 |           0.92574 |           0.929153 |      0.984202 |                   0 |                      0 |          0.0529124 |       -0.0479863 |
|        10 | 1.36058  |  1.2226   |    1.29167 |           1.16455 |           1.17982  |      1.14305  |                   0 |                      0 |         -0.104701  |       -0.763441  |
|        21 | 1.9863   |  1.7872   |    1.7872  |           1.39423 |           1.39423  |      1.22639  |                   1 |                      0 |          0.0920041 |       -1.12      |
|        42 | 2.87805  |  2.53428  |    2.53428 |           1.4632  |           1.4632   |      1.29808  |                   1 |                      0 |          0.349105  |       -1.25729   |


## Randomized controls (mean)

| control                     |   horizon | metric            | stat   |   n_matched |   n_unmatched |   observed |   random_median |   random_p025 |   random_p975 |   p_two_sided |   p_holm |
|:----------------------------|----------:|:------------------|:-------|------------:|--------------:|-----------:|----------------:|--------------:|--------------:|--------------:|---------:|
| cot_conditioned_random_open |         5 | mfe               | mean   |         274 |             1 |  1.16566   |      1.2662     |    1.16642    |     1.37066   |    0.0493951  | 1        |
| cot_conditioned_random_open |         5 | mae_high          | mean   |         274 |             1 |  1.21685   |      1.08056    |    0.977853   |     1.18743   |    0.0127987  | 1        |
| cot_conditioned_random_open |         5 | prestop_mfe_low   | mean   |         274 |             1 |  1.09248   |      1.22432    |    1.12301    |     1.3306    |    0.0115988  | 0.939506 |
| cot_conditioned_random_open |         5 | stop_conservative | mean   |         274 |             1 |  0.277372  |      0.277372   |    0.229927   |     0.328467  |    1          | 1        |
| cot_conditioned_random_open |         5 | return_unstopped  | mean   |         274 |             1 |  0.0535564 |      0.171416   |    0.0131574  |     0.324713  |    0.140986   | 1        |
| cot_conditioned_random_open |         5 | return_stopped    | mean   |         274 |             1 |  0.0214894 |      0.159304   |    0.0159367  |     0.300856  |    0.059794   | 1        |
| pattern_without_cot         |         5 | mfe               | mean   |         273 |             2 |  1.16633   |      1.13871    |    1.0387     |     1.24403   |    0.594741   | 1        |
| pattern_without_cot         |         5 | mae_high          | mean   |         273 |             2 |  1.21791   |      1.28888    |    1.19907    |     1.38468   |    0.131787   | 1        |
| pattern_without_cot         |         5 | prestop_mfe_low   | mean   |         273 |             2 |  1.09289   |      1.08065    |    0.979875   |     1.18613   |    0.819118   | 1        |
| pattern_without_cot         |         5 | stop_conservative | mean   |         273 |             2 |  0.278388  |      0.289377   |    0.241758   |     0.340659  |    0.689531   | 1        |
| pattern_without_cot         |         5 | return_unstopped  | mean   |         273 |             2 |  0.0516932 |     -0.00468191 |   -0.158039   |     0.149556  |    0.458354   | 1        |
| pattern_without_cot         |         5 | return_stopped    | mean   |         273 |             2 |  0.0195087 |      0.00608236 |   -0.125792   |     0.142369  |    0.848915   | 1        |
| cot_conditioned_random_open |        10 | mfe               | mean   |         274 |             1 |  1.64426   |      1.81689    |    1.68786    |     1.94861   |    0.0089991  | 0.755924 |
| cot_conditioned_random_open |        10 | mae_high          | mean   |         274 |             1 |  1.7399    |      1.5183     |    1.37902    |     1.66971   |    0.00519948 | 0.462754 |
| cot_conditioned_random_open |        10 | prestop_mfe_low   | mean   |         274 |             1 |  1.47472   |      1.67919    |    1.54108    |     1.81702   |    0.00239976 | 0.225577 |
| cot_conditioned_random_open |        10 | stop_conservative | mean   |         274 |             1 |  0.463504  |      0.408759   |    0.357664   |     0.459854  |    0.0429957  | 1        |
| cot_conditioned_random_open |        10 | return_unstopped  | mean   |         274 |             1 | -0.0616913 |      0.241687   |    0.036712   |     0.44655   |    0.00519948 | 0.462754 |
| cot_conditioned_random_open |        10 | return_stopped    | mean   |         274 |             1 | -0.0420978 |      0.22435    |    0.0478205  |     0.401881  |    0.0029997  | 0.278972 |
| pattern_without_cot         |        10 | mfe               | mean   |         273 |             2 |  1.6461    |      1.63661    |    1.49691    |     1.78249   |    0.90171    | 1        |
| pattern_without_cot         |        10 | mae_high          | mean   |         273 |             2 |  1.74104   |      1.77148    |    1.63362    |     1.92105   |    0.675532   | 1        |
| pattern_without_cot         |        10 | prestop_mfe_low   | mean   |         273 |             2 |  1.47593   |      1.50821    |    1.36347    |     1.65908   |    0.665733   | 1        |
| pattern_without_cot         |        10 | stop_conservative | mean   |         273 |             2 |  0.465201  |      0.454212   |    0.40293    |     0.505495  |    0.70133    | 1        |
| pattern_without_cot         |        10 | return_unstopped  | mean   |         273 |             2 | -0.0530785 |     -0.0995092  |   -0.335662   |     0.129266  |    0.689331   | 1        |
| pattern_without_cot         |        10 | return_stopped    | mean   |         273 |             2 | -0.0334133 |      0.0184839  |   -0.161527   |     0.20242   |    0.574143   | 1        |
| cot_conditioned_random_open |        21 | mfe               | mean   |         274 |             1 |  2.44939   |      2.6011     |    2.42945    |     2.77476   |    0.0821918  | 1        |
| cot_conditioned_random_open |        21 | mae_high          | mean   |         274 |             1 |  2.47186   |      2.21065    |    2.02646    |     2.40951   |    0.00979902 | 0.813319 |
| cot_conditioned_random_open |        21 | prestop_mfe_low   | mean   |         274 |             1 |  1.97316   |      2.16355    |    1.97879    |     2.35322   |    0.0437956  | 1        |
| cot_conditioned_random_open |        21 | stop_conservative | mean   |         274 |             1 |  0.591241  |      0.554745   |    0.50365    |     0.60219   |    0.145785   | 1        |
| cot_conditioned_random_open |        21 | return_unstopped  | mean   |         274 |             1 |  0.0689308 |      0.259681   |   -0.00846509 |     0.515304  |    0.161184   | 1        |
| cot_conditioned_random_open |        21 | return_stopped    | mean   |         274 |             1 |  0.0559677 |      0.171818   |   -0.0318603  |     0.382532  |    0.267773   | 1        |
| pattern_without_cot         |        21 | mfe               | mean   |         273 |             2 |  2.45578   |      2.35279    |    2.13785    |     2.5826    |    0.372563   | 1        |
| pattern_without_cot         |        21 | mae_high          | mean   |         273 |             2 |  2.47309   |      2.68765    |    2.45324    |     2.94655   |    0.0725927  | 1        |
| pattern_without_cot         |        21 | prestop_mfe_low   | mean   |         273 |             2 |  1.9778    |      2.01359    |    1.79867    |     2.24378   |    0.762324   | 1        |
| pattern_without_cot         |        21 | stop_conservative | mean   |         273 |             2 |  0.589744  |      0.6337     |    0.586081   |     0.684982  |    0.0873913  | 1        |
| pattern_without_cot         |        21 | return_unstopped  | mean   |         273 |             2 |  0.0747403 |     -0.322387   |   -0.678449   |     0.0245556 |    0.0251975  | 1        |
| pattern_without_cot         |        21 | return_stopped    | mean   |         273 |             2 |  0.0618061 |     -0.0700264  |   -0.29647    |     0.170156  |    0.273773   | 1        |
| cot_conditioned_random_open |        42 | mfe               | mean   |         274 |             1 |  3.64074   |      3.7078     |    3.48075    |     3.9474    |    0.570743   | 1        |
| cot_conditioned_random_open |        42 | mae_high          | mean   |         274 |             1 |  3.48743   |      3.2097     |    2.9618     |     3.47744   |    0.0427957  | 1        |
| cot_conditioned_random_open |        42 | prestop_mfe_low   | mean   |         274 |             1 |  2.58397   |      2.74017    |    2.4715     |     3.02435   |    0.253375   | 1        |
| cot_conditioned_random_open |        42 | stop_conservative | mean   |         274 |             1 |  0.711679  |      0.656934   |    0.613139   |     0.70073   |    0.019998   | 1        |
| cot_conditioned_random_open |        42 | return_unstopped  | mean   |         274 |             1 |  0.145712  |      0.259732   |   -0.0864222  |     0.599637  |    0.517148   | 1        |
| cot_conditioned_random_open |        42 | return_stopped    | mean   |         274 |             1 |  0.114396  |      0.194132   |   -0.0660574  |     0.47311   |    0.557144   | 1        |
| pattern_without_cot         |        42 | mfe               | mean   |         273 |             2 |  3.63786   |      3.32974    |    3.01757    |     3.6553    |    0.0627937  | 1        |
| pattern_without_cot         |        42 | mae_high          | mean   |         273 |             2 |  3.49678   |      3.86535    |    3.53346    |     4.22627   |    0.0279972  | 1        |
| pattern_without_cot         |        42 | prestop_mfe_low   | mean   |         273 |             2 |  2.58561   |      2.53805    |    2.23181    |     2.86678   |    0.774323   | 1        |
| pattern_without_cot         |        42 | stop_conservative | mean   |         273 |             2 |  0.714286  |      0.758242   |    0.714286   |     0.798535  |    0.0677932  | 1        |
| pattern_without_cot         |        42 | return_unstopped  | mean   |         273 |             2 |  0.127859  |     -0.534408   |   -1.01223    |    -0.0597724 |    0.00459954 | 0.418558 |
| pattern_without_cot         |        42 | return_stopped    | mean   |         273 |             2 |  0.103138  |     -0.0879784  |   -0.379645   |     0.221115  |    0.221978   | 1        |


## Clustered uncertainty

|   horizon | metric           |   blocks |       mean |        low |     high |
|----------:|:-----------------|---------:|-----------:|-----------:|---------:|
|         5 | return_unstopped |       53 |  0.0579531 | -0.0978469 | 0.222822 |
|         5 | return_stopped   |       53 |  0.0260027 | -0.12268   | 0.175943 |
|         5 | prestop_mfe_low  |       53 |  1.09455   |  0.996165  | 1.19627  |
|        10 | return_unstopped |       53 | -0.0570313 | -0.290553  | 0.186356 |
|        10 | return_stopped   |       53 | -0.0375091 | -0.225318  | 0.145268 |
|        10 | prestop_mfe_low  |       53 |  1.47539   |  1.3611    | 1.59145  |
|        21 | return_unstopped |       53 |  0.0735282 | -0.324988  | 0.473054 |
|        21 | return_stopped   |       53 |  0.0606122 | -0.204342  | 0.339254 |
|        21 | prestop_mfe_low  |       53 |  1.97361   |  1.78491   | 2.17429  |
|        42 | return_unstopped |       53 |  0.137676  | -0.640224  | 0.901497 |
|        42 | return_stopped   |       53 |  0.107262  | -0.310806  | 0.531307 |
|        42 | prestop_mfe_low  |       53 |  2.58221   |  2.24235   | 2.94719  |