from datetime import datetime, timezone

import pytest

from etl.partners import normalize_fastfreight, normalize_oceanlink, normalize_quickhaul

T = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def test_fastfreight():
    raw = {"tracking_number": "FF001", "status": "IN_TRANSIT", "origin": "Dallas, TX",
           "destination": "Newark, NJ", "estimated_delivery": "2026-03-02T12:00:00Z",
           "updated_at": "2026-03-01T12:00:00Z",
           "events": [{"status": "CREATED", "location": "Dallas, TX", "timestamp": "2026-03-01T00:00:00Z"}]}
    s, events = normalize_fastfreight(raw)
    assert s["tracking_no"] == "FF001" and s["status"] == "IN_TRANSIT"
    assert s["source_updated_at"] == T
    assert events[0]["status"] == "CREATED"


def test_oceanlink_maps_numeric_codes_and_epochs():
    raw = {"consignmentId": "OL001", "stateCode": 35, "route": {"from": "Miami, FL", "to": "Seattle, WA"},
           "etaEpoch": int(T.timestamp()), "lastEventEpoch": int(T.timestamp()),
           "history": [{"code": 10, "loc": "Miami, FL", "ts": int(T.timestamp())}]}
    s, events = normalize_oceanlink(raw)
    assert s["status"] == "DELAYED"
    assert s["origin"] == "Miami, FL" and s["eta"] == T
    assert events[0]["status"] == "CREATED"


def test_quickhaul_maps_text_status_and_naive_timestamps():
    raw = {"shipment": {"id": "QH001", "state": "Out for delivery"},
           "origin": {"city": "Memphis", "state": "TN"}, "destination": {"city": "Atlanta", "state": "GA"},
           "eta": "2026-03-01 12:00:00", "updated": "2026-03-01 12:00:00",
           "tracking": [{"state": "Picked up", "city": "Memphis", "time": "2026-03-01 12:00:00"}]}
    s, events = normalize_quickhaul(raw)
    assert s["status"] == "OUT_FOR_DELIVERY"
    assert s["destination"] == "Atlanta, GA"
    assert s["source_updated_at"] == T and events[0]["status"] == "PICKED_UP"


def test_unknown_status_becomes_unknown(caplog):
    raw = {"consignmentId": "OL9", "stateCode": 77, "route": {"from": "a", "to": "b"},
           "etaEpoch": 0, "lastEventEpoch": int(T.timestamp()), "history": []}
    s, _ = normalize_oceanlink(raw)
    assert s["status"] == "UNKNOWN"
    assert "unmapped status" in caplog.text


def test_missing_field_raises_keyerror():
    with pytest.raises(KeyError):
        normalize_fastfreight({"tracking_number": "x"})
