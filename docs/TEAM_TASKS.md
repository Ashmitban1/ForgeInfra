# 3-Person ownership

| Person | Owns | First milestone |
| --- | --- | --- |
| **1** | `backend/main.py`, `backend/reliability.py`, `backend/schemas/`, `backend/storage/`, `hardware/` | Arduino/simulator → API → discrepancy |
| **2** | `backend/agents/`, `backend/modernization/` | Nemotron actually calls investigation and code-inspection tools; real patch tests |
| **3** | `frontend/`, `backend/integrations/` | React displays backend data; real Jira/Slack IDs; approval UI and Solana later |

Coordinate with Person 1 before modifying `backend/main.py` to register new routes. Preserve `docs/API_CONTRACT.md`. Each teammate works on their own Git branch, then opens a pull request. Secrets must not be committed.
