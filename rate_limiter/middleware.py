from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
import uuid
import time

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Bypass rate limiting for internal/admin routes
        if request.url.path in ["/health", "/metrics", "/api/v1/rules"]:
            return await call_next(request)

        # Identify client by Custom Header or IP
        client_id = request.headers.get("X-Client-ID") or request.client.host
        redis_client = request.app.state.redis_client

        # Fetch rule from Redis
        rule = await redis_client.get_rule(client_id)
        
        # Execute Algorithm
        if rule["algorithm"] == "token_bucket":
            allowed, remaining = await redis_client.execute_token_bucket(
                client_id, rule.get("capacity", 10), rule.get("refill_rate", 1.0)
            )
        else:
            allowed, remaining = await redis_client.execute_sliding_window(
                client_id, rule.get("limit", 10), rule.get("window_seconds", 60), str(uuid.uuid4())
            )

        # Reject if limit exceeded
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "algorithm": rule["algorithm"],
                    "retry_after": rule.get("window_seconds", 1) # Simplified retry logic
                }
            )

        # Add remaining requests to headers (Standard enterprise practice)
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))
        return response