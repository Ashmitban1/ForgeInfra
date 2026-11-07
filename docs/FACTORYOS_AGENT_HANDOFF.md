# FACTORYOS — MASTER AI AGENT HANDOFF

**HackUTD Zero Day 2026 | Portable context for any new ChatGPT / Claude / coding-agent session**  
**Snapshot:** November 7, 2026 (America/Chicago)  
**Project:** FactoryOS (evolved from the earlier concept **ShadowShift: Mission Control**)  
**Team:** **3 people**, not 4  
**Status:** Design and implementation plan agreed; **do not assume any specific module is built, deployed, wired, authenticated, or tested until the team confirms it.**

> **READ THIS FIRST — INSTRUCTIONS FOR THE RECEIVING AI**  
> You are joining an existing 24-hour hackathon project. Treat this file as the team's current decisions and technical contract. **Continue the work; do not restart ideation, rename the product, replace the sponsor strategy, or ask about decisions already answered here.** Prioritize functional, demonstrable engineering. Be proactive: propose the next concrete step, provide runnable code when asked, and preserve compatibility with the shared API contract. Distinguish (a) actual user-provided hardware and sponsor statements, (b) design decisions, and (c) illustrative or proposed features. Never claim a sample result, service integration, blockchain transaction, or test is real until independently observed. If a decision is not settled, present the best default and identify the assumption. Be especially careful with the hard submission deadline.

**What this file is:** A reusable context handoff / project specification, **not literal training of model weights**. Upload the file to a new AI session or paste its contents and ask the AI to continue.

---

## 0. Quick-start context (one-minute version)

**Mission:** Build **FactoryOS: an AI-powered infrastructure information-reliability and legacy-software modernization platform**. Data centers receive telemetry from sensors, monitoring APIs, logs, and incident systems. Information can be stale, inconsistent, incomplete, incorrectly prioritized, or delivered to the wrong technician. FactoryOS detects these issues, investigates them through genuine **NVIDIA Nemotron tool calls**, gets a structured **Gemini final recommendation**, creates/updates **Jira** tickets and **Slack** messages, and when monitoring software contributes to the issue, inspects and improves a **representative legacy application**, runs actual regression tests, obtains approval, and optionally records a **Solana** proof of approved repair.

**Primary sponsor challenges:**

1. **8090.AI:** “Build agents and tools that accelerate legacy system modernization. The world runs on old software. Make it easier to understand, improve, or replace.” (2026 event slides, p. 25.)
2. **NVIDIA:** “Use Nemotron Beyond a Chatbot.” Must use Nemotron and demonstrate **multi-step agent workflows, intelligent external tool integrations, and practical real-world application**, rather than just replies to prompts. (2026 slides, p. 64.)
3. **Northmark Compute & Cloud (NMC²):** “Mission: Keep the World Running.” Data center teams face **missed warnings, unclear handoffs, and the wrong information at the wrong time**. Build something that helps teams stay ahead. (2026 slides, p. 36.)

**Additional targets:** HackUTD Hardware Track and eligible 2026 MLH categories: **Tiger Data, Solana, SpaceXSI, GoDaddy Registry, Vultr, MongoDB Atlas, Gemini API**. These are awards/prize opportunities, not substitutes for the three company tracks. The **two-versus-three company-track submission limit is unresolved**: the public website was reported to say “up to two,” while a newer pasted Devpost overview reportedly allows three. Ask organizers / inspect the actual Devpost submission before assuming all three can be entered. Keep the product coherent regardless of eligibility.

**Winning demonstration:** Flip an Arduino switch to simulate a cooling fault while the sensor gives real temperature/humidity → independently detect a fault or legacy-system discrepancy → Nemotron calls real diagnostic/code tools → Gemini recommends escalation → Jira ticket and Slack alert/handoff → Nemotron proposes a targeted legacy-code repair → executable tests show the old defect and corrected behavior → human approval and optional Solana proof → replay the event to demonstrate resolution. **The switch is a simulated fault; the sensor readings are physical measurements.**

**Top rule:** **One genuine working vertical slice > 15 disconnected half-built prize features.** Using Jira, Slack, GitHub, cloud providers, other models, and existing APIs is intentional: the originality is in the intelligence, orchestration, correctness, and end-to-end flow.

---

## 1. Problem, why it matters, and actual users

### The Northmark-specific problem

Northmark did **not** specifically ask for legacy modernization. It asked for **data center operations reliability**. Teams can have many monitoring tools and still fail because:

- **Information mismanagement:** stale data, wrong timestamp, duplicated events, incomplete logs, and fragmentation across systems.
- **Conflicting / misleading information:** a physical fault signal may disagree with a legacy monitoring application that says NORMAL.
- **Alert fatigue / prioritization:** high-volume low-priority signals can obscure urgent ones.
- **Communication failure / unclear technician handoff:** the incoming shift does not know the last measurements, findings, previous attempts, open questions, ownership, or next action.
- **Wrong information at the wrong time:** critical signals may be routed late, sent to an off-duty person, or shown without context.
- **Legacy software limitations:** older monitoring code might only understand temperature and overlook newer fault input, or might poll/cache readings too slowly.
- **Trust / accountability:** authorized decisions and changes need verifiable supporting evidence.

