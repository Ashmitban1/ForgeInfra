"""Investigation jobs share canonical incidents, but not repair job records."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from backend.agents.investigation import SYSTEM_PROMPT, run_investigation
from backend.agents.nemotron import NemotronClient, NemotronConfig, NemotronError
from backend.agents.review_schemas import case_revision, material_incident
from backend.agents.tools import InvestigationTools
from backend.modernization.patching import DEFAULT_OUTPUT_ROOT, source_hash
from backend.modernization.repository import content_revision
from backend.modernization.runner import LEGACY_MONITOR_PATH
from backend.modernization.service import RepairService
from backend.modernization.testing import utc_now

LIMIT_FIELDS = ("max_rounds", "max_tool_calls", "request_timeout", "budget_seconds", "max_tokens", "enable_thinking")


class InvestigationService(RepairService):
    job_kind = "investigation"

    def __init__(self, repository, output_root: Path = DEFAULT_OUTPUT_ROOT / "investigations",
                 client_factory=NemotronClient, config_factory=NemotronConfig.from_environment,
                 tools_factory=InvestigationTools):
        super().__init__(repository, output_root)
        self.client_factory = client_factory
        self.config_factory = config_factory
        self.tools_factory = tools_factory

    def prepare_snapshot(self, snapshot: dict) -> dict:
        return material_incident(snapshot)

    def validate_snapshot(self, snapshot: dict):
        self.config_factory()  # Missing credentials are a 503 before accepting work.
        if not isinstance(snapshot.get("hardware"), dict):
            raise ValueError("Incident hardware evidence is missing")

    def request_identity(self, snapshot: dict) -> str:
        config = self.config_factory()
        return content_revision({
            "case_revision": case_revision(snapshot), "model": config.model,
            "source": source_hash(LEGACY_MONITOR_PATH), "system_prompt": SYSTEM_PROMPT,
            "limits": {key: getattr(config, key) for key in LIMIT_FIELDS},
        })

    def job_metadata(self) -> dict:
        config = self.config_factory()
        return {"agent": "nvidia-nemotron", "model": config.model,
                "limits": {key: getattr(config, key) for key in LIMIT_FIELDS},
                "tool_calls": [], "evidence": [], "provider_calls": []}

    def _run(self, job: dict):
        client = None
        workspace = self.output_root / job["job_id"]
        try:
            running = self.repository.update_job(job["job_id"], {"status": "RUNNING", "updated_at": utc_now()})
            self.repository.attach_job(running)
            config = replace(self.config_factory(), model=job["model"], **job["limits"])
            client = self.client_factory(config)
            tools = self.tools_factory(deepcopy(job["snapshot"]), workspace)

            def progress(update):
                current = self.repository.update_job(job["job_id"], {**update, "updated_at": utc_now()})
                self.repository.attach_job(current)
                (workspace / "trace.json").write_text(json.dumps(update, indent=2) + "\n", encoding="utf-8")

            result = run_investigation(client, tools, progress)
            current = self.repository.get_job(job["job_id"])
            changes = {"status": "COMPLETED", "active": False, "result": result, "updated_at": utc_now()}
            attached = self.repository.attach_job({**current, **changes})
            self.repository.update_job(job["job_id"], {**changes, "attached_to_incident": attached})
            (workspace / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except Exception as error:
            safe_error = {"code": error.code, "message": str(error)} if isinstance(error, NemotronError) else {
                "code": "INVESTIGATION_FAILED", "message": "Investigation execution or storage failed",
            }
            try:
                current = self.repository.get_job(job["job_id"])
                changes = {"status": "FAILED", "active": False, "error": safe_error, "updated_at": utc_now()}
                attached = self.repository.attach_job({**current, **changes})
                self.repository.update_job(job["job_id"], {**changes, "attached_to_incident": attached})
            except Exception:
                pass  # Startup recovery marks unfinished durable jobs INTERRUPTED.
        finally:
            try:
                if client is not None:
                    client.close()
            finally:
                self.slots.release()
