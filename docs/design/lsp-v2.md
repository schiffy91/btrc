# LSP v2 — Fast and Correct Editor Tooling

Status: IMPLEMENTED (2026-06-12). Companion to `precompiled-stdlib.md`.

> Implementation note: P0-P2 all landed. Per-file units live in
> `src/devex/lsp/units.py` + `workspace.py`; analyzer provenance/structured
> diags in `analyzer/core.py`; the seeded stdlib base and snapshot cache in
> `workspace.py`. Measured after: keystroke->diagnostics 0.3 ms (hello),
> 4.6 ms (game + 12 imported units); hover/definition/references/semantic
> tokens <=0.5 ms warm; LSP suite 171 s -> ~2 s. One latent compiler bug was
> found and fixed along the way: `_upgrade_class_type` mutates shared ASTs,
> so re-analysis reported its own pointer upgrades as "Redundant pointer"
> errors - synthesized types now carry an `auto_upgraded` stamp.

## 0. Symptoms, measured

All numbers from the real pipeline (`compute_diagnostics` exactly as the
server calls it), Python 3.13, repo at 40db541.

| What the editor does | Cost today | Why |
|---|---|---|
| One keystroke (`didChange`) | **478–548 ms, blocking** | full stdlib re-lex + re-parse every time (`use_ast_cache=False`); 31k tokens, 122+ decls |
| `semanticTokens/full` | **693–1019 ms** | classifies all ~31–34k resolved tokens to emit 3–57 for the user file |
| `definition` (worst case) | **685 ms** | `DefinitionMap.from_ast` rebuilt per request; `_resolve_name_pos` scans 31k tokens per decl (~3.8M ops) |
| All of the above | **serialized on one thread** | pygls sync handlers run on the event loop; no debounce, no cancellation |

A short typing burst queues N×(550 ms + 1000 ms) of blocking work → the
observed 5–20 s before a hover or cmd-click responds. On a project whose
imports live on Google Drive, `_resolve_traced` re-`open()`s every imported
file **per keystroke**, adding fileproviderd latency on top.

Correctness failures, each reproduced:

