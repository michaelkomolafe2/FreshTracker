# GET /items benchmark results

This benchmark measures the authenticated `GET /items` endpoint against the
Docker Compose application stack after seeding one benchmark user with 1,000
active inventory items.

## Environment context

| Context | Value |
| --- | --- |
| Date/time (UTC) | `2026-09-01 18:50 UTC` |
| FreshTracker commit | `a550606` |
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

## Result

| Metric | Value |
| --- | ---: |
| Average latency (`http_req_duration avg`) | 1.41 s |
| Median latency (`http_req_duration med`) | 1.26 s |
| p90 latency (`http_req_duration p(90)`) | 3.25 s |
| p95 latency (`http_req_duration p(95)`) | 3.78 s |
| Max latency (`http_req_duration max`) | 5.78 s |
| Request throughput (`http_reqs rate`) | 32.51 req/s |
| Total HTTP requests | 1,148 |
| Completed iterations | 1,147 |
| Failed HTTP requests | 0.00% |
| Checks passed | 2,295 / 2,295 |

## Procedure

1. Started the full Docker Compose stack and waited for the Flask API health
   check to pass.
2. Seeded `benchmark-20260901-001@example.com` with 1,000 active inventory
   items through the running API container.
3. Ran k6 with:
   `docker run --rm -v /Users/michael/Development/Projects/FreshTracker/benchmarks:/scripts grafana/k6 run -e BASE_URL=http://host.docker.internal:5000 -e ORIGIN=http://localhost:5173 -e BENCHMARK_EMAIL=benchmark-20260901-001@example.com -e BENCHMARK_PASSWORD=Benchmark-Password-1234 /scripts/benchmark_items.js`.

## Notes

`GET /items` includes authentication and the current session-refresh database
write, so this benchmark measures complete endpoint behavior rather than an
isolated inventory `SELECT`. The first setup request logs in once; the measured
loop then repeatedly requests the authenticated inventory list.
