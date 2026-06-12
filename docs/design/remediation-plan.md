# btrc Remediation Plan

Status: PROPOSAL (2026-06-12). Consolidates the full-codebase audit: four
directory audits (compiler, devex, language, stdlib) plus the LSP-v2 session
review. ~100 findings; every item marked **[proven]** was reproduced by
executing the actual compiler/LSP in a mirror, not just read.

Finding IDs reference the audit reports: `CMP-n` (compiler), `DEV-…` (devex),
`LANG-…` (language), `STD-…` (stdlib). The reports' full text is preserved in
the session transcript; this document is self-contained for review purposes.

---

## 0. Severity-0: silently wrong programs and destructive tooling

These produce wrong output or destroy user code today, with zero diagnostics.
Each is small enough to fix independently and first.

| # | What | Evidence | Fix |
|---|---|---|---|
| S0-1 | `(a) - 1` parses as a *cast* and emits invalid/miscompiled C, no diagnostic | CMP-2 [proven end-to-end] — `_CAST_FOLLOW_TOKENS` includes MINUS/STAR/AMP; analyzer never validates cast targets | IDENT casts require a known type name; analyzer rejects casts to unknown types |
| S0-2 | Integer suffixes / leading zeros crash the compiler with a Python traceback (`10u`, `0xFFul`, `0123`) | CMP-1 [proven] — lexer deliberately lexes suffixes, parser calls `int(tok.value, 0)` | strip suffixes before `int()`; ParseError with position for bad literals |
| S0-3 | Every local `Vector`/`Map`/`Set`/`List` leaks: no ARC scope release for monomorphized generics, and no path frees the struct (`delete` → user `free()` which doesn't `free(self)`; `X_destroy` doesn't release fields) | STD-C1 [proven via generated C] | One destructor protocol (see WS3) |
| S0-4 | Rename writes edits into **stdlib files on disk**; renaming `v.push` produced a TextEdit targeting `vector.btrc` | DEV-C2 [proven] | Refuse rename when the def site is under the stdlib dir |
| S0-5 | Variable rename is scope-blind: renames same-named locals in sibling functions and through shadowing | DEV-C1 [proven] | Scope-aware rename design (WS5-A, implementation-ready) |
| S0-6 | Rename/references miss identifiers inside f-strings → rename breaks compiles | DEV-C3 [proven] | Scan `nav_tokens` in references |
| S0-7 | Imports inside `/* */` comments are **executed** (or fail the build); a `class Vector` mention in a comment silently drops stdlib vector.btrc | LANG-C1, CMP-8 [proven] | Imports into the grammar (WS1) kill the regex pass |
| S0-8 | CLI analyzer-error positions are wrong in **both** cache modes (quotes wrong source line, or off by ~5000 lines) | CMP-3 [proven both] | Consume structured `Diag` + provenance in main.py (WS2-D) |
| S0-9 | Class registration is order-dependent: child-before-parent silently loses inherited members | CMP-4 [proven] | Two-pass registration (interfaces already do this) |
| S0-10 | Lambdas: variables used only inside try/catch are not captured → invalid C; try/catch inside lambda misses `setjmp.h` include | CMP-5, CMP-6 [proven] | Generic `dataclasses.fields()` walk; register include from `_lower_try_catch` |
| S0-11 | `Array<T>` ignores ARC (no keep on set, no releases) → dangling element pointers; bounds failures are message-less `exit(1)` | STD-C4 | Mirror Vector's keep/release; add stderr message |
| S0-12 | `JsonObject.parse` mis-parses any nested JSON (flat scanner; inner objects corrupt keys) | STD-C3 | Route through the depth-aware JsonText machinery (interim), real parser in WS4 |
| S0-13 | `Random.randint(5,4)` / `choice([])` → modulo-by-zero UB; `File.read()` UB on pipes (`fread(buf,1,(size_t)-1,…)`) | STD-C5, STD-C6 | Validate/clamp; chunked read loop |
| S0-14 | ~500-term expressions kill the analyzer with RecursionError; type inference is quadratic (measured 4× per doubling) | CMP-7, CMP-30 [measured] | Memoize `_infer_type` via the existing `node_types` dict |

**Gate:** each lands with a regression test; full suite (921 unit + 385 language + 267 LSP) green after each.

---

## WS1 — Make the language definition honest

The spec layer claims to be the single source of truth; today it lies in
specific, enumerated ways.

1. **Imports into grammar + AST** (LANG-(a), implementation-ready design in the
   language audit). `import` becomes a keyword; `ImportDecl` ASDL node with
   spec variants (StdGlob/StdModules/PackagePath/RelativePath/QuotedPath);
   `PATH_SPEC` lexer mode for `./x/**` forms; frontend keeps path *resolution*
   but resolves from parsed nodes, not regex lines. Kills S0-7, the TextMate
   bug class, and the LSP's import-blanking. Blast radius ≈13 files; only 2 of
   ~380 language tests use `import`; zero golden churn.
