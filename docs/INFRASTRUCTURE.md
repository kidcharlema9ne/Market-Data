# Infrastructure

- Store historical data in the private Cloudflare R2 Standard bucket intended as `insider-research`. Bucket setup and verification are pending. R2 provides object storage.
- Plan one acquisition of approximately 20 years of daily OHLCV in Parquet, including delisted securities and historical identifiers where available. Provider, coverage, size, cost, and dataset layout remain open. The archive may be frozen after the historical study.
- Python and GitHub Actions handle computation. Database engine and location remain open.
- The separate SEC scanner retrieves its own current price and volume data and delivers alerts via Pushover. Google Drive is a candidate for human-readable reports.
- Restrict R2 object read/write credentials to the project bucket. Store credentials in GitHub Actions secrets and keep them out of repository files, chat, and logs. Test upload, readback, and deletion with one temporary object.
- Paid services, data purchases, and bulk downloads require separate approval.
