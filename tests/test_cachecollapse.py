"""CacheCollapse end-to-end test suite.

Runs against the live stack on http://localhost:8090 and checks every success
check from the spec, plus the two issues found in review (shop recovery after an
attack, and live-feed update rate). Prints PASS/FAIL per test and a final tally.

Run:  python tests/test_cachecollapse.py
"""
import json
import time
import urllib.request
import urllib.error
import subprocess

BASE = "http://localhost:8090"
results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ((" -- " + detail) if detail else ""))


def api_get(path, timeout=15):
    t0 = time.time()
    try:
        r = urllib.request.urlopen(BASE + path, timeout=timeout)
        body = r.read().decode()
        return r.status, (time.time() - t0) * 1000.0, body
    except urllib.error.HTTPError as e:
        return e.code, (time.time() - t0) * 1000.0, e.read().decode()
    except Exception as e:
        return 0, (time.time() - t0) * 1000.0, str(e)


def control(action, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + "/control/" + action, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=5).read().decode()
    except Exception as e:
        return str(e)


def get_live(timeout=4):
    try:
        req = urllib.request.urlopen(BASE + "/live", timeout=timeout)
        for raw in req:
            line = raw.decode().strip()
            if line.startswith("data:"):
                req.close()
                return json.loads(line[5:])
    except Exception:
        return None
    return None


def sample_window(seconds, gap=0.5):
    out, end = [], time.time() + seconds
    while time.time() < end:
        s = get_live()
        if s:
            out.append(s)
        time.sleep(gap)
    return out


def peak(samples, key):
    return max((s.get(key, 0) for s in samples), default=0)


def fired_secs(samples, key):
    return sum(1 for s in samples if s.get(key))


# ---------------------------------------------------------------- tests
def t_containers():
    out = subprocess.run(["docker", "compose", "ps", "--format", "{{.Service}} {{.Status}}"],
                         capture_output=True, text=True, cwd=".").stdout
    up = [l for l in out.splitlines() if " Up" in l]
    record("1. all 9 containers running", len(up) >= 9, "%d up" % len(up))


def t_dashboard():
    code, _, body = api_get("/")
    record("2. dashboard page loads", code == 200 and "CacheCollapse Live Ops" in body)


def t_shop_page():
    code, _, body = api_get("/shop.html")
    record("3. shop website loads", code == 200 and "CacheShop" in body)


def t_api_and_cache():
    control("defense", {"rate_limit": False, "cache_lock": False})
    control("reset")
    time.sleep(1)
    c1, ms1, b1 = api_get("/api/products/1")
    ok_data = c1 == 200 and '"name"' in b1 and '"price"' in b1
    record("4. product API returns data", ok_data, "status %s" % c1)
    c2, ms2, _ = api_get("/api/products/1")
    record("5. cache works (2nd call faster)", c2 == 200 and ms2 < ms1,
           "1st=%dms 2nd=%dms" % (ms1, ms2))


def t_not_found():
    code, _, _ = api_get("/api/products/99999")
    record("6. unknown product -> 404", code == 404, "status %s" % code)


def t_baseline():
    control("preset", {"exp": 1})
    s = sample_window(14)
    hi_db = peak(s, "db_qps")
    alerts = fired_secs(s, "rule_alert") + fired_secs(s, "ml_alert")
    # Calm = low DB and at most a single transient blip (attacks fire dozens).
    record("7. baseline is calm (low DB, ~no alerts)", hi_db < 60 and alerts <= 1,
           "peak_db=%d alerts=%d" % (hi_db, alerts))


