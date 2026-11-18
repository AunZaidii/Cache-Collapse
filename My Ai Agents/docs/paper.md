# CacheCollapse: Reproducing, Detecting, and Mitigating Cache-Stampede-Driven Indirect Denial of Service in Containerized Web Applications

*Manal Aamir (SE-23070), Tayyaba Arshad (SE-23073), Noor Afza (SE-23075), Batool Fatima (SE-23076), Aun Zaidi (SE-23095)*

*Department of Software Engineering, NED University of Engineering and Technology, Karachi, Pakistan*

*This work was submitted in partial fulfilment of Course SE-401: Information Security (Complex Engineering Problem), Spring Semester 2026. No external funding was received.*

---

## Abstract

Containerized web applications almost universally place an in-memory cache
between a stateless application tier and a relational database to absorb read
traffic. This design is efficient under steady load, but it hides a structural
availability weakness: when a popular cache entry expires, a burst of otherwise
legitimate concurrent requests misses the cache simultaneously and is forwarded,
unthrottled, to the database. The resulting *cache stampede* (also called
dog-piling or the thundering-herd problem) converts a modest amount of
normal-looking traffic into a flood of redundant database queries. Because the
attacker never contacts the database directly and never violates any
application-level rule, the event is an **Indirect Distributed Denial of Service
(IDDoS)** that volume-based network defenses do not catch. This paper presents
**CacheCollapse**, a fully containerized testbed and defense framework that
(i) reproduces the cache-stampede IDDoS deterministically on a nine-container
Docker Compose stack of industry-standard services, (ii) detects it in real time
using two complementary mechanisms — an explainable multi-signal **rule-based
detector** and an unsupervised **IsolationForest** machine-learning detector
trained only on normal traffic — and (iii) mitigates it with a layered defense
combining **cache locking** (single-flight regeneration with
stale-while-revalidate), **application-layer rate limiting**, and
**edge rate limiting** at the reverse proxy. Across a three-experiment protocol,
an undefended attack drove database load from ~15 to a peak of ~230 queries/s,
raised average response time from ~130 ms to ~700 ms, and produced up to ~180
failed requests/s, while both detectors fired. With the layered defense enabled,
database load fell by roughly **25×** (to ~8 queries/s), failed requests dropped
to zero, and customer-visible latency on a demonstration storefront fell from the
hundreds of milliseconds to ~80 ms. An ablation study shows that cache locking
alone protects the database but not the proxy connection path, and that edge rate
limiting is required to keep legitimate users fast during the attack — a finding
with direct deployment relevance. The complete system is reproducible from a
single `docker compose up`, is instrumented with Prometheus/Grafana and a live
custom dashboard, and passes a 16-case automated test suite.

**Keywords:** cache stampede; thundering herd; indirect denial of service;
application-layer DDoS; containerized security; rate limiting; cache locking;
anomaly detection; isolation forest; availability.

---

## Highlights

- A reproducible nine-container Docker Compose testbed turns an ordinary
  Nginx–Flask–Redis–PostgreSQL stack into a controllable cache-stampede IDDoS
  laboratory in which an undefended attack raised peak database load ~15× and
  produced up to ~180 failed requests/s from legitimate-looking traffic.
- A multi-signal rule-based detector (database load, latency, and cache-miss rate
  evaluated together) and an unsupervised IsolationForest detector trained only on
  baseline traffic both identified the attack; a side-by-side comparison
  quantifies their trade-offs in training cost, false alarms, and interpretability.
- A layered mitigation of cache locking with stale-while-revalidate, application
  rate limiting, and edge rate limiting reduced database query load under attack by
  ~25× and restored failed requests to zero while keeping response time low.
- An ablation isolates a deployment-critical result: cache locking protects the
  database but not the proxy, so **edge** rate limiting is necessary to keep
  legitimate users responsive during the flood.

---

## Graphical Abstract

```
          Legitimate-looking burst                 Normal users
                    │                                    │
                    ▼                                    ▼
        ┌───────────────────────── Nginx (reverse proxy) ─────────────────────────┐
        │   EDGE rate limiting (limit_req, toggled live)                           │
        └───────────────┬───────────────────────────────────────────┬────────────┘
                        ▼                                            ▼
                 Flask web app  ──(hit)──►  Redis cache        Monitor
          app rate limit + cache lock          │ (TTL)   per-second metrics
                        │ (miss, single-flight) ▼              ├─ Rule detector
                        └──────────────►  PostgreSQL (victim)  └─ IsolationForest
                                 stale-while-revalidate serves losers instantly
```

---

## 1. Introduction

The availability of a web service is as much a security property as its
confidentiality or integrity. Denial-of-service attacks remain among the most
common and damaging threats to online systems, and the research community has
produced extensive taxonomies and defenses for network- and transport-layer
flooding [1], [2]. A harder class of attacks operates at the application layer:
here the adversary issues syntactically and semantically valid requests that are
individually indistinguishable from legitimate traffic, so that purely
volume-based or signature-based filters are ineffective [3], [4]. This paper
studies a particularly subtle member of that class in the setting most modern
software is deployed in — the containerized, multi-service web application.