Do not reduce the challenge to “we built a temperature dashboard” or “we replaced Jira.” The product is **an information reliability + incident intelligence + verified modernization loop**.

### Real users and their jobs-to-be-done

| User | What they need | FactoryOS capability |
|---|---|---|
| **Data center operations engineer (primary)** | What is actually wrong, how reliable is the evidence, what is urgent? | Mission Control, source comparison, clear explanations |
| **On-call field technician** | What happened, where, what was tried, what next? | Complete Jira incident and Slack handoff; acknowledgement/ownership |
| **Reliability / software engineer** | Is old code hiding or delaying a signal? Can a fix be made safely? | Source inspection, patch, test evidence, GitHub change |
| **Shift lead / operations manager** | Who owns the incident? Is it resolved? | Timeline, escalation and handoff, approval and closure |

### Business importance

Data center downtime can be expensive and operationally disruptive, but **do not invent Northmark-specific downtime, equipment, savings, or customer statistics**. The project's defensible claim is that improving information freshness, triage, handoff, and verified code changes can **reduce opportunities for missed alerts and response delays**. Measure the prototype's actual results rather than claiming production impact.

### What “legacy system” means here

We **do not possess Northmark production monitoring source code**. For the MVP, create a clearly labelled **representative legacy monitoring fixture**: a small old-style Python script / CSV-polled program / monolithic service with imperfect monitoring rules. “Legacy” describes architecture and maintenance burden, not necessarily COBOL. Our demonstrable sample bug is that the old monitor uses a temperature threshold but **ignores a new `cooling_fault` input**; an optional second scenario involves stale polling/cache timestamps. We modernize this controlled application and test it; never claim we have modified Northmark’s actual systems.

---

## 2. Scope and priority guardrails

### P0: Minimum credible end-to-end product

1. Arduino or simulator sends a versioned, timestamped sensor/fault event through Python serial gateway / FastAPI.
2. Backend evaluates monitoring output and a **deterministic reliability rule**. It detects a mismatch; this must work without a model.
3. Nemotron genuinely invokes **at least two tools**, e.g. fetch telemetry + inspect source, and returns grounded findings and a modernization plan.
4. Gemini reviews the gathered evidence and Nemotron plan, returns **structured final recommendation**. A backend policy layer validates allowed actions.
5. Dashboard shows actual incident data, source timestamps, evidence, tool activity and decision.
6. **Real Jira issue creation and real Slack notification** where credentials/permissions are available; show returned IDs and links. If unavailable, clearly label a fallback as simulated, never as a successful integration.
7. Show the legacy program's original behavior, apply or prepare a targeted patch, run real baseline + new regression tests, and show actual before/after results.
8. Required human approval before merge, staging deployment, changing infrastructure settings or transfers.

### P1: Strong additional proof / prize features

- Tiger Data time-series storage and meaningful history queries.
- MongoDB Atlas incident / agent trace / evidence documents.
- Deployed running backend and app (e.g. Vultr).
- Solana **devnet** repair evidence hash / authorized approval / independent Verify button.
- Technician acknowledgment/handoff flow and stale-data reliability scoring.
- GitHub branch/PR that links to the incident.

### P2: Stretch only after P0 works

- Gemini multimodal interpretation of maintenance diagrams, equipment labels or photos.
- Solana custom Anchor contract with on-chain state transitions, technician recognition, or escrow with valueless devnet tokens.
- Godaddy-branded domain; SpaceXSI qualifying development workflow.
- Extra sensor types, larger incident dataset, sophisticated prediction, multiple microservices or 3D visualization.

**Do NOT** let smart-contract complexity, building a Figma clone, a complicated neural anomaly detector, rewards/payments, or secondary prizes jeopardize the core demonstration. At the same time, **do not dismiss genuine third-party integrations** just because the sponsor may already have ticketing or monitoring: leveraging existing tools is the intended MVP strategy.

---

## 3. Confirmed vs proposed hardware

User showed photos of **ELEGOO UNO R3 starter kit** and **ELEGOO 37-in-1 sensor modules kit**. The kit inventory shown includes UNO R3 controller board, DHT11 temperature/humidity module, thermistor, tilt ball switch, active/passive buzzer, LEDs including RGB LED, LCD1602, relay, breadboard, USB cable, jumper wires, plus sensors in the 37-in-1 collection. **Physical possession was stated by the user, but individual parts and successful connection have not yet been validated.**

**Use the Arduino UNO R3, NOT an assumed ESP32.** It has no native Wi-Fi. Connect to a laptop over **USB serial**, run a Python `pyserial` gateway, and forward normalized events to FastAPI. Optional fallback: simulator emitting exactly the same JSON, clearly marked as simulated.

Suggested initial wiring targets (verify module labels, actual pinout and library compatibility first):

- UNO R3 + DHT11 for physical temperature/humidity reading.
- Tilt ball switch as a **simulated** cooling/fan failure signal. It does not measure real fan health.
- Green/yellow/red status LED or RGB LED; optional active buzzer for audible warning.
- Optional thermistor for second temperature source or sensor-disagreement scenario.
- No need to operate the relay or any mains-powered equipment. Keep the demonstration low-voltage.

