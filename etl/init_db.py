"""Apply sql/schema.sql and sql/views.sql (idempotent)."""
import pathlib

from etl.db import connect

SQL_DIR = pathlib.Path(__file__).resolve().parent.parent / "sql"

if __name__ == "__main__":
    with connect() as conn, conn.cursor() as cur:
        for name in ("schema.sql", "views.sql"):
            cur.execute((SQL_DIR / name).read_text())
            print(f"applied {name}")
