-- Token Bucket Lua Script
local key_tokens = KEYS[1]
local key_last_refill = KEYS[2]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

-- Get current state
local tokens = tonumber(redis.call('GET', key_tokens) or capacity)
local last_refill = tonumber(redis.call('GET', key_last_refill) or now)

-- Calculate refill
local elapsed = now - last_refill
local refill = elapsed * refill_rate
tokens = math.min(capacity, tokens + refill)

-- Check and consume
if tokens >= cost then
    tokens = tokens - cost
    redis.call('SET', key_tokens, tokens)
    redis.call('SET', key_last_refill, now)
    redis.call('EXPIRE', key_tokens, 3600)
    return {1, tokens}  -- ALLOWED, remaining tokens
else
    redis.call('SET', key_last_refill, now)
    return {0, tokens}  -- REJECTED, remaining tokens
end