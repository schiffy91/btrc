# Compiler token lifetime: bounded ownership change

## Claim (2026-10-08)

Owned paths:

- `src/compiler/btrc/pipeline/Pipeline.btrc`
- `docs/workstreams/compiler-token-lifetime.md`

Branch: `codex/compiler-token-lifetime`, based on
`06c3923a10671534d5fe16870c51ca87495297c1`. The parent integrator assigned these
paths under PLAN.md D29 after independent read-only review. This is a local
claim; no PR or CI dispatch is claimed. The previous runbook branch remains at
`0fec0960`, additionally preserved by `archive/runbook-before-token-lifetime`.

Scope: retain the parsed AST in the existing pipeline owner and end its local
lexer/parser/token-vector ownership immediately after successful parsing.
Preserve diagnostic rendering, phase marks, managed strings, subsequent AST
ownership and existing intentional keeps. No parser API, runtime, generated
source, worker protocol, artifact-cache or Python result API change belongs here.

Baseline: read-only inspection confirmed all three token owners currently live
in `compileResolved`'s function scope. Both lowerers emit managed releases at a
lexical block exit; the AST stores managed string aliases but no Token objects.
`ModuleUnitProgram` retains AST/analyzer/resolved sources, not the token owners.
The historical October 1 census attributes 98.5 MiB of retained memory to this
token stream. That is neither a current measurement nor an expected speedup.

Bounded validation ran in the parent-assigned single agent build lane, recorded
below. Parent gate work retains priority. Remaining proof must directly observe
token destruction and retain AST string contents under compiler sanitizers.
Full-process instructions and peak memory require a separate quiet-host lane;
shorter source scope alone does not qualify a performance improvement.

## Implementation checkpoint

`compileResolved` now declares its AST owner outside one lexical block containing
the existing lexer, token vector and parser. Successful parsing assigns the AST
to that owner. Lexer/parser failures still return the same positioned diagnostic
from the same phase, and every later stage is unchanged. No explicit release or
additional AST allocation was introduced.

The empty managed declaration is deliberate: self-hosted statement lowering
initializes it to NULL before cleanup registration (`Statements.btrc:531–535`),
then registers it as an owned lexical slot (`:591–610`). Therefore failures before
assignment can clean it safely, while successful assignment transfers the parse
result to the outer owner. The block's normal exit releases parser, vector and
lexer without releasing that outer AST. Both frontends' actual emitted cleanup
now confirms this ordering, as recorded below.

Static checks actually performed:

- Current reference lexer/parser accepted the full modified Pipeline source.
- Canonical BTRC formatter check passed for Pipeline.btrc.
- `git diff --check` passed.

The implementation source is `69ca0f17eb95aaf5213e93d9b134c6e15a30d3b9`.
It remains a candidate, not a performance-qualified change.

## Bounded qualification (2026-10-08)

Host: Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0. Evidence lives outside Drive at
`~/.cache/btrc/plan-consolidation-2026-10-07/subagent-delivery/token-lifetime/69ca0f17/`.
`build-result.json` and `validation-result.json` retain exact commands, source,
timestamps, status and logs; `qualified-hashes.json` hashes the compiler inputs,
binaries, emitted excerpts, scripts, diagnostic subprocess output and test
reports. `qualification-summary.json` records counts and limits.

The retained baseline is the integrator's qualified `06c3923a` MacOSMain build,
with receipt and original build log copied alongside its C and binary. The
baseline binary SHA256 is
`85c4029079568b3a73fbd6853148d5b1e8038a05224e6e75c4ccd3768511e1c3`.
Both baseline and candidate use Nix clang 21.1.8, strict C11 and `-O2`; this is
not an Apple-clang measurement. Candidate binary SHA256 is
`e93333767a73c19c449b454563a0d06dbce0e9e2a774d7bf06e413a34c3a9258`.

Results:

- Reference MacOSMain transpilation and strict native compilation passed.
- The candidate successfully transpiled its own MacOSMain source once. This
  emitted C was inspected, but was not compiled into another native stage;
  a bootstrap fixed point is still pending.
- A scratch harness reused the existing production-driver lexer/parser
  assertions with the already-built candidate: **120 passed, zero skipped**.
  It preserves subprocess commands, return codes and original diagnostics in
  `diagnostic-processes.jsonl`. This covers selected production boundaries,
  not the full inspection-driver modules; those were not rebuilt here.
- The normal corpus runner executed `FstringEscapes`, `StringCharEscapes`,
  `ExceptionCleanupScopeMarkers` and `SwitchCaseScopeArc` through both
  compilers: **8 passed, zero skipped** (2,028 other cases deselected).
- The existing scope/capture parity module passed **18 checks, zero skipped**,
  including paired semantic diagnostics and native execution.