Virtually every read-heavy web application interposes an in-memory cache, such as
Redis, between its application tier and its database, so that repeated requests
for the same object are answered from memory rather than from the database. The
cache entry is given a time-to-live (TTL) after which it expires and must be
regenerated from the database. This pattern is efficient under typical load, but
it creates a window of fragility at each expiry. If a popular ("hot") key expires
while many requests for it are in flight, all of those requests miss the cache at
the same instant and are forwarded to the database simultaneously. A single
expiry thus produces not one database query but *N* redundant queries, where *N*
is the instantaneous concurrency on that key. This phenomenon is known as a
**cache stampede**, **dog-pile**, or **thundering herd**, and it is well
documented as a performance hazard in large-scale systems [5], [6].

What is less often treated is that the same mechanism is a **security**
vulnerability. An adversary who understands the caching behavior of a target can
deliberately align a burst of requests for a single hot object with that object's
expiry, repeatedly, so that the database is driven into overload by traffic that
never leaves the normal request distribution of the application. The database —
not the web server — is the victim, and the web application is merely the conduit.
We refer to this as an **Indirect Distributed Denial of Service (IDDoS)**:
indirect because the attacker never addresses the victim component directly, and
distributed because the amplification is produced by the fan-out of concurrency
rather than by the attacker's own request volume. Because the attack rides on
legitimate application logic rather than on a software defect, it cannot be
patched away; it must be *detected* and *mitigated* as an operational property of
the system.

### 1.1. Problem Statement and the Complex Engineering Challenge

Investigating and defending this vulnerability in a containerized environment is a
genuine complex-engineering problem because its difficulty arises from the
*interaction* of well-understood components rather than from any single exotic
one. Three tensions must be resolved simultaneously:

- **Detection without a volumetric signature.** The attack's request rate at the
  web tier can be indistinguishable from a legitimate traffic spike or a flash
  crowd [4]. A detector keyed on request volume alone will either miss the attack
  or raise constant false alarms on benign bursts.
- **Mitigation without denying service to legitimate users.** A defense that
  simply rejects traffic to protect the database can itself become the denial of
  service. The mitigation must shed the *redundant* load (the stampede) while
  continuing to serve genuine users quickly.
- **Faithful, safe, and repeatable experimentation.** Studying an availability
  attack requires driving a realistic system into failure repeatedly and measuring
  per-component resource behavior, which demands an isolated, resettable,
  production-like environment rather than a single-process simulation.

These requirements are coupled: an overly aggressive guardrail degrades legitimate
users, while a cache-only fix that ignores the connection path leaves users slow
even when the database is healthy (Section 4). Resolving the problem therefore
requires an integrated architectural and algorithmic design, not merely a faster
database or a bigger cache.

### 1.2. Proposed Solution

We present **CacheCollapse**, a framework that addresses all three dimensions
together. It consists of: (i) a **reproducible containerized testbed** that
faithfully reconstructs the Nginx → Flask → Redis → PostgreSQL request path on an
isolated Docker Compose network and generates both normal traffic and a
controllable stampede attack; (ii) a **dual detection subsystem** that pairs an
explainable multi-signal rule with an unsupervised IsolationForest model trained
only on baseline behavior; and (iii) a **layered mitigation** combining
single-flight cache locking with stale-while-revalidate, an application-layer
per-client rate limiter, and an edge rate limiter at the reverse proxy that can be
toggled live. The entire system is observable through Prometheus/Grafana and a
purpose-built live dashboard, and it is driven from a browser so that each
experiment is reproducible on demand.

### 1.3. Contributions

- A **containerized IDDoS testbed** that reproduces the cache-stampede attack
  deterministically on nine interacting industry-standard services, with a
  control plane that switches traffic, attack, and each defense on and off live.
- A **multi-signal rule-based detector** that fires only when elevated database
  load, elevated latency, and an elevated cache-miss rate coincide, with a
  cold-cache warm-up suppression that eliminates start-up false alarms.
- An **unsupervised IsolationForest detector** trained exclusively on
  normal-baseline traffic with standardized features, and a controlled comparison
  of the rule-based and ML detectors on training cost, responsiveness, false
  alarms, and interpretability.
- A **layered mitigation** — cache locking with stale-while-revalidate,
  application rate limiting, and edge rate limiting — and an **ablation study**
  isolating each mechanism's contribution, including the deployment-critical
  finding that database-level and proxy-level protection are distinct and both
  required.
- A fully **reproducible, instrumented deployment** (single `docker compose up`,
  Prometheus/Grafana, live dashboard, demonstration storefront) validated by a
  16-case automated test suite.

---

## 2. Literature Review

### 2.1. Cache Stampede and the Thundering Herd

