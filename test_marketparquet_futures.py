"""Tests for the futures date rule in marketparquet_archive_transfer.py (no network)."""
import os
import sys
import types

# The transfer module imports boto3/pyarrow and needs R2 settings only when it runs;
# stub the two heavy imports so this test needs no packages and no secrets.
for name in ("boto3", "botocore", "botocore.exceptions", "pyarrow", "pyarrow.parquet"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["botocore.exceptions"].ClientError = Exception
sys.modules["pyarrow.parquet"].ParquetFile = object
sys.modules["boto3"].client = lambda *a, **k: None
os.environ.setdefault("R2_ENDPOINT_URL", "x")

from marketparquet_archive_transfer import dates_match  # noqa: E402


def test_stocks_must_match_exactly():
    assert dates_match({"2026-11-03"}, "2026-11-03", "stock_daily")
    assert not dates_match({"2026-11-02"}, "2026-11-03", "stock_daily")


def test_futures_accept_session_start_stamp():
    assert dates_match({"2026-11-03"}, "2026-11-03", "futures_daily")
    assert dates_match({"2026-11-02"}, "2026-11-03", "futures_daily")      # prior evening
    assert dates_match({"2026-10-30"}, "2026-11-02", "futures_daily")      # Friday evening -> Monday file


def test_futures_reject_wrong_or_future_dates():
    assert not dates_match({"2026-10-28"}, "2026-11-03", "futures_daily")  # too old
    assert not dates_match({"2026-11-04"}, "2026-11-03", "futures_daily")  # after file date
    assert not dates_match(set(), "2026-11-03", "futures_daily")


if __name__ == "__main__":
    for fn in (test_stocks_must_match_exactly, test_futures_accept_session_start_stamp, test_futures_reject_wrong_or_future_dates):
        fn()
    print("ok")
