"""P1's app/store with repair, NVIDIA investigation, and independent Gemini review."""

from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

# Explicit process environment wins, then backend/.env, then the repository .env.
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / "backend/.env", override=False)
load_dotenv(_root / ".env", override=False)

from backend import main
from backend.modernization.shared_repository import SharedIncidentRepository
from backend.modernization.router import create_modernization_router
from backend.modernization.service import RepairService
from backend.agents.router import create_investigation_router
from backend.agents.service import InvestigationService
from backend.agents.review import ReviewService
from backend.agents.review_router import create_review_router
from backend.modernization.approval import ApprovalService
from backend.modernization.approval_router import create_approval_router
from backend.integrations.router import create_notification_router
from backend.repairproof.repository import ProofRepository
from backend.repairproof.service import RepairProofService
from backend.repairproof.router import create_repairproof_router
from backend.repairproof.live import adapter_from_environment, LiveConfigurationError

class _LifespanService:
    """Keep route references stable while giving each lifespan fresh workers.

    Attribute assignments configure subsequent instances (useful for local
    scripted providers); assignments while running also affect that worker.
    Merely importing this module never starts a worker or opens a database.
    """

    def __init__(self, target):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_active", False)
        object.__setattr__(self, "_overrides", {})
        object.__setattr__(self, "_originals", {})

    def __getattr__(self, name):
        if not self._active and name in self._overrides:
            return self._overrides[name]
        return getattr(self._target, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            if name not in self._overrides:
                self._originals[name] = getattr(self._target, name)
            self._overrides[name] = value
            # Keep configured attributes visible to standard monkeypatch undo.
            object.__setattr__(self, name, value)
            if self._active:
                setattr(self._target, name, value)

    def __delattr__(self, name):
        if name not in self._overrides:
            raise AttributeError(name)
        self._overrides.pop(name)
        setattr(self._target, name, self._originals.pop(name))
        object.__delattr__(self, name)

    def _bind(self, target):
        for name, value in self._overrides.items():
            self._originals[name] = getattr(target, name)
            setattr(target, name, value)
        self._target = target
        self._active = True

    def _release(self):
        self._active = False


def _repository():
    return SharedIncidentRepository(
        main.get_incident_snapshot, main.publish_job, main.save_approval,
        database=main._store.incidents.database if main._store is not None else None,
    )


# Unstarted previews preserve local configuration hooks. Actual repositories are
# constructed after P1 restores canonical incidents and opens its Mongo client.
repository = _LifespanService(_repository())
service = _LifespanService(RepairService(repository))
investigation_service = _LifespanService(InvestigationService(repository.for_investigations()))
review_service = _LifespanService(ReviewService(repository.for_reviews(), repository.for_investigations()))
approval_service = _LifespanService(ApprovalService(repository, repository.for_investigations(), review_service))
repairproof_service = _LifespanService(RepairProofService(approval_service, ProofRepository(None)))
app = main.app
_p1_lifespan = app.router.lifespan_context


@asynccontextmanager
async def integrated_lifespan(app):
    async with _p1_lifespan(app):
        shared = _repository()
        workers = {
            service: RepairService(shared),
            investigation_service: InvestigationService(shared.for_investigations()),
            review_service: ReviewService(shared.for_reviews(), shared.for_investigations()),
        }
        repository._bind(shared)
        for handle, worker in workers.items():
            handle._bind(worker)
        gate = ApprovalService(shared, shared.for_investigations(), review_service)
        approval_service._bind(gate)
        # Construction never contacts RPC or reads private key bytes. Signing is
        # lazy, behind the enabled flag, authenticated durable approval, and fees.
        try:
            adapter = adapter_from_environment()
        except LiveConfigurationError:
            adapter = None
        repairproof_service._bind(RepairProofService(gate, ProofRepository(shared._database), adapter))
        app.state.p2_services = {"repair": service._target, "investigation": investigation_service._target,
                                 "review": review_service._target, "approval": gate, "repository": shared}
        try:
            yield
        finally:
            # Router lifespans normally close these first. Also cover partial
            # startup failures before P1 closes its shared database connection.
            for handle in reversed(workers):
                handle.close()
                handle._release()
            approval_service._release()
            repairproof_service.close()
            repairproof_service._release()
            repository._release()
            app.state.p2_services = None


app.router.lifespan_context = integrated_lifespan
app.include_router(create_modernization_router(service, investigation_service, review_service, approval_service))
app.include_router(create_investigation_router(investigation_service, review_service, approval_service))
app.include_router(create_review_router(review_service))
app.include_router(create_approval_router(approval_service))
app.include_router(create_repairproof_router(repairproof_service))
app.include_router(create_notification_router(
    main._incidents, main._lock, get_snapshot=main.get_incident_snapshot,
    publish_result=main.publish_notification,
))
