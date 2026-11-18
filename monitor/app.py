"""CacheCollapse monitor.

Runs three jobs in one container:
  * collector  -- every second, read the backend's metrics, work out per-second
                  rates, run both detectors, and append a CSV row.
  * live API   -- stream the latest numbers to the dashboard (Server-Sent Events)
                  and handle the control buttons.
  * detection  -- rule-based and ML, compared side by side.

The dashboard buttons set Redis flags that the load generator and backend read,
so the whole demo is driven live from the browser.
"""
import os
import time
import json
import threading

import redis
import requests
from flask import Flask, Response, request, jsonify
from prometheus_client.parser import text_string_to_metric_families

import detect_rules
from detect_ml import MLDetector
from logger_csv import CsvLogger

BACKEND = os.getenv("BACKEND_URL", "http://backend:5000")
r = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

app = Flask(__name__)
ml = MLDetector()
logger = CsvLogger(os.getenv("DATA_DIR", "/app/data"))

# Shared live state (updated by the collector, read by the SSE stream).
STATE = {
    "mode": "idle", "status": "healthy",
    "rps": 0, "db_qps": 0, "hit_rate": 0.0,
    "cache_hits": 0, "cache_misses": 0, "miss_rate": 0.0,
    "resp_avg_ms": 0.0, "resp_p95_ms": 0.0, "failed": 0,
    "rule": {"db_load": False, "response": False, "miss_rate": False},
    "rule_alert": False, "ml_score": 0.08, "ml_alert": False, "ml_ready": False,
    "detect_time": None, "recover_time": None,
    "rate_limit": False, "cache_lock": False,
}

_prev = None            # previous raw metric snapshot
_baseline_db = 0.0      # learned normal DB queries/sec
_attack_start = None    # when the current attack began
_unhealthy_since = None # when the system first became unhealthy in this attack
_normal_streak = 0      # consecutive normal ticks (to skip cold-cache warm-up)
_rule_hits = 0          # consecutive ticks the rule/ML say "attack" (debounce)
_ml_hits = 0
TICK = 0.5              # sample twice per second for a more live dashboard
WARMUP_TICKS = 6        # ignore the first ~3s of normal traffic (cache filling)


def flag(name):
    return r.get(name) == "1"


def scrape():
    """Read the backend's /metrics and return raw cumulative totals."""
    totals = {"requests": 0.0, "db": 0.0, "hits": 0.0, "miss": 0.0,
              "failed": 0.0, "lat_sum": 0.0, "lat_count": 0.0, "buckets": {}}
    try:
        text = requests.get(BACKEND + "/metrics", timeout=2).text
    except Exception:
        return None
    for fam in text_string_to_metric_families(text):
        for s in fam.samples:
            n = s.name
            if n == "cc_requests_total":
                totals["requests"] += s.value
            elif n == "cc_db_queries_total":
                totals["db"] = s.value
            elif n == "cc_cache_hits_total":
                totals["hits"] = s.value
            elif n == "cc_cache_misses_total":
                totals["miss"] = s.value
            elif n == "cc_failed_total":
                totals["failed"] = s.value
            elif n == "cc_latency_seconds_sum":
                totals["lat_sum"] = s.value
            elif n == "cc_latency_seconds_count":
                totals["lat_count"] = s.value
            elif n == "cc_latency_seconds_bucket":
                totals["buckets"][s.labels.get("le")] = s.value
    return totals


def p95_from_buckets(prev_b, cur_b, delta_count):
    """Approximate p95 latency (ms) from the change in histogram buckets."""
    if delta_count <= 0:
        return 0.0
    edges = sorted((float(le) for le in cur_b if le != "+Inf"))
    cum = 0.0
    target = 0.95 * delta_count
    for le in edges:
        d = cur_b.get(str(le), 0) - prev_b.get(str(le), 0)
        cum += d
        if cum >= target:
            return le * 1000.0
    return edges[-1] * 1000.0 if edges else 0.0


def current_mode():
    traffic, attack = flag("run:traffic"), flag("run:attack")
    rl, cl = flag("cfg:rate_limit"), flag("cfg:cache_lock")
    if attack:
        return "protected" if (rl or cl) else "attack"
    return "normal" if traffic else "idle"


