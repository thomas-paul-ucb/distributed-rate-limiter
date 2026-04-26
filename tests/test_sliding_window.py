import pytest
import asyncio
import uuid
from rate_limiter.storage.redis_client import RedisRateLimiter

@pytest.fixture
async def redis_client():
    client = RedisRateLimiter()
    await client.load_scripts()
    yield client
    await client.client.flushdb()
    await client.client.aclose()

@pytest.mark.asyncio
async def test_sliding_window_enforces_limit(redis_client):
    client_id = "test_user_window"
    limit = 2
    window = 1 # 1 second window
    
    # Request 1
    allowed, rem = await redis_client.execute_sliding_window(client_id, limit, window, str(uuid.uuid4()))
    assert allowed is True
    
    # Request 2
    allowed, rem = await redis_client.execute_sliding_window(client_id, limit, window, str(uuid.uuid4()))
    assert allowed is True
    
    # Request 3 (Boundary hit, should reject)
    allowed, rem = await redis_client.execute_sliding_window(client_id, limit, window, str(uuid.uuid4()))
    assert allowed is False
    
    # Wait for window to slide
    await asyncio.sleep(1.1)
    
    # Request 4 (Should pass again)
    allowed, rem = await redis_client.execute_sliding_window(client_id, limit, window, str(uuid.uuid4()))
    assert allowed is True