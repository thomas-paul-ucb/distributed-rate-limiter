import asyncpg
import logging
import os

logger = logging.getLogger(__name__)

class PostgresClient:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def connect(self):
        """Initialize the async connection pool and create tables."""
        try:
            self.pool = await asyncpg.create_pool(self.db_url)
            logger.info("Connected to PostgreSQL pool.")
            await self.initialize_schema()
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def close(self):
        """Cleanly close the connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed.")

    async def initialize_schema(self):
        """Creates the tables exactly as defined in the architectural blueprint."""
        schema = """
        CREATE TABLE IF NOT EXISTS rate_limit_rules (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(255) NOT NULL,
            endpoint VARCHAR(255),
            algorithm VARCHAR(50) NOT NULL,
            limit_count INTEGER NOT NULL,
            window_seconds INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(client_id, endpoint)
        );

        CREATE TABLE IF NOT EXISTS rejected_requests (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(255) NOT NULL,
            endpoint VARCHAR(255),
            algorithm VARCHAR(50),
            rejected_at TIMESTAMP DEFAULT NOW()
        );
        """
        async with self.pool.acquire() as connection:
            await connection.execute(schema)
            logger.info("PostgreSQL schema initialized.")

    async def get_rule(self, client_id: str, endpoint: str):
        """Fetch a specific rule for a client and endpoint."""
        query = "SELECT * FROM rate_limit_rules WHERE client_id = $1 AND endpoint = $2"
        async with self.pool.acquire() as connection:
            record = await connection.fetchrow(query, client_id, endpoint)
            if record:
                return dict(record)
            return None

    async def set_rule(self, client_id: str, endpoint: str, algorithm: str, limit_count: int, window_seconds: int):
        """Insert or update a rate limit rule."""
        query = """
            INSERT INTO rate_limit_rules (client_id, endpoint, algorithm, limit_count, window_seconds)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (client_id, endpoint) 
            DO UPDATE SET algorithm = $3, limit_count = $4, window_seconds = $5
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, client_id, endpoint, algorithm, limit_count, window_seconds)

    async def log_rejection(self, client_id: str, endpoint: str, algorithm: str):
        """Asynchronously log a rejected request for the audit trail."""
        query = """
            INSERT INTO rejected_requests (client_id, endpoint, algorithm)
            VALUES ($1, $2, $3)
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, client_id, endpoint, algorithm)