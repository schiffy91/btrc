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

Validation is pending. Parent gate work has priority: this packet will perform
no compiler/native build, test or measurement until the parent assigns a slot.
The first proof must inspect actual emitted cleanup, retain AST string contents
after token-owner destruction, and preserve lexer/parser failure cleanup.
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
lexer without releasing that outer AST. This describes source/lowering intent;
actual emitted cleanup still needs verification under both frontends.

Static checks actually performed:

- Current reference lexer/parser accepted the full modified Pipeline source.
- Canonical BTRC formatter check passed for Pipeline.btrc.
- `git diff --check` passed.

No semantic analysis, transpilation, native execution, benchmark or full gate has
run for this candidate. The source revision is an implementation checkpoint, not
a performance-qualified change.

## Scheduled proof and regression commands

The parent selects a free build/gate slot, adequate disk, source-matched compiler
inputs and the existing qualified environment. First generate the compiler's C
with the reference frontend, then use that built candidate for the self-hosted
generation/bootstrap path. Inspect the actual `CompilerPipeline_compileResolved`
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
not a process regression. Preserve phase marks and compare whole-process retired
instructions and peak footprint in the separate quiet-host campaign, with the
same named compiler, pinned workload, alternating repeated pairs and `--jobs 1`.
No speedup, current-byte saving, M11 acceptance or Linux-regression explanation is
claimed until those measurements run.

This path does not retry the rejected substring-bound scan, pointer-length
cache, shared-empty-vector, TLS, optimization-level or concurrent-gate changes.
Other kept cyclic AST/IR graphs are outside this change.