def t_attack():
    # Make sure the ML model has trained on the baseline before testing detection.
    control("preset", {"exp": 1})
    for _ in range(18):
        live = get_live()
        if live and live.get("ml_ready"):
            break
        time.sleep(1)
    control("preset", {"exp": 2})
    s = sample_window(18)
    pr, pd, pf = peak(s, "resp_avg_ms"), peak(s, "db_qps"), peak(s, "failed")
    rule, ml = fired_secs(s, "rule_alert"), fired_secs(s, "ml_alert")
    record("8. attack overloads the DB", pr > 200 and pf > 20,
           "peak_resp=%dms peak_db=%d peak_failed=%d" % (pr, pd, pf))
    record("9. rule detector fires on attack", rule > 0, "%d samples alerted" % rule)
    record("10. ML detector fires on attack", ml > 0, "%d samples alerted" % ml)
    return pr, pf


def t_protected(unprot_resp, unprot_fail):
    control("reset")
    time.sleep(2)
    control("preset", {"exp": 1})
    time.sleep(10)                      # warm + train before protected run
    control("preset", {"exp": 3})
    s = sample_window(16)
    pr, pd, pf = peak(s, "resp_avg_ms"), peak(s, "db_qps"), peak(s, "failed")
    record("11. cache locking keeps DB load low", pd < 40, "peak_db=%d" % pd)
    record("12. protection preserves availability", pf <= 2 and pr < max(300, unprot_resp),
           "peak_resp=%dms peak_failed=%d (vs attack resp=%d fail=%d)"
           % (pr, pf, unprot_resp, unprot_fail))


def t_recovery():
    # Attack, then stop, and confirm the system returns to healthy (the sync bug).
    control("reset"); time.sleep(1)
    control("preset", {"exp": 2})
    time.sleep(10)
    control("reset")                    # stop attack + traffic
    healthy_at = None
    start = time.time()
    while time.time() - start < 15:
        c, ms, _ = api_get("/api/products/5")
        if c == 200 and ms < 250:
            healthy_at = time.time() - start
            break
        time.sleep(1)
    record("13. system recovers after attack stops", healthy_at is not None,
           "recovered in %.1fs" % healthy_at if healthy_at else "did NOT recover in 15s")


def t_shop_under_protection():
    # With defenses ON, a legitimate client (different from the attacker) must still
    # be served -- the rate limiter must not starve the shop.
    control("reset"); time.sleep(2)
    control("preset", {"exp": 1}); time.sleep(6)
    control("preset", {"exp": 3}); time.sleep(6)       # attack + defenses
    ok = 0
    for i in range(20):
        code, _, _ = api_get("/api/products/%d" % (i % 12 + 1))
        if code == 200:
            ok += 1
    control("reset")
    record("16. shop served while protected", ok >= 18, "%d/20 product requests OK" % ok)


def t_live_rate():
    # Expect ~2 updates/sec: the collector timestamp should move within ~0.7s.
    control("preset", {"exp": 1})
    time.sleep(2)
    a = get_live(); time.sleep(0.6); b = get_live()
    moved = a and b and (a.get("rps") != b.get("rps") or a.get("db_qps") != b.get("db_qps")
                         or a.get("resp_avg_ms") != b.get("resp_avg_ms"))
    record("14. live feed updates faster than 1s", bool(moved),
           "two samples 0.6s apart differ" if moved else "samples identical")


def t_controls():
    ok = True
    for act, body in [("traffic", {"on": True}), ("attack", {"on": True}),
                      ("defense", {"rate_limit": True}), ("reset", {})]:
        r = control(act, body)
        ok = ok and '"ok": true' in r.replace(" ", "").replace('"ok":true', '"ok": true') \
            or "ok" in r
    record("15. control endpoints respond", ok)


def main():
    print("=== CacheCollapse test run ===")
    t_containers()
    t_dashboard()
    t_shop_page()
    t_api_and_cache()
    t_not_found()
    t_baseline()
    pr, pf = t_attack()
    t_protected(pr, pf)
    t_recovery()
    t_shop_under_protection()
    t_live_rate()
    t_controls()
    control("reset")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n=== SUMMARY: %d passed, %d failed ===" % (passed, failed))
    print("RESULT:", "ALL PASSED" if failed == 0 else "SOME FAILED")


if __name__ == "__main__":
    main()
