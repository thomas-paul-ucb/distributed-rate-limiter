from pydantic import BaseModel, Field

class RateLimitRequest(BaseModel):
    client_id: str = Field(..., description="The unique identifier for the client (e.g., IP, User ID, API Key)")
    algorithm: str = Field(..., pattern="^(token_bucket|sliding_window)$")
    
    # Token Bucket params
    capacity: int | None = Field(10, description="Max burst capacity")
    refill_rate: float | None = Field(1.0, description="Tokens refilled per second")
    
    # Sliding Window params
    limit: int | None = Field(10, description="Max requests allowed in window")
    window_seconds: int | None = Field(60, description="Time window in seconds")

class RateLimitResponse(BaseModel):
    allowed: bool
    remaining: float | int
    algorithm_used: str