import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError
import logging
import os
import time

logger = logging.getLogger(__name__)

class RedisRateLimiter:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.pool = redis.ConnectionPool.from_url(redis_url, decode_responses=True)
        self.client = redis.Redis(connection_pool=self.pool)
        self.scripts = {}
        
        # Self-healing Circuit Breaker State
        self._circuit_breaker_tripped = False
        self._circuit_breaker_tripped_at = None
        self._circuit_breaker_timeout = 30  # Retry Redis after 30 seconds

    def _is_circuit_open(self) -> bool:
        """Checks if the circuit breaker is tripped, attempting recovery if timeout has passed."""
        if not self._circuit_breaker_tripped:
            return False
            
        if time.time() - self._circuit_breaker_tripped_at > self._circuit_breaker_timeout:
            logger.info("Circuit breaker attempting recovery...")
            self._circuit_breaker_tripped = False
            return False
            
        return True

    def _trip_circuit_breaker(self):
        """Trips the circuit breaker and records the timestamp."""
        self._circuit_breaker_tripped = True
        self._circuit_breaker_tripped_at = time.time()
        logger.warning("Circuit breaker tripped! Defaulting to fail-open.")

    async def close(self):
        """Cleanly close the connection pool on app shutdown."""
        await self.client.aclose()
        logger.info("Redis connection pool closed.")

    async def load_scripts(self):
        try:
            with open("rate_limiter/scripts/token_bucket.lua", "r") as f:
                self.scripts['token_bucket'] = self.client.register_script(f.read())
            with open("rate_limiter/scripts/sliding_window.lua", "r") as f:
                self.scripts['sliding_window'] = self.client.register_script(f.read())
            logger.info("Lua scripts loaded into Redis.")
        except (redis.ConnectionError, TimeoutError) as e:
            logger.error(f"Failed to load scripts: {e}")
            self._trip_circuit_breaker()

    async def execute_token_bucket(self, client_id: str, capacity: int, refill_rate: float, cost: int = 1):
        if self._is_circuit_open():
            return True, capacity 
            
        try:
            keys = [f"tb:{client_id}:tokens", f"tb:{client_id}:last_refill"]
            # FIX: Added cost as the 4th argument
            args = [capacity, refill_rate, time.time(), cost]
            
            result = await self.scripts['token_bucket'](keys=keys, args=args)
            return bool(result[0]), float(result[1])
        except (redis.ConnectionError, TimeoutError):
            self._trip_circuit_breaker()
            return True, capacity

    async def execute_sliding_window(self, client_id: str, limit: int, window_seconds: int, request_id: str):
        if self._is_circuit_open():
            return True, limit 
            
        try:
            keys = [f"sw:{client_id}"]
            now = time.time()
            # FIX: Corrected order -> now, window, limit, request_id
            args = [now, window_seconds, limit, request_id]
            
            result = await self.scripts['sliding_window'](keys=keys, args=args)
            return bool(result[0]), int(result[1])
        except (redis.ConnectionError, TimeoutError):
            self._trip_circuit_breaker()
            return True, limit

    async def set_rule(self, client_id: str, algorithm: str, params: dict):
        key = f"rule:{client_id}"
        mapping = {"algorithm": algorithm}
        mapping.update({k: str(v) for k, v in params.items()})
        await self.client.hset(key, mapping=mapping)
        return True

    async def get_rule(self, client_id: str):
        key = f"rule:{client_id}"
        rule = await self.client.hgetall(key)
        
        if not rule:
            return {"algorithm": "token_bucket", "capacity": 10, "refill_rate": 1.0}
            
        algorithm = rule.get("algorithm", "token_bucket")
        
        if algorithm == "token_bucket":
            return {
                "algorithm": algorithm,
                "capacity": int(rule.get("capacity", 10)),
                "refill_rate": float(rule.get("refill_rate", 1.0))
            }
        elif algorithm == "sliding_window":
            return {
                "algorithm": algorithm,
                "limit": int(rule.get("limit", 10)),
                "window_seconds": int(rule.get("window_seconds", 60))
            }