The cache-stampede problem is long recognized in high-scale systems engineering.
Nishtala et al., describing Facebook's memcache deployment, document "stale sets"
and "thundering herds" as first-order concerns and introduce *leases* — per-key
tokens that permit only one client to regenerate a missing value while others
briefly wait — reporting a large reduction in peak database query rate as a
result [6]. Vattani, Chierichetti, and Lowenstein formalize the mitigation side of
the problem, deriving theoretically optimal *probabilistic early recomputation*
(often called XFetch), in which an item is refreshed slightly before its TTL with
a probability that rises as expiry approaches, smoothing regenerations over time
[5]. Both lines of work treat the stampede as a performance and capacity-planning
hazard. CacheCollapse builds on their mitigation insights — single-flight
regeneration is the security-hardened descendant of memcache leases — but reframes
the stampede as an *attacker-triggerable* availability vulnerability and adds the
detection and operational-defense dimensions that performance-oriented treatments
do not require.

### 2.2. Denial of Service and Application-Layer Attacks

Classical DoS/DDoS research classifies attacks and defenses primarily at the
network and transport layers. Mirkovic and Reiher provide the canonical taxonomy
of attack and defense mechanisms [1], and Zargar, Joshi, and Tipper survey the
defense landscape against flooding attacks, emphasizing that effective protection
must span prevention, detection, and response [2]. Application-layer DoS is
recognized as a distinct and harder problem: Xie and Yu model normal browsing
behavior to detect app-layer attacks on popular websites that use ordinary HTTP
GET requests [4], and Praseed and Thilagam survey the full space of
application-layer DDoS, stressing that such attacks can be mounted at low volume
with legitimate requests and are therefore difficult to separate from genuine
traffic [3]. The cache-stampede IDDoS studied here is an extreme point on this
spectrum: not only are the individual requests legitimate, the *aggregate* rate at
the web tier need not be anomalous — the damage is produced downstream by cache
semantics. This places it beyond the reach of defenses keyed on request content or
web-tier volume alone.

### 2.3. Availability Attacks in Containerized and Cloud Environments

The deployment context of this work is the containerized microservice
application. Containers have become the dominant packaging and orchestration unit
for such systems [7], [8], with cluster managers like Kubernetes tracing their
lineage to internal systems such as Borg and Omega [9], and the microservice style
itself decomposing applications into independently deployed, interacting services
[10]. This architecture expands the availability attack surface in ways specific
to the environment. Security analyses of Docker and the container ecosystem
catalog isolation and configuration weaknesses [11], [12], but availability — as
opposed to isolation — has received comparatively less attention. A directly
relevant example is the *Yo-Yo attack* of Sides, Bremler-Barr, and Rosensweig, in
which periodic bursts drive an auto-scaling controller to oscillate between
scale-up and scale-down, degrading performance and inflating cost while evading
simple volume detection [13]. CacheCollapse is complementary: like the Yo-Yo
attack it exploits an emergent property of a standard cloud-native pattern
(there, elasticity; here, caching) using legitimate-looking traffic, and like that
work it must be studied in an orchestrated, resettable environment.

### 2.4. Detection: Rule-Based and Machine-Learning Anomaly Detection

Anomaly detection is the natural framing for an attack with no fixed signature.
Chandola, Banerjee, and Kumar's survey organizes the field by technique and
assumption and underlines that detector choice depends on the availability of
labeled data and on interpretability requirements [15]. Among unsupervised
methods, the IsolationForest of Liu, Ting, and Zhou is attractive for operational
use: it isolates anomalies directly with randomized trees, has near-linear
complexity, needs no labels, and performs well with small training samples [16];
we use its scikit-learn implementation [17]. CacheCollapse deliberately pairs an
unsupervised ML detector with an explainable multi-signal rule, because the two
occupy different points in the design space surveyed in [15]: the rule is
transparent and needs no training but encodes a fixed hypothesis about the
attack's signature, whereas the forest adapts to the observed baseline but is less
interpretable and requires a clean training window.

### 2.5. Mitigation: Rate Limiting and Request Coalescing

Rate limiting is the standard operational control for abusive traffic. Raghavan et
al. study distributed rate limiting that enforces a global aggregate limit across
many sites while preserving fair flow behavior [14], and production reverse proxies
expose mature local rate limiters — Nginx's `ngx_http_limit_req_module` implements
a leaky-bucket limiter keyed on client address with a configurable burst [19].
Request coalescing / single-flight regeneration is the stampede-specific control,
realized in practice through Redis TTLs and `SET … NX` mutual-exclusion primitives
[18], [20] and conceptually descended from memcache leases [6]. Stability-pattern
practice further recommends serving slightly stale data rather than blocking
during regeneration, and bounding failure propagation between tiers [18]. A
contribution of this paper is to show, empirically and in a containerized setting,
that these controls are **not interchangeable**: coalescing protects the database,
rate limiting protects the request path, and only their combination preserves
end-to-end availability during the attack (Section 4.5).

A shared gap across the reviewed literature motivates this work. Performance
treatments of the stampede provide mitigation but no attacker model or detection
[5], [6]; application-layer DoS research provides detection but not the
cache-specific mechanism or a reproducible container testbed [3], [4]; and
container-security work catalogs weaknesses but rarely instruments a specific
availability attack end to end [11], [12]. CacheCollapse integrates attack
reproduction, dual detection, and layered mitigation in one reproducible system.

---

## 3. Methodology

### 3.1. Threat Model and Attack Chain