**Example physical event:** DHT11 reports 29.4°C and 54% humidity (numbers illustrative); switch flips to `cooling_fault=true`; legacy monitoring returns NORMAL because it checks only `temperature>35`; independent safety rule returns WARNING. This is a deliberate demo fault that exposes missing monitoring logic, not a claim a data center at 29.4°C is necessarily unsafe.

Device identity and evidence: gateway assigns device ID, observed/received timestamps, sequence number if possible, source identifier and `fault_is_simulated=true`. Check stale/duplicate sequences. Do not claim a sensor is trusted merely because a reading is on-chain.

---

## 4. Data sources and what they actually tell us

### Physical data
- Arduino DHT11: real measured ambient temperature/humidity.
- Tilt switch: binary **simulated equipment fault**.
- Optional vibration / thermistor for a second scenario; do not claim industrial predictive-maintenance precision.

### Digital input sources
- **Legacy monitoring API / script:** what an existing monitoring application reports (`NORMAL` / `WARNING`, sample time, code revision). In the MVP this is our representative fixture.
- **Prometheus API / host exporter / psutil-derived metrics:** real CPU/memory/server utilization if a real monitored machine is connected. A laptop acting as a server must be labeled as such.
- **Open-Meteo:** outdoor weather context (not a substitute for internal rack readings).
- **Logs:** application poll, cache, error and transformation events.
- **Jira:** past issues, current incidents, owners, status, history.
- **Slack:** incident communication, delivered messages and acknowledgements if implemented.
- **GitHub:** the representative old code, commit history, source diff, patch PR.
- **Runbooks/docs:** historical steps, component dependencies and known issues (can be fixture documents).

### Storage roles
- **Tiger Data:** frequent timestamped telemetry, alert streams, anomaly windows / history queries.
- **MongoDB Atlas:** incidents, evidence manifests, investigation summaries, agent tool traces, code/test reports, flexible documents.
- Begin with SQLite / JSON if the external database setup would stall P0, then upgrade with real integrations.

**Misinformation vs mismanagement:** The challenge is broader than hostile misinformation. A reading can be true but stale or sent to the wrong person. Separate `is_data_fresh`, `is_source_consistent`, and `is_actionable` rather than trusting an opaque AI score.

---

## 5. Canonical demo scenario and acceptance criteria

**Canonical scenario ID: `INC-COOLING-001`; device `RACK-01`.**

1. Hardware gateway emits a reading and a switch-generated cooling fault.
2. Independent detection logic sees the fault and emits WARNING promptly.
3. The legacy monitoring fixture ignores that field and reports NORMAL.
4. Reliability layer compares the two with matching incident/device identifiers and time windows and records **`legacy_missed_fault`**. If a separate stale-data scenario is tested, explicitly record `stale_legacy_reading` based on timestamps.
5. Nemotron queries tools for telemetry, current legacy decision, source code, previous incident if available, and test results. It identifies the relevant old code rule with a source reference.
6. Gemini reviews Nemotron's evidence bundle and recommends an action such as `ESCALATE` and `INVESTIGATE_SOFTWARE`.
7. Backend sends urgent operational alert without waiting for AI and handles Jira/Slack execution (safe idempotent retries).
8. Code-patching workflow proposes the new `cooling_fault` condition, runs baseline tests and new test case. Before patch: missing-fault test fails. After patch: tests pass.
9. Authorized person reviews diff/test output and approves an isolated staging change; no production actions.
10. Replay same fault through the updated monitor: now WARNING; store evidence and optionally anchor approved report hash to Solana devnet. Incident handoff includes what happened, what was verified, what remains outstanding.

**A serious conceptual distinction:** Fixing the *monitoring software* does not fix the *physical cooling equipment*. The technician still needs to inspect the simulated physical fault. The modernization part fixes detection/communication deficiencies.

**P0 successful demo evidence:** actual input timestamp, actual mismatch, Nemotron tool calls and outputs, actual Gemini structured response, real Jira key/Slack message if available, actual test command output, code diff, approval outcome, and post-fix replay. UI should show honest statuses (`live`, `demo`, `simulated`, `pending`, `failed`).

---

## 6. Team split — exactly three people

The team agreed to **three architecture-owned workstreams** rather than assigning people only by sponsor. These roles were used in the last finalized PDF and should not be silently changed.

### PERSON 1 — Hardware, data, shared FastAPI backend

**Primary fit:** Northmark + Hardware + Tiger Data / MongoDB + some Vultr.

**Ownership:**

- Connect UNO R3/DHT11/tilt switch; write Arduino firmware and Python serial gateway.
- Build shared FastAPI application and `POST /api/telemetry`.
- Implement telemetry validation, timestamps, source identifiers, freshness, duplicates, missing values and mismatch detection.
- Integrate a real external monitoring source or a transparently labeled fixture.
- Expose incident and telemetry retrieval APIs; persist locally and then to Tiger Data/MongoDB if feasible.
- Coordinate environment variables and backend service deployment.

**First deliverable:** Hardware or simulator event reaches FastAPI; legacy output disagrees with an independent rule and a structured incident is returned.

**Definition of done:** Person 2 and Person 3 can both fetch **the same incident and evidence** by ID; source timestamps and reliability reasons are available.

