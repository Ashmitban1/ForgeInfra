"""Named reviewer credentials for the local approval API; no shared model keys."""

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import re


class ApprovalAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Reviewer:
    reviewer_id: str


def token_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApprovalAuth:
    def __init__(self, reviewers: dict[str, str]):
        self.reviewers = reviewers

    @classmethod
    def from_environment(cls):
        try:
            reviewers = json.loads(os.environ.get("FACTORYOS_APPROVERS_JSON", ""))
            if not isinstance(reviewers, dict) or not 1 <= len(reviewers) <= 32:
                raise ValueError()
            for reviewer_id, digest in reviewers.items():
                if (not re.fullmatch(r"[A-Za-z0-9_.@-]{1,80}", reviewer_id)
                        or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
                    raise ValueError()
            if len(set(reviewers.values())) != len(reviewers):
                raise ValueError()
            return cls(reviewers)
        except (ValueError, TypeError):
            raise ApprovalAuthError("Configure FACTORYOS_APPROVERS_JSON with named reviewer token digests") from None

    def authenticate(self, token: str) -> Reviewer | None:
        if not 32 <= len(token) <= 256:
            return None
        supplied = token_digest(token)
        for reviewer_id, digest in self.reviewers.items():
            if hmac.compare_digest(supplied, digest):
                return Reviewer(reviewer_id)
        return None
