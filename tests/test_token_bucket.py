import pytest
import asyncio
from rate_limiter.storage.redis_client import RedisRateLimiter

@pytest.fixture
async def redis_client():
    client = RedisRateLimiter()
    await client.load_scripts()
    yield client
    await client.client.flushdb() # Clean up after test
    await client.client.aclose()

@pytest.mark.asyncio
async def test_token_bucket_allows_and_rejects(redis_client):
    client_id = "test_user_bucket"
    capacity = 2
    refill_rate = 1.0 # 1 token per second
    
    # Request 1: Should pass
    allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
    assert allowed is True
    assert remaining == 1
    
    # Request 2: Should pass
    allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
    assert allowed is True
    assert remaining == 0
    
    # Request 3: Should fail (bucket empty)
    allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
    assert allowed is False
    assert remaining == 0
    
    # Wait for refill
    await asyncio.sleep(1.1)
    
    # Request 4: Should pass (1 token refilled)
    allowed, remaining = await redis_client.execute_token_bucket(client_id, capacity, refill_rate)
    assert allowed is True