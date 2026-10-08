# Module finish-reply lifetime candidate

Base: `3974d47bc87851b1ac19b8d2b4bd5022f2d94676`. Branch:
`codex/module-finish-reply-3974`. Integrator-assigned under D29; claim precedes
production commit. Only ModuleUnits.btrc changes production. No token71352,
generic4d930, runtime, wire/cache-key, generated-source or graph-keep changes.

The consumer already acquires an owning local reply and independently copies
record.text through substring. Clearing the consumed vector slot lets the
existing iteration cleanup retire that original reply before the next record,
instead of keeping every original reply beside its copied C text. The local
remains alive through parsing, diagnostics, record/cache serialization and update.
The full batch is still gathered first; initial reply-batch allocation is unchanged.

## Evidence and qualification

Source review was accepted before this isolated candidate. Preparation rechecked
all4496 archived3974 input bytes/Git blobs/modes and the actual completed build:
binary55170f4048b6c976c0857da1498888ff32f87853baa9ca2498a83d3e531ddb30;
generatedC5160f6d8aa64b982556018be7a5117dae41972406d8d2616aea54dbbcfdcdb6e.
Original Clang21.1.8, shell and actual Python identities are preserved in the
retained build-result-amended.json; the initial generated-output admission failure
is retained alongside its truthful amendment, not erased or counted as a pass.

Private preparation: `/private/tmp/btrc-audit-repair/module-finish-reply-lifetime/`.
`baseline-build-receipt.json` SHA 3a8c0c072aaf3c451ca51e9d8cb60b655c46a7ffd002ec8658cf6283951d79c4 projects that authentic build;
`QUALIFICATION.md`, `OBSERVER.md` and `semantics-selection.json` define the next
bounded lane. Existing instrument.py/probe.c/validate.py require actual baseline
retention and candidate destruction at next-record/end boundaries with jobs1/3,
owner PID/ticket checks and identical emitted C. The uninstrumented CatalogMain
comparison process receipt remains to be executed; a build receipt cannot replace it.
The unchanged selected module tests cover worker parity/timing, warm/edit/cache
replay, corrupt stored generations and strict native corpus execution.

Current status: **source-only; no candidate build, lifetime observation, native
semantic qualification, sanitizer result or measurement**. All required full-tree
compiler gates remain pending on the eventual integrated candidate. Historical
73MiB duplicate replies motivate the experiment but do not predict current peak
savings. Whole-program CompileStdlibHeavy does not use this module-unit loop.
D9 quiet measurements must use uninstrumented matched binaries; current-product
<=1.5GiB, time/instruction targets and formal acceptance remain unproved.