2. **ASDL contract repairs**: `TryCatchStmt.catch_block` → optional (parser
   already emits None for try/finally — LANG-C3 [proven]); required fields stop
   getting silent `None` defaults (LANG-D4); `source_file` provenance becomes a
   spec'd attribute instead of a monkey-patch (LANG-D5).
3. **Name spans in ASDL** (LANG-(c)): `name_line/name_col` on the 13 named
   constructors + positions for EnumValue/RichEnumVariant/FieldDef (today: no
   position at all). Parser cost ~30 lines (name tokens already in hand); fixes
   the interface-MethodSig wrong-position bug [proven]; deletes ~110 lines of
   LSP side-tables; enables enum-variant/struct-field navigation.
4. **Positions stop poisoning equality**: generator emits line/col (and the new
   name spans) as `field(compare=False)` (LANG-D3 — the generic-dedup bug class
   is still armed).
5. **Drift table**: fix the 14 documented-vs-real divergences (LANG-(b)) —
   mostly spec edits (trailing commas, `keep` placements, anonymous
   struct/enum, `static` access alias), plus two parser fixes: cast follow-set
   missing SIZEOF [proven: `(int)sizeof(int)` rejected], unary `+` missing.
   Document the *actual* `<`-disambiguation and cast follow-sets in the
   grammar's notes; delete or implement the vapor keyword `override`.
6. **Generated-file integrity**: `make ast-generate` + round-trip test
   (checked-in ast_nodes.py already differs from fresh generator output —
   LANG-D6 [proven]); asdl_parser stops silently dropping unknown characters
   and validates field types (LANG-D7).
7. **Self-hosting groundwork**: asdl_btrc.py currently emits btrc that does not
   parse (keyword-collision `default`, untyped sum refs — LANG-C2 [proven]).
   Fix field-name escaping + base-class mapping; add a generate→parse smoke
   test. Align the two generators' optional-field semantics (LANG-D8).

---

## WS2 — Compiler correctness and diagnostics

A. **Parser**: S0-1, S0-2; ternary-with-assignment misparse (CMP-28); stop
   discarding the typed-catch annotation (CMP-26); stop mutating the token list
   with synthetic `>` tokens where avoidable.

B. **Analyzer**: S0-9 two-pass registration; S0-10 capture walk; S0-14
   memoization; `_has_return` missing loop bodies (CMP-27); report undefined
   identifiers instead of deferring typos to gcc (CMP-24); `_types_compatible`
   honors pointer depth and stops treating unknown↔unknown as compatible
   (CMP-24, also the root of the misleading bench_strings error); fix
   `_compute_cyclable_flags` doc + dead loop (CMP-29).

C. **AST immutability** (CMP-(a) inventory is complete: 13 analyzer sites, 0 in
   IR gen). Move `stmt.type`/`param.type`/`return_type`/`captures` writes into
   side tables keyed like `node_types`; retire the `auto_upgraded` stamp. This
   makes analysis idempotent by construction (the LSP currently depends on a
   patch), unblocks WS5-B, and removes the self-hosting trap. Mechanical but
   wide; gate on full suite + LSP idempotency tests.

D. **Diagnostics end-to-end**: main.py consumes `analyzed.diags` + the
   provenance map (S0-8) and deletes the `"msg at line:col"` string parsing
   (CMP-16); spans widen from 1 char to the offending token (DEV-P2); error
   messages stop blaming stdlib lines for user errors (STD-D2 observation).
   Parser error *recovery* (keep parsing past first error) is acknowledged but
   deferred — biggest single UX win for editing, largest parser surgery; do it
   after WS1 lands so recovery rules are written against the honest grammar.

E. **Caches & packaging**: cache keys gain a compiler-code hash (today:
   hand-bumped constants serve stale artifacts — CMP-11; same for the LSP's
   `_UNIT_CACHE_VERSION` — DEV-D5); pkg.py cache key includes URL hash, lock
   validates against manifest hash, library code raises instead of
   `sys.exit(1)` (CMP-9/10/13 — the exit is reachable from the LSP);
   stdlib_archive manifest gets a version stamp (CMP-14); `.btrc-cache` moves
   out of `os.getcwd()` to a project-root- or XDG-anchored location (CMP-12,
   DEV-D5); delete dead `cache.py` (CMP-17 [verified unused]).

F. **IR hygiene**: `_fn_ptr_typedefs` module-global onto the generator (CMP-18,
   cross-compile leak); mangling includes pointer depth (CMP-19,
   `Vector<int*>` vs `Vector<int>` collide today); consolidate the three
   IR→C-text renderers and shrink the 13 files emitting raw C outside the
   emitter (CMP-20) — incremental, file-by-file, alongside the >300-line
   decomposition (13 violations listed in CMP-(b)).

