from prometheus_client import Counter, Histogram, Gauge

# Total requests categorized by algorithm and result (allowed/rejected)
requests_total = Counter(
    'rate_limiter_requests_total', 
    'Total requests checked', 
    ['algorithm', 'result']
)

# How long the rate limit check (DB + Redis) takes
request_latency = Histogram(
    'rate_limiter_latency_seconds', 
    'Rate limit check latency'
)

# Number of unique clients we have rules for in the system
active_clients = Gauge(
    'rate_limiter_active_clients', 
    'Number of clients with active limits'
)