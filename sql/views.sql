CREATE OR REPLACE VIEW v_status_by_partner AS
SELECT p.name AS partner, s.status, COUNT(*) AS shipments
FROM shipments s JOIN partners p USING (partner_id)
GROUP BY p.name, s.status;

-- shipments flagged DELAYED/EXCEPTION, or still moving past their ETA
CREATE OR REPLACE VIEW v_delayed_shipments AS
SELECT p.name AS partner, s.tracking_no, s.status, s.origin, s.destination, s.eta,
       ROUND(EXTRACT(EPOCH FROM (now() - s.eta)) / 3600.0, 1) AS hours_past_eta
FROM shipments s JOIN partners p USING (partner_id)
WHERE s.status IN ('DELAYED', 'EXCEPTION')
   OR (s.status <> 'DELIVERED' AND s.eta < now());

-- hours from first event to delivery, per partner (for the partner scorecard)
CREATE OR REPLACE VIEW v_delivery_time AS
SELECT p.name AS partner,
       COUNT(*) AS delivered_shipments,
       ROUND(AVG(EXTRACT(EPOCH FROM (d.event_ts - f.event_ts)) / 3600.0), 1) AS avg_hours_to_deliver
FROM shipments s
JOIN partners p USING (partner_id)
JOIN LATERAL (SELECT MIN(event_ts) event_ts FROM shipment_events WHERE shipment_id = s.shipment_id) f ON TRUE
JOIN LATERAL (SELECT MAX(event_ts) event_ts FROM shipment_events
              WHERE shipment_id = s.shipment_id AND status = 'DELIVERED') d ON TRUE
WHERE s.status = 'DELIVERED' AND d.event_ts IS NOT NULL
GROUP BY p.name;

-- is each feed fresh? (SLA is 30 min between refreshes)
CREATE OR REPLACE VIEW v_feed_freshness AS
SELECT p.name AS partner,
       MAX(r.finished_at) FILTER (WHERE r.status = 'SUCCESS') AS last_success,
       ROUND(EXTRACT(EPOCH FROM (now() - MAX(r.finished_at) FILTER (WHERE r.status = 'SUCCESS'))) / 60.0, 1) AS minutes_since_success,
       COUNT(*) FILTER (WHERE r.status = 'FAILED' AND r.started_at > now() - interval '1 day') AS failures_last_24h
FROM partners p LEFT JOIN etl_run_log r USING (partner_id)
GROUP BY p.name;
