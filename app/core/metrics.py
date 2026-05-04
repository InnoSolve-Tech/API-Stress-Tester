from prometheus_client import Counter, Histogram, Gauge

# Metrics for the target server under test
TARGET_REQUESTS_TOTAL = Counter(
    "stress_tester_target_requests_total",
    "Total number of requests sent to the target server",
    ["method", "status_code", "endpoint"]
)

TARGET_REQUEST_LATENCY = Histogram(
    "stress_tester_target_request_duration_seconds",
    "Latency of requests to the target server",
    ["method", "endpoint"],
    buckets=(.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, float("inf"))
)

CURRENT_RPS = Gauge(
    "stress_tester_current_rps",
    "Current requests per second being generated"
)

ACTIVE_WORKERS = Gauge(
    "stress_tester_active_workers",
    "Number of active worker tasks"
)

THROTTLED_REQUESTS_TOTAL = Counter(
    "stress_tester_throttled_requests_total",
    "Number of requests not started because the stress tester reached its in-flight request limit",
    ["method", "endpoint", "reason"]
)
