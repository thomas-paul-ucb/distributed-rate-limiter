from fastapi import FastAPI
from contextlib import asynccontextmanager
from rate_limiter.storage.redis_client import RedisRateLimiter
from rate_limiter.api.routes import router
import os
from rate_limiter.middleware import RateLimitMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Redis Pool and Load Scripts
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = RedisRateLimiter(redis_url=redis_url)
    await redis_client.load_scripts()
    
    # Attach client to app state for global access
    app.state.redis_client = redis_client
    
    yield # Application runs here
    
    # Shutdown: Close Redis connection gracefully
    await app.state.redis_client.client.aclose()

app = FastAPI(
    title="Distributed Rate Limiter API",
    description="High-performance rate limiting service utilizing Redis Lua scripts.",
    lifespan=lifespan
)

app.add_middleware(RateLimitMiddleware)
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "redis_circuit_breaker_tripped": app.state.redis_client._circuit_breaker_tripped}