# Michael’s GitHub master index

Start here when Michael describes a system by nickname or remembers what it does. Last checked November 21, 2026. All repository names below belong to `kidcharlema9ne`. Private links require an assistant connection with access to the named repository.

## “Send it from my Gmail like the SPY test”

The live Gmail sender is in **insider-buying-research**. Open [insider-buying-research/.github/workflows/spy-qqq-close.yml](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/.github/workflows/spy-qqq-close.yml) for the secret mappings and [insider-buying-research/spy_qqq_live/check.py](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/spy_qqq_live/check.py) for the SPY email and Pushover implementation. The similarly named **spy-qqq-trend** holds strategy research.

| GitHub Actions secret name | Purpose |
|---|---|
| `SPYQQQ_GMAIL_ADDRESS` | Gmail sender and SMTP login |
| `SPYQQQ_GMAIL_APP_PASSWORD` | Gmail app password |
| `SPYQQQ_EMAIL_TO` | Email recipient |
| `PUSHOVER_TOKEN`, `PUSHOVER_USER` | Pushover application and recipient used by the SPY workflow |

[Repository Actions secret settings](https://github.com/kidcharlema9ne/insider-buying-research/settings/secrets/actions). These are names only. Keep values in secret storage. A new repo does not inherit these secrets. To reuse Gmail, run the mail step in the repo that already owns the credentials. For a working cross-repository PDF example, read [insider-buying-research/.github/workflows/ig-gmail.yml](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/.github/workflows/ig-gmail.yml). That sender specifically handles IG reports. For another report, adapt the pattern to its own data, recipient and delivery trigger.

## Find a project by what Michael calls it

| If Michael says… | Start here |
|---|---|
| IG sentiment, IG positioning, IG Bank report, percent long or short | [IG-Sentiment-Report/IG_SENTIMENT.md](https://github.com/kidcharlema9ne/IG-Sentiment-Report/blob/main/IG_SENTIMENT.md). Official archive is `data/ig_sentiment/history.csv`. The report is `reports/IG_Sentiment_latest.pdf`. |
| IG timer, 4:05 report, did the IG email go out? | [Active cron-job.org job 8887886](https://console.cron-job.org/jobs/8887886) dispatches [IG-Sentiment-Report/.github/workflows/ig-sentiment.yml](https://github.com/kidcharlema9ne/IG-Sentiment-Report/blob/main/.github/workflows/ig-sentiment.yml). Check the separate Gmail workflow above for delivery. The old COT repo contains an archive. |
| SPY/QQQ live signal, Monday status, 200-day alerts, trade email | [insider-buying-research/.github/workflows/spy-qqq-close.yml](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/.github/workflows/spy-qqq-close.yml). Live state and code are under `spy_qqq_live/`. |
| SPY/QQQ backtest, 3% bands, portfolio allocations | [spy-qqq-trend/README.md](https://github.com/kidcharlema9ne/spy-qqq-trend/blob/main/README.md). Core script is `spy_qqq_timing.py`. |
| COT report, commercials, large or small specs | [cot-history/RUN_REPORT.md](https://github.com/kidcharlema9ne/cot-history/blob/main/RUN_REPORT.md) for the report. [cot-history/COT_SYSTEM_MASTER.md](https://github.com/kidcharlema9ne/cot-history/blob/main/COT_SYSTEM_MASTER.md) for the trading system. |
| Futures prices, MarketParquet, historical daily futures, R2 | [insider-buying-research/FUTURES_DATA.md](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/FUTURES_DATA.md) for storage location and retrieval instructions. |
| Insider buying research, Form 4 backtests, clusters, CFO filters | [insider-buying-research/docs/LEADS_DIGEST.md](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/docs/LEADS_DIGEST.md) for findings. [insider-buying-research/AGENTS.md](https://github.com/kidcharlema9ne/insider-buying-research/blob/main/AGENTS.md) for the shared research log and reading order. |
| Live insider scanner, insider alerts | [insider-scanner/README.md](https://github.com/kidcharlema9ne/insider-scanner/blob/main/README.md). Scanner entry point is `insider_scanner.py`. |
| Stocktwits sentiment, Stock Twits report | [stocktwits-sentiment/README.md](https://github.com/kidcharlema9ne/stocktwits-sentiment/blob/main/README.md). See `symbols.txt`, `scraper.py` and `reports/`. |
| Contrarian trading alerts | [Contrarian-Trading-Alerts/README.md](https://github.com/kidcharlema9ne/Contrarian-Trading-Alerts/blob/main/README.md). See `scraper.py`. |
| Kalshi, prediction markets, perpetual funding scan | [Kalshi/README.md](https://github.com/kidcharlema9ne/Kalshi/blob/main/README.md). See `kalshi_scan.py` and `funding_scan.py`. |

## Keep this index useful

When creating or moving a system, add its plain-English nicknames, exact owner/repo, authoritative file and live workflow here. If scheduling, data and delivery live in different places, list each one. Link to secret names and settings only. For an unfamiliar nickname, check the owner’s current repository list and project READMEs before concluding the project is missing. If a private link fails, verify the assistant’s repository access.
