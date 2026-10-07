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
