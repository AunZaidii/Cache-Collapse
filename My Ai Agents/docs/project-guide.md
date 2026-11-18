# CacheCollapse — The Complete Project Guide (Plain-English)

*A full, easy-to-read walkthrough of the whole project: what it does, how it works,
and what every single file is for. No prior knowledge assumed.*

---

## Part 1 — What is this project, in one minute?

Imagine a busy shop. Behind the counter there is a **slow storeroom** (the database)
and a **fast front shelf** (the cache). When a customer asks for "Product 1", the
shopkeeper first checks the front shelf. If it's there, they hand it over instantly.
If not, they walk to the slow storeroom, fetch it, put a copy on the front shelf, and
hand it over. To keep the shelf fresh, each copy is thrown away after a few seconds.

Now the trick: **the moment a popular item is thrown off the shelf, a crowd of
customers all ask for it at the same time.** The shelf is empty, so *every one* of
them sends the shopkeeper running to the slow storeroom at once. The storeroom gets
mobbed and jams up. The shop slows to a crawl — not because anyone broke a rule, but
because of normal shopping behaviour at a bad moment.

That "crowd hitting the empty shelf" is a **cache stampede**. When an attacker does
it *on purpose*, it becomes an attack. The clever part: the attacker never touches
the storeroom (database). They only send normal-looking requests to the shop
(website). The website does the damage to its own database. That's why we call it an
**Indirect** Denial-of-Service attack — the website is the weapon, the database is
the victim.

**This project builds that whole shop in software, attacks it, detects the attack,
and defends against it — and lets you watch all of it happen live in your browser.**

---

## Part 2 — The 9 helpers (containers)

The project is split into **9 small programs**, each running in its own **container**
(a container is like a sealed lunchbox that holds one program and everything it needs
to run). They all talk to each other on a private network. Here is each one in plain
words:

| Helper | Easy explanation |
|---|---|
| **nginx** | The **front door / security guard**. Every request comes here first. It also does "rate limiting" (turning away a flood of requests). |
| **backend** | The **shopkeeper**. A small web app that answers "give me Product X". It checks the cache, and only goes to the database if needed. |
| **redis** | The **fast front shelf** (the cache). Keeps answers in memory for a few seconds so they can be served instantly. |
| **db (PostgreSQL)** | The **slow storeroom** (the database). Holds the real product data. This is the victim that gets overwhelmed. |
| **loadgen** | The **crowd simulator**. A script that pretends to be customers — both calm normal shoppers and the attacking mob. |
| **monitor** | The **security camera + alarm**. Watches everything every half-second, decides if an attack is happening (two ways), and records the numbers. |
| **frontend** | The **control room screen**. A web page with live graphs and buttons so you can run the whole demo. Also includes a demo shop page. |
| **prometheus** | A **note-taker** that collects numbers over time (industry-standard). |
| **grafana** | A **chart maker** that draws those numbers as professional dashboards. |

---

## Part 3 — How a single request travels

When someone asks for a product, here is the journey:

```
You → nginx (front door) → backend (shopkeeper) → redis (fast shelf)
                                   │
                                   └─(only if the shelf is empty)→ db (slow storeroom)
```

1. The request arrives at **nginx**.
2. nginx passes it to the **backend**.
3. The backend asks **redis**: "do you have this product?"
   - **Yes (a "cache hit")** → send it back instantly (about 12 milliseconds).
   - **No (a "cache miss")** → go to **db**, fetch it (about 180 milliseconds, much
     slower), put a copy in redis for next time, then send it back.

So a cache *hit* is ~15× faster than a cache *miss*. The whole attack is about forcing
lots of misses at the same time.

---

## Part 4 — The attack, step by step

1. We set the cache to forget items quickly (a short **TTL** = "time to live", e.g. a
   few seconds).
2. The **loadgen** sends a big **burst** of requests — hundreds at once — all for the
   same small set of "hot" products.
3. It keeps rotating which hot product it hammers, so that at any moment *some*
   product has just expired from the shelf.
4. Every time a product is expired and the burst hits it, **all those requests miss
   the cache together and rush the database at once.**
5. The database can only handle so many at a time, so requests pile up, slow down, and
   some start failing. **That is the overload.**

With no defense, in our tests this pushed the database from ~15 queries/second up to
~230/second, made responses ~5× slower, and caused up to ~180 failed requests per
second.

---

## Part 5 — How we detect the attack (two ways)

