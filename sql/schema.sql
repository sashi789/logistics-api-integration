CREATE TABLE IF NOT EXISTS partners (
    partner_id  SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL
);

INSERT INTO partners (code, name) VALUES
    ('fastfreight', 'FastFreight Express'),
    ('oceanlink',   'OceanLink Cargo'),
    ('quickhaul',   'QuickHaul Logistics')
ON CONFLICT (code) DO NOTHING;

-- one row per shipment, holds the latest known state
CREATE TABLE IF NOT EXISTS shipments (
    shipment_id        BIGSERIAL PRIMARY KEY,
    partner_id         INT NOT NULL REFERENCES partners(partner_id),
    tracking_no        TEXT NOT NULL,
    status             TEXT NOT NULL,
    origin             TEXT,
    destination        TEXT,
    eta                TIMESTAMPTZ,
    source_updated_at  TIMESTAMPTZ NOT NULL,
    first_loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (partner_id, tracking_no)
);
CREATE INDEX IF NOT EXISTS ix_shipments_status ON shipments (status);

-- append-only tracking history
CREATE TABLE IF NOT EXISTS shipment_events (
    event_id     BIGSERIAL PRIMARY KEY,
    shipment_id  BIGINT NOT NULL REFERENCES shipments(shipment_id),
    status       TEXT NOT NULL,
    location     TEXT,
    event_ts     TIMESTAMPTZ NOT NULL,
    UNIQUE (shipment_id, event_ts, status)
);

-- incremental load bookmark per partner
CREATE TABLE IF NOT EXISTS etl_watermark (
    partner_id             INT PRIMARY KEY REFERENCES partners(partner_id),
    last_source_updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id         BIGSERIAL PRIMARY KEY,
    partner_id     INT NOT NULL REFERENCES partners(partner_id),
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ,
    status         TEXT NOT NULL,          -- RUNNING / SUCCESS / FAILED
    rows_fetched   INT DEFAULT 0,
    events_loaded  INT DEFAULT 0,
    error_message  TEXT
);
