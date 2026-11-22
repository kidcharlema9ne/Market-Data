"""Which trading day should the price files contain by now? Shared by the daily gate, the futures updater and the ETF fetcher.

expected_day(now_et, settle_hour_minute, holidays): today if it is a trading day and the clock is at or after the settle time,
otherwise the previous trading day. Weekends are never trading days. Pass NYSE_HOLIDAYS for ETFs; for futures pass an empty set
(futures trade on some stock-market holidays, and the vendor probe handles the rest).
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SETTLE = time(16, 10)  # ETF official closing prints are final a few minutes after 4:00 pm ET
def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    """A fixed-date holiday on a Saturday is observed Friday, on a Sunday Monday."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def nyse_holidays_for_year(year):
    """NYSE full-day closures worked out from the rules (no list to maintain). Not predictable: one-off closures such as national days
    of mourning; the stale-price warning and the retrying timer cover those."""
    days = {
        _nth_weekday(year, 1, 0, 3),                 # Martin Luther King Jr. Day, third Monday of January
        _nth_weekday(year, 2, 0, 3),                 # Presidents Day, third Monday of February
        _easter(year) - timedelta(days=2),           # Good Friday
        _last_weekday(year, 5, 0),                   # Memorial Day, last Monday of May
        _observed(date(year, 7, 4)),                 # Independence Day
        _nth_weekday(year, 9, 0, 1),                 # Labor Day, first Monday of September
        _nth_weekday(year, 11, 3, 4),                # Thanksgiving, fourth Thursday of November
        _observed(date(year, 12, 25)),               # Christmas
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))       # Juneteenth, a market holiday since 2022
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:                      # New Year's Day on a Saturday is NOT observed on the Friday before
        days.add(_observed(new_year))
    return days


def nyse_holidays(first_year=2020, last_year=2045):
    out = set()
    for y in range(first_year, last_year + 1):
        out |= nyse_holidays_for_year(y)
    return out


NYSE_HOLIDAYS = nyse_holidays()   # worked out from the rules for 2020 to 2045; nothing to update by hand


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
