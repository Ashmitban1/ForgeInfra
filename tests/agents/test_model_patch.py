import pytest

from backend.modernization.patching import create_model_proposal, source_hash
from backend.modernization.runner import LEGACY_MONITOR_PATH


def test_model_assignment_is_preserved_in_separate_candidate(tmp_path):
    revision = source_hash(LEGACY_MONITOR_PATH)
    assignment = 'status = "WARNING" if event.get("cooling_fault", False) or temperature > 35 else "NORMAL"'
    proposal = create_model_proposal(assignment, revision, tmp_path)
    assert assignment in proposal.candidate.read_text()
    assert proposal.proposal_origin == "nemotron_generated_patch"
    assert proposal.original_revision == revision == source_hash(LEGACY_MONITOR_PATH)


@pytest.mark.parametrize("assignment", [
    'status = __import__("os").system("echo unexpected")',
    'status = "WARNING" if open("/etc/passwd").read() else "NORMAL"',
    'status = "WARNING" if event.__class__ else "NORMAL"',
    'status = "WARNING" if event.get("other_field", False) else "NORMAL"',
    'status = "WARNING"\nimport os',
    'other_variable = "WARNING" if temperature > 35 else "NORMAL"',
])
def test_model_patch_policy_rejects_unsupported_operations(tmp_path, assignment):
    with pytest.raises(ValueError):
        create_model_proposal(assignment, source_hash(LEGACY_MONITOR_PATH), tmp_path)
    assert not list(tmp_path.iterdir())


def test_model_patch_rejects_uninspected_revision(tmp_path):
    with pytest.raises(ValueError, match="revision changed"):
        create_model_proposal('status = "WARNING" if temperature > 35 else "NORMAL"', "sha256:" + "0" * 64, tmp_path)
