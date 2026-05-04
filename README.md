# FastAPI Stress Tester

A high-performance API stress testing tool built with FastAPI, aiohttp, and Prometheus.

## Setup & Running

### 1. Run with Docker

This spins up the Stress Tester, Prometheus for metrics collection, Grafana for visualization, and Alertmanager.

```bash
docker-compose up --build -d
```

When the target API is running on your host machine, do not use `localhost` in
`target_url`. From inside the `stress-tester` container, `localhost` points to
the container itself. Use Docker Desktop's host alias instead:

```json
{
  "target_url": "http://host.docker.internal:8080/api/endpoint",
  "requests_per_second": 100,
  "duration_seconds": 60,
  "timeout": 10.0,
  "connect_timeout": 10.0,
  "max_connections": 100
}
```

After changing the code or Docker configuration, restart the containers:

```bash
docker-compose down
docker-compose up --build -d
```

### 2. Run Locally

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## What Was Added

The stress tester now supports multiple load profiles, improved networking behavior, clearer timeout logging, and Grafana-ready metrics.

### Stress Test Types

- `sustained`: Maintains a constant RPS for the entire test duration.
- `burst`: Hits the target RPS for `burst_duration_seconds`, then drops to a 10% baseline load.
- `ramp_up`: Gradually increases from 0 RPS to the target RPS over `ramp_up_duration_seconds`.

### Network & Timeout Fixes

The aiohttp client has been tuned to reduce misleading timeout failures where the target endpoint is hit but the client does not complete cleanly:

- Uses DNS caching in `TCPConnector` to reduce repeated Docker network DNS lookups.
- Uses a configurable connection pool, defaulting to `1000` concurrent outbound connections.
- Uses explicit total, socket-connect, and socket-read timeouts.
- Defaults request timeout to `10.0` seconds.
- Reads response bodies so aiohttp can drain responses and reuse connections cleanly.
- Logs timeout failures with method, target URL, configured timeout, and elapsed time.
- Applies backpressure when active requests reach `max_connections` instead of creating unlimited queued tasks.
- Samples repeated timeout logs so high-RPS failures do not overload stdout or block Prometheus scrapes.

## API Guide

The Stress Tester is controlled through a REST API.

### Start a Stress Test

Endpoint: `POST /test/start`

Base payload:

```json
{
  "target_url": "https://api.example.com/v1/endpoint",
  "test_type": "sustained",
  "requests_per_second": 100,
  "duration_seconds": 60,
  "method": "GET",
  "headers": {
    "Authorization": "Bearer YOUR_TOKEN",
    "Content-Type": "application/json"
  },
  "payload": {
    "key": "value"
  },
  "timeout": 10.0,
  "connect_timeout": 10.0,
  "max_connections": 100
}
```

- `target_url`: The API endpoint to stress. If the stress tester is running in Docker and the target API is running on your host machine, use `http://host.docker.internal:<port>/<path>` instead of `localhost`.
- `test_type`: One of `sustained`, `burst`, or `ramp_up`.
- `requests_per_second`: Constant RPS for `sustained`, or peak RPS for `burst` and `ramp_up`.
- `duration_seconds`: Total test duration.
- `method`: HTTP method, such as `GET`, `POST`, `PUT`, `PATCH`, or `DELETE`.
- `headers`: Optional request headers.
- `payload`: Optional JSON body for `POST`, `PUT`, and `PATCH` requests.
- `timeout`: Seconds before a request is marked as timed out.
- `connect_timeout`: Optional seconds allowed for opening a TCP connection. Defaults to `timeout`.
- `max_connections`: Maximum concurrent in-flight requests and outbound connections. Increase this for high-RPS tests only if the stress tester and target API have enough CPU, memory, sockets, and database capacity.
- `burst_duration_seconds`: Duration of the high-intensity burst when `test_type` is `burst`.
- `ramp_up_duration_seconds`: Time taken to reach target RPS when `test_type` is `ramp_up`.

