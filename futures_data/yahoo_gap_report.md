# Yahoo gap probe (read-only)

Ratio = (archive or vendor close) / (Yahoo close). 1.000 means same contract and same price level.

| market | price symbol | Yahoo bars in gap | ratio before gap (archive/Yahoo) | ratio after gap (vendor/Yahoo) | biggest Yahoo move 11-06..11-16 vs typical | verdict |
|---|---|---|---|---|---|---|
| ZW | ZW | 5 | 1.0000 | 1.0000 | 2.5% vs 1.2% | CLEAN |
| KE | KE | 5 | 1.0000 | 1.0000 | 2.7% vs 1.1% | CLEAN |
| ZC | ZC | 5 | 1.0280 | 1.0299 | 2.2% vs 0.7% | level mismatch: do not use |
| ZS | ZS | 5 | 1.0083 | 1.0000 | 3.6% vs 0.5% | level mismatch: do not use |
| ZL | ZL | 5 | 1.0000 | 1.0000 | 2.5% vs 0.9% | CLEAN |
| ZB | US | 5 | 1.0000 | 1.0000 | 1.2% vs 0.5% | CLEAN |
| UB | UB | 5 | 1.0000 | 1.0000 | 1.4% vs 0.5% | CLEAN |
| HO | HO | 5 | 0.9378 | 0.9410 | 4.1% vs 1.3% | level mismatch: do not use |
| NG | NG | 5 | 1.0000 | 1.0000 | 7.3% vs 1.7% | levels match but a big move/roll jump in the window: check |
| ZM | ZM | 5 | 1.0000 | 1.0000 | 1.8% vs 1.0% | CLEAN |
| CT | CT | 5 | 1.0000 | 1.0000 | 2.3% vs 0.8% | CLEAN |
| ZT | ZT | 5 | 0.9988 | 0.9988 | 0.3% vs 0.0% | CLEAN |
| ZN | ZN | 5 | 1.0000 | 1.0000 | 0.8% vs 0.2% | CLEAN |
| TN | TN | 5 | 1.0000 | 1.0000 | 0.9% vs 0.3% | CLEAN |
| ZF | ZF | 5 | 1.0000 | 1.0000 | 0.6% vs 0.1% | CLEAN |
| ZQ | ZQ | 5 | 1.0000 | 1.0000 | 0.0% vs 0.0% | CLEAN |
| HE | HE | 5 | 1.1069 | 1.0984 | 4.4% vs 0.9% | level mismatch: do not use |
| LE | LE | 5 | 1.0185 | 1.0188 | 1.4% vs 0.7% | level mismatch: do not use |
| GF | GF | 5 | 0.9877 | 0.9873 | 1.9% vs 0.5% | level mismatch: do not use |
| CL | CL | 5 | 0.9873 | 0.9886 | 4.4% vs 2.0% | level mismatch: do not use |
| BZ | BZ | 5 | 1.0000 | 1.0000 | 5.8% vs 1.3% | level mismatch: do not use |
| CC | CC | 5 | 1.0182 | 1.0283 | 5.2% vs 1.5% | level mismatch: do not use |
| PL | PL | 5 | 0.9985 | 1.0002 | 2.7% vs 1.3% | CLEAN |
| SB | SB | 5 | 1.0000 | 1.0000 | 2.2% vs 1.3% | CLEAN |
| KC | KC | 5 | 0.9819 | 0.9804 | 4.2% vs 1.4% | level mismatch: do not use |
| SI | SI | 5 | 1.0032 | 1.0013 | 4.6% vs 1.5% | level mismatch: do not use |
| HG | HG | 5 | 1.0195 | 1.0173 | 1.8% vs 0.7% | level mismatch: do not use |
| GC | GC | 5 | 1.0000 | 1.0000 | 2.9% vs 0.7% | CLEAN |
| 6C | AD | 5 | 1.0013 | 1.0000 | 0.5% vs 0.2% | CLEAN |
| 6S | E1 | 5 | 1.0000 | 1.0000 | 1.0% vs 0.3% | CLEAN |
| 6M | MP | 5 | 0.9980 | 1.0000 | 0.8% vs 0.4% | level mismatch: do not use |
| 6B | B6 | 5 | 1.0000 | 1.0000 | 0.7% vs 0.2% | CLEAN |
| 6J | J1 | 5 | 1.0022 | 0.9999 | 0.7% vs 0.2% | CLEAN |
| DX | DX | none | | | | NO YAHOO DATA |
| 6E | E6 | 5 | 1.0012 | 1.0000 | 0.7% vs 0.2% | CLEAN |
| 6L | BR | 5 | 1.0000 | 1.0000 | 2.4% vs 0.5% | level mismatch: do not use |
| RB | RB | 5 | 0.9841 | 0.9939 | 4.5% vs 1.4% | level mismatch: do not use |
| 6N | N6 | 5 | 1.0000 | 1.0000 | 1.6% vs 0.3% | levels match but a big move/roll jump in the window: check |
| VX | VX | none | | | | NO YAHOO DATA |
| YM | YM | 5 | 1.0000 | 1.0000 | 2.2% vs 0.5% | levels match but a big move/roll jump in the window: check |
| SR3 | SR3 | 0 | nan | 1.0000 | 0.0% vs nan% | incomplete (0 of 5 gap days) |
| SR1 | SR1 | 0 | nan | 0.9983 | 0.0% vs nan% | incomplete (0 of 5 gap days) |
| ES | ES | 5 | 1.0000 | 1.0000 | 2.3% vs 0.5% | levels match but a big move/roll jump in the window: check |
| MES | MES | 5 | 1.0000 | 1.0000 | 2.3% vs 0.5% | levels match but a big move/roll jump in the window: check |
| NQ | NQ | 5 | 1.0000 | 1.0000 | 3.4% vs 0.7% | levels match but a big move/roll jump in the window: check |
| MNQ | MNQ | 5 | 1.0000 | 1.0000 | 3.4% vs 0.7% | levels match but a big move/roll jump in the window: check |
| 6A | A6 | 5 | 0.9994 | 1.0000 | 0.9% vs 0.3% | CLEAN |
| RTY | RTY | 5 | 1.0000 | 1.0000 | 3.2% vs 0.5% | levels match but a big move/roll jump in the window: check |

CLEAN markets (21 of 48): ZW, KE, ZL, ZB, UB, ZM, CT, ZT, ZN, TN, ZF, ZQ, PL, SB, GC, 6C, 6S, 6B, 6J, 6E, 6A.
