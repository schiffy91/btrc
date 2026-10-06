<!--
Packet report for a CODEX.md unit or WORKSTREAMS.md packet (§3.7). Title the PR `[CX-…] <packet title>`
(Claude's lanes use `[CL-…]`) and open it as a draft against `main`: the draft PR is
for CI only, and Claude integrates it (§3.8). Fill this in as the work proceeds.
-->

Packet: CX-…  <title>                 Branch: codex/…   Base: <main sha, or the base packet's branch when stacked>

## Owned paths

<copied from the unit in CODEX.md, or from the packet in docs/workstreams/codex.md>

## Commits

- <sha> <subject>

## Tests

Every command run, with passed / skipped / failed counts, per frontend where it applies:

- `nix develop --command python3 -m pytest src/tests/python/test_x.py -q -rs` → 41 / 2 / 0 (python), 41 / 2 / 0 (selfhost)

## CI

Queued run ids are fine at handoff; Claude reads the results.

- ci.yml run <id>: green | red (<job>) | queued
- macos.yml run <id>: …
- windows.yml run <id>: …
- <lane workflow (Claude adds it, D28)> run <id>: …

## Skip gate

- skip-reports jobs green (run ids); rules added: <rule ids> (`fragment:` commit)

## Acceptance

Copied from the packet, each item ticked with evidence:

- [ ] … — evidence: <run id / log line / count>

## Fragments and derived files

- `fragment:` <file> <what>
- `derived:` <regenerated outputs>
- `btrc.symbols` owner-line diff (root modules, §3.4)

## Catalog rows changed

- <catalog shard / row ids, or "none">

## Compiler requests

```text
REQUEST(<target>): <one line>
Repro: <minimal .btrc or command; show both frontends where relevant>
Expected / actual: <…>
Blocks: <which steps of this packet>
Workaround in this branch: <none | what, and how it is removed later>
```

## Deferrals and stand-in evidence

- …
