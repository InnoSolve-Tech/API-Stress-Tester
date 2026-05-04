from fastapi import FastAPI, BackgroundTasks, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from app.schemas.config import StressTestConfig
from app.core.engine import engine
import uvicorn

app = FastAPI(title="FastAPI Stress Tester")

# Instrument the FastAPI app itself (Control Plane metrics)
Instrumentator().instrument(app=app).expose(app)

@app.post("/test/start")
async def start_test(config: StressTestConfig, background_tasks: BackgroundTasks):
    """Starts a stress test in the background."""
    # If a test is already running, we stop it first
    await engine.stop()

    # Use BackgroundTasks to run the engine without blocking the API response
    background_tasks.add_task(engine.run_test, config)

    return {"status": "started", "config": config}

@app.post("/test/stop")
async def stop_test():
    """Stops the currently running stress test."""
    await engine.stop()
    return {"status": "stopped"}

@app.get("/test/status")
async def get_status():
    """Checks if a test is currently active."""
    is_running = not engine._stop_event.is_set() and len(engine._active_tasks) > 0
    return {
        "running": is_running,
        "active_workers": len(engine._active_tasks)
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
