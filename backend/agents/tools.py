"""Allowlisted diagnostic tools scoped to one immutable incident and source snapshot."""

from copy import deepcopy
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.modernization.docker_runner import resolve_image
from backend.modernization.patching import REPOSITORY_ROOT, create_model_proposal, source_hash
from backend.modernization.pipeline import execute_incident_repair, test_summary
from backend.modernization.runner import LEGACY_MONITOR_PATH
from backend.modernization.testing import run_acceptance_tests


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TestArguments(NoArguments):
    revision_id: Literal["original", "candidate"]


class PatchArguments(NoArguments):
    source_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status_assignment: str = Field(min_length=1, max_length=300)


TOOL_DEFINITIONS = {
    "get_incident_snapshot": (NoArguments, "Read the actual immutable incident captured for this investigation."),
    "inspect_legacy_code": (NoArguments, "Read the known original monitor, numbered lines, and source revision."),
    "read_monitoring_requirements": (NoArguments, "Read independent monitoring requirements, including fault and threshold behavior."),
    "run_regression_tests": (TestArguments, "Execute independent acceptance cases in Docker. A successful tool may return failing tests; inspect exit_code and counts."),
    "verify_monitor_patch": (PatchArguments, "Propose one status assignment against the inspected revision and actually verify it in Docker. Only temperature, 35, event.get('cooling_fault', False), boolean operators, and WARNING/NORMAL are allowed. Example format: status = \"WARNING\" if CONDITION else \"NORMAL\". It creates a separate candidate; it never deploys or approves it."),
}


class InvestigationTools:
    def __init__(self, snapshot: dict, workspace: Path):
        self.snapshot = deepcopy(snapshot)
        self.workspace = workspace
        workspace.mkdir(parents=True, exist_ok=False)
        self.original = workspace / "monitor.py"
        self.original.write_bytes(LEGACY_MONITOR_PATH.read_bytes())
        self.original_revision = source_hash(self.original)
        self.requirements = (REPOSITORY_ROOT / "fixtures/legacy_monitor/requirements.md").read_text()
        self.requirements_revision = source_hash(REPOSITORY_ROOT / "fixtures/legacy_monitor/requirements.md")
        self.generated_repair = None
        self.candidate = None
        self.tests_run = 0
        self.patch_attempts = 0
        (workspace / "incident-snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")

    @staticmethod
    def schemas() -> list[dict]:
        return [{"type": "function", "function": {
            "name": name, "description": description, "parameters": schema.model_json_schema(),
        }} for name, (schema, description) in TOOL_DEFINITIONS.items()]

    def execute(self, name: str, raw_arguments: str) -> tuple[dict, dict]:
        if name not in TOOL_DEFINITIONS or len(raw_arguments) > 8192:
            raise ValueError("Unknown tool or oversized arguments")
        schema = TOOL_DEFINITIONS[name][0]
        arguments = schema.model_validate_json(raw_arguments)
        if name == "get_incident_snapshot":
            data = {"incident": deepcopy(self.snapshot)}
        elif name == "inspect_legacy_code":
            data = {
                "path": "fixtures/legacy_monitor/monitor.py", "source_revision": self.original_revision,
                "lines": [{"line": number, "text": text} for number, text in enumerate(
                    self.original.read_text().splitlines(), start=1)],
            }
        elif name == "read_monitoring_requirements":
            data = {"path": "fixtures/legacy_monitor/requirements.md",
                    "source_revision": self.requirements_revision, "content": self.requirements}
        elif name == "run_regression_tests":
            if self.tests_run >= 2:
                raise ValueError("Diagnostic test limit reached; use existing evidence")
            source = self.original if arguments.revision_id == "original" else self.candidate
            if source is None:
                raise ValueError("No candidate exists yet")
            self.tests_run += 1
            actual = run_acceptance_tests(source, self.workspace, f"diagnostic-{self.tests_run}", resolve_image())
            summary = test_summary(actual, self.workspace)
            # Keep prompts/traces bounded; full raw output remains in verifier artifacts.
            summary["stdout"] = summary["stdout"][-8000:]
            summary["stderr"] = summary["stderr"][-2000:]
            data = {"revision_id": arguments.revision_id, "tests": summary}
        else:
            if self.patch_attempts >= 2:
                raise ValueError("Patch attempt limit reached")
            if arguments.source_revision != self.original_revision:
                raise ValueError("Patch must target the inspected source revision")
            self.patch_attempts += 1
            proposal = create_model_proposal(arguments.status_assignment, self.original_revision, self.workspace)
            self.candidate = proposal.candidate
            self.generated_repair = execute_incident_repair(self.snapshot, self.workspace, proposal)
            data = {
                key: deepcopy(self.generated_repair[key]) for key in (
                    "repair_id", "proposal_origin", "verification_status", "original_revision",
                    "candidate_revision", "diff_revision", "diff", "approval_status", "deployed", "replay",
                )
            }
            data["tests"] = {label: {key: value for key, value in result.items()
                                     if key in {"exit_code", "passed", "failed", "skipped", "cases"}}
                             for label, result in self.generated_repair["tests"].items()}
        return arguments.model_dump(), data