G. **Single source of truth sweep**: builtin names (`print`/`len`/…) stop
   shadowing user functions (CMP-22 — builtin check precedes function-table
   lookup); the string-method API table exists once, not in 5 files (CMP-23);
   `TYPE_KEYWORDS`/cast follow-sets derive from or are documented in the
   grammar (CMP-22, LANG-D9); import_visibility becomes scope-aware (CMP-15).

---

## WS3 — ARC: one memory model, written down

1. **Destructor protocol** (fixes S0-3): generated `X_destroy` = release
   ARC-managed fields → call user `free()`/`__del__` if present → `free(self)`.
   `delete` always calls `X_destroy`. Scope release includes monomorphized
   generic locals. Stdlib collections' `free()` methods drop their
   `free(self)`-adjacent duties and become pure element-release helpers.
   Verify with a leak-counting language test (allocate/destroy cycles around
   every collection; assert balance via the existing string-pool/alloc hooks)
   and ASan in `make test-c11`.
2. **Array joins ARC** (S0-11).
3. **Ownership conventions documented and annotated** (STD-D8): pop/popBack
   transfer +1 (caller must release or bind); get/first/last borrow; keys()
   retains. Write it in each collection's header comment; add `keep` где
   missing; the docs become the contract for the self-hosted port.

---

## WS4 — Stdlib coherence

1. **Error-signaling convention** (STD-D1, conventions table in the stdlib
   audit): adopt one rule — *index/invariant violations may abort (with a
   message, catchable-panic later); data-dependent failures throw or return
   null/Result*. Migrate the outliers: `Map.get` missing key (abort today),
   graph.btrc data errors, json's `exit(1)`, array's silent exits, fs's
   int-code returns, io's silent write failures (data loss). error.btrc /
   result.btrc either get adopted by these APIs or deleted.
2. **Sequence-type end state** (STD-(c)): Vector is *the* sequence; `[...]`
   always means Vector (no target-typing); builtin `split()` returns
   `Vector<string>` (today it's a raw `string*` that type-checks against
   `List<string>` by accident); List is documented as (or renamed to) the
   deque; the two broken bench files get the 5-token Vector fix.
3. **Binary safety**: introduce `Bytes` (ptr+len) and carry it through
   `recv`/file IO/`HttpResponse.body` — fixes the NUL-truncation family
   (STD-C2) and is gap #1 of the missing-API ranking.
4. **JSON**: one API (fold jsonx), a real tree parser (depth-aware), `\uXXXX`
   + control-char escaping, float accessors (S0-12, STD-D4).
5. **C-include leakage** (STD-D3, 28 includes + 1 define): compiler-recognized
   include mechanism (`@include("sys/socket.h")` on extern blocks or
   `import c.<header>`) feeding `IRModule.includes`; `_DARWIN_C_SOURCE` moves
   to the emitter prologue. Pairs naturally with WS1's ImportDecl work.
6. **Correctness batch**: http robustness (chunked encoding, sendAll EINTR
   retry, URL percent-decode, reason() table, temp-dir try/finally — STD-D6);
   datetime gets epoch conversions and `Timer` switches `clock()` →
   `CLOCK_MONOTONIC` (STD-D7 — Timer currently measures CPU time, near-zero
   for anything that sleeps); string semantics contract documented (byte-based,
   ASCII-only case ops — STD-D5); Path/FileSystem unify on the stat-based
   implementation (STD-D9); polish list STD-P1..P10 (alias dedup, toInt error
   channel, negative repeat, env-var empty-vs-unset, …).
