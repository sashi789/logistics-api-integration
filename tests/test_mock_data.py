from datetime import datetime, timedelta, timezone

from mock_api.data import SHIPMENTS_PER_PARTNER, build_shipments

NOW = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)


def test_deterministic():
    assert build_shipments("fastfreight", NOW) == build_shipments("fastfreight", NOW)


def test_tracking_numbers_unique():
    nums = [s["tracking_no"] for s in build_shipments("quickhaul", NOW)]
    assert len(nums) == len(set(nums)) and len(nums) <= SHIPMENTS_PER_PARTNER * 2


def test_status_moves_forward_over_time():
    later = NOW + timedelta(hours=6)
    before = {s["tracking_no"]: len(s["events"]) for s in build_shipments("oceanlink", NOW)}
    after = {s["tracking_no"]: len(s["events"]) for s in build_shipments("oceanlink", later)}
    assert any(after.get(k, 0) > v for k, v in before.items())


def test_updated_since_filters():
    all_rows = build_shipments("fastfreight", NOW)
    cutoff = all_rows[len(all_rows) // 2]["updated"]
    assert all(s["updated"] > cutoff for s in build_shipments("fastfreight", NOW, updated_since=cutoff))
