"""Which trading day should the price files contain by now? Shared by the daily gate, the futures updater and the ETF fetcher.

expected_day(now_et, settle_hour_minute, holidays): today if it is a trading day and the clock is at or after the settle time,
otherwise the previous trading day. Weekends are never trading days. Pass NYSE_HOLIDAYS for ETFs; for futures pass an empty set
(futures trade on some stock-market holidays, and the vendor probe handles the rest).
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SETTLE = time(16, 10)  # ETF official closing prints are final a few minutes after 4:00 pm ET
NYSE_HOLIDAYS = {date.fromisoformat(d) for d in (
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26",
    "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24")}


def now_et():
    return datetime.now(ET)


def is_trading_day(d, holidays):
    return d.weekday() < 5 and d not in holidays


def expected_day(now, holidays=frozenset(), settle=SETTLE):
    d = now.date()
    if not (is_trading_day(d, holidays) and now.time() >= settle):
        d -= timedelta(days=1)
    while not is_trading_day(d, holidays):
        d -= timedelta(days=1)
    return d
