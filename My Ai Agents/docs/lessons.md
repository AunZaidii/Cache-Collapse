# Lessons Learned

- **Verify interactive code by actually rendering it.** The dashboard mockup looked
  fine but its `tick()` read an uninitialized array (`S._rps`) and threw on the
  first call, so nothing animated. It was only caught when screenshots came out
  empty. Lesson: for anything interactive, render/run it, don't assume it works.

- **Finish a tool before copying it.** The Markdown→PDF helper was copied to
  `tools/` before image support was added, so the design PDF first came out with
  the screenshots as raw text instead of pictures. Lesson: finish the helper, then
  copy, then generate.

- **Keep metric counters in one process.** With multiple gunicorn workers each
  worker has its own counters, so totals split. The backend runs 1 worker + many
  threads so the Prometheus counters stay consistent and concurrency still happens.

- **Always put a timeout on browser fetches, and don't overlap polling.** The shop
  page fired 12 fetches every 2s with no timeout; during an attack they hung and
  piled up, leaving the page stuck "red" even after the attack stopped. Fix: an
  AbortController timeout per request + schedule the next refresh only after the
  current one finishes.

- **Don't flag the cold-cache warm-up as an attack.** When traffic first starts the
  cache is empty, so everything misses at once — which briefly looks like a
  stampede and caused a false alarm on the baseline. Suppress detection during the
  short warm-up (attacks run in a different mode, so they are unaffected).

- **Forward the real client IP through the proxy for per-client rate limiting.**
  The limiter bucketed by the address it saw, which was Nginx's — so the attacker
  and real shoppers shared one budget and the attacker starved the shop even with
  protection on. Fix: Nginx sends `X-Forwarded-For`, so each real client is limited
  separately.

- **Serve stale cache during a stampede instead of queuing.** With cache locking,
  waiting requests piled up and the protected site became slow (~2.5 s latency).
  Serving the slightly-stale copy immediately (stale-while-revalidate) keeps the
  site fast while one request refreshes the cache.

- **Rate-limit at the EDGE, not just the app, to protect the proxy.** The attacker's
  flood congests Nginx the same whether defenses are on or off — app-layer rate
  limiting only lightens the database. The shop stayed slow under protection because
  Nginx was still flooded. Real fix: Nginx-level `limit_req`, toggled live by
  rewriting an include file and reloading Nginx, so the flood is rejected before it
  can congest the proxy. On Docker Desktop (Windows) the host port-forward also adds
  latency under a connection flood, which edge limiting relieves.