We assume an external adversary who can send ordinary HTTP requests to the
application's public endpoint and who knows (or can probe) that responses for a set
of hot objects are cached with a short TTL. The adversary cannot reach the database
or cache directly, cannot read internal metrics, and issues only well-formed
requests that are individually valid. The attack chain is:

```
hot cache entry expires  →  N concurrent requests for it arrive  →
N simultaneous cache misses  →  N redundant database queries  →  database overload
```

Let a hot key *k* have regeneration time *d* (the time to fetch from the database
and repopulate the cache). If *N* requests for *k* arrive within the window
(*t_expiry*, *t_expiry* + *d*), an unprotected system issues *N* database queries;
an ideal single-flight system issues **1**. The ratio *N* : 1 is the stampede
amplification, and the attacker maximizes it by (a) concentrating requests on hot
keys and (b) phasing bursts to expiry. To make the window recur frequently and the
attack observable, our testbed uses a short TTL and an attacker that rotates its
burst across a small pool of hot keys so that, at any instant, some key is
expiring (Section 3.3).

### 3.2. System Architecture

CacheCollapse is a nine-service Docker Compose application on one isolated bridge
network; each service is a separate container so that CPU, memory, and I/O can be
attributed per component and the whole system reset between runs. Table 1 lists the
services.

**Table 1. CacheCollapse containerized services.**

| # | Service | Role |
|---|---|---|
| 1 | Nginx | Public reverse proxy; hosts edge (`limit_req`) rate limiting |
| 2 | Flask app | `GET /products/<id>`; hosts cache-locking + app rate limiting |
| 3 | Redis | Cache (short TTL) and shared control bus |
| 4 | PostgreSQL | The victim database; seeded with 100 product records |
| 5 | Load generator | Asynchronous normal traffic and the burst attack |
| 6 | Monitor | Per-second metrics, rule + ML detection, CSV logging, live feed |
| 7 | Frontend | Live control/monitoring dashboard and demonstration storefront |
| 8 | Prometheus | Time-series metrics collection |
| 9 | Grafana | Standard dashboards over Prometheus |

The request path is Nginx → Flask → Redis, with a PostgreSQL read only on a cache
miss. Redis additionally serves as a lightweight **control bus**: the dashboard
writes run-state and defense flags that the load generator and the Flask app read,
so that traffic, attack, and each defense can be toggled live and every experiment
is reproducible from the browser.

### 3.3. Attack and Normal-Traffic Generation

The load generator is an asynchronous client that reads two flags from the control
bus. When *normal traffic* is on, it issues a steady, low-rate stream of requests
spread across the catalog, representing a benign population whose requests mostly
hit the cache. When *attack* is on, it issues large concurrent bursts aimed at a
small pool of hot keys, rotating the target key between bursts so that the pool is
continuously cycling through expiry. This rotation is what converts an isolated,
one-shot stampede into a *sustained* overload: because each key's TTL is short
relative to the inter-burst interval on that key, nearly every burst lands on an
expired entry and regenerates a fresh stampede.

### 3.4. Instrumentation and Metrics

The monitor samples the system twice per second. It scrapes the Flask app's
Prometheus metrics, computes per-interval rates, runs both detectors, appends a row
to a CSV log, and streams the result to the dashboard over Server-Sent Events. The
measured quantities are: requests/s, database queries/s, cache hits and misses (and
the derived miss rate *m* = misses / (hits + misses)), average and p95 response
time, failed requests/s, and per-container CPU and memory. Two event timings are
recorded per attack: **detect time** (from attack onset to first alert) and
**recover time** (from defense activation to return to a healthy state). Failed
requests are split into two counters: `HTTP 503` responses, which indicate genuine
database overload, and `HTTP 429` responses, which indicate *intentional* shedding
by the rate limiter; only the former count as availability failures, so that an
active defense is not mis-scored as an outage.

### 3.5. Rule-Based Detector

The rule-based detector encodes the attack's multi-signal signature. It raises an
alert only when elevated database load, elevated latency, and an elevated cache-miss
rate hold *simultaneously*:

```
alert  ⇔  (q_db > K · q̄_base)  ∧  (L̄ > τ_L)  ∧  (m > τ_m)
```

where *q_db* is database queries/s, *q̄_base* is a learned baseline of normal
database load, *L̄* is average response time, and *m* is the cache-miss rate. In our
configuration *K* = 5, *τ_L* = 200 ms, and *τ_m* = 0.5. Requiring all three
conditions is what distinguishes an attack from a benign flash crowd: a legitimate
traffic spike raises request volume but is *served from cache*, so it does not
simultaneously raise database load and the miss rate. Two engineering safeguards
make the rule robust: a **cold-cache warm-up suppression** disables alerting during
the first few seconds after traffic starts (when an empty cache briefly mimics a
stampede), and the baseline *q̄_base* is learned online from steady normal traffic.

### 3.6. Machine-Learning Detector

