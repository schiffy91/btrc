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

Focused qualification passed on source `5594563d925ba55f9755c837d13d0a6394ef265d`:
unchanged original 5aa source under the actual inherited option reproduced the
two exact usage failures. The candidate passed all 84 checks: 61 skip-ledger and
23 coordination cases, with zero failures, errors or skips. Actual collection,
JUnit and skip-ledger identities agreed; source/tool/archive/log and nested
artifact inventories closed unchanged, and all eight process groups were reaped
and absent. The existing two-worker child still explicitly uses loadgroup.

Result `skip-ledger-child-env-5594563d-attempt-1/result.json` SHA256:
`c394967badaa58cb72a4ac5e91e0c2eb74fbe78a005f8cc2c3760d5c27ac70b7`.
Independent audit SHA256:
`2c837e02ed890b32a0771e3366f7422eba967ef1098a24c9ea87298a908177a3`.
This report-only follow-up preserves the qualified test bytes. Full final hosted
qualification remains required; publication is held until an allocated CI slot.
