"""Read-only metrics for the backend host, separate from rack telemetry."""
from datetime import datetime, timezone
import math
import socket

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

try:
    import psutil
except ImportError:
    psutil = None


router = APIRouter()
CPU_SAMPLE_SECONDS = 0.1


def percentage(value: float) -> float:
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Invalid percentage")
    return value


def collect_system_metrics() -> dict:
    """Sample CPU over a fixed window; retain successful metrics on partial failure."""
    result = {
        "schema_version": "1.0",
        "source": {
            "kind": "host_system",
            "host_id": socket.gethostname(),
            "collector": "psutil",
            "scope": "backend_host",
            "is_simulated": False,
        },
        "sample_started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observed_at": None,
        "status": "UNAVAILABLE",
        "cpu": None,
        "memory": None,
        "errors": [],
    }
    if psutil is None:
        result["errors"].append({"metric": "collector", "code": "dependency_unavailable"})
    else:
        # A positive interval avoids psutil's meaningless first nonblocking sample.
        # This synchronous route runs in FastAPI's thread pool, outside telemetry locks.
        try:
            result["cpu"] = {
                "utilization_pct": percentage(psutil.cpu_percent(interval=CPU_SAMPLE_SECONDS)),
                "sample_interval_seconds": CPU_SAMPLE_SECONDS,
            }
        except (OSError, RuntimeError, ValueError, psutil.Error):
            result["errors"].append({"metric": "cpu", "code": "collection_failed"})
        try:
            memory = psutil.virtual_memory()
            if (memory.total <= 0 or not 0 <= memory.available <= memory.total
                    or not 0 <= memory.used <= memory.total):
                raise ValueError("Invalid memory counters")
            result["memory"] = {
                "total_bytes": memory.total,
                "available_bytes": memory.available,
                "used_bytes": memory.used,
                "utilization_pct": percentage(memory.percent),
            }
        except (OSError, RuntimeError, ValueError, psutil.Error):
            result["errors"].append({"metric": "memory", "code": "collection_failed"})
    if result["cpu"] is not None or result["memory"] is not None:
        result["status"] = "DEGRADED" if result["errors"] else "OK"
    result["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return result


@router.get("/api/system/metrics")
def get_system_metrics(request: Request) -> JSONResponse:
    result = collect_system_metrics()
    headers = {"Cache-Control": "no-store"}
    store = getattr(request.app.state, "telemetry_store", None)
    if store is not None:
        store.queue_host(result)
        store.flush()
        headers["X-FactoryOS-Telemetry-Persistence"] = (
            "persisted" if store.health()["status"] == "OK" else "pending"
        )
    return JSONResponse(
        content=result,
        status_code=503 if result["status"] == "UNAVAILABLE" else 200,
        headers=headers,
    )
