"""Rule-based detector.

Fires when ALL three conditions hold at once -- the signature of a cache stampede:
  1. database load is far above its normal baseline,
  2. response time is high,
  3. the cache-miss rate is high.

Checking several signals together (not just "many requests") is what makes this
reliable: a normal traffic spike raises requests but NOT the miss rate, because
the cache still serves it.
"""

DB_MULTIPLIER = 5       # "high DB load" = more than 5x the learned baseline
BASELINE_FLOOR = 5      # never treat less than this many q/s as the baseline
RESP_MS_LIMIT = 200     # "high response time"
MISS_RATE_LIMIT = 0.5   # "high miss rate"


def evaluate(sample, baseline_db):
    """Return (conditions dict, fired bool) for one per-second sample."""
    base = max(baseline_db, BASELINE_FLOOR)
    c1 = sample["db_qps"] > DB_MULTIPLIER * base
    c2 = sample["resp_avg_ms"] > RESP_MS_LIMIT
    c3 = sample["miss_rate"] > MISS_RATE_LIMIT
    conditions = {"db_load": c1, "response": c2, "miss_rate": c3}
    return conditions, (c1 and c2 and c3)