7. **Missing APIs, ranked** (STD-(d)): Bytes (with #3), JSON parser (with #4),
   regex (POSIX regcomp — libc-only), comparator sort + `mapTo<U>` (today you
   cannot sort objects by field or map int→string), time arithmetic + `sleep` +
   monotonic now. Honorable mentions: percent-encoding (http server needs it
   itself), base64/sha.
8. **gpu runtime**: replace its 12 asserts with NULL returns + `ok()` probes
   (the tray runtime is the model — gui/tray are already clean); fix the
   `btrc_gpu_available` int/bool/missing-from-header drift.

---

## WS5 — LSP exactness

A. **Pure LSP fixes** (no compiler changes; the scope-aware-rename design in
   the devex audit is implementation-ready):
   - Token-space brace matching replaces every `+50/+500/+1000` scope constant
     [proven bleed across functions]; block-granular `VarDef` ranges;
     `find_var_def` innermost-match; rename filters by def-site identity;
     refuse rename on unresolvable identifiers and stdlib def sites (S0-4/5/6,
     DEV-C4, DEV-D1, DEV-D2 — hover's parallel scope walk collapses onto
     DefinitionMap).
   - Mid-edit correctness: completion/signature re-lex the current line instead
     of trusting stale snapshot tokens [proven wrong-receiver completion]
     (DEV-C5); the uncached-fallback pipeline run takes the validate lock
     (DEV-C6); publish-after-lock-release generation race + did_close
     resurrection fixed (DEV-D3); stdlib_units atomic init (DEV-D4).
   - URI/path: Windows `url2pathname`, stop `resolve()`-ing symlinks into
     split document identity [proven /tmp vs /private/tmp] (DEV-C7).
   - builtins.py: regenerate (ListNode + 6 JsonText methods stale), add the
     generator round-trip test, flip precedence so the live class_table beats
     static tables (DEV-(c), DEV-D7).
   - Caches: LRU-cap `_stdlib_base_cache` (a mid-edit `class Strings {` mints
     multi-MB entries forever); unit-cache version derives from a content hash
     (DEV-D5).
   - Cursor-at-word-end hits the preceding token [proven hover no-op at the
     most common caret position] (DEV-P1); diagnostics span the token (DEV-P2);
     prepare_rename uses the grammar keyword set (DEV-P3).
B. **Analyzer occurrence table** (DEV-(b), gated behind a flag the compiler
   path never pays for): SymbolInfo gains def sites; identifier resolution
   records `id(node) → (kind, def_file, def_line, def_col)`; LSP builds a
   position index per snapshot. References/rename become def-site grouping
   (exact), hover shows analyzer-inferred types. Depends on WS2-C for full
   payoff but can land before it.
C. **Protocol additions, ranked** (DEV-(d)): real diagnostic ranges (with
   WS2-D); `workspace/symbol` (~50 lines over already-parsed units — highest
   value per line); `documentHighlight` (after A, not before); codeAction
   quick-fixes (insert-missing-import via per-unit `defined_names`,
   did-you-mean); pull diagnostics last (also carries imported-file diags —
   today type errors in imported files are invisible until opened, DEV-D6).
D. **Extension**: explicit relative `serverCommand` honored before localServer
   (DEV-D8); prepare_lsp_package excludes `.venv`/`.btrc-cache`/build
   artifacts and aligns the bundle flake's python version (DEV-D9); config
   changes prompt a client restart (DEV-P7).

---

## WS6 — Performance (after correctness)

Memoized inference (S0-14, biggest), optimizer name-scan via word-boundary
regex over a set instead of `name in text` × 1300 (CMP-32 — also a soundness
nit: substring matches keep dead code), module-level operator-trie cache
(CMP-34), generic-instance dedup set (CMP-33), and the precompiled-stdlib
plan-of-record for the CLI (stdlib_archive.py is the WIP; finish behind a flag
with the 385-test suite as the gate — the LSP side is already solved by seeded
analysis).

---

## Sequencing

```
Phase 1  S0 batch (S0-1..S0-14 minus S0-3/S0-7) + WS5-A          [small, independent fixes; suite green after each]
Phase 2  WS2-D diagnostics end-to-end + WS2-E caches/pkg          [provenance machinery already exists in frontend.py]
Phase 3  WS1 imports-into-grammar + ASDL batch (regenerate world) [one coordinated landing; 2 language tests touched]
Phase 4  WS3 ARC destructor protocol (S0-3) + STD error-convention migration
Phase 5  WS2-C AST immutability + WS5-B occurrence table          [paired: the latter is the payoff of the former]
Phase 6  WS4 stdlib additions (Bytes → JSON → regex → sort/mapTo → time) + WS5-C/D protocol & extension
Phase 7  WS6 perf + WS2-F IR hygiene + file-size decomposition    [opportunistic, file-by-file]
```

Rationale: Phase 1 stops active damage with zero architectural risk. Phase 2
makes every later phase debuggable (correct positions, trustworthy caches).
Phase 3 is the one "regenerate the world" landing and unlocks Phases 4-6
cleanly (ImportDecl, name spans, compare=False). Phase 4 changes generated C
the most — it gets ASan + leak tests before stdlib API work builds on it.
Parser error recovery and self-hosted-generator completion ride after Phase 3.

**Test gates per phase**: full suite (921/385/267 + ext 16) green; Phase 1 adds
~25 regression tests for the S0 items; Phase 3 re-validates the 393-file corpus
diagnostics-equivalence gate; Phase 4 adds leak/ASan assertions; Phase 5 re-runs
the LSP idempotency tests with the `auto_upgraded` stamp deleted.

**What not to churn** (consistent across all four audits): the six-stage
pipeline boundaries, the grammar-driven lexer/token validation, the generated
AST discipline, the reachability DCE, the per-file-unit LSP architecture, and
frontend.py's orchestration shape — the work above *finishes* those designs
rather than replacing them.
