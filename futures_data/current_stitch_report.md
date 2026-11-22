# Stitched current futures (rebased with the vendor roll file)

Stored files: 4906; R2 write times 2026-11-08 .. 2026-11-21; newest stored day 2026-11-06.
Roll file: 90 rolls, 2026-09-07 .. 2026-11-20.

Stored-file write dates (count of files written per day, last 25 write days):

- 2026-11-08: 4886
- 2026-11-12: 1
- 2026-11-13: 1
- 2026-11-14: 3
- 2026-11-19: 2
- 2026-11-21: 13

## Rolls after the newest stored day, per market, and the factor applied to its newest stored day

| market | roll date | ratio | detected | files already written after detection | factor on newest stored day |
|---|---|---|---|---|---|
| ZC (ZC) | 2026-11-18 | 1.0280 | 2026-11-19T04:59 | 100% | 1.0000 |
| HO (HO) | 2026-11-16 | 0.9378 | 2026-11-17T04:58 | 100% | 1.0000 |
| HE (HE) | 2026-11-16 | 1.1069 | 2026-11-17T04:58 | 100% | 1.0000 |
| LE (LE) | 2026-11-13 | 1.0185 | 2026-11-14T04:59 | 100% | 1.0000 |
| GF (GF) | 2026-11-09 | 0.9877 | 2026-11-10T04:58 | 100% | 1.0000 |
| CL (CL) | 2026-11-12 | 0.9873 | 2026-11-13T04:57 | 100% | 1.0000 |
| KC (KC) | 2026-11-18 | 0.9819 | 2026-11-19T04:59 | 100% | 1.0000 |
| HG (HG) | 2026-11-17 | 1.0158 | 2026-11-18T04:58 | 100% | 1.0000 |
| RB (RB) | 2026-11-11 | 0.9841 | 2026-11-12T04:57 | 100% | 1.0000 |
| VX (VX) | 2026-11-09 | 0.9362 | 2026-11-10T04:58 | 100% | 1.0000 |

## Seam check at rolls already inside the stored data (after rebasing)

return = ln(next day close / roll day close) in the stitched series; a seam shows as return close to ln(ratio) with |ln(ratio)| well above the market's typical daily move.

| market | roll date | ln(ratio) | return across roll | typical daily move | verdict |
|---|---|---|---|---|---|
| ZS | 2026-11-02 | +0.977% | -0.226% | 0.541% | ok |
| ZL | 2026-09-28 | +0.633% | +1.090% | 1.109% | ok |
| NG | 2026-09-21 | +4.999% | +4.461% | 1.481% | POSSIBLE SEAM |
| NG | 2026-10-23 | +14.436% | -0.922% | 1.614% | ok |
| CT | 2026-09-21 | +3.915% | -0.205% | 1.040% | ok |
| HE | 2026-09-14 | -12.691% | -0.661% | 0.804% | ok |
| LE | 2026-09-11 | +1.154% | +1.308% | 0.600% | ok |
| GF | 2026-09-08 | -1.047% | -0.821% | 0.628% | ok |
| GF | 2026-10-09 | -0.936% | -0.249% | 0.742% | ok |
| CL | 2026-09-11 | -4.196% | +0.302% | 2.048% | ok |
| CL | 2026-10-13 | -0.944% | +0.780% | 2.027% | ok |
| BZ | 2026-09-21 | -4.931% | -1.095% | 1.944% | ok |
| BZ | 2026-10-23 | -4.397% | -0.863% | 1.760% | ok |
| CC | 2026-11-03 | +1.787% | +0.904% | 1.358% | ok |
| PL | 2026-09-21 | +1.149% | +1.330% | 1.272% | ok |
| SB | 2026-09-21 | +5.368% | +0.649% | 1.176% | ok |
| 6S | 2026-09-08 | +1.026% | -0.168% | 0.271% | ok |
| 6M | 2026-09-08 | -0.730% | +0.102% | 0.225% | ok |
| 6J | 2026-09-08 | +0.705% | +0.030% | 0.135% | ok |
| VX | 2026-09-08 | +10.135% | +3.359% | 1.938% | ok |
| VX | 2026-10-09 | +2.155% | -1.394% | 1.549% | ok |
| YM | 2026-09-14 | +0.786% | -0.622% | 0.366% | ok |
| ES | 2026-09-11 | +0.881% | -0.447% | 0.453% | ok |
| MES | 2026-09-14 | +0.885% | -0.479% | 0.446% | ok |
| NQ | 2026-09-11 | +1.006% | -0.794% | 0.960% | ok |
| MNQ | 2026-09-08 | +0.995% | -0.311% | 1.004% | ok |
| RTY | 2026-09-08 | +0.736% | -1.383% | 0.615% | ok |

Possible seams at past rolls: 1.

## Final series per market

| market | last day | last source | rebased days | days across gap 11-06 to 11-16 |
|---|---|---|---|---|
| ZW (ZW) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| KE (KE) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZC (ZC) | 2026-11-20 | vendor_public | 4709 | 5 of 5 |
| ZS (ZS) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZL (ZL) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZB (US) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| UB (UB) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| HO (HO) | 2026-11-20 | vendor_public | 4698 | 5 of 5 |
| NG (NG) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZM (ZM) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| CT (CT) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZT (ZT) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZN (ZN) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| TN (TN) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZF (ZF) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| ZQ (ZQ) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| HE (HE) | 2026-11-20 | vendor_public | 4716 | 5 of 5 |
| LE (LE) | 2026-11-20 | vendor_public | 4716 | 5 of 5 |
| GF (GF) | 2026-11-20 | vendor_public | 4716 | 5 of 5 |
| CL (CL) | 2026-11-20 | vendor_public | 4730 | 5 of 5 |
| BZ (BZ) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| CC (CC) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| PL (PL) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| SB (SB) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| KC (KC) | 2026-11-20 | vendor_public | 4733 | 5 of 5 |
| SI (SI) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| HG (HG) | 2026-11-20 | vendor_public | 4734 | 5 of 5 |
| GC (GC) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6C (AD) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6S (E1) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6M (MP) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6B (B6) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6J (J1) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| DX (DX) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6E (E6) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6L (BR) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| RB (RB) | 2026-11-20 | vendor_public | 4700 | 5 of 5 |
| 6N (N6) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| VX (VX) | 2026-11-20 | vendor_public | 4598 | 5 of 5 |
| YM (YM) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| SR3 (SR3) | 2026-11-20 | vendor_public | 0 | 0 of 5 |
| SR1 (SR1) | 2026-11-20 | vendor_public | 0 | 0 of 5 |
| ES (ES) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| MES (MES) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| NQ (NQ) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| MNQ (MNQ) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| 6A (A6) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
| RTY (RTY) | 2026-11-20 | vendor_public | 0 | 5 of 5 |
