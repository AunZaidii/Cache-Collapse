# CacheCollapse

A small lab that shows how a **cache stampede** (an indirect DDoS) can overload a
database through normal-looking web traffic — and how **rate limiting** and
**cache locking** stop it. Everything runs in Docker, and you drive the whole demo
live from a browser dashboard.

## What's inside (9 containers)

| Service | Role |
|---|---|
| `nginx` | Front door / reverse proxy (port **8090**) |
| `backend` | Flask app, `GET /products/<id>` — holds cache-locking + rate-limit logic |
| `redis` | Cache (short TTL) + shared control bus |
| `db` | PostgreSQL — the victim, seeded with 100 fake products |
| `loadgen` | Generates normal traffic and the burst attack |
| `monitor` | Scrapes metrics, rule + ML detection, CSV logging, live feed |
| `frontend` | The custom live dashboard + control panel |
| `prometheus` | Time-series metrics collector |
| `grafana` | Ready-made dashboards (port **3000**) |

## Run it

You need **Docker Desktop** running. Then, in this folder:

```
docker compose up --build
```

First start takes a few minutes (it downloads images and builds). When it's up:

- **Dashboard:** http://localhost:8090
- **Grafana:** http://localhost:3000  (dashboard: *CacheCollapse*)
- **Prometheus:** http://localhost:9090

Stop everything with `Ctrl+C`, then `docker compose down`.

## Drive the demo (from the dashboard)

1. **Start normal traffic** → steady low lines (baseline).
2. **Launch attack** with defenses off → DB queries spike, latency jumps, failures
   climb, status goes **Overloaded**, both detectors fire.
3. Turn **Cache locking** and **Rate limiting** on, attack again → DB stays flat,
   status stays **Protected**.

Or use the **Exp 1 / 2 / 3** preset buttons.

## Results for the report

The monitor writes one CSV row per second to **`results/`** (metrics + both
detectors' output). Use it with pandas/matplotlib to make the report graphs.

## Configuration

All knobs are in **`.env`** (cache TTL, simulated DB query time, attack defaults).
No real secrets — local dev values only.
