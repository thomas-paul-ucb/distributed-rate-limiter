import pytest
from httpx import AsyncClient, ASGITransport
from rate_limiter.main import app, lifespan

@pytest.fixture(autouse=True)
async def init_lifespan():
    """
    Automatically triggers the FastAPI lifespan events for all tests,
    ensuring Redis is connected and attached to app.state.
    """
    async with lifespan(app):
        yield

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

@pytest.mark.asyncio
async def test_middleware_rate_limiting():
    # Test that the middleware correctly blocks requests that exceed the default limit
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        status_codes = []
        for _ in range(11):
            # /check requires a POST request with a JSON body
            response = await ac.post(
                "/api/v1/check", 
                headers={"X-Client-ID": "test_integration_user"},
                json={
                    "client_id": "test_integration_user", 
                    "algorithm": "token_bucket"
                }
            )
            status_codes.append(response.status_code)
        
        # The 11th request should be blocked by the middleware with a 429
        assert 429 in status_codes