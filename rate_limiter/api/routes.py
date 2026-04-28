from fastapi import APIRouter, HTTPException, Request
from rate_limiter.api.models import RateLimitRequest, RateLimitResponse
import uuid
from pydantic import BaseModel

router = APIRouter()

# --- POSTGRES RULES ENGINE ---

class RuleCreate(BaseModel):
    client_id: str
    endpoint: str = "global"
    algorithm: str
    limit_count: int = 10
    window_seconds: int = 60

@router.post("/rules")
async def create_rule(rule: RuleCreate, request: Request):
    """Admin endpoint to create or update a rate limit rule in Postgres."""
    pg_client = request.app.state.pg_client
    
    if rule.algorithm not in ["token_bucket", "sliding_window"]:
        raise HTTPException(status_code=400, detail="Invalid algorithm. Use 'token_bucket' or 'sliding_window'.")

    # Save directly to Postgres (Persistent Storage)
    await pg_client.set_rule(
        client_id=rule.client_id,
        endpoint=rule.endpoint,
        algorithm=rule.algorithm,
        limit_count=rule.limit_count,
        window_seconds=rule.window_seconds
    )
    
    return {"message": "Rule successfully saved to database.", "rule": rule.model_dump()}

@router.get("/rules/{client_id}")
async def get_rule(client_id: str, request: Request, endpoint: str = "global"):
    """Admin endpoint to fetch a specific rule from Postgres."""
    pg_client = request.app.state.pg_client
    rule = await pg_client.get_rule(client_id, endpoint)
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found for this client and endpoint.")
        
    return {"rule": rule}


# --- REDIS DATA PLANE CHECK ---

@router.post("/check", response_model=RateLimitResponse)
async def check_rate_limit(request_data: RateLimitRequest, request: Request):
    """Direct testing endpoint to hit the Redis data plane."""
    redis_client = request.app.state.redis_client

    if request_data.algorithm == "token_bucket":
        allowed, remaining = await redis_client.execute_token_bucket(
            client_id=request_data.client_id,
            capacity=request_data.capacity,
            refill_rate=request_data.refill_rate
        )
    elif request_data.algorithm == "sliding_window":
        allowed, remaining = await redis_client.execute_sliding_window(
            client_id=request_data.client_id,
            limit=request_data.limit,
            window_seconds=request_data.window_seconds,
            request_id=str(uuid.uuid4())
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid algorithm")

    # If blocked, we return a 429 Too Many Requests in a real middleware scenario.
    # Here, we are acting as a dedicated rate limit check service.
    return RateLimitResponse(
        allowed=allowed,
        remaining=remaining,
        algorithm_used=request_data.algorithm
    )