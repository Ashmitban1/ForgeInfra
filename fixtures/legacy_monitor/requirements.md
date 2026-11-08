# Independent monitoring requirements for the controlled fixture

These are team-authored demo requirements, not Northmark production policy.

1. Temperature strictly above 35 degrees Celsius requires WARNING.
2. Temperature exactly 35, or lower, with no cooling fault remains NORMAL.
3. An explicit cooling_fault=true requires WARNING even below the temperature threshold.
4. High temperature combined with a cooling fault still requires WARNING.
5. Preserve the device identity, observation timestamp, and source-content revision in output.
6. Treat the cooling fault as a simulated equipment-failure input in this demo.
7. Monitoring repair does not repair equipment; continued fault input must still warn.
8. Keep the original version reproducible and verify a separate candidate before human review.

Acceptance expectations are independently authored in
tests/modernization/test_repair_requirements.py and must not be changed to fit a patch.
