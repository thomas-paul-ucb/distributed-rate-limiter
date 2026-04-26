from fastapi import APIRouter, HTTPException, Request
from rate_limiter.api.models import RateLimitRequest, RateLimitResponse
import uuid

router = APIRouter()

@router.post("/check", response_model=RateLimitResponse)
async def check_rate_limit(request_data: RateLimitRequest, request: Request):
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