"""Real Google schema/key smoke check with entirely synthetic input, no repository source."""

from datetime import datetime, timezone
import json
from pathlib import Path

from dotenv import load_dotenv

from backend.agents.gemini import GeminiClient, GeminiConfig, GeminiError
from backend.agents.review import redact
from backend.agents.review_schemas import ReviewConclusion, fault_context


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / "backend/.env", override=False)
    load_dotenv(root / ".env", override=False)
    client = None
    try:
        config = GeminiConfig.from_environment()
        client = GeminiClient(config)
        # This data is created here, not read from a repo fixture, incident API,
        # database, previous model output, or an actual hardware observation.
        bundle = {
            "test_label": "ENTIRELY_SYNTHETIC_NOT_A_REAL_INVESTIGATION",
            "incident": {"incident_id": "SYNTHETIC-GEMINI-CHECK",
                         "observed_at": datetime.now(timezone.utc).isoformat(),
                         "cooling_fault": True, "fault_is_simulated": True,
                         "hardware": {"source_kind": "simulator", "fault_is_simulated": True},
                         "reported_status": "NORMAL", "expected_status": "WARNING"},
            "evidence": [{"evidence_id": "synthetic-evidence-1", "description": "Entirely fabricated test telemetry."}],
            "candidate": None,
        }
        bundle["fault_context"] = fault_context(bundle["incident"])
        text, metadata = client.review(bundle, (
            "Review this entirely synthetic telemetry example. It contains no repair candidate "
            "or executable proof, so repair_assessment must be NO_CANDIDATE. Cite synthetic-evidence-1. "
            "Recommend only advisory actions, require human approval, and state that inputs are synthetic. "
            "Set fault_provenance to SIMULATED. Never describe the simulated signal as a physical equipment fault. "
            "Return only the JSON object required by the supplied schema."
        ), ReviewConclusion.model_json_schema())
        conclusion = ReviewConclusion.model_validate_json(text)
        if (set(conclusion.evidence_ids) != {"synthetic-evidence-1"}
                or conclusion.repair_assessment != "NO_CANDIDATE" or conclusion.fault_provenance != "SIMULATED"):
            raise ValueError()
        result = redact({"provider_mode": "LIVE_GOOGLE_SYNTHETIC_INPUT_ONLY",
                         "provider": metadata, "result": conclusion.model_dump(),
                         "scope": "Key, model, HTTP protocol, and structured schema only; no stored incident review."}, config.api_key)
        output = root / "artifacts/modernization/gemini-synthetic-live-check.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "SUCCESS", "model": metadata["model"], "evidence_file": str(output)}))
        return 0
    except GeminiError as error:
        print(json.dumps({"status": "FAILED", "code": error.code, "message": str(error)}))
        return 1
    except ValueError:
        print(json.dumps({"status": "FAILED", "code": "INVALID_REVIEW", "message": "Synthetic review failed schema/evidence checks"}))
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
