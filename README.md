# Market Data

Michael's market data: daily futures prices (and equity price archives) stored in Cloudflare R2, plus the
workflows that load and refresh them and the alert senders that need the shared Gmail and Pushover secrets.

[Michael's GitHub master index](https://github.com/kidcharlema9ne/Master-Index) locates projects by nickname.

- [FUTURES_DATA.md](FUTURES_DATA.md): where the daily futures prices live and how to fetch them (any futures task starts here).
- [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md): Cloudflare R2 bucket `insider-research` and how Actions reaches it.
- `marketparquet_archive_transfer.py` and the `marketparquet-*.yml` workflows: load MarketParquet futures and equity data into R2.
- `futures_data/`: builds the continuous futures price set from R2.
- `spy_qqq_live/` with `spy-qqq-delivery.yml`, plus `ig-gmail.yml` and the Pushover workflows: alert senders. They live here because the Gmail and Pushover secrets are stored in this repo.

The insider buying research study now lives in [insider-scanner](https://github.com/kidcharlema9ne/insider-scanner)
(see `research_docs/` there). This repo's earlier history still holds the study's original commits and Actions run records.
