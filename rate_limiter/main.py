from fastapi import FastAPI, Response
from contextlib import asynccontextmanager
from rate_limiter.storage.redis_client import RedisRateLimiter
from rate_limiter.storage.postgres_client import PostgresClient
from rate_limiter.api.routes import router
from rate_limiter.middleware import RateLimitMiddleware
from rate_limiter.utils.metrics import active_clients # Import this at the top
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- REDIS STARTUP ---
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = RedisRateLimiter(redis_url=redis_url)
    await redis_client.load_scripts()
    app.state.redis_client = redis_client
    
    # --- POSTGRES STARTUP ---
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:secret@localhost:5432/ratelimiter")
    pg_client = PostgresClient(db_url=db_url)
    await pg_client.connect()
    app.state.pg_client = pg_client
    
    yield # Application runs here
    
    # --- SHUTDOWN ---
    await app.state.redis_client.close()
    await app.state.pg_client.close()

app = FastAPI(
    title="Distributed Rate Limiter API",
    description="High-performance rate limiting service utilizing Redis Lua scripts.",
    lifespan=lifespan
)

# Important: Middleware handles the metric recording for each request
app.add_middleware(RateLimitMiddleware)
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "redis_circuit_breaker_tripped": app.state.redis_client._circuit_breaker_tripped,
        "postgres_connected": app.state.pg_client.pool is not None
    }

@app.get("/metrics")
async def metrics():
    """Endpoint for Prometheus to scrape metrics."""
    # 1. Update the Active Clients gauge by counting rules in Postgres
    try:
        # Check if pg_client exists in state to avoid 500 errors during startup/shutdown
        pg_client = getattr(app.state, "pg_client", None)
        if pg_client and pg_client.pool:
            async with pg_client.pool.acquire() as conn:
                count = await conn.fetchval("SELECT count(DISTINCT client_id) FROM rate_limit_rules")
                active_clients.set(count if count is not None else 0)
    except Exception as e:
        # Log the error but don't crash the metrics page
        print(f"Error updating metrics from Postgres: {e}")

    # 2. Return all Prometheus metrics (including those recorded in middleware)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)