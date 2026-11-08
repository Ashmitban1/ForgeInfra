// Architecture examples, never runtime operational data. Status reflects this checkout.
export const phases = [
  {
    id: 'observe', title: 'Observe', caption: 'Read the physical signal', icon: 'signal',
    input: 'Sensor + simulated fault switch',
    processing: 'Ingest timestamped readings',
    output: '29.4°C · 54% RH · cooling_fault=true',
    technology: 'Arduino Uno · DHT11 · Python · FastAPI',
    status: 'Implemented locally',
    note: 'Sensor and gateway code exists. The cooling-fault switch is deliberately simulated; FactoryOS does not control cooling equipment. Host CPU/RAM via psutil is a separate planned feed in this checkout.',
    tools: [
      ['Arduino', 'Sensor firmware; verify physical hardware separately.'],
      ['DHT11', 'Temperature/humidity sensor; cooling fault is simulated.'],
      ['FastAPI', 'Timestamped telemetry ingestion implemented locally.'],
    ],
  },
  {
    id: 'detect', title: 'Detect', caption: 'Catch the missed warning', icon: 'compare',
    input: '29.4°C / simulated fault=true',
    processing: 'Compare legacy and independent rules',
    output: 'legacy_missed_fault → incident',
    technology: 'Python · reliability rules · FastAPI',
    status: 'Implemented locally',
    note: 'Detection is independent of AI availability. Live ingestion currently uses the team-authored placeholder legacy function, not Northmark software. MongoDB Atlas is planned in this checkout; canonical incidents currently live in memory.',
    tools: [
      ['Python', 'Team-authored legacy placeholder; not Northmark code.'],
      ['Reliability Engine', 'Independent deterministic mismatch detection.'],
    ],
  },
  {
    id: 'investigate', title: 'Investigate', caption: 'Find the software cause', icon: 'code',
    input: 'Incident evidence + source',
    processing: 'Inspect code; independently review',
    output: 'Example: cooling_fault ignored',
    technology: 'NVIDIA Nemotron · Gemini · tool registry',
    status: 'Awaiting integration',
    note: 'Agent modules are stubs in this checkout. The example is an explanation of the intended investigation, not a model response or successful tool call. Humans retain operational decisions.',
    tools: [
      ['NVIDIA Nemotron', 'Planned tool-based source inspection.'],
      ['Gemini', 'Planned independent evidence review.'],
    ],
  },
  {
    id: 'verify', title: 'Verify', caption: 'Test before you trust', icon: 'verify',
    input: 'Original + candidate + incident',
    processing: 'Run regression tests + replay',
    output: 'Example: NORMAL → WARNING',
    technology: 'Docker · pytest · source diff · snapshot replay',
    status: 'Awaiting integration',
    note: 'The handoff describes a manually authored repair example, not an AI-generated fix. This checkout has no connected repair endpoint or per-incident Docker results. No pass totals are presented as verified. A completed job is not proof of passing tests; passing tests are not approval, deployment, or equipment recovery.',
    tools: [
      ['Docker', 'Planned isolated candidate verification.'],
      ['pytest', 'Tests exist; connected per-incident outcomes unavailable.'],
    ],
  },
  {
    id: 'act', title: 'Respond', caption: 'Connect the human response', icon: 'response',
    input: 'Incident + real Jira URL',
    processing: 'Create ticket; notify responders',
    output: 'Ticket + message; incident stays open',
    technology: 'Jira · Slack · FactoryOS · shared data layer',
    status: 'Notifications implemented',
    note: 'Jira creation and generic Slack connectivity were live-verified separately. The combined adapter is implemented and mocked-tested; a fresh combined live delivery remains unverified. Notifications can run immediately after detection, without waiting for agents or repair. Approval, Solana and deployment are not implemented.',
    tools: [
      ['Jira', 'Real Jira Task creation implemented.'],
      ['Slack', 'Real Slack adapter implemented; state requires provider confirmation.'],
    ],
  },
];

export const personas = [
  { id: 'operator', title: 'Operators', keyword: 'Monitor', icon: 'signal', description: 'Monitor infrastructure', destination: 'Mission Control', problems: [0, 1], route: 'mission' },
  { id: 'responder', title: 'Technicians', keyword: 'Respond', icon: 'response', description: 'Respond to incidents', destination: 'Incident Response', problems: [0, 2], route: 'investigate' },
  { id: 'engineer', title: 'Engineers', keyword: 'Modernize', icon: 'code', description: 'Verify software repairs', destination: 'Modernization', problems: [1, 3], route: 'engineering' },
  { id: 'manager', title: 'Managers', keyword: 'Oversee', icon: 'layers', description: 'Oversee reliability', destination: 'Operations', problems: [1, 2], route: 'operations' },
];
export const problems = [
  ['Missed Alerts', 'Faults go undetected', 'Independent checks'],
  ['Conflicting Data', 'Monitoring disagrees', 'Shared evidence'],
  ['Slow Response', 'Disconnected workflows', 'Connected response'],
  ['Legacy Risk', 'Unsafe software changes', 'Test before change'],
];
