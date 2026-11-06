# Infrastructure

| Component | Decision or status |
| --- | --- |
| Source control | Private GitHub repository for documentation, Python code, and GitHub Actions. |
| Historical dataset storage | Cloudflare R2 Standard. Intended private bucket is `insider-research`. The GitHub Actions connection passed on November 6, 2026. [Run 42201493380](https://github.com/kidcharlema9ne/insider-buying-research/actions/runs/42201493380) verified upload, byte-for-byte readback, deletion, and absence of the test object afterward. |
| Price archive | Parquet with daily OHLCV, delisted securities, and point-in-time security identifiers where available. Plan one acquisition of about 20 years. Provider, exact coverage, size, cost, and layout are pending verification. |
| Archive maintenance | May freeze the archive after the historical study. |
| Database | Database engine, schema deployment, and location are undecided. R2 stores objects. |
| Computation | Python research programs and GitHub Actions run the computation. R2 provides storage. |
| Scanner | Separate SEC Form 4 scanner fetches current price and volume as needed and delivers alerts via Pushover. Scanner filters do not define the research universe. |
| Reports | Google Drive is a candidate for human-readable reports. Final report location is open. |

## R2 setup and verification

1. Create or verify the private Standard bucket and confirm account terms before enabling any paid service.
2. Create an Object Read & Write credential limited to this bucket. Save the values in repository Actions secrets `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`. Supply the account S3 endpoint as `R2_ENDPOINT_URL`. Keep credentials out of files, chat, and logs.
3. Configure the Python boto3 client to use the account's S3 endpoint and the bucket. Upload a small object under a unique test key, read it back and compare bytes, delete it, and verify the key is absent.
4. Verify the provider, including pre-failure LEH and original Washington Mutual WM, identifier mapping, and the archive's scope and cost before requesting authorization for acquisition.

No paid services, purchases, bulk downloads, or large compute jobs are authorized by this setup.

## Historical research validation

- The historical SEC archive workflow stores original quarterly ZIPs under `sec/insider-transactions/quarterly-original-zips/`. The downstream SEC-to-prices preparation workflow builds a SQLite candidate snapshot at `sec/insider-transactions/derived/purchase_candidates.sqlite3` and checks the downloaded bytes against the stored SHA-256 before auditing. The current snapshot scope is 2006 Q1 through 2026 Q3.
- The Free-year research smoke test uses the existing bucket-scoped Actions secrets. It reads the pinned original GameStop filing and verified daily partitions under `samples/marketparquet/stock_daily/`, checks them against an XNYS session calendar and publishes HTML and JSON as the `real-data-research-smoke` artifact. This workflow has a single pinned security identity and exercises price-only calculations.
- Record live run conclusions and scope in [development status](DEVELOPMENT_STATUS.md).
