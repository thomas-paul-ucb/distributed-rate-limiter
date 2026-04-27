import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError
import logging
import os
import time

logger = logging.getLogger(__name__)

class RedisRateLimiter:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        # Use a connection pool to handle high concurrency
        self.pool = redis.ConnectionPool.from_url(redis_url, decode_responses=True)
        self.client = redis.Redis(connection_pool=self.pool)
        self.scripts = {}
        self._circuit_breaker_tripped = False

    async def load_scripts(self):
        """Loads Lua scripts into Redis cache on startup via SCRIPT LOAD."""
        script_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
        
        try:
            with open(os.path.join(script_dir, 'token_bucket.lua'), 'r') as f:
                self.scripts['token_bucket'] = await self.client.script_load(f.read())
                
            with open(os.path.join(script_dir, 'sliding_window.lua'), 'r') as f:
                self.scripts['sliding_window'] = await self.client.script_load(f.read())
                
            logger.info("Successfully loaded Lua scripts into Redis.")
            self._circuit_breaker_tripped = False
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Failed to connect to Redis during startup: {e}")
            self._circuit_breaker_tripped = True

    async def execute_token_bucket(self, client_id: str, capacity: int, refill_rate: float, cost: int = 1):
        """Executes the Token Bucket Lua script atomically."""
        if self._circuit_breaker_tripped:
            return True, capacity  # Fail-Open strategy

        key_tokens = f"rate_limit:{client_id}:tokens"
        key_last_refill = f"rate_limit:{client_id}:last_refill"
        now = time.time()

        try:
            result = await self.client.evalsha(
                self.scripts['token_bucket'],
                2, key_tokens, key_last_refill,
                capacity, refill_rate, now, cost
            )
            return bool(result[0]), float(result[1])
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis unavailable, circuit breaker tripped: {e}")
            self._circuit_breaker_tripped = True
            return True, capacity  # Fail-Open strategy

    async def execute_sliding_window(self, client_id: str, limit: int, window_seconds: int, request_id: str):
        """Executes the Sliding Window Lua script atomically."""
        if self._circuit_breaker_tripped:
            return True, limit  # Fail-Open strategy

        key = f"rate_limit:{client_id}:window"
        now = time.time()

        try:
            result = await self.client.evalsha(
                self.scripts['sliding_window'],
                1, key,
                now, window_seconds, limit, request_id
            )
            return bool(result[0]), int(result[1])
        except (ConnectionError, TimeoutError) as e:
            logger.warning(f"Redis unavailable, circuit breaker tripped: {e}")
            self._circuit_breaker_tripped = True
            return True, limit  # Fail-Open strategy

    async def set_rule(self, client_id: str, algorithm: str, params: dict):
        """Stores a custom rate limit rule for a client in a Redis Hash."""
        key = f"rule:{client_id}"
        mapping = {"algorithm": algorithm}
        mapping.update({k: str(v) for k, v in params.items()})
        await self.client.hset(key, mapping=mapping)
        return True

    async def get_rule(self, client_id: str):
        """Fetches the custom rate limit rule for a client."""
        key = f"rule:{client_id}"
        rule = await self.client.hgetall(key)
        if not rule:
            return {"algorithm": "token_bucket", "capacity": 10, "refill_rate": 1.0} # Default
        
        formatted_rule = {"algorithm": rule["algorithm"]}
        for k, v in rule.items():
            if k != "algorithm":
                formatted_rule[k] = float(v) if '.' in v else int(v)
        return formatted_rule