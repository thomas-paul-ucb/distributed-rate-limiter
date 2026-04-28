from fastapi import FastAPI, Response
from contextlib import asynccontextmanager
from rate_limiter.storage.redis_client import RedisRateLimiter
from rate_limiter.storage.postgres_client import PostgresClient
from rate_limiter.api.routes import router
import os
from rate_limiter.middleware import RateLimitMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- REDIS STARTUP ---
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = RedisRateLimiter(redis_url=redis_url)
    await redis_client.load_scripts()
    app.state.redis_client = redis_client
    
    # --- POSTGRES STARTUP ---
    # Matches the credentials in your docker-compose
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
    # Update active_clients gauge before scraping
    # This is a bit heavy for every scrape, but fine for this scale
    # In production, you'd update this on a background task
    pg_client = app.state.pg_client
    async with pg_client.pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(DISTINCT client_id) FROM rate_limit_rules")
        from rate_limiter.utils.metrics import active_clients
        active_clients.set(count)
        
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)