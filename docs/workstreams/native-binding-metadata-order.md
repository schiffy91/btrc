# Native binding metadata table ownership

Before this repair, the self-hosted manifest parser attached a child table to its current arbitrary table block. Legal TOML that places `[[native.sources]]` between a binding and its callback metadata consequently fails, while the Python reference accepts it. The observed Range fixture failure is retained under `/private/tmp/btrc-audit-repair/macos-range-current-f75-r4/`; its original and reordered manifests have identical parsed TOML (canonical SHA256 `49a2c3b894dcd68c943535480be6b3a55bf9c6d59993e8648ba109fbcaa78566`).

This packet owns the self-hosted package parser and existing paired package/callback tests. It retains the most recent binding array item independently of the current table cursor, route every binding child family to that item, and preserve missing-owner, unknown-table and duplicate validation. No Python production, generated ABI, native provider or language changes are intended.

The fixture-only checkpoint precedes the production correction. New fixtures exercise unrelated source/framework/package tables, newest-array-item ownership, duplicate and missing-owner rejection, and an actual native callback invocation using the existing paired compiler/native test owners. The baseline and fresh self-host qualification are recorded below; source review alone is not runtime evidence. Full final-tree gates remain required for integration.

## Retained baseline

Fixture-only `0d466d8d`, unchanged f75 production, and native f75 binary `60639d608d3e09bec4dcdfaf76d3575cdeb135b04d2102858cf15a9f089efbf3` were exercised under the gate/build locks. `/private/tmp/btrc-audit-repair/native-binding-metadata-order/baseline-1` retains original commands, logs, JUnit, exact source inventory and tool hashes. All children were reaped and final source/tools remained unchanged.

The 16 manifest cases had 11 failures and five passes: ten legal reordered/latest-owner cases were rejected by the self-hosted parser, and the wrong-latest-binding negative reached the old missing-owner diagnostic rather than the required selected-symbol diagnostic. The four real callback cases had two reference native passes (plain and ASan/UBSan) and two self-hosted metadata-resolution failures. There were no skips or setup errors.

The minimal production correction preserves a separate latest-binding reference while retaining every existing child-family dispatch/validation. Flat property-table duplicate tracking is now per binding, so a separated repeated table cannot become accepted merely because the table cursor moved. The fresh compiler and paired proof below qualify this correction.

Independent source/fixture review is clear. Ruff, BTRC formatter and `git diff --check` pass. The repaired paired runs are recorded below.

## Fresh candidate qualification

Production `6b83cf1b1ffe1600d8ade721cb1e28d2ecca1902` was archived and built through the unchanged retained compiler-build recipe using the original Nix shell and Clang 21.1.8. The build authenticated the exact eight source/test donors versus the retained 3974 baseline (five already-qualified f75 donors plus this parser and two test files). Its final source/tool inventories remained unchanged; all owned process groups were absent after completion.

- Build receipt: `~/.cache/btrc/plan-consolidation-2026-10-07/native-binding-metadata-order-6b83cf1b/result.json`.
- Fresh binary SHA256: `53839021816bd41f9185fd1ec2c80a0c60b10e2f5171bbc72d513f94760e85c4`.
- Generated compiler C SHA256: `5faf603757366b0fe2aa990b5ce4d1ae732371b871d2c60aaeeb9afc85d80435`.
- Paired proof: `/private/tmp/btrc-audit-repair/native-binding-metadata-order/candidate-1/result.json`, SHA256 `cbc648afd4e5ebf9f8bbaacc089c3438e4363fe55df8ba05b54ca62e6078f33c`.

The same 16 manifest cases all passed (13.46 seconds), including legal reordered metadata, latest-array-item selection and rejection guards. The same four real native callback rows all passed (3.86 seconds): reference/selfhost, each plain and ASan/UBSan. No skips, errors or failed assertions were admitted. The proof authenticated the build inventory and interpreter, retained original per-process deadlines, and verified source/tools and receipt/adapter hashes after both stages. All child groups were absent and gate/build locks released.

This qualifies the bounded metadata ownership repair. It does not qualify the entire native manifest surface or repair the independent foreground-dependent Range pointer/Select keyboard failures. Full final-tree gates, bootstrap and integration remain pending; no publication was performed by this packet.

Independent result review rehashed the exact 20 test identities, logs and recorded pins and found no failure/error/skip. The proof's `final_tools` field covers only its recorded pin set: Python, native reader, selfhost binary, scripts and build receipt/inventory. The original native test helper selects absolute `/usr/bin/clang` with `apple_environment()` and the host SDK. It did not independently hash Apple clang or the inherited shell profile at both ends. `candidate-1/post-run-native-tool-association.json` records the honestly timed later association, including profile equality to its pre-existing retained hash; this is not retroactive before/after tool evidence. The original passing receipt is unchanged, and no repeat was performed merely to manufacture earlier hashes.
