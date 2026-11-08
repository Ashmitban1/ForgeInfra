"""Prepare manual or constrained model-authored candidates without changing the baseline."""

from dataclasses import dataclass
import ast
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
    proposal_origin: str = "manually_authored_demo_patch"


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
    return _write_proposal(original_bytes, candidate_source, output_root, "manually_authored_demo_patch")


def _write_proposal(original_bytes: bytes, candidate_source: str, output_root: Path, origin: str) -> RepairProposal:
    source = original_bytes.decode("utf-8")
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
        source_hash(original), source_hash(candidate), source_hash(diff), origin,
    )


def create_model_proposal(status_assignment: str, expected_revision: str, output_root: Path) -> RepairProposal:
    """Accept a model-authored rule for this known fixture, not arbitrary source/shell."""
    if source_hash(LEGACY_MONITOR_PATH) != expected_revision:
        raise ValueError("The inspected original revision changed")
    line = status_assignment.strip()
    if len(line) > 300 or "\n" in line or "\r" in line:
        raise ValueError("Provide one bounded status assignment")
    try:
        tree = ast.parse(line)
    except SyntaxError:
        raise ValueError("Invalid status assignment") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        raise ValueError("Only the status assignment can change")
    statement = tree.body[0]
    if (len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name)
            or statement.targets[0].id != "status" or not isinstance(statement.value, ast.IfExp)
            or not isinstance(statement.value.body, ast.Constant) or statement.value.body.value != "WARNING"
            or not isinstance(statement.value.orelse, ast.Constant) or statement.value.orelse.value != "NORMAL"):
        raise ValueError("Keep WARNING/NORMAL output and change only its condition")
    allowed = (ast.BoolOp, ast.Or, ast.And, ast.Compare, ast.Gt, ast.GtE, ast.Eq,
               ast.Name, ast.Load, ast.Constant, ast.Call, ast.Attribute)
    for node in ast.walk(statement.value.test):
        if not isinstance(node, allowed):
            raise ValueError("Unsupported operation in monitoring rule")
        if isinstance(node, ast.Name) and node.id not in {"temperature", "event"}:
            raise ValueError("Unsupported rule variable")
        if isinstance(node, ast.Constant) and not (
            type(node.value) is bool or node.value == 35 or node.value == "cooling_fault"
        ):
            raise ValueError("Unsupported rule constant")
        if isinstance(node, ast.Attribute) and not (
            isinstance(node.value, ast.Name) and node.value.id == "event" and node.attr == "get"
        ):
            raise ValueError("Only cooling_fault lookup is permitted")
        if isinstance(node, ast.Call) and not (
            isinstance(node.func, ast.Attribute) and len(node.args) == 2 and not node.keywords
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == "cooling_fault"
            and isinstance(node.args[1], ast.Constant) and node.args[1].value is False
        ):
            raise ValueError("Only event.get('cooling_fault', False) is permitted")
    original_bytes = LEGACY_MONITOR_PATH.read_bytes()
    if "sha256:" + hashlib.sha256(original_bytes).hexdigest() != expected_revision:
        raise ValueError("The inspected original revision changed")
    source = original_bytes.decode("utf-8")
    original_line = '    status = "WARNING" if temperature > 35 else "NORMAL"\n'
    if source.count(original_line) != 1:
        raise ValueError("Original rule changed; review the target")
    candidate = source.replace(original_line, "    " + line + "\n", 1).replace(
        "intentionally ignores cooling_fault", "Nemotron-generated rule candidate", 1,
    ).replace("Apply the original temperature-only rule", "Apply the proposed monitoring rule", 1).replace(
        "# Original rule: newer fields, including cooling_fault, are ignored.",
        "# Nemotron-generated candidate; actual behavior must pass independent tests.", 1,
    )
    return _write_proposal(original_bytes, candidate, output_root, "nemotron_generated_patch")