### PERSON 2 — NVIDIA Nemotron, Gemini, legacy modernization

**Primary fit:** NVIDIA + 8090.AI + MLH Gemini.

**Ownership:**

- Implement an **actual NVIDIA Nemotron tool-calling agent**, tool registry, trace logger and bounded investigation loop.
- Tools retrieve data from Person 1's endpoints, inspect logs / legacy source / documentation and execute tests.
- Integrate Gemini to review evidence and produce **validated structured final recommendation**; maintain Nemotron as the agent orchestrator.
- Create and test the representative legacy monitoring fixture and regression bug.
- Analyze legacy code, propose minimal patch, produce a diff, run unit/regression tests, and demonstrate before/after behavior.
- Provide AI/repair routes and evidence payloads; optionally GitHub PR integration with Person 3.

**First deliverable:** Nemotron invokes real functions to read code/data and returns findings linked to evidence. No hard-coded “AI is investigating” UI simulation.

**Definition of done:** A known monitoring rule defect is localized, a proposed patch is generated and test evidence proves behavior changed as expected without breaking baseline scenarios.

### PERSON 3 — React frontend, operations automation, approvals, Solana

**Primary fit:** Northmark user experience + Jira/Slack + MLH Solana + GoDaddy.

**Ownership:**

- Build polished React Mission Control dashboard (server/device view, incident status, telemetry, data-source conflict, event timeline).
- Show actual Nemotron tool invocations, evidence, Gemini recommendations, code diff and test results.
- Integrate Jira create/update/assign plus Slack alerts and complete technician handoff.
- Build approval UI, explicit gated high-impact actions and API wiring.
- Add optional devnet Solana evidence verification after golden path works; support UX, demo recording and submission.
- Help Person 1 deploy frontend and backends.

**First deliverable:** Dashboard renders a shared mock incident JSON, with source freshness, mismatch and pending investigation.

**Definition of done:** A live incident can be inspected, linked to actual Jira/Slack activity, and show approved repair/test verification. No fake success signals.

### Coordination rules

- **Person 1 owns backend bootstrapping and schema**, but Persons 2 and 3 own their modules / routers. Avoid editing the same files concurrently; use feature branches and merge often.
- **Person 2 must not wait for physical hardware**; consume versioned mock JSON until real telemetry arrives.
- **Person 3 must not wait for AI/DB access**; render static mock with the final schema, then swap to real endpoints.
- A cross-team integration check should occur immediately after the first working implementation of each interface, not only at the end.
- **Person 3 leading Solana** does not relieve Person 2 of supplying a code revision/evidence hash or Person 1 of backend verification and persistence.
- Shared README should record current functionality, demo steps, credentials needed (names only), known issues, and owner.

---

## 7. API/data contract v1 — freeze before independent development

The following is a **proposed shared contract** derived from the agreed plan, not proof that routes have already been implemented. If the team changes it, version it and update this file. **All components must preserve the same incident ID and trace IDs** across telemetry, agent actions, Jira, Slack, GitHub, tests and optional Solana proofs.

### Incoming telemetry (normalized by gateway)

```json
{
  "schema_version": "1.0",
  "device_id": "RACK-01",
  "source_kind": "arduino_serial",
  "observed_at": "2026-11-07T21:00:00Z",
  "received_at": "2026-11-07T21:00:01Z",
  "sequence": 42,
  "temperature_c": 29.4,
  "humidity_pct": 54.0,
  "cooling_fault": true,
  "fault_is_simulated": true
}
```

The UTC timestamps are illustrative. The Arduino Uno typically does not have a synchronized clock; the gateway can timestamp receipt and make the measurement-time limitations explicit. `source_kind` can be `arduino_serial` or `simulator`; UI must not confuse them.

### Canonical incident object

```json
{
  "schema_version": "1.0",
  "incident_id": "INC-COOLING-001",
  "device_id": "RACK-01",
  "created_at": "2026-11-07T21:00:02Z",
  "status": "OPEN",
  "severity": "HIGH",
  "hardware": {
    "temperature_c": 29.4,
    "humidity_pct": 54.0,
    "cooling_fault": true,
    "fault_is_simulated": true,
    "source_kind": "arduino_serial",
    "observed_at": "2026-11-07T21:00:00Z"
  },
  "legacy_monitor": {
    "status": "NORMAL",
    "source_revision": "demo-legacy-v1",
    "sampled_at": "2026-11-07T21:00:00Z"
  },
  "expected_status": "WARNING",
  "reliability": {
    "mismatch": true,
    "reasons": ["legacy_missed_fault"],
    "evidence_quality": "PARTIAL"
  },
  "investigation": {
    "status": "PENDING",
    "agent": "nvidia-nemotron",
    "tool_calls": [],
    "findings": [],
    "evidence_ids": []
  },
  "decision_review": {
    "status": "PENDING",
    "reviewer": "gemini",
    "recommendation": null
  },
  "integrations": {
    "jira_key": null,
    "jira_url": null,
    "slack_message_id": null,
    "github_pr_url": null,
    "solana_tx_signature": null
  }
}
```

All values above are **sample/test data**. An empty ID is not a successful external integration. Never create a visual “verified” label unless the verification operation actually succeeded.

