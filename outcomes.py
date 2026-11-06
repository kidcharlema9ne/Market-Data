"""Measure one already-qualified disclosure against a verified session calendar.

All prices and cash amounts must be on the same split-adjusted share basis.
Run as a module with a JSON input file, or use measure() from a data adapter.
"""
from bisect import bisect_right
from calendar import monthrange
from datetime import date, datetime, timezone
from math import isfinite
from statistics import mean
import argparse
import json


def _positive(value):
    return value is not None and isfinite(value) and value > 0


def _six_months(day):
    year, month = divmod(day.year * 12 + day.month - 1 + 6, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _metrics(value, entry, atr, issue=None):
    if issue:
        return {"pct": None, "atr": None, "issue": issue}
    change = value - entry
    return {
        "pct": 100 * change / entry,
        "atr": change / atr if atr else None,
        "issue": None,
    }


def measure(accepted_at, session_opens, bars, *, calendar_through,
            cash_dividends, dividend_coverage_through, atr_method):
    """Return all five horizons, retaining metric-specific missing values.

    session_opens is an authoritative, contiguous calendar of aware datetimes,
    with dates expressed in the exchange's local timezone. Supply enough
    calendar before the filing and through calendar_through (inclusive).
    bars maps session dates to OHLC dicts for one resolved security.
    cash_dividends maps ex-dates to verified per-share cash amounts. Its
    coverage date certifies completeness from entry through that date.
    Stop passing prices at unresolved terminal events. This kernel only
    measures ordinary listed paths and does not model terminal proceeds.
    """
    if atr_method != "simple_mean_14":
        raise ValueError("Only explicit simple_mean_14 smoke-test mode is implemented")
    if accepted_at.utcoffset() is None or any(
        opening.utcoffset() is None for opening in session_opens
    ):
        raise ValueError("Acceptance and session opens require timezones")
    days = [opening.date() for opening in session_opens]
    if days != sorted(set(days)) or (days and days[-1] > calendar_through):
        raise ValueError("Session dates must be unique, ordered and within coverage")
    openings = [opening.astimezone(timezone.utc) for opening in session_opens]
    index = bisect_right(openings, accepted_at.astimezone(timezone.utc))
    if index == 0 and openings:
        raise ValueError("Calendar must include at least one open before acceptance")
    entry_day = days[index] if index < len(days) else None
    entry = bars.get(entry_day, {}).get("open")
    entry_issue = None if _positive(entry) else (
        "missing_entry_open" if entry_day else "entry_outside_calendar"
    )

    ranges = []
    if entry_day and index >= 15:
        for prior in range(index - 14, index):
            bar = bars.get(days[prior], {})
            high, low = bar.get("high"), bar.get("low")
            close = bars.get(days[prior - 1], {}).get("close")
            if not all(map(_positive, (high, low, close))) or low > high:
                break
            ranges.append(max(high, close) - min(low, close))
    atr = mean(ranges) if len(ranges) == 14 else None
    atr_issue = None if atr else (
        "zero_atr" if atr == 0 else "insufficient_pre_entry_true_ranges"
    )

    stops = {str(n): index + n for n in (11, 21, 43, 64)}
    anniversary = _six_months(entry_day) if entry_day else None
    stops["6m"] = (
        bisect_right(days, anniversary)
        if anniversary and anniversary <= calendar_through else None
    )
    horizons = {}
    for label, stop in stops.items():
        end_day = days[stop - 1] if entry_day and stop and stop <= len(days) else None
        issue = entry_issue or (None if end_day else "horizon_outside_calendar")
        window = [bars.get(day, {}) for day in days[index:stop]] if end_day else []
        metrics = {}
        for name, field, extreme in (
            ("maximum_appreciation", "high", max),
            ("maximum_adverse_excursion", "low", min),
        ):
            values = [bar.get(field) for bar in window]
            metric_issue = issue or (
                None if all(map(_positive, values)) else f"missing_window_{field}"
            )
            value = extreme(values) if not metric_issue else None
            metrics[name] = _metrics(value, entry, atr, metric_issue)

        close = bars.get(end_day, {}).get("close")
        close_issue = issue or (None if _positive(close) else "missing_end_close")
        metrics["price_only_ending_return"] = _metrics(close, entry, atr, close_issue)
        ending_issue = close_issue
        total = None
        if not ending_issue:
            if dividend_coverage_through is None or dividend_coverage_through < end_day:
                ending_issue = "unverified_dividend_coverage"
            else:
                # Buying at the ex-date open does not confer that day's dividend.
                total = close + sum(
                    amount for day, amount in cash_dividends.items()
                    if entry_day < day <= end_day
                )
        metrics["ending_total_return"] = _metrics(total, entry, atr, ending_issue)
        horizons[label] = {"end_date": end_day, **metrics}

    return {
        "entry_date": entry_day, "entry_open": entry if not entry_issue else None,
        "entry_issue": entry_issue, "entry_atr": atr, "atr_issue": atr_issue,
        "atr_method": atr_method, "horizons": horizons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=argparse.FileType("r"),
                        help="JSON with opportunity_id and measure() arguments")
    args = parser.parse_args()
    data = json.load(args.input)
    opportunity_id = data.pop("opportunity_id")
    data["accepted_at"] = datetime.fromisoformat(data["accepted_at"])
    data["session_opens"] = list(map(datetime.fromisoformat, data["session_opens"]))
    for field in ("bars", "cash_dividends"):
        data[field] = {date.fromisoformat(day): value for day, value in data[field].items()}
    for field in ("calendar_through", "dividend_coverage_through"):
        if data[field] is not None:
            data[field] = date.fromisoformat(data[field])
    print(json.dumps({"opportunity_id": opportunity_id, **measure(**data)}, default=str))


if __name__ == "__main__":
    main()
