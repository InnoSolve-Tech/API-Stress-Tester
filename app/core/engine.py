import asyncio
import time
import aiohttp
import logging
from typing import Optional
from app.core.metrics import TARGET_REQUESTS_TOTAL, TARGET_REQUEST_LATENCY, CURRENT_RPS, ACTIVE_WORKERS, THROTTLED_REQUESTS_TOTAL
from app.schemas.config import StressTestConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StressEngine:
    def __init__(self):
        self._stop_event = asyncio.Event()
        self._current_test: Optional[StressTestConfig] = None
        self._active_tasks = set()
        self._failure_log_counts = {}
        self._last_throttle_log = 0.0

    async def stop(self):
        """Stop the currently running stress test."""
        self._stop_event.set()
        for task in self._active_tasks:
            task.cancel()
        self._active_tasks = set()
        CURRENT_RPS.set(0)
        ACTIVE_WORKERS.set(0)
        logger.info("Stress test stopped.")

    def _should_log_failure(self, failure_type: str) -> bool:
        count = self._failure_log_counts.get(failure_type, 0) + 1
        self._failure_log_counts[failure_type] = count
        return count <= 5 or count % 100 == 0

    async def _worker(self, session: aiohttp.ClientSession, config: StressTestConfig):
        """A worker that sends requests as fast as possible relative to the RPS target."""
        # In a real RPS implementation, we coordinate workers.
        # For this engine, we use a simple loop with a delay to match total RPS.
        # interval = 1 / (config.requests_per_second / num_workers)

        # Since we use a dynamic worker pool based on RPS, we can use a token-bucket
        # or a simple sleep in the main loop. Here, the main loop manages the rate.
        pass

    async def run_test(self, config: StressTestConfig):
        """Starts the stress test according to the provided configuration."""
        self._stop_event.clear()
        self._current_test = config
        self._failure_log_counts = {}
        self._last_throttle_log = 0.0

        logger.info(f"Starting {config.test_type} stress test: {config.target_url} @ {config.requests_per_second} RPS")

        # Use a single session with DNS caching and a configurable connection pool.
        connector = aiohttp.TCPConnector(
            limit=config.max_connections,
            ttl_dns_cache=300,          # Cache DNS lookups for 5 minutes
            use_dns_cache=True
        )
        timeout = aiohttp.ClientTimeout(
            total=config.timeout,
            sock_connect=min(config.connect_timeout or config.timeout, config.timeout),
            sock_read=config.timeout,
        )

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            start_time = time.time()
            end_time = start_time + config.duration_seconds

            while time.time() < end_time and not self._stop_event.is_set():
                now = time.time()
                elapsed = now - start_time

                # Calculate current RPS based on test type
                current_rps = config.requests_per_second

                if config.test_type == "ramp_up":
                    ramp_duration = config.ramp_up_duration_seconds or 10
                    # Linear ramp from 0 to target RPS
                    current_rps = min(config.requests_per_second, (elapsed / ramp_duration) * config.requests_per_second)

                elif config.test_type == "burst":
                    burst_duration = config.burst_duration_seconds or 5
                    # High RPS for the burst duration, then back to a low base (or 0)
                    if elapsed < burst_duration:
                        current_rps = config.requests_per_second
                    else:
                        current_rps = config.requests_per_second // 10 # 10% base load after burst

                if current_rps <= 0:
                    await asyncio.sleep(0.1)
                    continue

                interval = 1.0 / current_rps
                loop_start = time.time()

                if len(self._active_tasks) >= config.max_connections:
                    THROTTLED_REQUESTS_TOTAL.labels(
                        method=config.method,
                        endpoint=str(config.target_url),
                        reason="max_connections",
                    ).inc()
                    ACTIVE_WORKERS.set(len(self._active_tasks))

                    if now - self._last_throttle_log >= 5:
                        logger.info(
                            "Throttling new requests: active=%s max_connections=%s target_rps=%s url=%s",
                            len(self._active_tasks),
                            config.max_connections,
                            current_rps,
                            config.target_url,
                        )
                        self._last_throttle_log = now

                    await asyncio.sleep(0.001)
                    continue

                # Fire a request
                task = asyncio.create_task(self._send_request(session, config))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)
                ACTIVE_WORKERS.set(len(self._active_tasks))

                elapsed_loop = time.time() - loop_start
                await asyncio.sleep(max(0, interval - elapsed_loop))
                CURRENT_RPS.set(current_rps)

        await self.stop()

    async def _send_request(self, session: aiohttp.ClientSession, config: StressTestConfig):
        """Sends a single request and records metrics."""
        start = time.time()
        status_code = "unknown"
        try:
            # Handle payload based on method
            kwargs = {}
            if config.method.upper() in ["POST", "PUT", "PATCH"]:
                kwargs["json"] = config.payload

            async with session.request(
                method=config.method,
                url=str(config.target_url),
                headers=config.headers,
                **kwargs
            ) as response:
                status_code = str(response.status)
                # Drain the body so aiohttp can reuse the connection cleanly.
                await response.read()
        except asyncio.TimeoutError as e:
            elapsed = time.time() - start
            if self._should_log_failure(type(e).__name__):
                logger.info(
                    "Request timed out: method=%s url=%s timeout=%.2fs connect_timeout=%.2fs elapsed=%.2fs error=%s",
                    config.method,
                    config.target_url,
                    config.timeout,
                    min(config.connect_timeout or config.timeout, config.timeout),
                    elapsed,
                    type(e).__name__,
                )
            status_code = "error"
        except Exception as e:
            elapsed = time.time() - start
            if self._should_log_failure(type(e).__name__):
                logger.info(
                    "Request failed: method=%s url=%s elapsed=%.2fs error=%s - %s",
                    config.method,
                    config.target_url,
                    elapsed,
                    type(e).__name__,
                    e,
                )
            status_code = "error"
        finally:
            latency = time.time() - start
            # Record Prometheus metrics
            TARGET_REQUESTS_TOTAL.labels(
                method=config.method,
                status_code=status_code,
                endpoint=str(config.target_url)
            ).inc()
            TARGET_REQUEST_LATENCY.labels(
                method=config.method,
                endpoint=str(config.target_url)
            ).observe(latency)

# Singleton instance for the control plane
engine = StressEngine()
