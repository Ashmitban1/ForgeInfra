"""P1's app/store with repair, NVIDIA investigation, and independent Gemini review."""

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
from backend.agents.review import ReviewService
from backend.agents.review_router import create_review_router

repository = MemoryIncidentRepository(_incidents, _lock)
service = RepairService(repository)
investigation_service = InvestigationService(repository.for_investigations())
review_service = ReviewService(repository.for_reviews(), repository.for_investigations())
app.include_router(create_modernization_router(service, investigation_service, review_service))
app.include_router(create_investigation_router(investigation_service, review_service))
app.include_router(create_review_router(review_service))
