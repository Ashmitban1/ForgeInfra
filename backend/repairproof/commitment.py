"""Versioned byte contract; deliberately matches existing approval JSON hashes."""
import base64
import hashlib
import json

from backend.modernization.repository import content_revision

DOMAIN = b"FactoryOS/RepairProof/v1\n"


def canonical_bytes(value) -> bytes:
    # Preserve v1 approval semantics: ASCII escapes, sorted keys, no whitespace,
    # finite JSON numbers. Consumers hash these bytes, not reserialized objects.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_bundle(package: dict, decision: dict, *, proof_id: str, signer: str,
                 genesis_hash: str, memo_program: str) -> dict:
    package_bytes = canonical_bytes(package["data"])
    if digest(package_bytes) != package["package_revision"]:
        raise ValueError("Frozen package hash mismatch")
    if (decision["decision"] != "APPROVE"
            or decision["package_revision"] != package["package_revision"]
            or decision["candidate_revision"] != package["candidate_revision"]
            or package["data"]["binding"]["candidate_revision"] != package["candidate_revision"]):
        raise ValueError("Frozen decision binding mismatch")
    envelope = {
        "schema": "factoryos.repairproof.v1", "proof_id": proof_id,
        "incident_identity": package["data"]["incident_identity"],
        "package_revision": package["package_revision"],
        "candidate_revision": package["candidate_revision"],
        "approval_decision_id": decision["decision_id"],
        "approval_revision": content_revision(decision), "publisher": signer,
        "network_genesis_hash": genesis_hash, "memo_program": memo_program,
    }
    envelope_bytes = canonical_bytes(envelope)
    return {"envelope": envelope, "commitment": digest(DOMAIN + envelope_bytes),
            "package_bytes_b64": base64.b64encode(package_bytes).decode("ascii"),
            "approval_bytes_b64": base64.b64encode(canonical_bytes(decision)).decode("ascii"),
            "envelope_bytes_b64": base64.b64encode(envelope_bytes).decode("ascii")}
