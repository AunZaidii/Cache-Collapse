# Development — CacheCollapse

*What was built in the development phase, how it fits together, and how to run it.
Based on docs/spec.md and docs/design.md.*

## 1. What was built

A complete, runnable 9-container system. One command — `docker compose up --build`
— starts the whole lab, and the entire demo (normal traffic, attack, defenses) is
driven live from a browser dashboard. Nothing is deployed online; everything runs
locally on Docker.

The system can reproduce all three experiments:

1. **Baseline** — steady traffic, low DB load.
2. **Attack, no defense** — a burst overloads the database (the stampede).
3. **Attack + defense** — rate limiting + cache locking keep it available.

…and it detects the attack two ways (rule-based and ML) and logs every metric to
CSV for the report.

## 2. How the pieces connect

```
 Browser ── nginx(8080) ──┬── frontend (dashboard)
                          ├── /api  → backend (Flask) ── redis (cache) 
                          │                            └ postgres (DB)
                          └── /live,/control → monitor (SSE + buttons)

 loadgen ── /api → nginx → backend        (normal traffic + burst attack)
 monitor ── scrapes backend /metrics every second
 prometheus ── scrapes backend /metrics → grafana (dashboards)

 Redis also carries the live controls:
   run:traffic, run:attack      (read by loadgen)
   cfg:rate_limit, cfg:cache_lock (read by backend)
   — all set by the dashboard buttons via the monitor.
```

Redis is used for two jobs: the **product cache**, and a tiny **control bus** so the
dashboard can switch traffic and defenses on and off while everything is running.

## 3. The code, service by service

### backend/ (Flask web app)
- `app.py` — the `GET /products/<id>` endpoint. On a cache hit it returns Redis
  data; on a miss it reads PostgreSQL and fills the cache. It hosts both defenses:
  - **cache locking:** on a miss it tries a Redis `SET NX` lock; only the winner
    queries the DB, the losers wait and reuse that result (N misses → 1 query).
  - **rate limiting:** an app-layer per-client, per-second cap (so the dashboard can
    toggle it live). Nginx also ships a `limit_req` zone for the static version.
  - Exposes `/metrics` (Prometheus format) for the monitor and Grafana.
- `db.py` — a thread-safe PostgreSQL connection pool (max 25). Each read runs a
  deliberately slow query (`pg_sleep`) so the stampede shows as real DB load; when
  the pool is exhausted the request fails with 503 — the visible overload.
- Runs under gunicorn with **1 worker / 200 threads**, so hundreds of requests hit
  at once (that concurrency is what makes the stampede real) while the metric
  counters stay in a single process.

### database/ (PostgreSQL)
- `init.sql` — the `products` table. `seed.sql` — 100 fake products. Both run
  automatically on first container start. No real data.

### nginx/
- `nginx.conf` — routes `/` to the dashboard, `/api/` to the backend, and
  `/live` + `/control/` to the monitor. Holds the optional `limit_req` zone.

### loadgen/ (traffic generator)
- `loadgen.py` — async (aiohttp). Reads `run:traffic` / `run:attack` from Redis and
  produces steady normal traffic and/or a 500-request burst at product #1.

### monitor/ (watcher + detectors + live API)
- `app.py` — every second, scrapes the backend's metrics, computes per-second rates
  (RPS, DB q/s, cache hit/miss, latency, failures), runs both detectors, writes a
  CSV row, and streams the result to the dashboard over SSE. Also handles the
  control buttons (`/control/...`).
- `detect_rules.py` — fires when DB load ≫ baseline **and** response time high
  **and** miss rate high (all three together).
- `detect_ml.py` — an `IsolationForest` trained only on baseline samples; flags the
  attack as an anomaly. Lets the report compare rules vs ML.
- `logger_csv.py` — one metrics row per second into `results/`.

### frontend/ (live dashboard)
- `index.html` — the custom console. Connects to `/live` (SSE) for live charts and
  posts to `/control/...` for the buttons. Same design approved in the mockup.

### monitoring/ (Prometheus + Grafana)
- `prometheus.yml` scrapes the backend. Grafana auto-loads the *CacheCollapse*
  dashboard (DB q/s, latency, cache hits/misses, failures).

## 4. Files added

```
docker-compose.yml, .env, .gitignore, README.md
backend/   app.py  db.py  requirements.txt  Dockerfile
database/  init.sql  seed.sql
nginx/     nginx.conf
loadgen/   loadgen.py  requirements.txt  Dockerfile
monitor/   app.py  detect_rules.py  detect_ml.py  logger_csv.py  requirements.txt  Dockerfile
frontend/  index.html
monitoring/ prometheus.yml  grafana/provisioning/...  grafana/dashboards/cachecollapse.json
results/   (CSV output written here at run time)
```

## 5. How to run it

1. Start **Docker Desktop**.
2. In the project folder: `docker compose up --build`
3. Open **http://localhost:8080** (dashboard), **http://localhost:3000** (Grafana).
4. Click *Start normal traffic*, then *Launch attack*; toggle the defenses to see
   the difference. Metrics are saved to `results/`.
5. Stop with `Ctrl+C`, then `docker compose down`.

## 6. Notes / decisions (including tuning found during testing)

- The spec mentioned Locust for normal traffic; to make the demo fully live and
  button-driven, normal traffic and the burst are both produced by one async
  generator controlled through Redis. The behaviour (steady vs burst) is unchanged.
- **Public port is 8090** (not 8080): port 8080 was already taken by another app on
  the dev machine (a WSL relay). Change it in `.env` (`PUBLIC_PORT`) if needed.
- **Short cache TTL (4s).** With a single hot product the stampede is only a brief
  spike at the expiry instant. The attacker therefore rotates across ~20 hot
  products, so entries are always expiring and the overload is *sustained* and
  clearly visible — both realistic and demo-friendly.
- **Rate-limit rejections are counted separately** (`cc_rejected_total`, HTTP 429)
  from real failures (`cc_failed_total`, HTTP 503). Shedding the attacker is the
  defense working, not a failure — so "failed requests" stays near zero under
  protection, which is the correct availability story.
- **ML baseline warm-up.** The first few seconds of normal traffic (cold cache) are
  skipped before training the IsolationForest, otherwise the cold-start miss/DB
  spike pollutes "normal" and the model stops recognising attacks. Standardised
  features are used so every signal contributes.
- The simulated DB query time (`DB_QUERY_DELAY_MS`) and pool size are the main knobs
  for how severe the stampede looks.

## 7. Verification (smoke test results)

Built and run on Docker 29.8.2. All 9 containers come up; `db` reports healthy.
Measured from the live metrics / CSV:

| Scenario | Response (peak) | DB q/s (peak) | Failed/s (peak) | Rule | ML |
|---|---|---|---|---|---|
| Normal baseline | ~130 ms | ~17 | 0 | — | — |
| Attack, no defense | ~490 ms | ~160 | ~180 | fires | fires |
| Attack + defenses | ~120 ms | ~5 | 0 | — | — |

- Product API: 1st call ~180 ms (DB), 2nd call ~12 ms (cache). ✅
- Cache locking cuts DB load ~25× under attack; rate limiting sheds the flood. ✅
- Rule detector fires on the clear overload seconds; the ML detector (once its
  baseline is trained) fires on essentially every attack second — a useful
  rules-vs-ML comparison for the report.