### Proposed routes and ownership

| Route | Owner | Purpose |
|---|---|---|
| `POST /api/telemetry` | 1 | Ingest normalized telemetry event; evaluate deterministic rules |
| `GET /api/telemetry/latest` | 1 | Latest sensor / API measurements with timestamps |
| `GET /api/incidents` | 1 | Incident list and reliability reasons |
| `GET /api/incidents/{id}` | 1 | Canonical incident and evidence manifest |
| `POST /api/incidents/{id}/investigate` | 2 | Kick off a bounded Nemotron tool-using investigation |
| `GET /api/incidents/{id}/analysis` | 2 | Nemotron findings + trace + Gemini review status |
| `POST /api/incidents/{id}/repair` | 2 | Propose patch, run controlled verification, return diff/test results |
| `POST /api/incidents/{id}/notify` | 3 | Run policy-checked Jira/Slack actions; return external IDs |
| `POST /api/repairs/{id}/approve` | 3 UI + backend | Submit explicit authorized human approval |
| `GET /api/repairs/{id}/verify` | 3 / shared | Verify evidence / chain record when implemented |

**Route ownership ≠ separately deployed services.** They can all be routers mounted into one FastAPI app. For slower agent jobs, return a job/operation ID and poll status rather than blocking every request. Frontend updates can use polling at first; SSE/WebSocket is optional.

### Suggested result shape for investigation

```json
{
  "incident_id": "INC-COOLING-001",
  "status": "COMPLETE",
  "suspected_cause": "legacy_monitor_ignores_fault_flag",
  "confidence_label": "medium",
  "evidence_ids": ["sensor-event-42", "legacy-source-line-17"],
  "tool_calls": [
    {"tool": "get_telemetry_window", "status": "success", "duration_ms": 131},
    {"tool": "inspect_legacy_code", "status": "success", "duration_ms": 46}
  ],
  "recommended_next_steps": ["escalate_incident", "create_patch_proposal"]
}
```

Do not fabricate `duration_ms`, evidence IDs, model certainty or tools that did not run. Treat numerical LLM confidence as uncalibrated unless validated.

---

## 8. Technical behavior and agent workflow

### A. Deterministic reliability engine (Person 1)

- Normalize units, timestamps, device ID and source IDs.
- Flag stale data when `now - sampled_at > configured_ttl` (example TTL must be chosen/declared, not assumed universal).
- Flag duplicate/reordered sequence events, missing fields, inconsistent monitoring outputs and unexpected values.
- Compare independent physical/simulated fault signal to what the legacy monitor reports for the same device/event. Avoid simply comparing unlike sensors or timestamps without normalization.
- Produce a structured `reliability.reasons[]` and a transparent explanation. If using an “Information Reliability Score,” define its deterministic ingredients, do not present an unvalidated AI number as a scientific measure.
- **Critical fault notification should not wait for the LLMs**. The AI can enrich, prioritize, and contextualize while the core alert proceeds.

### B. Nemotron tool-using investigation (Person 2)

Nemotron is the **primary multi-step agent/orchestrator** for the NVIDIA challenge. It should decide which tools to invoke based on available evidence, operate within an allowlisted environment, and expose inspectable call traces. Suggested safe tool registry:

```text
get_latest_telemetry(device_id)
get_telemetry_window(device_id, from_time, to_time)
get_legacy_monitor_output(device_id, event_id)
get_system_logs(component, time_window)
search_incident_history(query)
read_runbook(reference)
inspect_legacy_code(path_or_function)
run_regression_tests(test_suite_id)
generate_patch_proposal(incident_id, evidence_ids)
compare_old_and_new_behavior(test_case_ids)
```

Additional action tools require separate permissions and policy gates:

```text
create_jira_issue(incident_id, validated_payload)
send_slack_notification(incident_id, validated_message)
create_github_branch_or_pr(approved_patch_id)
create_staging_deploy(approved_revision)
```

A good tool trace shows **tool input (redacted), actual execution result, retrieved evidence, and next agent step**. Never pass arbitrary LLM shell commands into a privileged process; use defined tool functions and constrained/sandboxed execution.

### C. Gemini final recommendation (Person 2)

Team decided to use **Gemini for the final AI decision/recommendation**, while keeping Nemotron central to planning, investigation, code reasoning and tool use. Gemini receives the evidence manifest, data-quality flags, Nemotron findings and candidate actions, and produces validated JSON. Example:

```json
{
  "recommendation": "ESCALATE",
  "severity": "HIGH",
  "actions": ["create_jira_incident", "notify_on_call", "investigate_legacy_code"],
  "evidence_ids": ["sensor-event-42", "legacy-source-line-17"],
  "needs_human_approval": false,
  "explanation": "A fresh, simulated cooling fault is present but the legacy monitor reports NORMAL."
}
```

The structured output is an **AI recommendation**, not cryptographic or operational authority. A deterministic policy layer controls action eligibility. If the evidence is stale, sources disagree substantially, or models disagree, escalate and seek human review. A model should **not** autonomously shut off servers, merge unreviewed patches, deploy to production, transfer funds or misstate physical fault certainty.

### D. Modernization flow (Person 2)

