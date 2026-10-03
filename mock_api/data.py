"""Deterministic fake shipment data.

Shipment state is a pure function of (partner, index, now), so every call to the
mock API returns slightly newer statuses -- the same thing a real tracking API does.
"""
import random
from datetime import datetime, timedelta, timezone

CITIES = [
    "Charlotte, NC", "Dallas, TX", "Atlanta, GA", "Chicago, IL", "Newark, NJ",
    "Los Angeles, CA", "Houston, TX", "Memphis, TN", "Seattle, WA", "Miami, FL",
]
STAGES = ["CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"]
PARTNERS = {"fastfreight": "FF", "oceanlink": "OL", "quickhaul": "QH"}
SHIPMENTS_PER_PARTNER = 40
CYCLE_HOURS = 168  # a shipment slot is reused every week with a new tracking number


def _build_one(partner, idx, cycle, now):
    rng = random.Random(f"{partner}-{idx}")  # per-slot constants
    phase = rng.randint(0, CYCLE_HOURS - 1)
    stage_hours = [rng.randint(4, 16) for _ in STAGES[1:]]
    origin, dest = rng.sample(CITIES, 2)
    delayed = rng.random() < 0.15  # ~15% get stuck in a DELAYED state mid-route
    delay_hours = rng.randint(12, 36) if delayed else 0
    broken = rng.random() < 0.03   # ~3% end in EXCEPTION (lost / damaged)

    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=phase)
    start = anchor + timedelta(hours=CYCLE_HOURS * cycle)

    events = [(STAGES[0], origin, start)]
    t = start
    for i, stage in enumerate(STAGES[1:]):
        t = t + timedelta(hours=stage_hours[i])
        if stage == "OUT_FOR_DELIVERY" and delayed:
            events.append(("DELAYED", "In transit hub", t))
            t = t + timedelta(hours=delay_hours)
        if stage == "DELIVERED" and broken:
            events.append(("EXCEPTION", dest, t))
            break
        loc = origin if stage == "PICKED_UP" else dest if stage in ("OUT_FOR_DELIVERY", "DELIVERED") else "Regional hub"
        events.append((stage, loc, t))

    eta = start + timedelta(hours=sum(stage_hours))
    seen = [e for e in events if e[2] <= now]
    if not seen:
        return None
    return {
        "tracking_no": f"{PARTNERS[partner]}{idx:03d}{cycle % 1000:03d}",
        "origin": origin,
        "destination": dest,
        "eta": eta,
        "status": seen[-1][0],
        "updated": seen[-1][2],
        "events": [{"status": s, "location": l, "ts": ts} for s, l, ts in seen],
    }


def build_shipments(partner, now=None, updated_since=None):
    now = now or datetime.now(timezone.utc)
    out = []
    for idx in range(SHIPMENTS_PER_PARTNER):
        phase = random.Random(f"{partner}-{idx}").randint(0, CYCLE_HOURS - 1)
        anchor = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=phase)
        current = int((now - anchor).total_seconds() // 3600 // CYCLE_HOURS)
        for cycle in (current - 1, current):
            s = _build_one(partner, idx, cycle, now)
            if s and (updated_since is None or s["updated"] > updated_since):
                out.append(s)
    out.sort(key=lambda s: (s["updated"], s["tracking_no"]))
    return out
