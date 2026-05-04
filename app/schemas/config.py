from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, Dict, Any, Literal

class StressTestConfig(BaseModel):
    target_url: HttpUrl
    test_type: Literal["sustained", "burst", "ramp_up"] = "sustained"
    requests_per_second: int = Field(..., gt=0, description="Target RPS for sustained, or peak RPS for burst/ramp")
    duration_seconds: int = Field(..., gt=0, description="Total duration of the test in seconds")
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    payload: Optional[Any] = None
    timeout: float = 10.0
    connect_timeout: Optional[float] = Field(None, gt=0, description="Seconds allowed for opening a TCP connection; defaults to timeout")
    max_connections: int = Field(1000, gt=0, description="Maximum concurrent outbound connections")

    # Additional parameters for specific test types
    burst_duration_seconds: Optional[int] = Field(None, description="Duration of the high-intensity burst")
    ramp_up_duration_seconds: Optional[int] = Field(None, description="Time taken to reach target RPS")
