import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://logistics:logistics@localhost:5433/logistics")
BASE_URL = os.getenv("MOCK_API_URL", "http://localhost:5050")

FASTFREIGHT_API_KEY = os.getenv("FASTFREIGHT_API_KEY", "ff-test-key")
OCEANLINK_TOKEN = os.getenv("OCEANLINK_TOKEN", "ol-test-token")
QUICKHAUL_TOKEN = os.getenv("QUICKHAUL_TOKEN", "qh-test-token")

PAGE_SIZE = 25
REQUEST_TIMEOUT = 10  # seconds
