"""Local P2 wrapper around P1's live app/store; no new canonical incident store."""

from backend.main import app, _incidents, _lock
from backend.modernization.repository import MemoryIncidentRepository
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService

repository = MemoryIncidentRepository(_incidents, _lock)
service = RepairService(repository)
app.include_router(create_modernization_router(service))