1. Identify a relevant rule in a small real, runnable representative legacy application.
2. Link that rule to incident evidence and source file/line or function.
3. Create modernization proposal with diff/change rationale; keep patch minimal.
4. Show original baseline behavior and a failing regression test for the newly recognized condition.
5. Execute unit/regression tests on the patched version in a sandbox. Show raw results.
6. Compare before/after behavior; confirm existing expected behavior is preserved on defined tests, not “all behavior is proven equivalent.”
7. Request a human approval before merging or staging deployment.
8. Replay the same incident through the updated monitor and demonstrate a fixed detection gap.

### E. Incident/technician workflow (Person 3)

A Jira record/handoff should include: incident ID; device/rack; source timestamps; readings; explicitly simulated fault status; impact/severity and basis; evidence links; what was investigated; uncertainty; what has already been attempted; owner; next safe steps; who must acknowledge; last update and status. Slack message should include a short summary and the canonical Jira link, not secrets or raw large logs. Add idempotency keys so retries don't create multiple Jira issues or spam Slack.

### F. Solana ProofOps (Person 3, with help)

Optional *after* the golden path: canonicalize a repair evidence JSON manifest, compute SHA-256 hash, register a minimal devnet record bound to an authorized signer and code revision, and implement **Verify Evidence** to fetch on-chain data and recompute the hash. This detects alterations **after** attestation; does not prove an original sensor measurement or model inference was truthful. Don't put private infrastructure data, secrets, customer records or confidential source code on public chain. If custom smart contracts are attempted, enforce role-based approval and approved state transitions; off-chain workers still execute Jira/Slack/deployment actions. Technician reward or payment system is only stretch and should use valueless devnet tokens and human authorization.

---

## 9. Folder structure and repo conventions

```text
FactoryOS/
├── README.md
├── .env.example                 # variable names only, no secrets
├── backend/
│   ├── main.py                 # Person 1 integrates routers
│   ├── schemas/
│   │   └── incident.py         # versioned shared contract
│   ├── telemetry/              # Person 1
│   │   ├── ingestion.py
│   │   ├── reliability.py
│   │   ├── external_apis.py
│   │   └── storage.py
│   ├── agents/                 # Person 2
│   │   ├── nemotron.py
│   │   ├── gemini.py
│   │   ├── tools.py
│   │   └── investigation.py
│   ├── modernization/         # Person 2
│   │   ├── legacy_monitor.py
│   │   ├── code_analysis.py
│   │   ├── patching.py
│   │   └── testing.py
│   └── integrations/          # Person 3
│       ├── jira.py
│       ├── slack.py
│       └── solana.py
├── frontend/                   # Person 3 — React UI
├── hardware/                   # Person 1
│   ├── arduino/
│   └── serial_gateway.py
├── fixtures/                   # representative legacy app + sample event JSON
├── tests/
└── docs/
    ├── architecture.md
    └── demo_script.md
```

Choose Python FastAPI + React/Tailwind as the base stack. `pytest` for backend and regression tests. React charts and dependency graph are optional enhancements. Use Git feature branches (`feat/telemetry`, `feat/agents`, `feat/dashboard`) and keep a working `main` branch.

**External credentials:** `NVIDIA_API_KEY`, `GEMINI_API_KEY`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `SLACK_WEBHOOK_URL` or Slack bot credentials, `MONGODB_URI`, Tiger Data connection string, cloud deployment credentials and `SOLANA_RPC_URL` if applicable. These are indicative names, not proof of service availability. Put secrets only in local environment / deployment secret storage, **never in this handoff, screenshots, browser console, committed code, or Devpost**.

---

## 10. Validation and failure-mode checklist

### Hardware / data
- [ ] Arduino connects and emits parseable lines; DHT11 read errors handled.
- [ ] Physical sensor measurements and simulated fault states visibly distinguished.
- [ ] USB serial disconnect and malformed JSON do not crash the backend.
- [ ] Gateway and backend agree on timestamps, units, source IDs and incident IDs.
- [ ] Real and synthetic/API fixture readings are visibly labeled.
- [ ] Stale, duplicate, missing-data and mismatch cases have deterministic tests.

### AI and modernization
- [ ] A real Nemotron API call occurs with permitted multi-step tool use.
- [ ] Logs show tool results, not a fabricated trace.
- [ ] Gemini returns validated structured recommendation; invalid JSON handled.
- [ ] Prompt-injection defenses: logs, tickets, code comments and docs are **untrusted content**, not instructions to execute.
- [ ] Legacy source is genuine runnable fixture, not a screenshot.
- [ ] Reproduction: original program fails the defined new case; patch version passes.
- [ ] Existing baseline tests also pass.
- [ ] AI cannot directly run arbitrary shell commands, deploy production code or transfer assets.

### Automation / security
- [ ] Jira issue exists and returned key/URL opens (if claimed).
- [ ] Slack message truly delivered (if claimed).
- [ ] Retries do not create duplicate tickets/actions.
- [ ] Technician handoff includes clear ownership and next steps.
- [ ] Approval checks actual authorized identity; no client-only trust.
- [ ] Solana verification (if claimed) actually fetches transaction/account state and recomputes evidence hash.
- [ ] External API outages have explicit `unavailable`/`pending` states and fallback rather than simulated success.