def collector():
    global _prev, _baseline_db, _attack_start, _unhealthy_since, _normal_streak
    global _rule_hits, _ml_hits
    while True:
        time.sleep(TICK)
        cur = scrape()
        if cur is None:
            continue
        if _prev is None:
            _prev = (time.time(), cur)
            continue

        t0, prev = _prev
        now = time.time()
        dt = max(now - t0, 0.001)
        _prev = (now, cur)

        d_req = max(0.0, cur["requests"] - prev["requests"])
        d_db = max(0.0, cur["db"] - prev["db"])
        d_hit = max(0.0, cur["hits"] - prev["hits"])
        d_miss = max(0.0, cur["miss"] - prev["miss"])
        d_fail = max(0.0, cur["failed"] - prev["failed"])
        d_lat_sum = max(0.0, cur["lat_sum"] - prev["lat_sum"])
        d_lat_cnt = max(0.0, cur["lat_count"] - prev["lat_count"])

        rps = d_req / dt
        db_qps = d_db / dt
        total_cache = d_hit + d_miss
        miss_rate = (d_miss / total_cache) if total_cache else 0.0
        hit_rate = (d_hit / total_cache) if total_cache else 1.0
        resp_avg = (d_lat_sum / d_lat_cnt * 1000.0) if d_lat_cnt else 0.0
        resp_p95 = p95_from_buckets(prev["buckets"], cur["buckets"], d_lat_cnt)

        sample = {"rps": rps, "db_qps": db_qps, "miss_rate": miss_rate,
                  "resp_avg_ms": resp_avg, "failed": d_fail}

        mode = current_mode()

        # Learn the baseline only from steady normal traffic (skip the cold-cache
        # warm-up, whose miss/DB spike would otherwise pollute "normal").
        if mode == "normal":
            _normal_streak += 1
        else:
            _normal_streak = 0
        if mode == "normal" and _normal_streak > WARMUP_TICKS and db_qps > 0:
            _baseline_db = 0.8 * _baseline_db + 0.2 * db_qps if _baseline_db else db_qps
            ml.observe_baseline(sample)

        conditions, rule_alert = detect_rules.evaluate(sample, _baseline_db)
        ml_score, ml_alert = ml.score(sample)

        # The cold cache at the very start of normal traffic briefly looks like an
        # attack (one big burst of misses). Don't raise an alert during that warm-up;
        # real attacks run in attack/protected mode and are unaffected.
        if mode == "normal" and _normal_streak <= WARMUP_TICKS:
            rule_alert = False
            ml_alert = False
            conditions = {k: False for k in conditions}

        # Debounce the ML detector only (it can blip on a single odd tick). The rule
        # detector already needs all three conditions at once, so it does not blip on
        # calm traffic and is left responsive.
        _ml_hits = _ml_hits + 1 if ml_alert else 0
        ml_alert = _ml_hits >= 2

        # Attack timing (detect / recover).
        if flag("run:attack"):
            if _attack_start is None:
                _attack_start = now
                STATE["detect_time"] = None
                STATE["recover_time"] = None
                _unhealthy_since = None
        else:
            _attack_start = None

        healthy = (db_qps < max(_baseline_db, 5) * 2) and resp_avg < 120 and d_fail < 3
        status = "healthy"
        if mode == "attack":
            status = "overloaded" if not healthy else "healthy"
        elif mode == "protected":
            status = "protected" if healthy else "degraded"

        alert = rule_alert or ml_alert
        if _attack_start is not None:
            if alert and STATE["detect_time"] is None:
                STATE["detect_time"] = round(now - _attack_start, 1)
            if not healthy and _unhealthy_since is None:
                _unhealthy_since = now
            if healthy and _unhealthy_since is not None and STATE["recover_time"] is None:
                STATE["recover_time"] = round(now - _unhealthy_since, 1)

        STATE.update({
            "mode": mode, "status": status,
            "rps": round(rps), "db_qps": round(db_qps),
            "hit_rate": round(hit_rate, 3), "miss_rate": round(miss_rate, 3),
            "cache_hits": round(d_hit), "cache_misses": round(d_miss),
            "resp_avg_ms": round(resp_avg), "resp_p95_ms": round(resp_p95),
            "failed": round(d_fail),
            "rule": conditions, "rule_alert": rule_alert,
            "ml_score": round(ml_score, 2), "ml_alert": ml_alert, "ml_ready": ml.ready,
            "rate_limit": flag("cfg:rate_limit"), "cache_lock": flag("cfg:cache_lock"),
        })

        logger.write({
            "ts": round(now, 2), "mode": mode, "rps": round(rps),
            "db_qps": round(db_qps), "cache_hits": round(d_hit),
            "cache_misses": round(d_miss), "hit_rate": round(hit_rate, 3),
            "resp_avg_ms": round(resp_avg), "resp_p95_ms": round(resp_p95),
            "failed": round(d_fail), "rule_alert": int(rule_alert),
            "ml_score": round(ml_score, 2), "ml_alert": int(ml_alert),
        })


