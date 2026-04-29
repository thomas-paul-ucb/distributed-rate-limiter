# Distributed Rate Limiter

A production-grade, high-performance rate limiting service built as a standalone sidecar — the architectural pattern used by companies like Stripe, Kong, and Envoy. Supports multiple algorithms, atomic Redis operations via Lua scripts, full observability, and automated CI/CD.

---

## Architecture

```
Client Request
      │
      ▼
┌─────────────────┐
│   API Gateway   │  ← FastAPI entry point
│   (FastAPI)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Rate Limiter   │  ← Middleware (sidecar pattern)
│   Middleware    │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌────────────┐
│ Redis │ │  Postgres  │
│ (hot  │ │  (rules +  │
│ path) │ │   audit)   │
└───────┘ └────────────┘
         │
         ▼
┌─────────────────┐
│   Prometheus    │  ← Metrics scraping every 5s
│   + Grafana     │  ← Live dashboard
└─────────────────┘
```

**Sidecar Pattern:** The rate limiter runs as a separate service that intercepts all incoming requests before they reach your application logic. Any service can plug into it without modifying its own code.

---

## Algorithms

### Token Bucket
Allows burst traffic up to a capacity limit, then refills at a steady rate. Best for APIs that want to allow occasional spikes while controlling average throughput.

```
Capacity: 10 tokens | Refill: 2/sec

[●●●●●●●●●●] → request → [●●●●●●●●●] 9 remaining
[●●●●●●●●●] → request → [●●●●●●●●] 8 remaining
...
[] → request → REJECTED (429)
+1 second → [●●] refilled
```

### Sliding Window Counter
Strict rate limiting using a rolling time window. Prevents boundary bursts by always looking at the exact last N seconds. Best for payment APIs, authentication endpoints, or anywhere hard limits are required.

```
Fixed Window Problem (naive):
:00 ──────────── :60 ──────────── :120
   100 requests      100 requests
   (200 hit server in 2 seconds at boundary)

Sliding Window Solution:
At any moment, count requests in the last 60 seconds.
Never exceeds the limit regardless of timing.
```

---

## Why Lua Scripts for Atomicity

The core engineering challenge: a naive read-check-write pattern creates race conditions under concurrent load.

```python
# WRONG — Race condition
tokens = redis.get("tokens")       # Step 1: Read  → 1 token
if tokens > 0:                     # Step 2: Check → pass
    redis.set("tokens", tokens-1)  # Step 3: Write → 0 tokens
# Two concurrent requests both read "1 token" at Step 1
# Both pass the check, both decrement
# Result: 2 requests allowed when only 1 should be
```

Redis executes Lua scripts as a single atomic operation — nothing else can run between the read and write. This eliminates race conditions entirely, even under high concurrency.

```lua
-- Atomic token bucket check (simplified)
local tokens = tonumber(redis.call('GET', KEYS[1]) or ARGV[1])
if tokens >= 1 then
    redis.call('SET', KEYS[1], tokens - 1)
    return {1, tokens - 1}  -- allowed
end
return {0, 0}  -- rejected
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Language | Python 3.11 | Core application |
| Web Framework | FastAPI | Async API server |
| Rate Limit Storage | Redis 7 | Atomic Lua script execution, sub-ms reads |
| Rules + Audit | PostgreSQL 15 | Persistent rule storage, rejection logs |
| Metrics | Prometheus | Scrapes /metrics every 5s |
| Visualization | Grafana | Live dashboard |
| Redis Metrics | redis-exporter | Exposes Redis internals to Prometheus |
| Containerization | Docker + Compose | Full local stack |
| Cloud | AWS EC2 | Production deployment |
| CI/CD | GitHub Actions | Automated test + deploy on push to main |

---

## Benchmark Results

Load tested with Locust (200 concurrent users, 10 users/sec spawn rate):

| Metric | Result |
|---|---|
| Peak Requests Per Second | ~444 RPS |
| Total Requests Generated | 87,669 |
| Rate Limited (429) responses | 165 confirmed blocks |
| Service stability | Survived full load test, all containers remained healthy |
| Windows Docker network | Crashed under peak load (Docker Desktop proxy limitation, not application failure) |

> These numbers were recorded on a local development machine (Windows, Docker Desktop). AWS EC2 deployment results will be added after cloud deployment.

---

## Self-Healing Circuit Breaker

If Redis becomes unreachable, the rate limiter fails open (allows traffic through) rather than blocking your entire API. After 30 seconds it automatically attempts recovery.

```
Redis unreachable
      │
      ▼