A normal traffic spike (like a sale going viral) also sends lots of requests — but it
is served from the cache, so it does **not** hammer the database. So "lots of
requests" alone is a bad alarm. We look deeper.

### Way 1 — The Rule (simple "IF this AND this AND this")
The alarm rings only when **three things are true at the same time**:
- database load is much higher than normal, **AND**
- responses are slow (over 200 ms), **AND**
- the cache-miss rate is high (lots of empty-shelf moments).

A real shopping spike raises requests but is served from cache, so it does **not**
tick all three boxes. Only a real stampede does. This rule is easy to understand and
needs no training. (It lives in `monitor/detect_rules.py`.)

### Way 2 — The Machine-Learning model (learns what "normal" looks like)
We also train a small AI model called an **Isolation Forest**. We let it watch calm,
normal traffic for a few seconds so it learns the "shape" of normal. After that, if
live traffic looks very different from what it learned, it raises a flag. It needs no
labels and no examples of attacks — it just notices "this doesn't look normal". (It
lives in `monitor/detect_ml.py`.)

**We use both** so the report can compare them: the Rule is transparent and instant;
the AI is more sensitive once trained. Together they are stronger than either alone.

---

## Part 6 — How we stop the attack (the defenses)

We use **three layers** of defense, because — and this was a key discovery — no single
one is enough.

1. **Cache locking (single-flight).** When a product is missing and a crowd asks for
   it, only **one** request is allowed to go to the database. Everyone else waits a
   split second and gets the same answer once it's ready. So 500 misses become **1**
   database query instead of 500. (In `backend/app.py`.)

2. **Stale-while-revalidate.** While that one request refreshes the shelf, everyone
   else is instantly handed a **slightly older copy** instead of waiting. The site
   stays fast. We keep a spare "older copy" of every product ready from the start.

3. **Rate limiting (two places).**
   - **At the app (backend):** each customer is capped at a number of requests per
     second; extras are politely turned away.
   - **At the front door (nginx):** the attacker's flood is rejected **right at the
     entrance**, before it can clog the shopkeeper or the doorway. This is the part
     that keeps real customers fast during an attack.

With all defenses on, the database load dropped ~25×, failures fell to zero, and the
demo shop stayed fast (~80 ms).

---

## Part 7 — Every folder and file, explained

Here is the whole project, file by file, in plain words.

### Root folder (the main project folder)

- **`docker-compose.yml`** — The **master recipe**. It lists all 9 helpers, how to
  build them, which ports to open, and how they connect. The single command
  `docker compose up` reads this file and starts everything.
- **`.env`** — A small **settings file**. Holds simple knobs like the database
  password, the cache TTL (how fast items expire), how slow we pretend the database
  is, and the website's port (8090). No real secrets — just local demo values.
- **`.gitignore`** — A list of files Git should **ignore** (like the `.env` file and
  the results CSVs), so they are not uploaded by accident.
- **`README.md`** — The short **"how to run it" note** for anyone opening the project.
- **`deploy.sh`** — A **one-command script** to set the project up on a cloud server
  (installs Docker, starts everything). Only used if you deploy online.
- **`share-remote.bat`** — A **double-click helper** (Windows) that opens a temporary
  public link so teammates on other networks can see your running demo. Optional.

### `backend/` — the shopkeeper (the web app)

- **`app.py`** — The **heart of the web app**. It answers `GET /products/<id>`. Inside
  it: the cache-check logic, the cache-locking defense, the stale-copy serving, the
  app-layer rate limiter, and it publishes its numbers for the monitor to read. In
  easy terms, this file *is* the shopkeeper's brain.
- **`db.py`** — The **door to the database**. It opens a small pool of connections to
  PostgreSQL and runs the product query. It also deliberately makes each query take a
  little time, so the overload is visible. When the pool is full (too many at once),
  it reports "busy" — that's the overload showing up.
- **`requirements.txt`** — The **shopping list of Python libraries** the backend
  needs (Flask for the web part, redis, the Postgres driver, etc.).
- **`Dockerfile`** — The **build instructions** for the backend's container: start
  from Python, install the requirements, copy the code, and run it with a web server
  that can handle many requests at once.

### `database/` — the storeroom (PostgreSQL)

- **`init.sql`** — Runs once when the database first starts. It **creates the table**
  that holds products (id, name, description, price, stock).
- **`seed.sql`** — Also runs once at first start. It **fills the table with 100 fake
  products** so there is something to serve. All made-up data — nothing real.

### `nginx/` — the front door / security guard

