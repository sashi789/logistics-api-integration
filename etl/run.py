"""Pull every partner API and load into Postgres.

    python -m etl.run                     # incremental (uses watermark)
    python -m etl.run --full              # ignore watermark, re-pull everything
    python -m etl.run --partner quickhaul

A failure in one partner does not stop the others; exit code is 1 if any failed.
"""
import argparse
import logging
import sys

from etl.db import connect
from etl.load import load_partner
from etl.partners import PARTNER_FUNCS

log = logging.getLogger("etl")


def run_partner(conn, code, full=False):
    fetch, normalize = PARTNER_FUNCS[code]
    with conn, conn.cursor() as cur:
        cur.execute("SELECT partner_id FROM partners WHERE code = %s", (code,))
        partner_id = cur.fetchone()[0]
        cur.execute("INSERT INTO etl_run_log (partner_id, started_at, status) VALUES (%s, now(), 'RUNNING') RETURNING run_id",
                    (partner_id,))
        run_id = cur.fetchone()[0]
        cur.execute("SELECT last_source_updated_at FROM etl_watermark WHERE partner_id = %s", (partner_id,))
        row = cur.fetchone()
        since = None if full or not row else row[0]

    try:
        records, skipped = [], 0
        for raw in fetch(since):
            try:
                records.append(normalize(raw))
            except (KeyError, TypeError, ValueError) as exc:
                skipped += 1  # one bad record shouldn't sink the batch
                log.warning("%s: skipping malformed record (%s): %.200r", code, exc, raw)
        log.info("%s: fetched %d records (since=%s, skipped=%d)", code, len(records), since, skipped)

        with conn, conn.cursor() as cur:
            events = load_partner(cur, partner_id, records)
            if records:
                newest = max(s["source_updated_at"] for s, _ in records)
                cur.execute(
                    """INSERT INTO etl_watermark (partner_id, last_source_updated_at) VALUES (%s, %s)
                       ON CONFLICT (partner_id) DO UPDATE SET last_source_updated_at = GREATEST(
                           etl_watermark.last_source_updated_at, EXCLUDED.last_source_updated_at)""",
                    (partner_id, newest))
            cur.execute("""UPDATE etl_run_log SET status='SUCCESS', finished_at=now(), rows_fetched=%s, events_loaded=%s
                           WHERE run_id=%s""", (len(records), events, run_id))
        log.info("%s: loaded, %d new events", code, events)
        return True
    except Exception as exc:
        log.exception("%s: run failed", code)
        conn.rollback()
        with conn, conn.cursor() as cur:
            cur.execute("UPDATE etl_run_log SET status='FAILED', finished_at=now(), error_message=%s WHERE run_id=%s",
                        (str(exc)[:500], run_id))
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--partner", choices=PARTNER_FUNCS)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    conn = connect()
    results = {code: run_partner(conn, code, args.full) for code in ([args.partner] if args.partner else PARTNER_FUNCS)}
    failed = [c for c, ok in results.items() if not ok]
    if failed:
        log.error("failed partners: %s", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