# ------------------------------------------------------------------ live API
@app.route("/live")
def live():
    def stream():
        while True:
            yield "data: %s\n\n" % json.dumps(STATE)
            time.sleep(TICK)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/control/<action>", methods=["POST"])
def control(action):
    body = request.get_json(silent=True) or {}
    if action == "traffic":
        r.set("run:traffic", "1" if body.get("on", True) else "0")
    elif action == "attack":
        r.set("run:traffic", "1")
        r.set("run:attack", "1" if body.get("on", True) else "0")
    elif action == "defense":
        if "rate_limit" in body:
            r.set("cfg:rate_limit", "1" if body["rate_limit"] else "0")
            set_edge_ratelimit(bool(body["rate_limit"]))
        if "cache_lock" in body:
            r.set("cfg:cache_lock", "1" if body["cache_lock"] else "0")
    elif action == "preset":
        exp = str(body.get("exp"))
        rl = exp == "3"
        r.set("run:traffic", "1")
        r.set("run:attack", "0" if exp == "1" else "1")
        r.set("cfg:rate_limit", "1" if rl else "0")
        r.set("cfg:cache_lock", "1" if rl else "0")
        set_edge_ratelimit(rl)
    elif action == "reset":
        for k in ("run:traffic", "run:attack", "cfg:rate_limit", "cfg:cache_lock"):
            r.set(k, "0")
        set_edge_ratelimit(False)
        # Clear the fresh cache + locks + rate buckets to re-arm the stampede, but
        # KEEP the stale safety-net so cache locking can always serve instantly.
        _clear_keys("product:*"); _clear_keys("lock:*"); _clear_keys("rl:*")
        STATE["detect_time"] = None
        STATE["recover_time"] = None
    else:
        return jsonify(error="unknown action"), 404
    return jsonify(ok=True, state=current_mode())


def _clear_keys(pattern):
    for key in r.scan_iter(pattern):
        r.delete(key)


NGINX_DYN = os.getenv("NGINX_DYN", "/app/nginxdyn/ratelimit.conf")


def set_edge_ratelimit(on):
    """Rewrite the Nginx edge rate-limit include; Nginx reloads it within ~1s. When
    on, the attacker's flood is rejected at the proxy instead of congesting it."""
    try:
        with open(NGINX_DYN, "w") as f:
            f.write("limit_req zone=api_rl burst=20 nodelay;\n" if on
                    else "# edge rate limiting OFF\n")
    except Exception as e:
        print("edge rate-limit write failed:", e, flush=True)


@app.route("/debug/ml")
def debug_ml():
    import numpy as np
    base = ml._baseline
    info = {"ready": ml.ready, "n_baseline": len(base)}
    if base:
        arr = np.array(base, dtype=float)
        info["feature_max"] = arr.max(axis=0).tolist()
        info["feature_mean"] = arr.mean(axis=0).tolist()
        info["features"] = ["db_qps", "resp_avg_ms", "miss_rate", "rps", "failed"]
        info["test_attack_score"] = ml.score(
            {"db_qps": 140, "resp_avg_ms": 350, "miss_rate": 0.8, "rps": 200, "failed": 150})
    return jsonify(info)


@app.route("/healthz")
def healthz():
    return "ok", 200


# Start the collector as soon as the module loads (single worker).
threading.Thread(target=collector, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000, threaded=True)