The ML detector is an unsupervised IsolationForest [16], [17] trained only on
normal traffic — no attack samples and no labels are required. Each one-interval
sample is the feature vector **x** = [*q_db*, *L̄*, *m*, requests/s, failed/s].
Because these features span very different scales, they are standardized to
zero mean and unit variance using statistics estimated on the baseline window
before the forest is fit; at inference each live sample is standardized with the
same statistics and scored. A sample flagged as an outlier by the forest's own
decision function is an anomaly. Two safeguards mirror the rule detector: the model
trains only after a short warm-up so the baseline is clean, and an alert must
persist for two consecutive samples (debounce) to be reported, which removes
isolated single-interval blips while leaving a sustained attack easily detectable.

### 3.7. Mitigation I — Cache Locking with Stale-While-Revalidate

The stampede-specific control is single-flight regeneration. On a cache miss for
key *k*, the Flask app attempts to acquire a short-lived mutex via
`SET lock:k 1 NX PX T`. The single winner queries the database and writes two
copies to the cache: a *fresh* copy under the normal TTL and a *stale* copy under a
much longer TTL. Every other concurrent miss (a "loser") does **not** queue on the
database; it immediately returns the stale copy. Thus *N* simultaneous misses
produce exactly **one** database query, and the losers are served in cache time
rather than waiting for regeneration. A stale copy is pre-warmed for every key at
start-up so that the defense is instant even if an attack begins before any value
has been cached. Serving slightly-stale data during regeneration follows
established stability-pattern practice [18] and is the security-oriented
generalization of memcache leases [6].

### 3.8. Mitigation II — Layered Rate Limiting (Application and Edge)

Rate limiting sheds the attacker's excess concurrency. CacheCollapse implements it
at two layers, and shows (Section 4.5) that both are needed. The **application
layer** enforces a per-client, per-second cap inside the Flask app using Redis
counters, returning `HTTP 429` to excess requests; because it runs behind the
proxy, it is toggled live and does not require a proxy reload. The **edge layer**
uses Nginx's leaky-bucket `limit_req` keyed on client address [19]; when the
operator enables rate limiting, the monitor rewrites a small included
configuration fragment and triggers an Nginx reload, so the attacker's flood is
rejected at the proxy *before* it consumes application or connection resources. A
necessary supporting detail is that the proxy forwards the real client address to
the application, so that the per-client limiter buckets the attacker and a genuine
user separately rather than treating all traffic as one client.

### 3.9. Experimental Protocol

Experiments follow a three-condition protocol executed from the dashboard:
**E1 — Baseline** (normal traffic only); **E2 — Attack, undefended** (burst attack
with all defenses off); and **E3 — Attack, defended** (same attack with cache
locking, application rate limiting, and edge rate limiting enabled). Each condition
is sampled for a fixed window, and all metrics of Section 3.4 are logged. A
demonstration storefront page ("CacheShop"), which loads a set of hot products and
reports per-item load time, provides a customer's-eye view of availability during
each condition. All experiments ran on a single host under Docker Desktop
(Docker 29.x); training time for the forest is a few seconds of baseline traffic.

---

## 4. Results and Analysis

### 4.1. Setup

The database was seeded with 100 product records; a short cache TTL and a
rotating-hot-key attacker (Section 3.3) were used so that stampedes recur and the
overload is sustained rather than a single transient. Reported figures are
representative values from the logged runs; because the attack is bursty, per-metric
peaks and interval averages are distinguished where relevant.

### 4.2. Cache Behavior (Sanity Check)

The caching path behaves as designed: the first request for a product is answered
from the database in ~180 ms (including the deliberately modeled query cost), and
the immediately following request for the same product is answered from Redis in
~12 ms — a ~15× speed-up that confirms the cache is the component under contention
during a stampede.

### 4.3. The Three-Experiment Comparison

Table 2 summarizes the three conditions. Under the undefended attack (E2), database
load rose from a baseline of ~15 queries/s to a peak of ~230 queries/s, average
response time rose from ~130 ms to a peak of ~700 ms, the cache-miss rate climbed
toward ~0.88, and up to ~180 requests/s failed with `HTTP 503` — a clear overload
produced entirely by legitimate-looking requests. With the layered defense enabled
(E3), database load fell to ~8 queries/s (a ~25× reduction versus the undefended
attack), response time returned to ~90 ms, and `HTTP 503` failures fell to zero.

**Table 2. Three-experiment comparison (representative values).**

| Condition | DB queries/s (peak) | Avg. response (peak) | Failed/s (503) | Status |
|---|---|---|---|---|
| E1 — Baseline | ~15 | ~130 ms | 0 | Healthy |
| E2 — Attack, undefended | ~230 | ~700 ms | ~180 | Overloaded |
| E3 — Attack, defended | ~8 | ~90 ms | 0 | Protected |

### 4.4. Detection: Rule-Based vs. Machine-Learning

Both detectors identified the attack in E2 and remained silent in E1. Their
behavior differs in ways that matter operationally, summarized in Table 3. The
rule-based detector requires no training and is immediately available, is fully
interpretable (an alert names exactly which of the three conditions held), and —
because it demands all three signals at once — did not fire on calm baseline
traffic. However, because the attack is bursty, the three conditions align only
intermittently, so the rule fires on a subset of attack intervals. The
IsolationForest, once trained on a short baseline window, fired on essentially
every attack interval and so provided denser, faster confirmation, at the cost of
requiring a clean training window and offering less transparent justification.
Using them together yields both properties: the rule explains *why* an alert
occurred while the forest provides sensitive, continuous confirmation. This
side-by-side evaluation is itself a contribution, operationalizing the
assumption-driven trade-offs catalogued in the anomaly-detection literature [15].

