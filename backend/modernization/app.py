"""Local P2 wrapper around P1's app/store, with repair and NVIDIA investigation."""

from pathlib import Path
from dotenv import load_dotenv

# Explicit process environment wins, then backend/.env, then the repository .env.
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / "backend/.env", override=False)
load_dotenv(_root / ".env", override=False)

from backend.main import app, _incidents, _lock
from backend.modernization.repository import MemoryIncidentRepository
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService
from backend.agents.router import create_investigation_router
from backend.agents.service import InvestigationService

repository = MemoryIncidentRepository(_incidents, _lock)
service = RepairService(repository)
investigation_service = InvestigationService(repository.for_investigations())
app.include_router(create_modernization_router(service, investigation_service))
app.include_router(create_investigation_router(investigation_service))
