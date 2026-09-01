# GET /items benchmark results

This benchmark measures the authenticated `GET /items` endpoint against the
Docker Compose application stack after seeding one benchmark user with 1,000
active inventory items.

## Environment context

| Context | Value |
| --- | --- |
| Date/time (UTC) | `2026-09-01 21:39 UTC` |
| FreshTracker commit | `bac3247` |
| Working tree | Local changes present during benchmark |
| Host/runner | Local macOS Docker Desktop |
| Operating system | `Darwin 25.0.0 arm64` |
| Flask/Gunicorn configuration | Gunicorn, 2 workers, 4 threads, Python 3.10.21 |
| PostgreSQL version/configuration | PostgreSQL 16.14 via `postgres:16-alpine` |
| Database location | Local Docker Compose `db` service |
| Seeded inventory | 1 benchmark user, 1,000 active items |
| Load profile | 50 virtual users for 30 seconds |
| k6 version | k6 v2.2.0, linux/arm64 Docker image |
| Network conditions | k6 Docker container to local API through `host.docker.internal` |

## Bottleneck

The inventory query used the existing `ix_inventory_items_user_status_expiry`
index and returned 1,000 rows in 16.34 ms under `EXPLAIN ANALYZE`, so the query
plan was not the multi-second latency source. The higher-impact bottleneck was
session refresh behavior: every successful authenticated request updated the
same `sessions.last_seen_at` row. Under the k6 profile, all 50 virtual users
shared one benchmark login, which turned a read-heavy endpoint into a contended
write path. The fix throttles session refresh writes to once every five minutes
per active session while preserving 30-minute idle expiry.

## Before and after

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| Average latency (`http_req_duration avg`) | 1.41 s | 392.49 ms | 72.2% lower |
| Median latency (`http_req_duration med`) | 1.26 s | 413.85 ms | 67.2% lower |
| p90 latency (`http_req_duration p(90)`) | 3.25 s | 491.02 ms | 84.9% lower |
| p95 latency (`http_req_duration p(95)`) | 3.78 s | 509.67 ms | 86.5% lower |
| Max latency (`http_req_duration max`) | 5.78 s | 627.71 ms | 89.1% lower |
| Request throughput (`http_reqs rate`) | 32.51 req/s | 125.83 req/s | 287.0% higher |
| Total HTTP requests | 1,148 | 3,843 | 234.8% higher |
| Completed iterations | 1,147 | 3,842 | 234.9% higher |
| Failed HTTP requests | 0.00% | 0.00% | unchanged |
| Checks passed | 2,295 / 2,295 | 7,685 / 7,685 | unchanged pass rate |

## Procedure

1. Started the full Docker Compose stack and waited for the Flask API health
   check to pass.
2. Seeded `benchmark-20260901-optimized@example.com` with 1,000 active
   inventory items through the running API container.
3. Ran k6 with:
   `docker run --rm -v /Users/michael/Development/Projects/FreshTracker/benchmarks:/scripts grafana/k6 run -e BASE_URL=http://host.docker.internal:5000 -e ORIGIN=http://localhost:5173 -e BENCHMARK_EMAIL=benchmark-20260901-optimized@example.com -e BENCHMARK_PASSWORD=Benchmark-Password-1234 /scripts/benchmark_items.js`.

## Notes

`GET /items` includes authentication and the current session-refresh database
write, so this benchmark measures complete endpoint behavior rather than an
isolated inventory `SELECT`. The first setup request logs in once; the measured
loop then repeatedly requests the authenticated inventory list.
