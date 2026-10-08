# Native binding metadata table ownership

The self-hosted manifest parser currently attaches a child table to its current arbitrary table block. Legal TOML that places `[[native.sources]]` between a binding and its callback metadata consequently fails, while the Python reference accepts it. The observed Range fixture failure is retained under `/private/tmp/btrc-audit-repair/macos-range-current-f75-r4/`; its original and reordered manifests have identical parsed TOML (canonical SHA256 `49a2c3b894dcd68c943535480be6b3a55bf9c6d59993e8648ba109fbcaa78566`).

This packet owns the self-hosted package parser and existing paired package/callback tests. It will retain the most recent binding array item independently of the current table cursor, route every binding child family to that item, and preserve missing-owner, unknown-table and duplicate validation. No Python production, generated ABI, native provider or language changes are intended.

The fixture-only checkpoint precedes the production correction. New fixtures exercise unrelated source/framework/package tables, newest-array-item ownership, duplicate and missing-owner rejection, and an actual native callback invocation using the existing paired compiler/native test owners. Tests and fresh self-host qualification are pending; source review is not runtime evidence. Full final-tree gates remain required for integration.
