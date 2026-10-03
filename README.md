# Logistics API Integration

Python ETL that pulls shipment-tracking data from 3 carrier REST APIs, normalizes it, and loads it into PostgreSQL.
Refreshed every 30 minutes by a GitHub Actions schedule. Everything runs locally; the "carrier" APIs are a Flask mock with generated test data.

```
mock_api (Flask, 3 partners)  ->  etl/partners.py (extract + normalize)  ->  etl/load.py (upsert)  ->  Postgres  ->  reporting views
        ^ different auth, paging, field names, status codes, timestamp formats per partner
```

| Partner | Auth | Paging | Quirks |
|---|---|---|---|
| FastFreight | `X-API-Key` | page / page_size | ISO-8601 timestamps |
| OceanLink | Bearer token | offset / limit | epoch seconds, numeric status codes, camelCase |
| QuickHaul | `Token` header | cursor | nested objects, text statuses, naive UTC timestamps |

## Quick start

```bash
make install && source .venv/bin/activate
cp .env.example .env && export $(grep -v '^#' .env | xargs)
make db-up            # Postgres 16 in Docker on :5433  (or point DATABASE_URL at any Postgres)
make init-db          # tables + views
make mock-api &       # fake partner APIs on :5050
make etl              # run twice to see the incremental load: 2nd run fetches only changes
make export           # CSVs of the reporting views -> exports/
make dashboard        # self-contained HTML dashboard -> exports/dashboard.html
pytest -q             # unit tests; set TEST_DATABASE_URL (throwaway DB!) for the DB test too
```

Try `MOCK_FLAKY_RATE=0.3 make mock-api` to see retries/backoff working, or change a key in `.env` to see a clean 401 failure.

## Design decisions

- **Idempotent loads** – `INSERT ... ON CONFLICT` on `(partner_id, tracking_no)`; events are insert-only with a unique key. Re-running never duplicates.
- **Incremental pulls** – a per-partner watermark (`etl_watermark`) is sent as `updated_since` and only advanced after a successful load. `--full` ignores it.
- **Resilience** – retries with exponential backoff on 429/5xx (respects `Retry-After`), request timeouts, one partner failing doesn't block the others, one malformed record is skipped and logged instead of failing the batch. Exit code is non-zero if any partner failed so Actions turns red.
- **Observability** – every run is recorded in `etl_run_log`; `v_feed_freshness` shows minutes since last success and failures in 24h.
- **Normalization** – each partner's statuses map to one canonical set (`CREATED, PICKED_UP, IN_TRANSIT, DELAYED, OUT_FOR_DELIVERY, DELIVERED, EXCEPTION`); anything unmapped becomes `UNKNOWN` with a warning.

## Reporting views

`v_status_by_partner`, `v_delayed_shipments` (flagged or past ETA), `v_delivery_time` (partner scorecard), `v_feed_freshness`.

## GitHub Actions

- `ci.yml` – runs the tests (with a Postgres service container) on every push / PR.
- `refresh.yml` – cron `*/30 * * * *` + manual trigger (`full` option). Spins up Postgres + the mock API, runs the ETL, writes the views to the job summary and uploads CSVs as an artifact.

**Limitation:** an Actions runner is ephemeral, so the Postgres inside it is rebuilt each run (the job is a *demo of the scheduled refresh*, not a durable store). To persist data, point `DATABASE_URL` at a hosted Postgres (Neon / Supabase free tier) via a repo secret and drop the service container. Also, GitHub can delay scheduled runs by several minutes, and the schedule only fires from the default branch.

## Dashboard

`python -m etl.dashboard` turns the reporting views into one self-contained HTML file (inline SVG, no JS libraries, no BI tool, works offline, light/dark aware). It shows KPI tiles, outcomes by partner, time to deliver, feed health against the 30-minute SLA, daily event volume, the most overdue shipments and recent runs. Each chart has a "view as table" fallback. The Actions refresh job builds it and uploads it with the CSVs.

## Docs

[docs/troubleshooting.md](docs/troubleshooting.md) – runbook for common failures.
