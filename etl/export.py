"""Dump the reporting views to CSV + print a summary (used by the GitHub Actions refresh job)."""
import csv
import pathlib

from etl.db import connect

VIEWS = ["v_status_by_partner", "v_delayed_shipments", "v_delivery_time", "v_feed_freshness"]

if __name__ == "__main__":
    out = pathlib.Path("exports")
    out.mkdir(exist_ok=True)
    with connect() as conn, conn.cursor() as cur:
        for view in VIEWS:
            cur.execute(f"SELECT * FROM {view}")
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            with open(out / f"{view}.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
            print(f"{view}: {len(rows)} rows")
