"""CacheCollapse backend web app.

One endpoint, GET /products/<id>, backed by Redis (cache) and PostgreSQL (DB).
It is the entry point the attack flows through, and it hosts both defenses:

  * cache locking  -- on a miss, only ONE request queries the DB; the rest wait
                      for that result (N misses -> 1 query).
  * rate limiting  -- an app-layer per-client cap (so the dashboard can toggle it
                      live; nginx also ships a limit_req zone for the static case).

Both defenses are read from Redis on every request, so the dashboard buttons can
turn them on and off while the system is running.
"""
import os
import time
import json
import redis
from flask import Flask, jsonify, request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

import db

app = Flask(__name__)

CACHE_TTL = int(os.getenv("CACHE_TTL", "10"))
RATE_LIMIT_RPS = int(os.getenv("RATE_LIMIT_RPS", "50"))
LOCK_WAIT_MS = 50            # how long a waiting request sleeps between cache re-checks
LOCK_MAX_WAIT_S = 1.5        # give up waiting after this and fall back to the DB
STALE_TTL = CACHE_TTL * 15   # how long a slightly-old copy stays servable

r = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

# --- Prometheus metrics (for Prometheus + Grafana) -------------------------
M_REQS = Counter("cc_requests_total", "All requests", ["result"])
M_DB = Counter("cc_db_queries_total", "Database queries made")
M_HIT = Counter("cc_cache_hits_total", "Cache hits")
M_MISS = Counter("cc_cache_misses_total", "Cache misses")
M_FAIL = Counter("cc_failed_total", "Requests that failed because the DB was overloaded (503)")
M_REJECT = Counter("cc_rejected_total", "Requests the rate limiter shed on purpose (429)")
M_LAT = Histogram("cc_latency_seconds", "Request latency",
                  buckets=(.01, .05, .1, .25, .5, 1, 2, 5, 10))


def cfg(key, default):
    """Read a live config flag from Redis (set by the dashboard)."""
    v = r.get("cfg:" + key)
    return default if v is None else v == "1"


def bootstrap_config():
    """Seed the live config from .env the first time the app starts."""
    if r.get("cfg:rate_limit") is None:
        r.set("cfg:rate_limit", "1" if os.getenv("RATE_LIMIT_ON", "false") == "true" else "0")
    if r.get("cfg:cache_lock") is None:
        r.set("cfg:cache_lock", "1" if os.getenv("CACHE_LOCK_ON", "false") == "true" else "0")


def rate_limited(client):
    """Simple per-client, per-second fixed-window limiter backed by Redis."""
    bucket = "rl:%s:%d" % (client, int(time.time()))
    n = r.incr(bucket)
    if n == 1:
        r.expire(bucket, 2)
    return n > RATE_LIMIT_RPS


def load_product(product_id):
    """Return a product dict, using the cache. Raises db.PoolBusy on overload."""
    key = "product:%d" % product_id
    stale_key = "stale:" + key
    cached = r.get(key)
    if cached is not None:
        M_HIT.inc()
        return json.loads(cached)

    # Cache miss.
    M_MISS.inc()

    if not cfg("cache_lock", False):
        # No defense: every miss goes straight to the database (the stampede).
        return _query_and_fill(key, stale_key, product_id)

    # Cache locking: only the lock winner refreshes from the DB.
    lock_key = "lock:" + key
    got = r.set(lock_key, "1", nx=True, px=3000)
    if got:
        try:
            return _query_and_fill(key, stale_key, product_id)
        finally:
            r.delete(lock_key)

    # We are a "loser". Instead of waiting in a queue (which makes the site slow
    # under attack), serve the slightly-stale copy immediately -- the site stays
    # fast and available while one request refreshes the cache behind the scenes.
    stale = r.get(stale_key)
    if stale is not None:
        M_HIT.inc()
        return json.loads(stale)

    # Truly cold (no stale yet): wait briefly for the winner, then fall back.
    waited = 0.0
    while waited < LOCK_MAX_WAIT_S:
        time.sleep(LOCK_WAIT_MS / 1000.0)
        waited += LOCK_WAIT_MS / 1000.0
        cached = r.get(key)
        if cached is not None:
            M_HIT.inc()
            return json.loads(cached)
    return _query_and_fill(key, stale_key, product_id)


def _query_and_fill(key, stale_key, product_id):
    M_DB.inc()
    product = db.get_product(product_id)
    if product is not None:
        payload = json.dumps(product)
        r.set(key, payload, ex=CACHE_TTL)        # fresh copy (short TTL)
        r.set(stale_key, payload, ex=STALE_TTL)  # stale copy served during a stampede
    return product


def warm_stale():
    """Pre-load a stale copy of every product at startup, so the cache-locking
    defense can serve instantly from the very first miss (even if an attack starts
    before anything is cached). Does NOT warm the fresh cache, so the attack still
    causes real misses when fresh entries expire."""
    try:
        for p in db.get_all_products():
            r.set("stale:product:%d" % p["id"], json.dumps(p), ex=3600)
        print("stale cache warmed for all products", flush=True)
    except Exception as e:
        print("stale warm failed (will populate on demand):", e, flush=True)


@app.route("/products/<int:product_id>")
def products(product_id):
    start = time.time()
    client = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")

    if cfg("rate_limit", False) and rate_limited(client):
        # Shed on purpose -- this is the defense working, not a failure.
        M_REJECT.inc()
        M_REQS.labels("rate_limited").inc()
        return jsonify(error="rate limited"), 429

    try:
        product = load_product(product_id)
    except db.PoolBusy:
        M_FAIL.inc()
        M_REQS.labels("overloaded").inc()
        return jsonify(error="database busy"), 503
    finally:
        M_LAT.observe(time.time() - start)

    if product is None:
        M_REQS.labels("not_found").inc()
        return jsonify(error="not found"), 404

    M_REQS.labels("ok").inc()
    return jsonify(product)


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/healthz")
def healthz():
    return "ok", 200


db.init_pool()
bootstrap_config()
warm_stale()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