Circuit Breaker trips
      │
      ▼
All requests: ALLOWED (fail-open)
      │
   30 seconds
      │
      ▼
Recovery attempt
      │
   ┌──┴──┐
   ▼     ▼
Redis  Redis still
back   down → reset timer
  │
  ▼
Circuit Breaker resets
Normal operation resumes
```

Health endpoint exposes circuit breaker state for orchestrator monitoring:
```json
GET /health
{
  "status": "healthy",
  "redis_circuit_breaker_tripped": false,
  "postgres_connected": true
}
```

---

## API Reference

### Check Rate Limit
```
POST /api/v1/check
Headers: X-Client-ID: user_123

Response 200 (allowed):
{
  "allowed": true,
  "remaining": 7,
  "algorithm": "token_bucket"
}

Response 429 (rate limited):
{
  "error": "Too Many Requests",
  "retry_after": 60
}
```

### Create / Update Rule
```
POST /api/v1/rules
{
  "client_id": "user_123",
  "endpoint": "/api/payments",
  "algorithm": "sliding_window",
  "limit_count": 100,
  "window_seconds": 60
}
```

### Get Rule
```
GET /api/v1/rules/{client_id}
```

### Metrics (Prometheus)
```
GET /metrics
```

### Health
```
GET /health
```

---

## Running Locally

**Prerequisites:** Docker Desktop, Docker Compose

```bash
git clone https://github.com/thomas-paul-ucb/distributed-rate-limiter
cd distributed-rate-limiter
docker-compose up --build
```

Services available at:
| Service | URL |
|---|---|
| Rate Limiter API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## Load Testing

```bash
pip install locust
locust -f load_tests/locustfile.py --host=http://localhost:8000
```

Open http://localhost:8089 to configure and run the load test.

---

## Project Structure

```
distributed-rate-limiter/
├── .github/workflows/ci.yml      ← GitHub Actions CI/CD
├── rate_limiter/
│   ├── main.py                   ← FastAPI app + lifespan
│   ├── middleware.py             ← Rate limit middleware (sidecar)
│   ├── algorithms/               ← Algorithm implementations
│   ├── scripts/
│   │   ├── token_bucket.lua      ← Atomic token bucket
│   │   └── sliding_window.lua    ← Atomic sliding window
│   ├── storage/
│   │   ├── redis_client.py       ← Redis + circuit breaker
│   │   └── postgres_client.py    ← Rules + audit log
│   ├── api/routes.py             ← REST endpoints
│   └── utils/metrics.py          ← Prometheus metrics
├── load_tests/locustfile.py      ← Locust load testing
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Observability

Prometheus metrics exposed at `/metrics`:

| Metric | Type | Description |
|---|---|---|
| `rate_limiter_requests_total` | Counter | Total requests by algorithm and result |
| `rate_limiter_latency_seconds` | Histogram | Request processing latency |
| `rate_limiter_active_clients` | Gauge | Clients with active rules in Postgres |

Redis internals (memory, connections, commands/sec) exposed via `redis-exporter` on port 9121.

---

## Future Improvements

- **Rule caching (LRU):** Cache Postgres rules in-memory to eliminate per-request DB lookups at scale
- **Distributed tracing (OpenTelemetry):** Trace latency breakdown between FastAPI and Redis
- **Redis Cluster:** Horizontal scaling via consistent hashing for multi-node deployments
- **gRPC interface:** Lower overhead alternative to HTTP for sidecar communication