### Demo / submission
- [ ] A complete vertical slice can be replayed without hidden manual data manipulation.
- [ ] One short recorded demo is captured as backup; show actual hardware and code/test output.
- [ ] Screenshots and video do not expose API keys, employee information or secret tokens.
- [ ] Devpost description separates built features, partially implemented features, and future plans.
- [ ] Demo demonstrates sponsor-specific value: 8090 code modernization, NVIDIA tool-using Nemotron, Northmark incident reliability/handoff.

---

## 11. Evidence, KPIs, and what judges should see

Demonstrable measurements:

| Claim / question | What to measure or show |
|---|---|
| Did FactoryOS detect unreliable information? | Known fault events, disagreement reason, timestamps, confusion matrix over **controlled fixtures** |
| Was the information stale? | Observed vs received vs legacy sample timestamps and TTL rule |
| How fast was detection? | Hardware event-to-backend alarm latency (local clock basis shown) |
| Did the agent act? | Nemotron tool call names, inputs/results and actual outputs |
| Was the incident coordinated? | Real Jira key, Slack message/link, ownership and acknowledgment |
| Did modernization fix the code? | Source diff, failing old regression, passing new regression + baseline |
| Was the repair authorized? | Human approval record; optional devnet attestation |
| Is the record unchanged? | On-chain hash mismatch when a test report is modified, with limitations explained |

**Presentation principle from prior winner research:** 2025 winners stood out through sponsor fit (Stamped/UpGuardian), genuine agent/tool work (DataDriver), unusual physical-to-software demonstrations (VisionScout), expressive visual UX (PoyoLabs), relatable full user journeys (NLB), multi-award integration (HarmoniQ) and branding (Hyperlynx). Their Devpost claims were not always independently verified; do not equate prize labels with proof of implementation. FactoryOS should be **easy to explain visually, technically deep and honest about simulated input**.

---

## 12. HackUTD 2026 tracks, rules and deadlines: snapshot and caveats

Source: user-supplied **`HACKUTD26Slides.pdf`** (123 pages). Exact relevant slides:

| Slide | Item |
|---|---|
| 25 | 8090 AI agents/tools for legacy modernization; listed prize DJI Mic Mini |
| 36 | Northmark mission: keep data centers running; prevent missed warnings and bad handoffs; listed 1st/2nd/3rd prizes |
| 64 | NVIDIA challenge: **Use Nemotron Beyond a Chatbot**, multi-step tools and real-world applicability |
| 79 | MLH Hardware Lab availability |
| 84 | MLH Tiger Data |
| 85 | MLH Solana |
| 86 | MLH SpaceXSI |
| 87 | MLH GoDaddy Registry |
| 88 | MLH Vultr |
| 89 | MLH MongoDB Atlas |
| 90 | MLH Gemini API |
| 105 | Judging listed 1 PM–4 PM; submission deadline noon |
| 106 | Initial Devpost deadline 11 PM |
| 108 | Final Devpost deadline noon |
| 112 | Design Track |
| 118–119 | Hardware Track and event hardware references |

**Schedule as of this snapshot:** Saturday Nov 7, 2026 initial Devpost entry by **11:00 PM** per slides; Sunday Nov 8 final entry by **12:00 PM CST**, judging **1:00–4:00 PM**. Check current Hackerpack/Devpost in case of changes. Demo video and repository may be mandatory; a user-provided Devpost overview reportedly says video ≤2 minutes; recheck current submission requirements rather than guessing.

**Company track count conflict:** Historic 2025 rules/public 2026 site say **2 company tracks**; a more recent pasted 2026 Devpost overview reportedly allows **3**. User wants **8090 + NVIDIA + Northmark** as three company targets. **Confirm eligibility with a HackUTD organizer / actual submission page**; do not silently drop Northmark or promise a 3-company submission before verification.

**MLH categories vs company tracks:** Seven MLH categories identified in 2026 slides: Tiger Data, Solana, SpaceXSI, GoDaddy, Vultr, MongoDB, Gemini. These are prize categories **not** a substitute for the selected third company. ElevenLabs/DigitalOcean appeared in provisional pre-event research, **but are not in these 2026 slides**. MLH and general tracks may have separate eligibility; confirm before claiming.

**Special category constraints:** Spacetime (2026 slides p. 50) requires its backend to power primary app functionality; *not chosen* as third sponsor. SpaceXSI prize has workflow/tooling requirements beyond merely having an IDE installed—check the current award page if targeting. Solana usefulness must go beyond writing a decorative hash. No need to enter unrelated sponsor challenges such as CBRE, EOG, Goldman, T-Mobile, PNC or Winstead unless team explicitly changes strategy.

**Pre-event work / reused code:** Verify current hackathon rules before relying on preexisting implementation. Research documents and planning are not automatically permission to submit pre-built code. Disclose reused dependencies and AI-assisted coding as required.

---

## 13. What has and has not been decided

### Locked decisions