- The two literal programs produced byte-identical C and stderr through the
  retained baseline and candidate production binaries, with strict imports and
  caches disabled. Both versions' outputs are retained.

The baseline, reference-emitted candidate and self-host-emitted candidate
`compileResolved` functions and parse-boundary excerpts are retained separately.
Both candidate outputs initialize/register the outer program slot before the
inner cleanup mark, hand the parsed AST into that slot, construct failure
diagnostics before cleanup, and clear/release parser, vector and lexer before
source stamping. The successful inner exit does not release the outer AST.
An independent read-only reviewer confirmed source and both emitted sequences
without finding a blocker. No compiler sanitizer or instrumented token census
has run; native application tests do not substitute for that remaining proof.

Scheduling durations were approximately 193 seconds for reference emission,
179 seconds for native compilation, and 89 seconds for bounded validation
(including 69 seconds for self-transpilation). These were concurrent with
integrator gate preparation, not quiet-host performance measurements. All
agent build/test processes ended at 2026-10-07 23:28:12 UTC, releasing the lane.

## Reproduction and remaining qualification

The parent selects a free build/gate slot, adequate disk, source-matched compiler
inputs and the existing qualified environment. First generate the compiler's C
with the reference frontend, then use that built candidate for the self-hosted
generation/bootstrap path. The retained `build.py` and `validate.py` reproduce
the bounded run above through `withlock.sh btrcc-build nix develop --profile
~/.cache/btrc/gcroots/harmonize-dev --command python3 <script>`. That profile used
`/nix/store/35r726j0hx21698i9p7ry53l1afprc84-python3-3.14.6-env/bin/python3`.
The validation script requires clean implementation revision `69ca0f17`; later
documentation commits do not change the production inputs. Inspect the actual
`CompilerPipeline_compileResolved`
body in both emitted outputs: its outer program slot starts NULL; the successful
parse assigns an owned AST; parser, tokens and lexer are each cleared/released
before `HostedAbiRepository_stampProgramSources`; the program is not released at
that inner boundary. Also inspect the lexer-failure and parser-failure exits.
Do not count braces or a source substring as emitted ownership proof.

Use the existing real production-driver regression modules after selecting that
candidate, rather than duplicating a toy parser in a new fixture:

```sh
python3 -m pytest -q src/tests/btrc/test_parser_diagnostics.py src/tests/btrc/test_lexer_diagnostics.py src/tests/btrc/test_scope_capture_parity.py src/tests/python/test_corpus_strict_imports.py --compilers=both
```

The parser/lexer harness includes the production compiler, not just inspection
tools. It covers fail-closed lexing, parse failures, f-string interpolation,
literal token/AST parity and later semantic processing. Existing ARC ownership
runtime/sanitizer tests remain required in the normal suite. The base's known
strict-import audit omission is an independent integrator repair; do not hide or
waive it in this branch. The eventual integrated candidate must pass the normal
paired corpus, bootstrap, C11 and remaining repository gates.

For candidate-specific lifetime evidence, instrument only a scratch emitted
compiler for a bounded run: capture the main parse vector's identity and observe
that vector and its token objects retire before the next pipeline stage. Read
AST names, raw numeric spellings, string values and interpolated expressions
after that boundary, under ASan/UBSan, comparing the application's emitted C,
link plan and diagnostics against each frontend's own baseline. Do not assert
that all Token allocations disappear: conditional resolution and visibility
have their own token owners. No such scratch instrumentation has been made yet.

## Measurement limits

Keep the historical 98.5 MiB retained-memory attribution separate from current
results. AST-managed string aliases remain alive; resolved source and shared
grammar ownership also remain. The mechanism shortens the main token graph's
lifetime, but need not reduce total destructor instructions or return every
freed byte to the OS.

`BtrccPhaseTimer.print` previously preceded function-return cleanup. Moving that
cleanup ahead of analysis makes its cost visible in later phase timing (normally
the visibility interval). A phase increase can therefore be moved accounting,
not a process regression. Both emitted candidates also release the previously
NULL AST slot and call `__btrc_poll_cycles()` when the assignment transfers the
parse result; the former declaration initializer did not add this poll. Its
whole-process cost must be measured rather than assumed negligible. Preserve
phase marks and compare whole-process retired
instructions and peak footprint in the separate quiet-host campaign, with the
same named compiler, pinned workload, alternating repeated pairs and `--jobs 1`.
No speedup, current-byte saving, M11 acceptance or Linux-regression explanation is
claimed until those measurements run.

This path does not retry the rejected substring-bound scan, pointer-length
cache, shared-empty-vector, TLS, optimization-level or concurrent-gate changes.
Other kept cyclic AST/IR graphs are outside this change.
