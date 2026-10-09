# Nested skip-ledger test options

The exact 5aa macOS unit job 113637920900 (run 37873882641) ended with
10,148 passed, 227 expected skips, and two failures. Both serial nested suites
disable xdist, but inherited the unit workflow's `PYTEST_ADDOPTS=--dist=loadgroup`.
Pytest rejected that option before writing their expected ledger. This was not
a GUI lease failure or compiler launch failure. The job's merge checkout tree
86839dc7a4ead26a2d5d48319da0b176b46ea907 matches the published head.

The existing `_run_inner` test helper removes inherited `PYTEST_ADDOPTS` from
its copied child environment. Explicit child arguments remain authoritative;
the two-worker case requests loadgroup explicitly. Existing collector and
injected-skip tests now inject the actual hostile parent option. All original
ledger, capability, expected/unexpected skip and gate assertions remain. No
workflow, global scheduler, skip classification, denominator or timeout changes.

Evidence: `pr68-5aa-macos-unit-failure/audit.json` SHA256
`fdd04b1a0fd71dfdcf2195653d6a1eef81249dc4e8f666ed4f85442df7a03d36`;
artifact 11596511387 SHA256
`9e0de5eec778dd8290d400d208f5728d416d2b5d17f25eb62bf583e8b1ece35a`.
No unit JUnit artifact was advertised; the original log and main unit ledger
are retained. The generic eight-pass nested ledger is not the unit denominator.

Focused qualification is prepared, not executed: unchanged original source
with the actual inherited option must reproduce the two exact usage failures;
candidate full skip-ledger and coordination suites must pass without skips or
errors. Full final hosted qualification remains required.
