"""One extractor + one normalizer per partner.

Extractors handle auth and pagination and yield raw JSON records.
Normalizers map a raw record to our common shape:
    ({tracking_no, status, origin, destination, eta, source_updated_at}, [events])
"""
import logging
from datetime import datetime, timezone

from etl import config
from etl.http import get_json, make_session

log = logging.getLogger(__name__)

CANONICAL = {"CREATED", "PICKED_UP", "IN_TRANSIT", "DELAYED", "OUT_FOR_DELIVERY", "DELIVERED", "EXCEPTION"}


def _check_status(status, source):
    if status not in CANONICAL:
        log.warning("unmapped status %r from %s -> UNKNOWN", status, source)
        return "UNKNOWN"
    return status


def _iso(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _epoch(value):
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _naive_utc(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if value else None


def _build(tracking_no, status, origin, destination, eta, updated, events):
    shipment = {
        "tracking_no": tracking_no, "status": status, "origin": origin,
        "destination": destination, "eta": eta, "source_updated_at": updated,
    }
    return shipment, events


# ---------------------------------------------------------------- FastFreight
FF_STATUS = {s: s for s in CANONICAL}


def fetch_fastfreight(since=None):
    session = make_session({"X-API-Key": config.FASTFREIGHT_API_KEY})
    page = 1
    while True:
        params = {"page": page, "page_size": config.PAGE_SIZE}
        if since:
            params["updated_since"] = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        body = get_json(session, f"{config.BASE_URL}/fastfreight/shipments", params)
        yield from body["data"]
        if page >= body["total_pages"]:
            break
        page += 1


def normalize_fastfreight(r):
    events = [
        {"status": _check_status(FF_STATUS.get(e["status"]), "fastfreight"),
         "location": e["location"], "event_ts": _iso(e["timestamp"])}
        for e in r["events"]
    ]
    return _build(r["tracking_number"], _check_status(FF_STATUS.get(r["status"]), "fastfreight"),
                  r["origin"], r["destination"], _iso(r["estimated_delivery"]),
                  _iso(r["updated_at"]), events)


# ------------------------------------------------------------------ OceanLink
OL_STATUS = {10: "CREATED", 20: "PICKED_UP", 30: "IN_TRANSIT", 35: "DELAYED",
             40: "OUT_FOR_DELIVERY", 50: "DELIVERED", 90: "EXCEPTION"}


def fetch_oceanlink(since=None):
    session = make_session({"Authorization": f"Bearer {config.OCEANLINK_TOKEN}"})
    offset = 0
    while True:
        params = {"offset": offset, "limit": config.PAGE_SIZE}
        if since:
            params["since_epoch"] = int(since.timestamp())
        body = get_json(session, f"{config.BASE_URL}/oceanlink/v2/tracking", params)
        yield from body["items"]
        offset += config.PAGE_SIZE
        if offset >= body["total"]:
            break


def normalize_oceanlink(r):
    events = [
        {"status": _check_status(OL_STATUS.get(e["code"]), "oceanlink"),
         "location": e["loc"], "event_ts": _epoch(e["ts"])}
        for e in r["history"]
    ]
    return _build(r["consignmentId"], _check_status(OL_STATUS.get(r["stateCode"]), "oceanlink"),
                  r["route"]["from"], r["route"]["to"], _epoch(r["etaEpoch"]),
                  _epoch(r["lastEventEpoch"]), events)


# ------------------------------------------------------------------- QuickHaul
QH_STATUS = {"Label created": "CREATED", "Picked up": "PICKED_UP", "In transit": "IN_TRANSIT",
             "Delayed": "DELAYED", "Out for delivery": "OUT_FOR_DELIVERY",
             "Delivered": "DELIVERED", "Delivery exception": "EXCEPTION"}


def fetch_quickhaul(since=None):
    session = make_session({"Authorization": f"Token {config.QUICKHAUL_TOKEN}"})
    cursor = None
    while True:
        params = {"limit": config.PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        if since:
            params["modified_after"] = since.strftime("%Y-%m-%d %H:%M:%S")
        body = get_json(session, f"{config.BASE_URL}/quickhaul/api/shipments", params)
        yield from body["shipments"]
        cursor = body["next_cursor"]
        if not cursor:
            break


def _city(d):
    return f"{d['city']}, {d['state']}"


def normalize_quickhaul(r):
    events = [
        {"status": _check_status(QH_STATUS.get(e["state"]), "quickhaul"),
         "location": e["city"], "event_ts": _naive_utc(e["time"])}
        for e in r["tracking"]
    ]
    return _build(r["shipment"]["id"], _check_status(QH_STATUS.get(r["shipment"]["state"]), "quickhaul"),
                  _city(r["origin"]), _city(r["destination"]), _naive_utc(r["eta"]),
                  _naive_utc(r["updated"]), events)


PARTNER_FUNCS = {
    "fastfreight": (fetch_fastfreight, normalize_fastfreight),
    "oceanlink": (fetch_oceanlink, normalize_oceanlink),
    "quickhaul": (fetch_quickhaul, normalize_quickhaul),
}
