# Test Report — CacheCollapse

**Date of test run:** 2026-10-22 (re-run after the protection fixes)
**Tested by:** Tester phase (automated suite `tests/test_cachecollapse.py`, run against
the live stack on http://localhost:8090)
**Result:** ✅ **ALL PASSED** (16 / 16)

The suite drives the system through the control API exactly as the dashboard
buttons do, samples the live metrics feed, and checks every success criterion from
the spec, plus the two issues raised in review (shop recovery, live update rate).

## Passed (15)

| # | Test | Evidence |
|---|---|---|
| 1 | All 9 containers running | 9 up |
| 2 | Dashboard page loads | HTTP 200, correct title |
| 3 | Shop website loads | HTTP 200, `CacheShop` present |
| 4 | Product API returns data | `/api/products/1` → 200 with name/price |
| 5 | Cache works (2nd call faster) | 1st 137 ms (DB) → 2nd 9 ms (cache) |
| 6 | Unknown product → 404 | `/api/products/99999` → 404 |
| 7 | Baseline is calm | peak DB 17 q/s, 0 false alarms |
| 8 | Attack overloads the DB | peak resp 500 ms, DB 227 q/s, 145 failed/s |
| 9 | Rule detector fires on attack | 10 samples alerted |
| 10 | ML detector fires on attack | 28 samples alerted |
| 11 | Cache locking keeps DB load low | peak DB 11 q/s (vs 227 unprotected) |
| 12 | Protection preserves availability | peak resp 152 ms, 0 failed (vs 500 ms / 145) |
| 13 | System recovers after attack stops | healthy again in ~2 s |
| 14 | Live feed updates faster than 1 s | two samples 0.6 s apart differ |
| 15 | Control endpoints respond | traffic / attack / defense / reset all OK |
| 16 | Shop served while protected | 20/20 product requests succeed under attack+defense |

## Failed

None.

## Bugs found during this cycle (all fixed, then re-tested)

**Bug 1 — Shop stayed "struggling" (red) after the attack ended.**
- *What happened:* with the attack stopped and no traffic, the shop page kept
  showing products failed in red.
- *What should happen:* once the attack stops, products load fast and the page
  returns to healthy/green.
- *Steps to repeat (before fix):* open the shop, launch an attack, stop it — cards
  stayed red.
- *Cause:* the shop fired 12 fetches every 2 s with no timeout; during the attack
  they piled up and some hung forever, so cards never updated afterward.
- *Fix:* added a 4 s per-request timeout (`AbortController`) and made the refresh
  non-overlapping (schedule the next one only after the current finishes). The shop
  now recovers within ~1 refresh after an attack ends.

**Bug 2 — Dashboard graphs updated only once per second (felt laggy).**
- *What should happen:* a live, continuously moving dashboard.
- *Fix:* the monitor now samples and streams **twice per second** (0.5 s), so the
  charts move about twice as often. (Per-millisecond is not meaningful for
  rate-based metrics such as queries/second, but 2 Hz reads as live.)

**Bug 3 — One false alarm during the baseline.**
- *What happened:* the detectors raised a single alert during calm baseline traffic.
- *What should happen:* no alerts when there is no attack.
- *Cause:* the cold cache at the very start of traffic causes one big burst of
  misses that briefly looks like an attack.
- *Fix:* detection is suppressed during the short warm-up after traffic starts, and
  the ML false-positive rate was tightened (contamination 0.03 → 0.01). Re-tested:
  baseline now raises 0 alerts while attacks are still detected.

**Bug 4 — Shop stayed "struggling" even with protection ON.**
- *What happened:* with both defenses on during an attack, the shop page stayed
  red/slow and did not go green.
- *What should happen:* with protection on, the attacker is throttled and the shop
  stays fast and available.
- *Cause (two parts):* (a) Nginx did not forward the real client address, so the
  app-layer rate limiter treated the attacker and the shop as the *same* client and
  the attacker ate the whole budget, rejecting the shop too. (b) Cache locking made
  waiting requests queue, so served requests were slow (latency up to ~2.5 s).
- *Fix:* (a) Nginx now forwards the real client IP (`X-Forwarded-For`), so the
  attacker is throttled while the shop passes through — verified 20/20 shop requests
  succeed under attack+defense. (b) Added stale-while-revalidate: during a stampede,
  waiting requests are served the slightly-stale cached copy immediately instead of
  queuing, dropping protected-mode latency from ~2451 ms to ~80–140 ms.

**Bug 6 — Shop stayed slow under protection (deeper cause).**
- *What happened:* even after Bug 4, enabling defenses mid-attack left the shop slow
  (~300–700 ms), not green.
- *Cause:* the attacker floods **Nginx** the same whether defenses are on or off —
  the app-layer rate limiter only lightens the **database**, not the proxy. So Nginx
  stayed congested and the shop's requests queued at the connection layer.
- *Fix:* added **edge rate limiting at Nginx**, toggled live by the dashboard's
  Rate-limiting switch (the monitor rewrites an Nginx include file and Nginx reloads
  within ~1 s). With it on, the attacker's flood is rejected at the proxy before it
  can congest anything. Measured shop latency under attack: **no defense ≈ 300–500 ms,
  protected ≈ 20–140 ms** — a clear, reliable green-under-protection. Also pre-warms a
  stale cache at startup so cache-locking can serve instantly from the first miss.

**Bug 5 — Occasional single-tick false alarm / flaky ML detection.**
- *Fix:* the ML detector is now debounced (needs two anomalous ticks in a row, so a
  single blip never alerts), the ML false-positive rate was tightened, and the model
  trains on a shorter baseline so it is reliably ready before an attack. Re-tested:
  baseline raises 0 alerts; attacks are detected by both rule and ML every run.

## How to reproduce the test run

```
# with the stack running (docker compose up)
python tests/test_cachecollapse.py
```

Expected tail: `SUMMARY: 16 passed, 0 failed` / `RESULT: ALL PASSED`.
