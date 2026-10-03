from psycopg2.extras import execute_values

UPSERT_SHIPMENTS = """
INSERT INTO shipments (partner_id, tracking_no, status, origin, destination, eta, source_updated_at)
VALUES %s
ON CONFLICT (partner_id, tracking_no) DO UPDATE SET
    status = EXCLUDED.status,
    origin = EXCLUDED.origin,
    destination = EXCLUDED.destination,
    eta = EXCLUDED.eta,
    source_updated_at = EXCLUDED.source_updated_at,
    loaded_at = now()
WHERE shipments.source_updated_at IS DISTINCT FROM EXCLUDED.source_updated_at
"""

INSERT_EVENTS = """
INSERT INTO shipment_events (shipment_id, status, location, event_ts)
VALUES %s
ON CONFLICT (shipment_id, event_ts, status) DO NOTHING
"""


def load_partner(cur, partner_id, records):
    """Upsert shipments + append new events. `records` = [(shipment, events), ...].
    Returns number of new events inserted. Caller owns the transaction."""
    if not records:
        return 0
    # the same tracking number can appear twice in one run if the source shifts pages mid-run
    latest = {}
    for shipment, events in records:
        latest[shipment["tracking_no"]] = (shipment, events)
    records = list(latest.values())

    execute_values(cur, UPSERT_SHIPMENTS, [
        (partner_id, s["tracking_no"], s["status"], s["origin"], s["destination"],
         s["eta"], s["source_updated_at"])
        for s, _ in records
    ])

    cur.execute("SELECT tracking_no, shipment_id FROM shipments WHERE partner_id = %s AND tracking_no = ANY(%s)",
                (partner_id, list(latest)))
    ids = dict(cur.fetchall())

    rows = [(ids[s["tracking_no"]], e["status"], e["location"], e["event_ts"])
            for s, events in records for e in events]
    if not rows:
        return 0
    execute_values(cur, INSERT_EVENTS, rows)
    return cur.rowcount
