from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import uuid

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Bypass rate limiting for internal/admin routes
        if request.url.path in ["/health", "/metrics"] or request.url.path.startswith("/api/v1/rules"):
            return await call_next(request)

        redis_client = request.app.state.redis_client
        pg_client = request.app.state.pg_client
        
        # In a real app, this comes from an Authorization header or API Key
        # We fallback to IP address if no custom header is present
        client_id = request.headers.get("X-Client-ID") or request.client.host
        endpoint = request.url.path

        # 1. Fetch rule from Postgres
        rule = await pg_client.get_rule(client_id, endpoint)
        
        # Fallback to a default strict rule if none exists in the DB
        if not rule:
            rule = {
                "algorithm": "token_bucket",
                "limit_count": 10,
                "window_seconds": 60  
            }

        algorithm = rule.get("algorithm")
        allowed = True
        remaining = 0

        # 2. Execute the fast atomic check in Redis
        if algorithm == "token_bucket":
            # Convert Postgres limit/window to capacity/refill_rate
            capacity = rule.get("limit_count", 10)
            refill_rate = capacity / rule.get("window_seconds", 60)
            allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
            
        elif algorithm == "sliding_window":
            limit = rule.get("limit_count", 10)
            window = rule.get("window_seconds", 60)
            request_id = str(uuid.uuid4())
            allowed, remaining = await redis_client.execute_sliding_window(client_id, limit, window, request_id)

        # 3. Handle Rejections and Audit Logging
        if not allowed:
            # Asynchronously log the rejection to Postgres without blocking the response
            await pg_client.log_rejection(client_id, endpoint, algorithm)
            
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "algorithm": algorithm,
                    "retry_after": rule.get("window_seconds", 60)
                }
            )

        # 4. Attach remaining limits to headers (Standard enterprise practice)
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))
        return response