"""Database access for the CacheCollapse backend.

A small thread-safe connection pool talks to PostgreSQL. Each product read runs a
deliberately slow query (pg_sleep) so that a cache stampede shows up clearly as
database load and latency. When the pool is empty (too many requests at once),
getconn raises and the caller turns that into a failed request -- exactly the
overload we want to demonstrate.
"""
import os
import psycopg2
from psycopg2.pool import ThreadedConnectionPool, PoolError

DB_QUERY_DELAY = float(os.getenv("DB_QUERY_DELAY_MS", "120")) / 1000.0

_pool = None


def init_pool():
    global _pool
    _pool = ThreadedConnectionPool(
        minconn=2,
        maxconn=12,                      # the DB's capacity -- the stampede exhausts this
        host=os.getenv("DB_HOST", "db"),
        dbname=os.getenv("POSTGRES_DB", "shopdb"),
        user=os.getenv("POSTGRES_USER", "shopuser"),
        password=os.getenv("POSTGRES_PASSWORD", "shoppass"),
    )


class PoolBusy(Exception):
    """Raised when every DB connection is in use (database overloaded)."""


def get_all_products():
    """Fetch every product quickly (no artificial delay) -- used once at startup to
    warm the stale cache so the cache-locking defense is instant from the start."""
    conn = _pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, description, price, stock FROM products")
            rows = cur.fetchall()
        conn.commit()
        return [{"id": r[0], "name": r[1], "description": r[2],
                 "price": float(r[3]), "stock": r[4]} for r in rows]
    finally:
        _pool.putconn(conn)


def get_product(product_id):
    """Read one product. Returns a dict, or None if it does not exist.

    Raises PoolBusy when the database cannot take the query right now.
    """
    try:
        conn = _pool.getconn()
    except PoolError:
        raise PoolBusy()
    try:
        with conn.cursor() as cur:
            # pg_sleep makes the query cost real database time.
            cur.execute(
                "SELECT id, name, description, price, stock, pg_sleep(%s) "
                "FROM products WHERE id = %s",
                (DB_QUERY_DELAY, product_id),
            )
            row = cur.fetchone()
        conn.commit()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "price": float(row[3]),
            "stock": row[4],
        }
    finally:
        _pool.putconn(conn)