- **`nginx.conf`** — The **front door's rulebook**. It says: send normal page visits
  to the frontend, send `/api/...` requests to the backend, send the live feed and
  control buttons to the monitor. It also forwards the real visitor's address (so the
  rate limiter can tell the attacker apart from a real user) and reloads itself when
  the edge rate-limit is switched on.
- **`dynamic/ratelimit.conf`** — A **tiny switch file**. When you flip "Rate limiting"
  on in the dashboard, the monitor writes the limiting rule into this file and nginx
  re-reads it within a second. When off, the file is empty. This is how the front-door
  defense turns on and off live.

### `loadgen/` — the crowd simulator

- **`loadgen.py`** — The **traffic maker**. It constantly checks two switches (set by
  your dashboard buttons): "normal traffic on?" and "attack on?". For normal traffic it
  sends a gentle, steady stream to random products. For the attack it sends big bursts
  at a rotating set of hot products — the stampede.
- **`requirements.txt`** — Its Python shopping list (an async HTTP client + redis).
- **`Dockerfile`** — Build instructions for the loadgen container.

### `monitor/` — the security camera + alarm + recorder

- **`app.py`** — The **control centre**. Every half-second it reads the backend's
  numbers, works out the live rates (requests/s, DB queries/s, cache hit/miss, response
  time, failures), runs **both** detectors, writes a line to the results file, and
  streams everything live to the dashboard. It also handles the dashboard **buttons**
  (start traffic, launch attack, toggle defenses, reset) by setting the switches that
  the loadgen and backend read, and it flips the nginx front-door limiter on/off.
- **`detect_rules.py`** — The **simple rule detector** (the "IF this AND this AND this"
  from Part 5).
- **`detect_ml.py`** — The **AI detector** (the Isolation Forest that learns normal and
  flags anything unusual).
- **`logger_csv.py`** — The **recorder**. It writes one row of numbers per reading into
  a CSV file in `results/`, which becomes the data for your report graphs.
- **`requirements.txt`** — Its Python shopping list (web parts, redis, scikit-learn for
  the AI, etc.).
- **`Dockerfile`** — Build instructions for the monitor container.

### `frontend/` — the control room screen

- **`index.html`** — The **live dashboard**. One self-contained web page with the
  status light, the control buttons, the live charts (response time, DB queries,
  cache hits vs misses, OK vs failed), and the two detector panels. It connects to the
  monitor's live feed and updates about twice a second.
- **`shop.html`** — The **demo storefront ("CacheShop")**. A simple shopping-style page
  that loads a set of products and shows how fast each one loaded. During an attack
  with no defense it turns red/slow; with the defenses on it stays green/fast. This is
  the attack "seen from a customer's point of view".

### `monitoring/` — the industry-standard dashboards

- **`prometheus.yml`** — Tells **Prometheus** where to collect numbers from (the
  backend) and how often.
- **`grafana/provisioning/datasources/datasource.yml`** — Tells **Grafana** to read its
  data from Prometheus.
- **`grafana/provisioning/dashboards/provider.yml`** — Tells Grafana where to find the
  ready-made dashboard file.
- **`grafana/dashboards/cachecollapse.json`** — The **ready-made Grafana dashboard**
  itself (the charts for DB load, latency, cache hits/misses, failures).

### `tests/` — the automatic checker

- **`test_cachecollapse.py`** — A **16-point automatic test**. It runs the whole system
  through its paces (is everything up? does the cache work? does the attack overload the
  DB? do both detectors fire? do the defenses protect? does it recover?) and prints
  "16 passed". This is the proof that everything works.

### `results/` — the recorded numbers

