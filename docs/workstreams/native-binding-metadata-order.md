# Native binding metadata table ownership

The self-hosted manifest parser currently attaches a child table to its current arbitrary table block. Legal TOML that places `[[native.sources]]` between a binding and its callback metadata consequently fails, while the Python reference accepts it. The observed Range fixture failure is retained under `/private/tmp/btrc-audit-repair/macos-range-current-f75-r4/`; its original and reordered manifests have identical parsed TOML (canonical SHA256 `49a2c3b894dcd68c943535480be6b3a55bf9c6d59993e8648ba109fbcaa78566`).

This packet owns the self-hosted package parser and existing paired package/callback tests. It will retain the most recent binding array item independently of the current table cursor, route every binding child family to that item, and preserve missing-owner, unknown-table and duplicate validation. No Python production, generated ABI, native provider or language changes are intended.

The fixture-only checkpoint precedes the production correction. New fixtures exercise unrelated source/framework/package tables, newest-array-item ownership, duplicate and missing-owner rejection, and an actual native callback invocation using the existing paired compiler/native test owners. Tests and fresh self-host qualification are pending; source review is not runtime evidence. Full final-tree gates remain required for integration.

## Retained baseline

Fixture-only `0d466d8d`, unchanged f75 production, and native f75 binary `60639d608d3e09bec4dcdfaf76d3575cdeb135b04d2102858cf15a9f089efbf3` were exercised under the gate/build locks. `/private/tmp/btrc-audit-repair/native-binding-metadata-order/baseline-1` retains original commands, logs, JUnit, exact source inventory and tool hashes. All children were reaped and final source/tools remained unchanged.

The 16 manifest cases had 11 failures and five passes: ten legal reordered/latest-owner cases were rejected by the self-hosted parser, and the wrong-latest-binding negative reached the old missing-owner diagnostic rather than the required selected-symbol diagnostic. The four real callback cases had two reference native passes (plain and ASan/UBSan) and two self-hosted metadata-resolution failures. There were no skips or setup errors.

The minimal production correction preserves a separate latest-binding reference while retaining every existing child-family dispatch/validation. Flat property-table duplicate tracking is now per binding, so a separated repeated table cannot become accepted merely because the table cursor moved. This is source implementation only until a fresh compiler and paired tests pass.

Independent source/fixture review is clear. Ruff, BTRC formatter and `git diff --check` pass. A fresh self-hosted compiler and repaired paired runs remain pending.
