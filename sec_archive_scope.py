"""Expected published quarters for the current historical SEC snapshot."""

QUARTERS = frozenset(
    f"{year}q{quarter}_form345.zip"
    for year in range(2006, 2027)
    for quarter in range(1, 5)
    if (year, quarter) <= (2026, 3)
)


def missing_quarters(names):
    return sorted(QUARTERS.difference(names))