- **`metrics_*.csv`** — One file per run, written by the monitor. Each row is one
  half-second snapshot (time, mode, requests/s, DB queries/s, cache hits/misses,
  response time, failures, and both detectors' outputs). These are the numbers behind
  the report's tables and graphs.

### `Project Documentation/` — all the write-ups

- **`CacheCollapse-Specification.pdf`** — what the project must do (the plan).
- **`CacheCollapse-Design.pdf`** — how it is designed, with UI screenshots.
- **`CacheCollapse-Development.pdf`** — how it was built.
- **`CacheCollapse-Test.pdf`** — the test results (16/16 passed).
- **`CacheCollapse-Deployment.pdf`** — how to put it online.
- **`CacheCollapse-Review-Paper.pdf`** — the formal research paper.
- **`LaTeX/main.tex` + `LaTeX/references.bib`** — the research paper in LaTeX form, for
  building a polished two-column PDF.
- **(this file) The Complete Project Guide** — the plain-English tour you are reading.

---

## Part 8 — How to run the whole thing

1. Make sure **Docker Desktop** is running.
2. Open a terminal in the project folder and type:
   ```
   docker compose up --build
   ```
   The first time, this takes a few minutes (it downloads and builds everything).
3. When it finishes, open your browser:
   - **Dashboard:** http://localhost:8090
   - **Demo shop:** http://localhost:8090/shop.html
   - **Grafana:** http://localhost:3000  ·  **Prometheus:** http://localhost:9090
4. To stop everything: press `Ctrl+C`, then type `docker compose down`.

---

## Part 9 — How to use the dashboard (the buttons)

- **Start normal traffic** — turns on gentle, everyday traffic. Charts show low,
  steady lines.
- **Launch attack** — starts the stampede. With defenses off, watch the DB-queries and
  response-time charts spike, failures climb, the status turn red "Overloaded", and
  both detectors light up.
- **Rate limiting / Cache locking toggles** — turn the defenses on. Watch the system
  calm down to green "Protected" while the attack is still running.
- **Exp 1 / Exp 2 / Exp 3** — one-click presets for the three experiments (baseline /
  attack-no-defense / attack-with-defense).
- **Reset** — stop everything and clear the charts.

Tip: open the **dashboard** and the **shop** side by side. Launch the attack and watch
the shop turn red; turn the defenses on and watch it go green again.

---

## Part 10 — The three experiments and what they show

| Experiment | What you do | What you see |
|---|---|---|
| **1. Baseline** | Normal traffic only | Calm. Low DB load (~15/s), fast responses, no alarms. |
| **2. Attack, no defense** | Launch attack, defenses off | Overload. DB load spikes (~230/s), responses slow (~700 ms), failures (~180/s), both alarms fire. |
| **3. Attack + defense** | Same attack, defenses on | Protected. DB load low (~8/s), fast responses, zero failures, shop stays green. |

The headline result: the defenses cut database load by about **25×** and brought
failures to **zero**, all while the attack kept running.

---

## Part 11 — If something looks wrong (quick fixes)

- **A page looks stuck or old** → hard-refresh the browser tab (`Ctrl+Shift+R`).
- **Graphs look flat** → there's no traffic yet; click "Start normal traffic" or
  "Launch attack". The charts only move when traffic is flowing.
- **`localhost:8090` doesn't open** → make sure Docker is running and the containers
  are up (`docker compose ps`). If another app already uses the port, it's set to 8090
  in `.env` and can be changed there.
- **A container won't start** → run `docker compose up --build` again; first-time
  builds can hit a slow download. The build is safe to retry.

---

## Part 12 — Mini-dictionary (every tech word in easy terms)

- **Container** — a sealed box holding one program and everything it needs to run.
- **Docker / Docker Compose** — the tool that runs containers; Compose runs many at
  once from one recipe file.
- **Cache** — a fast, temporary shelf that stores answers so you don't have to fetch
  them the slow way every time. Here it's **Redis**.
- **TTL (time to live)** — how long a cached item stays before it's thrown away.
- **Database** — the permanent, slower store of real data. Here it's **PostgreSQL**.
- **Cache hit / miss** — found on the shelf (hit, fast) vs not found (miss, must go to
  the database, slow).
- **Cache stampede** — many misses for the same item at the same moment, all hitting
  the database together.
- **Backend / Flask** — the web app that answers requests; Flask is the Python tool it
  is built with.
- **Nginx / reverse proxy** — the front door that receives all traffic and passes it to
  the right place.
- **Rate limiting** — capping how many requests a source may send, and turning away the
  rest.
- **Cache locking (single-flight)** — letting only one request refresh a missing item
  while the rest wait for its result.
- **Stale-while-revalidate** — serving a slightly older copy instantly while one request
  refreshes the fresh copy.
- **DoS / DDoS / IDDoS** — Denial of Service: making a service unavailable. *Indirect*
  (IDDoS) means the attacker overloads one part (the database) by sending normal
  requests to another part (the website).
- **Isolation Forest** — a small AI model that learns what "normal" looks like and
  flags anything that looks very different.
- **Prometheus / Grafana** — tools that collect numbers over time and draw them as
  charts.
- **Server-Sent Events (SSE)** — a way for the server to push live updates to the web
  page continuously.

---

*That's the whole project — every helper, every file, and every idea, in plain words.*
