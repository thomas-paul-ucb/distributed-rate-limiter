from fastapi import FastAPI
from contextlib import asynccontextmanager
from rate_limiter.storage.redis_client import RedisRateLimiter
from rate_limiter.api.routes import router
import os
from rate_limiter.middleware import RateLimitMiddleware

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