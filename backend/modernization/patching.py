"""Prepare a manually authored demo candidate without changing the baseline."""

from dataclasses import dataclass
import difflib
import hashlib
from pathlib import Path
import tempfile

from backend.modernization.runner import LEGACY_MONITOR_PATH

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts/modernization"


def source_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class RepairProposal:
    workspace: Path
    original: Path
    candidate: Path
    diff: Path
    original_revision: str
    candidate_revision: str
    diff_revision: str


def create_demo_proposal(output_root: Path = DEFAULT_OUTPUT_ROOT) -> RepairProposal:
    """Copy the trusted original and apply a fixed patch, never model commands."""
    original_bytes = LEGACY_MONITOR_PATH.read_bytes()
    source = original_bytes.decode("utf-8")
    old_rule = '    status = "WARNING" if temperature > 35 else "NORMAL"\n'
    new_rule = (
        '    status = "WARNING" if temperature > 35 or event.get("cooling_fault", False) else "NORMAL"\n'
    )
    if source.count(old_rule) != 1:
        raise ValueError("Original temperature rule changed; review the demo patch before proceeding")
    candidate_source = source.replace(old_rule, new_rule, 1).replace(
        '"""Team-authored legacy monitoring fixture; intentionally ignores cooling_fault."""',
        '"""Manually authored repair candidate for the FactoryOS demo monitor."""',
        1,
    ).replace(
        '    """Apply the original temperature-only rule to one telemetry record."""',
        '    """Recognize cooling faults while preserving the temperature threshold."""',
        1,
    ).replace(
        "    # Original rule: newer fields, including cooling_fault, are ignored.",
        "    # Candidate rule: cooling faults also require a warning.",
        1,
    )
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="repair-", dir=output_root))
    original = workspace / "original/monitor.py"
    candidate = workspace / "candidate/monitor.py"
    original.parent.mkdir()
    candidate.parent.mkdir()
    original.write_bytes(original_bytes)
    candidate.write_bytes(candidate_source.encode("utf-8"))
    diff = workspace / "repair.diff"
    diff.write_text("".join(difflib.unified_diff(
        source.splitlines(keepends=True), candidate_source.splitlines(keepends=True),
        fromfile="original/monitor.py", tofile="candidate/monitor.py",
    )), encoding="utf-8")
    return RepairProposal(
        workspace, original, candidate, diff,
        source_hash(original), source_hash(candidate), source_hash(diff),
    )