**Table 3. Detector comparison.**

| Property | Rule-based | IsolationForest (ML) |
|---|---|---|
| Training data | None | Baseline only (unsupervised) |
| Availability | Immediate | After short warm-up |
| False alarms on baseline | None (multi-signal) | Rare (tightened + debounced) |
| Coverage of attack intervals | Intermittent (bursty) | Dense |
| Interpretability | High (names the signals) | Low |

### 4.5. Mitigation Ablation

An ablation isolates each defense's contribution and yields the paper's central
deployment finding (Table 4). Cache locking alone **protects the database** —
database query load under attack drops to single digits because *N* misses are
coalesced to one query — but it does **not** by itself keep legitimate users fast:
with only application-layer controls, the attacker's flood still reaches and
congests the reverse proxy and the host's connection path, so the demonstration
storefront remained slow (hundreds of milliseconds) even though the database was
healthy. Adding **stale-while-revalidate** removed the regeneration queue so that
coalesced misses are served instantly rather than waiting. Adding **edge rate
limiting** removed the remaining congestion by rejecting the flood at the proxy;
only then did storefront latency fall to ~80 ms. In other words, database
protection and request-path protection are distinct problems requiring distinct
controls — a result that is easy to miss when a defense is evaluated by database
metrics alone.

**Table 4. Mitigation ablation (customer-visible behavior under attack).**

| Configuration | DB load | Storefront latency | Availability |
|---|---|---|---|
| No defense | Overloaded (~230 q/s) | Fails / very slow | Denied |
| Cache lock only | Protected (low) | Still slow (queuing/congestion) | Degraded |
| + Stale-while-revalidate | Protected | Improved | Degraded (proxy congested) |
| + Edge rate limiting | Protected (~8 q/s) | Fast (~80 ms) | Preserved |

### 4.6. Recovery

Recovery is fast. When the defenses are enabled during an ongoing attack, the
system returns to a healthy state — database load low, response time low, zero
`HTTP 503` failures — within roughly 1.5–2.5 s in the logged runs, because cache
locking immediately collapses the redundant queries and the pre-warmed stale cache
serves losers without waiting for regeneration.

### 4.7. Edge vs. Application Rate Limiting

Isolating the two rate-limiting layers confirms that they protect different things.
Application-layer limiting correctly sheds the attacker's excess *database* work
(returning `HTTP 429` rather than touching the database), but because the proxy has
already accepted and forwarded the connection, it does not relieve proxy or
connection-path congestion; under a heavy flood the customer-visible latency on the
storefront stayed high even though database metrics looked healthy. Enabling edge
`limit_req` rejected the flood at the proxy and brought storefront latency down by
roughly an order of magnitude. This is the empirical basis for recommending edge
rate limiting as part of the defense, not application limiting alone.

### 4.8. End-to-End Validation

The complete system is validated by a 16-case automated test suite exercised
against the live stack. The suite checks service health and routing, correct cache
behavior (slow first read, fast cached read), the calm baseline (no false alarms),
the undefended attack (database overload with both detectors firing), each
mitigation (database protection, availability preservation, storefront served while
defended), recovery after the attack stops, and the live-feed update rate. All 16
cases pass, providing repeatable evidence for the results above.

---

## 5. Comparative Analysis

CacheCollapse is best understood not as a competitor to any single prior system but
as an integration of concerns that prior work addresses only in part. Table 5
compares coverage across four dimensions relevant to the complex-engineering
problem: whether the work provides a *reproducible attack testbed* for the
cache-stampede IDDoS, whether it provides *real-time detection*, whether it
provides *layered mitigation* spanning both the database and the request path, and
whether it targets the *containerized* deployment setting specifically.

**Table 5. Capability coverage.** ✓ = addressed; ∼ = partial; × = not addressed.

| Work | Attack testbed | Detection | Layered mitigation | Containerized |
|---|---|---|---|---|
| Probabilistic prevention [5] | × | × | ∼ (coalescing only) | × |
| Memcache leases [6] | × | × | ∼ (coalescing only) | × |
| App-layer DDoS detection [3], [4] | × | ✓ | × | × |
| DDoS defense surveys [1], [2] | × | ∼ | ∼ | × |
| Container security [11], [12] | × | × | × | ∼ |
| Yo-Yo / auto-scaling attack [13] | ∼ | ∼ | × | ✓ |
| **CacheCollapse (this work)** | **✓** | **✓** | **✓** | **✓** |

Performance-oriented stampede work [5], [6] contributes the coalescing idea that
CacheCollapse hardens into a security control but offers no attacker model,
detection, or testbed. Application-layer DDoS work [3], [4] contributes detection
methodology but neither the cache-specific mechanism nor a reproducible container
environment. Container-security work [11], [12] catalogs weaknesses without
instrumenting a specific availability attack end to end. The Yo-Yo attack [13] is
the closest in spirit — an emergent-behavior availability attack on a cloud-native
pattern — and motivates our use of an orchestrated, resettable testbed, but targets
elasticity rather than caching and does not combine detection with layered
mitigation. CacheCollapse is the only one of these to address all four dimensions
together.