- Product name: **FactoryOS**.
- Concept: information reliability + operational coordination + **verified legacy modernization**.
- 3 company targets: **8090, NVIDIA, Northmark** (submission limit still needs organizer confirmation).
- **Three** team members, with fixed initial ownership in Section 6.
- Current physical kits: ELEGOO UNO R3 starter + 37-in-1; use USB-to-laptop gateway, not assumed ESP32.
- Bring both physical sensor readings and existing/real API data into analysis.
- **Nemotron** does genuine tool-using investigation/orchestration; **Gemini** does final structured AI recommendation; deterministic policy/human review govern safety and authorization.
- Jira + Slack + GitHub are welcome, meaningful MVP integrations (not a sign of lack of originality).
- Solana desired for trust/security (verification/smart approvals; rewards and payments optional), but must not derail P0.
- Prefer a polished, memorable visual demo and aggressively pursue legitimate MLH/hardware awards without fake functionality.

### Not yet verified / do not assume

- Any live source code, GitHub repository, deployed app, or tests exist.
- A Nemotron key/model endpoint, Gemini key, Jira project, Slack workspace, cloud, or Solana wallet is connected.
- Real Arduino wiring/serial stream functions yet.
- Northmark uses the particular toy legacy app or has a specific current production defect.
- The third company track is actually allowed in Devpost.
- The precise current sponsor/MLH judging requirements beyond the supplied slides.
- Which teammate owns a particular personal name or device; use Person 1/2/3 until assigned.
- Production-grade cryptographic guarantees, calibrated AI confidence, or ability to control a real data center.

---

## 14. Exact next actions for a fresh AI session

1. **Read this handoff and the team's latest source files, if provided.** If no repository exists, suggest the minimal shared repo structure and schema version. Do not ask what the whole project is.
2. Determine **which of the P0 modules already exist** (only if that is not clear from uploaded code or user status). A single focused question is okay; don't request a redundant project recap.
3. **Help Person 1** first with telemetry parser + sample events + deterministic mismatch logic + FastAPI endpoint. Provide runnable code and a curl/PowerShell test.
4. **Help Person 2** in parallel with legacy fixture, regression tests and genuine Nemotron tool-calling API. Use structured tool results and code references; then Gemini review.
5. **Help Person 3** with React dashboard wired to exact v1 contract, actual Jira+Slack integration, UI statuses, and approval panel.
6. Integrate as soon as a basic event can flow through all three systems; don't wait until final polish.
7. Add priority MLH data hosting / blockchain extras **after** sponsor-facing P0 is complete or in narrowly scoped parallel tasks that cannot block it.
8. Verify official submission rules and build the demo video/Devpost before deadlines.

### Copy/paste prompt to give another agent

> We are a **3-person** team at **HackUTD Zero Day 2026**, building **FactoryOS**. Read `FactoryOS_AI_Agent_Master_Handoff.md` completely and treat it as the current source of truth. We target **8090.AI + NVIDIA Nemotron + Northmark**, with a hardware integration using **ELEGOO Arduino UNO R3** and relevant MLH awards. Nemotron must be a real multi-step tool-using agent; Gemini reviews and returns the final AI recommendation; Jira/Slack coordinate incidents; a representative legacy monitoring program gets a tested fix; optional Solana verifies approvals/repair evidence. Preserve the API contract and 3-person ownership. Do not restart brainstorming, assume our hardware is an ESP32, or present simulations as completed integrations. **Continue from the code/status I provide next.** Your first job is to identify the next smallest working, testable increment and help implement it immediately.

---

## 15. Source inventory, provenance and historical context

### Materials provided in this project conversation

- **`Pasted text(1).txt`** — user-uploaded FactoryOS architecture/flow with physical/digital inputs, information reliability, Nemotron, Jira/Slack, legacy modernization, testing, deployment and optional Solana. The latest user request explicitly asked to split that plan between three people.
- **`FactoryOS_3_Person_Team_Plan.pdf`** — four-page latest three-person plan. This handoff preserves its responsibilities, endpoints and integration milestones.
- **`HACKUTD26Slides.pdf`** — primary provided event challenge statements and award/slides references.
- **Hardware photos** — ELEGOO UNO R3 starter + 37-in-1 kit. The parts pictured guide feasible hardware selection.
- **`HackUTD_2026_Complete_Research_Package_v2.zip`** — historical winner/strategy package. Contains `HackUTD_2026_Master_AI_Handoff_v2.md`, `HackUTD_2026_Master_Winning_Playbook_v2.pdf`, sponsor interview questions and notes. That *earlier* master handoff is pre-event and does **not** supersede the FactoryOS decisions in this file.
- Eight specifically discussed HackUTD 2025 Devposts: Hyperlynx, HarmoniQ, UpGuardian, Stamped, VisionScout, DataDriver, NLB and PoyoLabs. Key implementation lessons are summarized in Section 11; detailed case studies are in the prior research package.

### Project narrative in one sentence

**FactoryOS turns potentially late, conflicting or misleading data center information into a trustworthy, coordinated technician response, and when old monitoring software is responsible, it helps modernize and verify the software fix — with real AI tool use and optional cryptographic proof.**

### Last instruction to receiving AI

**Be fast, grounded, and practical.** This is a timed hackathon. Prioritize an actual successful end-to-end incident, transparent evidence, a clear demo, and a submitted project over polishing features nobody can verify. Bring forward the user's willingness to use existing automation tools and pursue creative additional categories, but keep the primary demo coherent.
