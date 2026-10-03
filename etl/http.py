import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from etl.config import REQUEST_TIMEOUT


def make_session(headers):
    """Session that retries 429/5xx with exponential backoff (honours Retry-After)."""
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(headers)
    return session


def get_json(session, url, params=None):
    resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()  # 401/404 etc. fail loudly, they are not retried
    return resp.json()
