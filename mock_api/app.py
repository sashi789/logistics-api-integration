"""Fake carrier APIs. Three partners, three different response shapes, three auth styles.

Set MOCK_FLAKY_RATE=0.2 to make ~20% of requests fail with 503 (to exercise retries).
"""
import os
import random
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from mock_api.data import build_shipments

app = Flask(__name__)

FF_KEY = os.getenv("FASTFREIGHT_API_KEY", "ff-test-key")
OL_TOKEN = os.getenv("OCEANLINK_TOKEN", "ol-test-token")
QH_TOKEN = os.getenv("QUICKHAUL_TOKEN", "qh-test-token")
FLAKY_RATE = float(os.getenv("MOCK_FLAKY_RATE", "0"))


@app.before_request
def maybe_fail():
    if request.path != "/health" and random.random() < FLAKY_RATE:
        return jsonify(error="service unavailable"), 503, {"Retry-After": "1"}


@app.get("/health")
def health():
    return jsonify(status="ok")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


# ---- FastFreight: X-API-Key, page/page_size, ISO timestamps ----------------
@app.get("/fastfreight/shipments")
def fastfreight():
    if request.headers.get("X-API-Key") != FF_KEY:
        return jsonify(error="invalid api key"), 401
    page = int(request.args.get("page", 1))
    size = min(int(request.args.get("page_size", 25)), 50)
    rows = build_shipments("fastfreight", updated_since=_parse_iso(request.args.get("updated_since")))
    chunk = rows[(page - 1) * size: page * size]
    return jsonify({
        "page": page,
        "total_pages": max(1, -(-len(rows) // size)),
        "data": [{
            "tracking_number": s["tracking_no"],
            "status": s["status"],
            "origin": s["origin"],
            "destination": s["destination"],
            "estimated_delivery": _iso(s["eta"]),
            "updated_at": _iso(s["updated"]),
            "events": [{"status": e["status"], "location": e["location"], "timestamp": _iso(e["ts"])}
                       for e in s["events"]],
        } for s in chunk],
    })


# ---- OceanLink: Bearer token, offset/limit, epoch seconds, numeric codes ----
OL_CODES = {"CREATED": 10, "PICKED_UP": 20, "IN_TRANSIT": 30, "DELAYED": 35,
            "OUT_FOR_DELIVERY": 40, "DELIVERED": 50, "EXCEPTION": 90}


@app.get("/oceanlink/v2/tracking")
def oceanlink():
    if request.headers.get("Authorization") != f"Bearer {OL_TOKEN}":
        return jsonify(message="unauthorized"), 401
    offset = int(request.args.get("offset", 0))
    limit = min(int(request.args.get("limit", 25)), 50)
    since = request.args.get("since_epoch")
    since_dt = datetime.fromtimestamp(int(since), tz=timezone.utc) if since else None
    rows = build_shipments("oceanlink", updated_since=since_dt)
    chunk = rows[offset: offset + limit]
    return jsonify({
        "offset": offset, "limit": limit, "total": len(rows),
        "items": [{
            "consignmentId": s["tracking_no"],
            "stateCode": OL_CODES[s["status"]],
            "route": {"from": s["origin"], "to": s["destination"]},
            "etaEpoch": int(s["eta"].timestamp()),
            "lastEventEpoch": int(s["updated"].timestamp()),
            "history": [{"code": OL_CODES[e["status"]], "loc": e["location"], "ts": int(e["ts"].timestamp())}
                        for e in s["events"]],
        } for s in chunk],
    })


# ---- QuickHaul: "Token" auth, cursor paging, nested objects, text statuses --
QH_STATES = {"CREATED": "Label created", "PICKED_UP": "Picked up", "IN_TRANSIT": "In transit",
             "DELAYED": "Delayed", "OUT_FOR_DELIVERY": "Out for delivery",
             "DELIVERED": "Delivered", "EXCEPTION": "Delivery exception"}


def _qh_time(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")  # naive UTC, no timezone marker


@app.get("/quickhaul/api/shipments")
def quickhaul():
    if request.headers.get("Authorization") != f"Token {QH_TOKEN}":
        return jsonify(detail="Authentication credentials were not provided."), 401
    cursor = int(request.args.get("cursor") or 0)
    limit = min(int(request.args.get("limit", 25)), 50)
    modified_after = request.args.get("modified_after")
    since_dt = datetime.strptime(modified_after, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) \
        if modified_after else None
    rows = build_shipments("quickhaul", updated_since=since_dt)
    chunk = rows[cursor: cursor + limit]
    nxt = cursor + limit
    return jsonify({
        "next_cursor": str(nxt) if nxt < len(rows) else None,
        "shipments": [{
            "shipment": {"id": s["tracking_no"], "state": QH_STATES[s["status"]]},
            "origin": dict(zip(("city", "state"), s["origin"].split(", "))),
            "destination": dict(zip(("city", "state"), s["destination"].split(", "))),
            "eta": _qh_time(s["eta"]),
            "updated": _qh_time(s["updated"]),
            "tracking": [{"state": QH_STATES[e["status"]], "city": e["location"], "time": _qh_time(e["ts"])}
                         for e in s["events"]],
        } for s in chunk],
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5050")))
