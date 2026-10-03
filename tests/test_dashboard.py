"""Dashboard rendering tests: no database needed, the data dict is built by hand."""
from datetime import date, datetime, timezone

from etl import dashboard


def sample(partner="FastFreight Express", minutes=5.0):
    return {
        "status": [{"partner": partner, "status": "DELIVERED", "shipments": 8},
                   {"partner": partner, "status": "IN_TRANSIT", "shipments": 1},
                   {"partner": partner, "status": "EXCEPTION", "shipments": 1}],
        "delivery": [{"partner": partner, "delivered_shipments": 8, "avg_hours_to_deliver": 40.5}],
        "freshness": [{"partner": partner, "minutes_since_success": minutes, "failures_last_24h": 0}],
        "delayed": [{"partner": partner, "tracking_no": "T1", "status": "EXCEPTION", "origin": "A", "destination": "B",
                     "eta": None, "hours_past_eta": 12.0}],
        "daily": [{"partner": partner, "day": date(2026, 10, d), "events": d * 3} for d in (1, 2, 3)],
        "runs": [{"partner": partner, "started_at": datetime(2026, 10, 3, tzinfo=timezone.utc), "status": "SUCCESS",
                  "rows_fetched": 10, "events_loaded": 4}],
    }


def test_builds_complete_page():
    page = dashboard.build(sample())
    assert page.startswith("<!doctype html>") and "<svg" in page
    assert "80%" in page                       # 8 of 10 delivered
    assert "Fresh" in page and "Exception" in page


def test_stale_feed_is_flagged_with_label_not_just_color():
    assert "Stale" in dashboard.build(sample(minutes=90.0))


def test_partner_names_are_escaped():
    page = dashboard.build(sample(partner='<img src=x onerror="alert(1)">'))
    assert "<img src=x" not in page
    assert "&lt;img" in page


def test_nice_max_gives_round_axis():
    assert dashboard.nice_max(43.6) == 60
    assert dashboard.nice_max(0) == 1
