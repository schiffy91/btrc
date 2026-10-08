# macOS GUI scheduling and report identity

Source: `37f0a63cb1399685265e04737cf116250ce69103`, based on exact `00e4537925211ea2e217171fb32ccbbef10840c8`. No publication or hosted rerun occurred.

Session 41915 completed with status 0. The original-source counterfactual, with only the candidate coordination test file overlaid, completed all eight inner cases successfully on three real xdist workers, then failed exactly at `AppKit cases were scheduled onto competing workers` (`3 == 1`). This is the intended scheduling RED, not a setup or child failure.

Candidate qualification passed all 84 collected cases: the complete 23-case coordination suite and 61 existing skip-ledger cases. There were zero failures, errors, or skips. The tests include three-worker affinity, independent-session kernel exclusion, ordinary work progressing while the GUI lease is held, copied report serialization, literal group text inside parameter identities, canonical JUnit and skip-ledger identities, cross-runner coverage lookup, and four malformed-mapping rejection controls.

The exact collection matched JUnit. Final source bytes/modes and pinned tools were unchanged. The only generated files within source archives were the recorded child skip ledgers. All eight runner-owned process groups were absent and their leaders reaped. The gate is released.

Evidence: `/Users/alexanderschiffhauer/.cache/btrc/plan-consolidation-2026-10-07/macos-gui-scheduling-37f0-attempt-1/`.

- `result.json`: `e1b95fcb0c1e08df6fc8d9b45a8478bb6dc3013749f40f6403a4d1117b7a7db9`
- Baseline JUnit: `66dec33896444eabc12744d8496c10126ffc5212c26507cbb135e4b727454d66`
- Candidate JUnit: `e3ac9452c0ae0a8afa338973f8403c4c92a76095a3f184477453b5f996d2df80`

This is a focused process-scheduling/reporting proof. It does not run native AppKit or the full hosted GUI roster and does not establish that the hosted duration problem is resolved. The original native-GUI roster, platform skips, three workers, kernel lease, per-test limits and 90-minute job bound remain unchanged. Future full qualification must preserve the historic roster as a subset if legitimate additional tests increase its total. Controller-synthesized worker-crash reports remain raw failures because they bypass worker serialization.

Independent retained-evidence audit has been requested and is pending.
