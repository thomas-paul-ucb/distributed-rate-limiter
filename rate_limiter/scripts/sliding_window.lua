-- Sliding Window Lua Script
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local request_id = ARGV[4]

-- Calculate the cutoff timestamp
local clear_before = now - window_seconds

-- 1. Remove requests older than the window (Slide the window)
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Count current requests in the window
local current_requests = tonumber(redis.call('ZCARD', key))

-- 3. Check limit
if current_requests < limit then
    -- Add the new request
    redis.call('ZADD', key, now, request_id)
    -- Set TTL to clean up automatically if no traffic occurs
    redis.call('EXPIRE', key, window_seconds)
    return {1, limit - current_requests - 1} -- ALLOWED, remaining
else
    return {0, 0} -- REJECTED, remaining
end