---

## 6. Discussion

### 6.1. Why a Layered Defense Is Necessary

The ablation (Section 4.5) shows that no single control is sufficient. Cache
locking is the only mechanism that addresses the *root cause* — it restores the
*N* : 1 query ratio to 1 : 1 — but it operates below the proxy and cannot relieve
congestion that the attacker's connection volume imposes on the edge. Rate limiting
relieves that congestion but, applied only at the application layer, acts too late
in the path; applied at the edge it protects the proxy but does not by itself fix
the redundant-query amplification if a limiter is tuned permissively. The correct
design composes them: edge rate limiting caps the flood, cache locking coalesces
the surviving misses, and stale-while-revalidate ensures the coalesced waiters are
served without delay. This layered, defense-in-depth structure mirrors the
prevention–detection–response framing urged in the DDoS defense literature [2].

### 6.2. Rules vs. Machine Learning

The detector comparison (Section 4.4) argues against treating rule-based and
ML detection as substitutes. The rule is the better *first* line because it is
immediate, interpretable, and free of training and false-alarm risk on benign
spikes; the forest is the better *continuous* confirmation because, once trained,
it fires densely on the attack and adapts to the observed baseline. Their
weaknesses are complementary — the rule's fixed hypothesis versus the forest's
training dependence and opacity — which is exactly why deploying both is preferable
to choosing one, consistent with the assumption-driven view of anomaly detection
[15].

### 6.3. Deployment Implications

The practical message for operators of cached, containerized web services is that
cache-stampede resilience is an availability-security property that must be designed
in, not an incidental benefit of adding a cache. Concretely: enable single-flight
regeneration (or lease-style coalescing) with a stale-serving fallback on hot keys;
rate-limit at the edge, not only in the application; forward real client identity so
per-client limits are meaningful; and monitor database load, latency, and cache-miss
rate *together*, since any one alone is an unreliable alarm. All of these are
realizable with standard components — Redis, Nginx, and a reverse proxy — as the
testbed demonstrates.

### 6.4. Limitations

Several limitations are acknowledged. First, the testbed runs on a single host under
Docker Desktop; the host's port-forwarding layer contributes some latency under
heavy connection load that a multi-node cluster deployment would not, so absolute
latency figures are environment-dependent while the *relative* effects
(defended vs. undefended) are robust. Second, the normal-traffic population and the
attacker are synthetic; validating against production traffic traces would
strengthen the detection evaluation. Third, the IsolationForest requires a clean
baseline window, so a system that is attacked from the moment it starts would train
on contaminated data; combining it with the always-available rule mitigates but does
not eliminate this. Fourth, the thresholds (*K*, *τ_L*, *τ_m*, the limiter rates)
were tuned on the testbed and would require site-specific calibration before
production use.

---

## 7. Conclusion

This paper presented CacheCollapse, a reproducible containerized framework for
studying and defending the cache-stampede Indirect DDoS — an availability attack in
which legitimate-looking requests, aligned with cache expiry, overload a database
through the application rather than attacking it directly. On a nine-container stack
of standard services, an undefended attack raised peak database load roughly 15×,
pushed average response time from ~130 ms to ~700 ms, and produced up to ~180 failed
requests/s. A multi-signal rule-based detector and an unsupervised IsolationForest
detector each identified the attack while remaining silent on benign traffic, and
their comparison clarified a genuine trade-off between interpretability and
continuous sensitivity. A layered mitigation — cache locking with
stale-while-revalidate, application rate limiting, and edge rate limiting — reduced
database query load by roughly 25×, eliminated `HTTP 503` failures, and restored
fast customer-visible response, recovering within a couple of seconds. An ablation
established the central operational result that database-level coalescing and
edge-level rate limiting protect different parts of the system and are both
required.

Future work will (1) replay production traffic traces to validate detection against
real flash crowds; (2) extend the testbed to a multi-node Kubernetes deployment to
study the interaction of stampede mitigation with auto-scaling and attacks such as
Yo-Yo [13]; (3) add probabilistic early recomputation [5] as a complementary
proactive control and compare it with reactive single-flight locking; and
(4) automate threshold calibration so the detectors self-tune to a site's baseline.

---

## CRediT Authorship Contribution Statement

**Manal Aamir:** Conceptualization, Methodology, Writing – Review and Editing.
**Tayyaba Arshad:** Investigation, Validation, Data Curation.
**Noor Afza:** Software (load generation and monitoring), Visualization.
**Batool Fatima:** Software (detection and mitigation), Validation.
**Aun Zaidi:** Conceptualization, Methodology, Software (system integration),
Writing – Original Draft.

---

## References

[1] J. Mirkovic and P. Reiher, "A taxonomy of DDoS attack and DDoS defense
mechanisms," *ACM SIGCOMM Computer Communication Review*, vol. 34, no. 2,
pp. 39–53, 2004. doi:10.1145/997150.997156.

