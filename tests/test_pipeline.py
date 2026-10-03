"""End-to-end test: mock API in-process -> ETL -> Postgres. Needs TEST_DATABASE_URL (a throwaway DB -- it is wiped)."""
import pytest

psycopg2 = pytest.importorskip("psycopg2")

import os  # noqa: E402

from etl import config, partners  # noqa: E402
from etl.init_db import SQL_DIR  # noqa: E402
from etl.load import load_partner  # noqa: E402
from mock_api.app import app  # noqa: E402


@pytest.fixture
def conn():
    # this fixture DROPs the public schema, so it only runs against an explicit throwaway DB
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    try:
        c = psycopg2.connect(url)
    except psycopg2.OperationalError:
        pytest.skip("no postgres available")
    with c, c.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for f in ("schema.sql", "views.sql"):
            cur.execute((SQL_DIR / f).read_text())
    yield c
    c.close()


class _Resp:
    def __init__(self, r):
        self.status_code, self._r = r.status_code, r

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._r.get_json()


class FlaskSession:
    """Lets the real extractors run against the Flask test client, no network needed."""
    def __init__(self, headers):
        self.client, self.headers = app.test_client(), headers

    def get(self, url, params=None, timeout=None):
        path = url.replace(config.BASE_URL, "")
        return _Resp(self.client.get(path, query_string=params, headers=self.headers))


@pytest.mark.parametrize("code", ["fastfreight", "oceanlink", "quickhaul"])
def test_load_is_idempotent(conn, monkeypatch, code):
    monkeypatch.setattr(partners, "make_session", FlaskSession)
    fetch, normalize = partners.PARTNER_FUNCS[code]
    records = [normalize(r) for r in fetch()]
    assert records

    with conn, conn.cursor() as cur:
        cur.execute("SELECT partner_id FROM partners WHERE code=%s", (code,))
        pid = cur.fetchone()[0]
        first = load_partner(cur, pid, records)
        second = load_partner(cur, pid, records)
        cur.execute("SELECT COUNT(*) FROM shipments WHERE partner_id=%s", (pid,))
        assert cur.fetchone()[0] == len(records)
    assert first > 0 and second == 0
