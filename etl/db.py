import psycopg2

from etl import config


def connect():
    return psycopg2.connect(config.DATABASE_URL)
