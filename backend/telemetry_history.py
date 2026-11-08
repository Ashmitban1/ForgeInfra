"""Additive charting APIs; existing telemetry request/response schemas are unchanged."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from backend.storage.mongo import StorageUnavailable


router = APIRouter()
SourceKind = Literal["arduino_serial", "simulator", "host_system"]


def query_window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=1)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="History timestamps must include a timezone")
    if not timedelta(0) < end - start <= timedelta(days=7):
        raise HTTPException(status_code=422, detail="History window must be positive and at most 7 days")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def history_store(request: Request):
    store = getattr(request.app.state, "telemetry_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Tiger Data history is not configured")
    return store


@router.get("/api/telemetry/history")
def get_telemetry_history(request: Request, source_kind: SourceKind,
                          source_id: str = Query(min_length=1, max_length=255),
                          start: datetime | None = None, end: datetime | None = None,
                          limit: int = Query(default=300, ge=1, le=1000)):
    start, end = query_window(start, end)
    store = history_store(request)
    try:
        rows = store.history(source_kind, source_id, start, end, limit)
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Tiger Data history unavailable") from None
    return {"source_kind": source_kind, "source_id": source_id,
            "start": start, "end": end, "samples": rows}


@router.get("/api/telemetry/summary")
def get_telemetry_summary(request: Request, source_kind: SourceKind,
                          source_id: str = Query(min_length=1, max_length=255),
                          start: datetime | None = None, end: datetime | None = None,
                          bucket_seconds: int = Query(default=300, ge=60, le=3600)):
    if bucket_seconds not in {60, 300, 900, 3600}:
        raise HTTPException(status_code=422, detail="bucket_seconds must be 60, 300, 900 or 3600")
    start, end = query_window(start, end)
    store = history_store(request)
    try:
        rows = store.summary(source_kind, source_id, start, end, bucket_seconds)
    except StorageUnavailable:
        raise HTTPException(status_code=503, detail="Tiger Data summary unavailable") from None
    return {"source_kind": source_kind, "source_id": source_id, "start": start,
            "end": end, "bucket_seconds": bucket_seconds, "buckets": rows}


@router.get("/api/telemetry/storage/health")
def get_telemetry_storage_health(request: Request):
    store = getattr(request.app.state, "telemetry_store", None)
    return store.health() if store is not None else {
        "backend": "tigerdata", "status": "DISABLED", "pending_samples": 0, "error": None,
    }


@router.get('/api/telemetry/sources')
def get_telemetry_sources(request: Request):
    store = getattr(request.app.state, 'telemetry_store', None)
    if store is None:
        return {'sources': [], 'storage_backend': 'disabled'}
    try:
        return {'sources': store.sources(), 'storage_backend': 'tigerdata'}
    except StorageUnavailable:
        raise HTTPException(503, 'Tiger Data source discovery unavailable') from None