1. **Glob imports comment out the file.** The TextMate grammar's
   `comment.block` rule sees `/*` inside `import ./semu/core/*;` and opens an
   unterminated block comment — *the entire rest of the file renders as
   comment* (verified with vscode-textmate; matches the "everything gray
   italic" screenshot). This is why "coloring rarely works": the always-on
   TextMate layer is dead in any file using directory imports, and the
   semantic-token layer that could paper over it takes ~1 s and is usually
   queued.
2. **Unmapped positions silently alias into the stdlib.** Features map editor
   position → concatenated-resolved-source position by scanning
   `source_positions` for a matching `(file, line)`. Import lines (and
   anything else not present in resolved output) have no entry, so the *raw
   document position is reinterpreted as a resolved position* — which lands
   inside the concatenated stdlib. Hovering an import line showing
   `class ListNode<T>` is exactly this. Same failure class hits cmd-click:
   wrong file opens, or nothing.
3. **Heuristic resolution instead of analyzer truth.** `resolve_variable_type`
   re-scans the AST per request with line-range scope guessing;
   `resolve_chain_type` walks tokens backwards through `.`/`(`/`)`;
   `find_enclosing_class` guesses class extent from max member line;
   `find_closing_brace_line` counts braces *including those inside strings and
   comments*. These are wrong under shadowing, nested functions, lambdas,
   generics, and multi-line constructs — the analyzer already knows the right
   answers and we don't ask it.

## 1. End state

A keystroke costs ~15–50 ms of *background* work. No request ever waits on a
recompile. Positions are always native to their file — there is no
resolved-space mapping to get wrong.

Latency budgets (the contract, enforced by tests):

| Operation | Budget |
|---|---|
| Syntax coloring (TextMate) | immediate, correct with glob imports |
| hover / definition / references | < 50 ms p95, **during** a typing burst |
| semanticTokens | < 50 ms (served from snapshot) |
| diagnostics after typing pauses | < 500 ms |
| server cold start | < 2 s (stdlib pre-parse from disk cache) |

Architecture:

```
                ┌────────────────────────────────────────────┐
                │ Workspace                                  │
                │   FileUnit cache: path → (hash, tokens,    │
                │     ast_decls, parse_errors)   ← per file  │
                │   StdlibUnits: parsed once at startup      │
                │   import graph: file → imports             │
                └────────────────────────────────────────────┘
 didChange ──► debounce 200 ms ──► worker thread:
                 re-lex+parse ONLY the edited file (~5–20 ms)
                 compose Program from cached decl lists (list concat)
                 analyze (~35 ms now; ~5 ms with pre-analyzed stdlib)
                 build Snapshot { class_table, occurrence index,
                                  DefinitionMap, semantic tokens,
                                  line→token index, diagnostics }
                 publish diagnostics; swap atomic snapshot pointer
 hover/def/refs/semanticTokens ──► read latest Snapshot (dict lookups, <5 ms)
```

Key invariant: **every token and AST node lives in its own file's
line/column space, always.** Cross-file navigation returns `(file, line,
col)` directly off the per-file units. The `source_positions` mapping layer
— and its entire bug class (#2) — is deleted from the LSP.

## 2. Atoms (one contract each)

| # | Atom | Contract | Proven by |
|---|---|---|---|
| A1 | Grammar `import` rule | An `import …;` line never opens a comment/string scope; path, `std.`, `{a,b}`, `*`/`**` get scopes | vscode-textmate fixture incl. the semu repro |
| A2 | `FileUnit.parse(path, text)` | text → (tokens, decls, parse_errors), positions native to the file; pure function of content hash | unit tests; property: reparse(idem) |
| A3 | `Workspace.invalidate(path)` | edits invalidate exactly that unit + composition; imports' cached units survive | unit test with 3-file graph |
| A4 | `compose(active_file)` | ordered decl list = stdlib units (minus skip-if-redefined) + imported units + active unit; O(total decls) list concat, no re-parse | golden: same analyzer result as today's concatenated pipeline on the test corpus |
| A5 | Analyzer structured errors | `errors: list[Diag(file, line, col, msg)]` — file comes from decl provenance (top-level decl → owning unit); string form kept for CLI | analyzer unit tests; CLI shows `file:line:col` (also fixes today's resolved-space CLI positions) |
| A6 | Occurrence index | during analysis, every resolved identifier occurrence in the *active* file records `(line, col, len) → symbol(def_file, def_line, def_col, kind, type_repr)` | hover/def/refs tests become table lookups; consistency fuzz: every IDENT token either indexed or diagnosed |
| A7 | Snapshot | immutable; built entirely on worker thread; features read-only | race test: 100 hovers during 100 edits, no torn reads |
| A8 | Debounce + cancel | new edit cancels in-flight analysis; trailing edge ≤ 200 ms | simulated stdio session, assert ≤ 1 analysis per burst |
| A9 | Server threading | `did_change` handler returns < 1 ms; analysis on `ThreadPoolExecutor`; feature handlers never compute pipelines | stdio harness latency assertions |
| A10 | Semantic tokens from snapshot | emitted only for active-file tokens; classification from occurrence index (not name-set guessing); served from cache | token-level goldens incl. the cases TextMate can't do |

## 3. Cascades

- A2+A3+A4 → **incremental frontend**: keystroke work = parse(one file) + analyze.
- A5+A6 → **correct features**: hover/definition/references/rename/semantic
  tokens all read one index produced by the real analyzer. The heuristic pile
  (`resolve_variable_type`, `resolve_chain_type`, `find_enclosing_class`,
  `find_closing_brace_line`, `DefinitionMap` rebuild-per-request,
  `document_position_to_resolved`) is deleted, not patched.
- A7+A8+A9 → **responsiveness**: stale-but-instant answers during bursts
  (VSCode-standard behavior), fresh within 500 ms of pausing.

## 4. Proof in realistic environments (kept as regression suites)

1. **Grammar suite** (extends `ext/test/grammar.test.js`): tokenize a fixture
   mirroring the semu layout (17 glob imports, f-strings, generics); assert
   zero `comment.block` leakage and expected scopes per line. CI-gated.
2. **Stdio protocol harness** (extends `lsp/tests/lsphelp.py`): drive the
   *real server process* over stdin/stdout — didOpen, 30-keystroke burst,
   interleaved hover/definition/semanticTokens — assert latency budgets and
   answer correctness against a multi-file fixture project. This simulates
   the editor; it is the test that would have caught every symptom above.
3. **Equivalence gate for A4/A5**: for every `src/tests/**/*.btrc`, composed
   analysis must produce the same diagnostics set as today's concatenated
   pipeline (modulo file-qualified positions).

## 5. Phases

**P0 — stop the bleeding (≈1 day, no architecture change)**
- A1 grammar fix. Fixes "coloring rarely works" on its own, instantly.
- A8/A9: debounce + worker thread + cancellation in `server.py`.
- Cache per-snapshot what's rebuilt per-request today: `DefinitionMap`,
  `navigation_tokens`, semantic tokens, a line→tokens dict (kills the O(31k)
  scans and the 3.8M-op `_resolve_name_pos`).
- Effect: editor never freezes; hover/def/coloring answer in <10 ms from the
  last snapshot; diagnostics ~700 ms after pause. Perceived ~20–50×.
- Risk: near zero. All additive.

**P1 — per-file units (the correctness fix, ≈3–5 days)**
- A2–A5: FileUnit cache, composition, analyzer provenance + structured
  errors. Stdlib parsed once at startup (reuse `_cached_stdlib_decls`).
- Delete LSP resolved-space mapping; all positions native. Bug class #2 dies.
- Keystroke cost: ~10–20 ms parse + ~35 ms analyze, off-thread.
  (Measured: analyze(stdlib)=31 ms, analyze(user-only)≈0 ms, cached-stdlib
  parse path total = 50–69 ms vs 478–548 ms today.)
- Risk: medium — analyzer error-contract change touches CLI + LSP tests
  (many `lsp/tests/test_final*.py` lock in resolved-space behavior and will
  need fixture updates, gated by the equivalence suite).

**P2 — analyzer-truth features + polish (≈1 week)**
- A6 occurrence index; rewrite hover/definition/references/rename/semantic
  tokens as lookups. "Completely correct" lands here (bug class #3).
- Pre-analyzed stdlib snapshot (schema-versioned JSON class/function tables): analyze drops
  ~31 ms → ~5 ms; aligns with `precompiled-stdlib.md`.
- Semantic token deltas (`full/delta`); `workspace/symbol` from the unit
  cache; cross-file references via import graph.

End-to-end: per-keystroke compute 550 ms → ~15 ms (≈35×); worst-case request
during a burst 5–20 s → <50 ms (**100–400×**); plus static coloring goes from
broken to always-on.

## 6. Non-goals / rejected

- **Rewriting the LSP outside Python** (native, or self-hosted btrc): once
  the model is per-file + indexed, Python costs ~15–50 ms per edit — far
  under perception. Rejected for now; the FileUnit boundary is exactly what
  a future btrc-hosted server would port anyway.
- **Tree-sitter highlighting**: VSCode's native stack is TextMate + semantic
  tokens; fixing those is cheaper and works in every VSCode distribution.
- **Editing `ext/launch.ts` resolution order**: `nix develop` cold-start cost
  is real but one-time; out of scope here (document `btrc.pythonPath` as the
  fast path).

## 7. Open questions for review

1. P1 keeps "active file + its import closure" as the analysis unit (like
   today, minus re-parsing). Project-wide always-on indexing (clangd-style
   background index of all .btrc files) is deferred to P2+ — acceptable?
2. Analyzer structured errors: extend `AnalyzedProgram` with a parallel
   `diags: list[Diag]` (string list kept for compatibility), or break the
   string contract in one go?
3. Budget enforcement in CI: hard-fail latency assertions can be flaky on
   loaded runners — propose generous CI budgets (3× targets) with tight
   budgets verified locally via `make bench-lsp`.