For very large tests such as `20000` RPS, one stress-tester container may become the bottleneck before the target API does. Watch `stress_tester_active_workers`, `stress_tester_throttled_requests_total`, container CPU, and target API latency. If throttling rises, the configured RPS is higher than this single container can safely drive at the current timeout and target latency.

For local Docker-to-host tests around a few hundred RPS, start with `max_connections` around `100`. A smaller warm keep-alive pool is often more stable than opening hundreds or thousands of new sockets to the host.

### Sustained Test Example

```bash
curl -X POST http://localhost:8000/test/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://host.docker.internal:8080/api/endpoint",
    "test_type": "sustained",
    "requests_per_second": 100,
    "duration_seconds": 60
  }'
```

### Burst Test Example

```bash
curl -X POST http://localhost:8000/test/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-api.com",
    "test_type": "burst",
    "requests_per_second": 500,
    "burst_duration_seconds": 10,
    "duration_seconds": 60
  }'
```

### Ramp Up Test Example

```bash
curl -X POST http://localhost:8000/test/start \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://your-api.com",
    "test_type": "ramp_up",
    "requests_per_second": 200,
    "ramp_up_duration_seconds": 30,
    "duration_seconds": 120
  }'
```

### Stop a Stress Test

Endpoint: `POST /test/stop`

```bash
curl -X POST http://localhost:8000/test/stop
```

### Check Status

Endpoint: `GET /test/status`

```bash
curl http://localhost:8000/test/status
```

Example response:

```json
{
  "running": true,
  "active_workers": 142
}
```

## Grafana Dashboard Guide

Add these queries to your Grafana panels to monitor the target server's health.

| Goal | PromQL Query | Recommended Visualization |
| :--- | :--- | :--- |
| Current Throughput | `sum(rate(stress_tester_target_requests_total[1m]))` | Time Series / Gauge |
| Error Rate (%) | `sum(rate(stress_tester_target_requests_total{status_code="error"}[1m])) / sum(rate(stress_tester_target_requests_total[1m])) * 100` | Stat / Gauge (%) |
| P95 Latency | `histogram_quantile(0.95, sum by (le) (rate(stress_tester_target_request_duration_seconds_bucket[1m])))` | Time Series |
| Status Code Breakdown | `sum by (status_code) (rate(stress_tester_target_requests_total[1m]))` | Stacked Area Chart |
| Active Connection Load | `stress_tester_active_workers` | Gauge |
| Throttled Requests | `sum(rate(stress_tester_throttled_requests_total[1m]))` | Time Series / Gauge |
| Alert Status | `ALERTS{alertname="HighErrorRate", alertstate="firing"}` | Stat, where 1 means alerting and 0 means healthy |

## Troubleshooting

- `TimeoutError`: If the target runs on your host machine while the stress tester runs in Docker, make sure `target_url` uses `host.docker.internal`, not `localhost`. If routing is correct, the target server may not be completing responses within the configured timeout; lower `requests_per_second` or increase `timeout`.
- `ConnectionTimeoutError`: The stress tester could not establish a socket quickly enough. The request did not necessarily reach the target API. Increase `connect_timeout`, reduce `requests_per_second`, reduce `max_connections` to encourage connection reuse, or check whether the host API and Docker network are accepting connections fast enough.
- Prometheus scrape timeout: The stress-tester process is overloaded. Reduce `requests_per_second`, reduce `timeout`, increase container resources, or run multiple stress-generator instances. Check `stress_tester_throttled_requests_total` to see whether the in-flight cap is being reached.
- Target API logs show `200` but stress tester logs `SocketTimeoutError`: The target produced a response, but the stress tester did not receive and drain the response body before its socket-read timeout. This is most common under client-side overload, Docker networking pressure, or large response bodies. Watch active workers; at `200` RPS and about `0.06s` target latency, active workers should stay low, not pinned at `max_connections`.
- Grafana charts not loading: Ensure the `stress-tester` container is healthy and Prometheus can scrape `http://stress-tester:8000/metrics`.
- Host API not reachable: Make sure the target API is running and listening on the expected port. If needed, bind it to `0.0.0.0` so Docker Desktop can reach it through `host.docker.internal`.
