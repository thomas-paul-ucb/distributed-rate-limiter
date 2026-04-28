from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import uuid
import time
from rate_limiter.utils.metrics import requests_total, request_latency, active_clients

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/health", "/metrics"] or request.url.path.startswith("/api/v1/rules"):
            return await call_next(request)

        # --- START METRICS TRACKING ---
        start_time = time.perf_counter()
        
        redis_client = request.app.state.redis_client
        pg_client = request.app.state.pg_client
        client_id = request.headers.get("X-Client-ID") or request.client.host
        endpoint = request.url.path

        # Fetch rule
        rule = await pg_client.get_rule(client_id, endpoint)
        if not rule:
            rule = {"algorithm": "token_bucket", "limit_count": 10, "window_seconds": 60}

        algorithm = rule.get("algorithm")
        allowed = True
        remaining = 0

        # Execute check
        if algorithm == "token_bucket":
            capacity = rule.get("limit_count", 10)
            refill_rate = capacity / rule.get("window_seconds", 60)
            allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
        elif algorithm == "sliding_window":
            allowed, remaining = await redis_client.execute_sliding_window(
                client_id, rule.get("limit_count"), rule.get("window_seconds"), str(uuid.uuid4())
            )

        # --- RECORD METRICS ---
        latency = time.perf_counter() - start_time
        request_latency.observe(latency)
        
        result_label = "allowed" if allowed else "rejected"
        requests_total.labels(algorithm=algorithm, result=result_label).inc()

        if not allowed:
            await pg_client.log_rejection(client_id, endpoint, algorithm)
            return JSONResponse(
                status_code=429,
                content={"error": "Too Many Requests", "retry_after": rule.get("window_seconds")}
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))
        return response