[2] S. T. Zargar, J. Joshi, and D. Tipper, "A survey of defense mechanisms against
distributed denial of service (DDoS) flooding attacks," *IEEE Communications
Surveys & Tutorials*, vol. 15, no. 4, pp. 2046–2069, 2013.
doi:10.1109/SURV.2013.031413.00127.

[3] A. Praseed and P. S. Thilagam, "DDoS attacks at the application layer:
Challenges and research perspectives for safeguarding web applications," *IEEE
Communications Surveys & Tutorials*, vol. 21, no. 1, pp. 661–685, 2019.
doi:10.1109/COMST.2018.2870658.

[4] Y. Xie and S.-Z. Yu, "Monitoring the application-layer DDoS attacks for popular
websites," *IEEE/ACM Transactions on Networking*, vol. 17, no. 1, pp. 15–25, 2009.
doi:10.1109/TNET.2008.925628.

[5] A. Vattani, F. Chierichetti, and K. Lowenstein, "Optimal probabilistic cache
stampede prevention," *Proceedings of the VLDB Endowment*, vol. 8, no. 8,
pp. 886–897, 2015. doi:10.14778/2757807.2757813.

[6] R. Nishtala, H. Fugal, S. Grimm, M. Kwiatkowski, H. Lee, H. C. Li, R. McElroy,
M. Paleczny, D. Peek, P. Saab, D. Stafford, T. Tung, and V. Venkataramani, "Scaling
Memcache at Facebook," in *Proc. 10th USENIX Symposium on Networked Systems Design
and Implementation (NSDI)*, 2013, pp. 385–398.

[7] C. Pahl, "Containerisation and the PaaS cloud," *IEEE Cloud Computing*, vol. 2,
no. 3, pp. 24–31, 2015. doi:10.1109/MCC.2015.51.

[8] D. Merkel, "Docker: Lightweight Linux containers for consistent development and
deployment," *Linux Journal*, vol. 2014, no. 239, 2014.

[9] B. Burns, B. Grant, D. Oppenheimer, E. Brewer, and J. Wilkes, "Borg, Omega, and
Kubernetes," *Communications of the ACM*, vol. 59, no. 5, pp. 50–57, 2016.
doi:10.1145/2890784.

[10] N. Dragoni, S. Giallorenzo, A. L. Lafuente, M. Mazzara, F. Montesi,
R. Mustafin, and L. Safina, "Microservices: Yesterday, today, and tomorrow," in
*Present and Ulterior Software Engineering*, M. Mazzara and B. Meyer, Eds. Springer,
2017, pp. 195–216. doi:10.1007/978-3-319-67425-4_12.

[11] T. Combe, A. Martin, and R. Di Pietro, "To Docker or not to Docker: A security
perspective," *IEEE Cloud Computing*, vol. 3, no. 5, pp. 54–62, 2016.
doi:10.1109/MCC.2016.100.

[12] S. Sultan, I. Ahmad, and T. Dimitriou, "Container security: Issues,
challenges, and the road ahead," *IEEE Access*, vol. 7, pp. 52976–52996, 2019.
doi:10.1109/ACCESS.2019.2911732.

[13] M. Sides, A. Bremler-Barr, and E. Rosensweig, "Yo-Yo attack: Vulnerability in
auto-scaling mechanism," in *Proc. ACM SIGCOMM Conference (Posters and Demos)*,
2016, pp. 103–104. doi:10.1145/2934872.2959420.

[14] B. Raghavan, K. Vishwanath, S. Ramabhadran, K. Yocum, and A. C. Snoeren,
"Cloud control with distributed rate limiting," in *Proc. ACM SIGCOMM Conference*,
2007, pp. 337–348. doi:10.1145/1282380.1282419.

[15] V. Chandola, A. Banerjee, and V. Kumar, "Anomaly detection: A survey," *ACM
Computing Surveys*, vol. 41, no. 3, article 15, 2009. doi:10.1145/1541880.1541882.

[16] F. T. Liu, K. M. Ting, and Z.-H. Zhou, "Isolation forest," in *Proc. 8th IEEE
International Conference on Data Mining (ICDM)*, 2008, pp. 413–422.
doi:10.1109/ICDM.2008.17.

[17] F. Pedregosa et al., "Scikit-learn: Machine learning in Python," *Journal of
Machine Learning Research*, vol. 12, pp. 2825–2830, 2011.

[18] M. T. Nygard, *Release It! Design and Deploy Production-Ready Software*,
2nd ed. Raleigh, NC: Pragmatic Bookshelf, 2018.

[19] Nginx, "Module ngx_http_limit_req_module," Nginx documentation. [Online].
Available: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html

[20] Redis, "Redis documentation: key expiration (EXPIRE/TTL) and distributed locks
with SET NX," Redis. [Online]. Available: https://redis.io/docs/

[21] Docker Inc., "Docker Compose documentation," Docker. [Online]. Available:
https://docs.docker.com/compose/

[22] B. Brazil, *Prometheus: Up & Running — Infrastructure and Application
Performance Monitoring*. Sebastopol, CA: O'Reilly Media, 2018.
