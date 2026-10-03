# C4 preprocessor conditionals (Stage 16)

PLAN.md Stage 16 lands C4 after `ccompat-c1-integrate`. The item is `ccompat-r18-preprocessor-conditionals`. D19 approves it. D20 fixes what an undefined identifier means. D21 puts the target spec in its own `src/language` file, generated into the existing modules.

The C1 row above already fixed the shape:
- conditionals are evaluated before lexing;
- dead lines are blanked, so positions survive;
- live `#define`, `#include` and `#undef` stay `PreprocessorDirective(string text)`.

C4 therefore changes no ASDL, no fat-`Node` field and no AST boundary record. D18's "C4's ASDL needs fold into Stage 15" holds vacuously.

One drafter and two adversarial reviewers produced this section (workflow `wf_926e5dfc-b6e`, 2026-10-02). One reviewer checked implementability; the other checked semantic soundness against C11. Every finding and its resolution is listed at the end.

C1's principles still hold:
- one representation per concept;
- kinds that fail closed;
- positions identical in both compilers;
- every deliberate refusal documented, with a test in both compilers.

C4 adds two of its own:
- **btrc evaluates `#if`, but C compiles the program.** When btrc evaluates, it cannot see C compiler flags, headers it does not read, or other files' macros. Anything it cannot see is refused, never guessed.
- **A file's conditioned text is a pure function of its raw text and the target.** It never depends on which file imported it, so every per-file and per-group cache stays context-free.

## Current state

| Fact | Evidence |
|------|----------|
| A `#` that starts a line (after `[ \t\f\v\r]*`) becomes one `PREPROCESSOR` token running to end of line, with `\` and `??/` splices folded in. The token does not track comments. A `//` comment ends at the newline even after a trailing `\`. | `src/compiler/python/lexer/lexer.py:648-650`, `:686-690`, `:711-715`, `:732-753`; `src/compiler/btrc/lexer/Lexer.btrc:93-101`, `:142-155` |
| Python columns count code points; btrc columns count bytes. | `lexer.py:678-685`; `Lexer.btrc:78-89` |
| Only the top level accepts a `PREPROCESSOR` token. In a body the two parsers fail differently: btrcc says `Expected expression, got PREPROCESSOR '#if 1'`, the reference says `Unexpected token '#if 1' in expression`. | `src/compiler/python/parser/parser.py:603-606`, `:660-662`; `src/compiler/btrc/parser/Parser.btrc:171` (probed in `wf_926e5dfc-b6e`) |
| Lowering accepts `#include`, `#define` and `#pragma pack`. It checks only trigraphs, `\n`/`\r` and a trailing `\`, so an unclosed `/*` passes through to C. Every other directive, `#undef` included, gets `unsupported preprocessor directive '#…'`. | `src/compiler/python/ir/lowering/translation_unit.py:861-888`; `src/compiler/btrc/ir/lowering/Declarations.btrc:4565-4605` |
| Both compilers normalize CR and CRLF to LF when they read a file, so lowering's `\r` check is unreachable from a file. | `src/compiler/python/frontend/sources.py:538`; `src/compiler/btrc/frontend/SourceIo.btrc:205-233` |
| Every live directive is hoisted, in source order, ahead of all C declarations. The analyzer reads a final-active macro namespace, and `collect` silently overwrites a redefinition. | `src/compiler/python/backend/c_emitter.py:1082-1116`; `analyzer/program.py:207-252`; `analyzer/declarations.py:263-280` (`:275`); `src/compiler/btrc/analyzer/SourceMacros.btrc:56-71` |
| The emitted C defines its own macros: `bool` through the `<stdbool.h>` prologue, `BTRC_INCLUDE_*` include guards, `BTRC_RT_*` freestanding features and `BTRC_FREESTANDING`. Only `__btrc_`, `__BTRC_`, `__gpu_` and `btrc_` are reserved prefixes. | `c_emitter.py:1104-1109`; `ir/optimizer.py:720-746`; `src/runtime/c/btrc_rt.h:8-20`; `analyzer/declarations.py:723` |
| A module unit lowers only its own group's directives. `merge_into` then appends each directive of the other groups unless the unit already has an equal one. | `translation_unit.py:456-457`; `src/compiler/python/application/modules.py:726-730`; `src/compiler/btrc/pipeline/ModuleUnits.btrc:739-746` |
| Every group's module-unit key includes the program interface, which hashes every top-level `PreprocessorDirective.text`. | `modules.py:519-566`, `:856-877`; `src/compiler/btrc/syntax/Identity.btrc:170-175` |
| The Python whole-program artifact key is the composed text plus `cache_identity()`, which covers paths, positions, graph and native plan but no raw file content. btrcc's key includes the raw root text and a digest of every file read. | `sources.py:407-429`; `application/compiler.py:197-222`, `:240-283`; `src/compiler/btrc/Compiler.btrc:30-41`; `SourceIo.btrc:311-319` |
| For an imported file, btrcc reports lexer, parser and semantic errors at combined line numbers with no file name; the reference reports the file position. Root-file positions agree. | probed: `Other.btrc:4:22` prints `at 7:22` from btrcc |
| btrcc already has a renderer that prints a file position, and the inventory and refusal regexes accept its output. | `src/compiler/btrc/frontend/Models.btrc:848-870` (`FeVisibilityDiagnostic.render`); `src/tests/btrc/test_c_compatibility_inventory.py:93-95` |
| Imports are found by lexing each file with the real lexer before composition. | `sources.py:772-863`, called from `frontend/imports.py:246-271`; `src/compiler/btrc/frontend/Resolver.btrc:84-286`, `:624-642` |
| btrc's frontend imports neither the analyzer nor the generated ABI tables. `HostedAbiRepository` lives in the analyzer and itself imports `frontend/Models.btrc`. Python's frontend already imports `abi.hosted`. | `Resolver.btrc:3-15`; `analyzer/HostedAbi.btrc:7-11`; `pipeline/Pipeline.btrc:21`, `:34`, `:61-67`; `frontend/imports.py:21` |
| `hosted_abi.toml` has no predefined-macro table, only `[names]`, `[platform]` and `[[functions]]`. Its names cover about 4,800 C macros. | `src/language/hosted_abi.toml:10`, `:1101`, `:8108`, `:8756`, `:11401` |
| Target values exist twice, as `operating_system`/`architecture` (`linux`/`macos`/`windows` × `x86_64`/`aarch64`). On a host it does not recognize, btrcc keeps an empty target; the reference refuses that host before resolving. | `frontend/packages.py:55-56`, `:158-193`; `src/compiler/btrc/frontend/Packages.btrc:25-75` |
| Both analyzers take `long` from the host (`struct.calcsize("@l")`, `LONG_MAX`), never from the target. | `analyzer/types.py:118-126`, `:158-159`; `src/compiler/btrc/analyzer/validation/Constants.btrc:316-319` |
| A package's `[[native.defines]]` become `-D` flags of the C build. From macros, the native reader exports only `NativeConstant` and `NativeStringConstant`, so an empty or function-like macro in a bound header is invisible. | `frontend/packages.py:576-582`, `:1343-1355`; `src/language/package-manifest.md:133-135`; `src/language/native_abi.asdl:25-26` |
| The LSP's persistent unit cache keys on schema, `FrontendFingerprint` and raw text. The fingerprint hashes only the grammar, the ASDL and the `syntax`/`lexer`/`parser`/`frontend` sources. | `src/devex/lsp/workspace/cache.py:150-159`; `src/devex/lsp/workspace/units.py:39-71`; `sources.py:542-573` |
| No `.btrc` file in `src` or `examples` uses `#if`, `#ifdef`, `#ifndef`, `#elif`, `#else`, `#endif` or `#undef`. Nine test sources use `#define`, and none defines a name twice. The only boundary source with a directive is `managed.source` (`#include <assert.h>`). | grep; `src/tests/fixtures/compiler_boundaries/sources/` |

## Decisions

| Item | Decision |
|------|----------|
| Where conditionals run | **Per file, in the front end.** Whenever the resolver first reads a `.btrc` file, it conditions the text before scanning it for directives. This covers the root, imports, btrc includes, relaxed-mode stdlib modules, the symbol-index fallback and LSP units. The result has the same lines; every dead line and every conditional-directive line becomes the empty string. Directive scanning, composition, lexing, parsing and every cache see only conditioned text. |
| Macro environment | **The target and this file.** A line of file F is evaluated against the selected target's predefined macros and the live `#define`/`#undef` lines of F above it. Other files' macros are invisible to `#if`. Program checks P1–P4 refuse the cases where that would silently differ from C. |
| Target spec | **`src/language/targets.toml`**, D21's spec file, created now. It holds target rows, the predefined-macro table and two name lists. `tools/compiler_codegen/hosted_abi.py` renders it into the existing `abi/generated.py` and `generated/hosted_abi/Tables.btrc`, so the 88/97 file inventories do not change. Stage 24 extends the same file. |
| Directives | `#if`, `#ifdef`, `#ifndef`, `#elif`, `#else`, `#endif` and `#error` are interpreted. `#elifdef` and `#elifndef` (C23) are refused at every level. Any other directive in a live group stays a `PreprocessorDirective`. In a dead group only conditional directive names are tracked, for nesting (C11 6.10.1p6). |
| Expressions | C11 6.10.1, computed in `intmax_t`/`uintmax_t`, which are 64-bit on every target. Operands are `defined`, integer and ASCII character constants, `true`/`false`, and object-like macros. Undefined behaviour and silent negative-to-unsigned conversions are errors. A payload is lexed only when it is evaluated. |
| D20 | An identifier that is **evaluated**, and is neither a macro defined earlier in the file nor a target macro, is an error naming it (I1). An unevaluated operand is never read, so nothing is silently 0 and no error is raised. That covers `0 && X`, `1 \|\| X` and the arm `?:` does not take, and it keeps `#if defined(X) && X > 2` usable. The C4 commit records this reading in PLAN.md's D20 row. |
| Function-like macros, `##`, `defined` produced by expansion | Refused in `#if` (I4, I8, I7). |
| Dead groups | Must lex with the real lexer. They are never parsed or analysed. |
| Redefinition | A `#define` of a name that is already defined must be identical (C11 6.10.3p2). Conditioning checks this within a file and the analyzer checks it across the program (M1). The reason: `#if` reads a value at its own position, while code reads the final one. |
| `#undef` | Accepted only for a macro that a non-stdlib btrc source `#define`s (M2). It updates the file's environment and is emitted as `#undef NAME` in hoisted order. Code may not use a macro that is `#undef`'d anywhere (U1, U2). |
| Reserved macro names | Neither `#define` nor `#undef` may name `defined`, a grammar keyword, a hosted-ABI name, one of the spec's foreign macro names, or a name with the `BTRC_` prefix (M3, M4, existing rules). |
| Dead imports and includes | Add no dependency edge, source, C include or native binding. |
| Module units | Every unit carries the program's whole directive list in source order. Only identical `IRInclude`s are deduplicated. |
| Caches | Every compiler cache keys on conditioned or composed text, so a target switch invalidates with no new key component. Two keys change: Python's whole-program `cache_identity()` gains the program-check records, and the LSP unit cache gains the target and its environment identity. |
| Positions | Conditioning errors and P1–P4 are file-local in both compilers. btrcc prints them with `FeVisibilityDiagnostic.render()`. |
| Inspection tools | `LexMain`, `ParseMain` and the boundary verifier's raw AST dump stay single-stage and raw. Conditional parity is observed through `FrontendMain --target`. |
| iOS / Android | Deferred to Stage 24. `__ANDROID__` is a target macro that no current target defines. |

## Shared owners

- **Target spec.** `targets.toml` is the only source of target rows and macro values. Stage 24 makes `PackageTarget` read the rows. `test_hosted_abi_contract.py` checks:
  - the generator's rules;
  - that the generated rows equal the spec;
  - that the target rows equal `PackageTarget`'s sets in both compilers (`packages.py:55-56`; `Packages.btrc:34-36`);
  - that `__CHAR_BIT__`, `__SIZEOF_SHORT__`, `__SIZEOF_INT__` and `__SIZEOF_LONG_LONG__` equal both analyzers' widths for every target.
- **Conditioning.** These are the only interpreters of conditional directives:
  - Python: `SourceConditionals` (the walk), `ConditionalEnvironment` (selection and classification) and `ConditionalExpression` (the evaluator). They live in `frontend/sources.py` beside `SourceDirectiveScanner`, with the `ConditionedSource` and `ConditionalTest` values and `PreprocessorConditionalError`.
  - btrc: `FeSourceConditionals`, `FeConditionalEnvironment` and `FeConditionalExpression` in `frontend/Resolver.btrc`. The `FeConditionedSource` and `FeConditionalTest` values live in `frontend/Models.btrc`.
  - **Dependency direction.** The environment is built where packages are resolved, just before import resolution.
    - Python builds it in `SourceResolver.resolve`. `sources.py` gains the `abi.hosted` import edge that `imports.py` already has.
    - btrc builds it in `CompilerPipeline.resolve`, which owns `HostedAbiRepository`. The pipeline passes the repository's owned-name set, with `GeneratedHostedAbiData`, to `FeConditionalEnvironment.forTarget`, and passes the result to `FeFrontendResolver`.
    - The btrc frontend imports the generated tables (data only) and never the analyzer. `FrontendMain` builds its environment through the same `CompilerPipeline` call.
  - **Call sites.**
    - Python: `ImportResolver._open_frame`; `StdlibRepository.source_mapped`, `_source_without_imports`, `defined_names` and `parsed_symbol_owners`; `CompilationPipeline.build_stdlib_archive`; LSP `FileUnit.parse`.
    - btrc: `FeFrontendResolver.openFrame`, `sourceWithoutImports`, `sourceAtSnapshot` and `definedTypeNames`; `FeImportVisibilityChecker.ensureStdlibIndex`; `FrontendMain`.
  - **Contract test.** Every `Lexer(` constructed in these places must read conditioned text: `frontend/`, `application/`, `pipeline/`, `devex/lsp/`, `tools/compiler_codegen/`, `src/tests/python/test_corpus_strict_imports.py` and `src/tests/python/test_hosted_abi_contract.py`. A reasoned allow-list holds the exceptions:
    - the inspection tools and the verifier's raw dump;
    - conditioning's own raw and payload lexes;
    - the main lexer;
    - the naming-convention contract, which lexes raw text for identifiers and is therefore stricter;
    - the LSP's text-before-cursor helpers.
- **Expressions.** Python `ConditionalExpression` and btrc `FeConditionalExpression` share one table-driven battery of about 60 expressions with their values and diagnostics. btrcc runs it through `src/tests/btrc/fixtures/ConditionalExpressionDriver.btrc`, which reads one case per line and prints a value or a diagnostic per line. `selfhost_driver` builds the driver once per btrcc fingerprint, as it does for `DirectiveCacheDriver.btrc`.
- **Source macro rules.**
  - Python `SourceMacroDeclarations._validate_mutation` and btrc `analyzer/SourceMacros.btrc` own, for the whole program: M1–M4, the keyword rule, and the existing reserved-name rules.
  - Conditioning applies the per-directive rules to its own file's live `#define`/`#undef` lines, through the same predicates and messages. Those rules are M1 within the file, M3, M4, the keyword rule, and the existing rules for names starting with `_`, compiler-reserved prefixes and hosted names.
  - So the environment never holds a name the analyzer refuses, and the refusal comes before any `#if` could read that name.
  - M2 and cross-file M1 need the whole program, so they stay in the analyzer.
  - Neither owner refuses a package `-D` name at a `#define`, so a fast-path file and a slow-path file give the same answer.
- **Stdlib symbol index.** `btrc.symbols` stays target-independent: an owner is the union, over every spec target, of the file's live declarations.
  - This applies to `tools/compiler_codegen/stdlib_symbols.py` (through `parsed_symbol_owners`), to `tools/compiler_codegen/builtins.py`, and to `test_hosted_abi_contract.py`'s prototype scan.
  - It also applies to btrc's fallback (`frontend/Visibility.btrc:483-516`), which receives every target's environment from `CompilerPipeline`.
  - A generator whose per-target results disagree for one name fails, naming the file and the two targets.
  - The generated-source check requires every stdlib module to condition without error for every target, to contain no `#undef`, and to record no test of an absent name. P1–P3 therefore cannot fire on the stdlib in any program.

## Conventions both compilers keep identical

- **Line structure.**
  - Conditioned text has exactly the raw file's lines, split on `"\n"`. A blanked line is the empty string, and live lines are byte-identical.
  - Every position, source map, `#line` mapping and `--debug` line is therefore unchanged.
  - Input is always LF-normalized before conditioning. Files are normalized by the readers above. LSP buffers are normalized in `FileUnit.parse` through `SourceFileReader`'s normalization (`sources.py:538`), exposed as a class method.
- **Positions.** Line and column are file-local and 1-based, counted as the lexer counts columns. Columns agree only on ASCII lines, because Python counts code points and btrc counts bytes (an existing lexer divergence). Every parity battery is therefore ASCII-only.
  - Directive-structure errors sit at the directive's `#`.
  - Shape errors sit at the offending character (`\`, `??/`, `/*`, `\f`, `\v`, `%:`, `??=`).
  - Operand, constant and identifier errors sit at that token, shifted by the payload's offset in the directive. A token produced by expanding a macro sits at the macro name in the directive.
  - Arithmetic errors sit at the operator (`?` for `?:`).
  - An unterminated conditional sits at the innermost open directive.
  - P1–P4 sit at the tested name. M1–M4 sit at the directive's `#`.
- **Rendering.**
  - The reference raises `PreprocessorConditionalError`, a `CompilerFailureKind.SYNTAX` failure carrying `file`. It prints `error: <message>` and then `--> <path>:<line>:<col>`.
  - btrcc prints the same message through `FeVisibilityDiagnostic.render()` and exits 1.
  - Both are file-local, also in imported files.
- **One error.** Only the first error is reported.
  - Files are taken in resolution order: the order in which the resolver opens them, depth-first and in source order, identical in both compilers.
  - Within a file, the order is the raw lex, then the shape checks in line order, then the directive walk in line order. The walk raises D13, the per-directive name rules, M1, and every D, E, I and A error.
  - Within one expression, the steps of C11 6.10.1p4 below run in order, and each reports its first error in token order.
- **Fast path.**
  - A file is a slow-path candidate when some line matches `^[ \t\f\v]*(#[ \t\f\v]*(if|el|en|er|\\|\?\?/|/\*)|%:|\?\?=)`. Any other file is returned untouched, without lexing.
  - A conditional can only be spelled on a candidate line, so a file without one has no conditional directive and no dead group.
  - On such a file the slow path would return the same text. Every error it could report there (the raw lex, the per-directive name rules, M1) is also reported by the main lexer or the analyzer, with the same message.
  - btrc scans by indexing the string and never calls `substring` in the loop.
- **Raw lexing.**
  - On the slow path, conditioning lexes the whole raw file with the real lexer. If that fails, conditioning reports the lexer's error at its file position. It never returns the raw text for the main lexer to fail on.
  - Fast-path files keep today's behaviour. For them, btrcc's combined positions in imported files remain the existing divergence, so the identical-position claim for a deferred lexical error covers only the root file.
- **Directive names.** After `#` and `[ \t\f\v]*`, the name is the longest identifier (`[A-Za-z_][A-Za-z0-9_]*`). In a conditional, `\f` and `\v` then give D17. `#ifdefX` and `#iff` are not conditionals; `#if(1)` is `#if`.

## Rules

### Directive processing

1. If the fast path finds no candidate line, return the text unchanged.
2. Lex the raw file. On failure, report the error.
3. Run the shape checks below.
4. Walk the `PREPROCESSOR` tokens in order with a stack.
   - Each entry holds its opening token, its state (*taking*, *seeking* or *done*) and whether `#else` has been seen.
   - A group is live when every enclosing entry is taking.
   - A conditional is **at a live level** when the group that encloses its whole if-section is live.
5. At a live level:
   - `#if` evaluates its payload; the entry starts taking or seeking.
   - `#elif` evaluates its payload while the entry is seeking. After a taken group, `#elif` sets the entry to done and is neither lexed nor evaluated; gcc and clang accept `#elif 1/0 garbage (` there.
   - `#ifdef X` and `#ifndef X` lex their payload. They take exactly one identifier, classified as `defined(X)` is.
   - `#else` and `#endif` lex their payload, which may hold only comments (D7).
   - In a live group, `#error` fails with D12.
   - In a live group, `#define` and `#undef` update the environment through `SourceSymbolDirective.parse` (Python) or `SourceMacroDefinition` (btrc), applying the per-directive name rules and M1.
   - Other directives are left alone.
6. At a dead level:
   - `#if`, `#ifdef` and `#ifndef` push an entry that is done.
   - `#elif`, `#else` and `#endif` get only the structural checks D1–D3.
   - D9 applies at every level.
   - Nothing else is read.
7. At end of file, an open entry gives D4.
8. Blank every conditional-directive line and every line of a dead group.
   - A group is exactly the lines strictly between two directive lines, because a directive owns its whole physical line.
   - The shape checks guarantee that a conditional directive is one physical line.

Blanking never cuts a comment or literal in half. A block comment hides any line inside it that starts with `#` from the lexer, exactly as C's translation phase 3 hides it from phase 4. String and character literals cannot span lines.

**btrcc with no target.**
- On a host it does not recognize, `FePackageTarget.host()` is empty.
- The environment is built lazily: when the walk first evaluates an `#if`, `#elif`, `#ifdef` or `#ifndef`, that directive fails with D13 at its `#`.
- The reference refuses such a host before resolving (`packages.py:166-180`).
- The LSP builds its environment the same lazy way, so on an unsupported host only files with conditionals get D13.

### Shape checks (C11 translation phases 1–3)

C removes line splices and comments before it recognizes directives (5.1.1.2; 6.10p2). btrc's `PREPROCESSOR` token does neither. Any construct where the two orders disagree is therefore refused on the slow path, with a position:

| Applies to | Check |
|------------|-------|
| every conditional directive, at every level | a splice (D10); a trigraph (D11, checked first); `\f` or `\v` after the `#` (D17); an unclosed `/*` (D15); a comment between `#` and the name (D16) |
| every directive line inside a dead group | a splice (D10); an unclosed `/*` (D15); a comment between `#` and the name (D16) |
| every candidate line whose `#` is followed (after spaces) by `\`, `??/` or `/*` | D10 or D16 |
| every line starting with `%:` or `??=` | D14 |
| a conditional directive whose preceding physical line ends in `\` or `??/` (a `//` comment that C would continue) | D10, at that `\` |

"Unclosed" is one textual rule in both compilers. Scan the directive left to right, skipping string and character literals. A `//` ends the scan. Every `/*` must be followed by `*/` on the same line.

Live non-conditional directives keep lowering's checks, which gain D15 and D17 with the same text, unpositioned like their siblings. Lowering keeps `unsupported preprocessor directive '#if'` (and the same for the other conditional names) reachable as an invariant. A test lowers a hand-built `PreprocessorDirective("#if 1")`.

### `#if` expressions

The grammar goes into `grammar.ebnf`'s `@syntax` section, which is documentary:

```
if_section   = if_group { elif_group } [ else_group ] "#endif" ;
if_group     = ( "#if" pp_expr | "#ifdef" IDENT | "#ifndef" IDENT ) { group_part } ;
elif_group   = "#elif" pp_expr { group_part } ;
else_group   = "#else" { group_part } ;
pp_expr      = pp_or [ "?" pp_expr ":" pp_expr ] ;      (* right-assoc; no comma *)
pp_or        = pp_and { "||" pp_and } ;   ... "&&", "|", "^", "&", "== !=",
               "< > <= >=", "<< >>", "+ -", "* / %"     (* all left-assoc *)
pp_unary     = ( "+" | "-" | "~" | "!" ) pp_unary | pp_primary ;
pp_primary   = INT_LIT | CHAR_LIT | "true" | "false" | IDENT
             | "defined" IDENT | "defined" "(" IDENT ")" | "(" pp_expr ")" ;
```

**Tokens.**
- **Pre-scan.** Before lexing, the payload is scanned for `#` and `%:`, skipping literals and comments; either gives E7. A macro replacement is scanned the same way, after `SourceSymbolDirective.uses_token_paste` (Python) or `SourceMacroDefinition` (btrc) checks it for `##`, `%:%:` and `??=??=` (I8).
- **Lexing.** The real lexer then runs over the payload. A lexer error is E0, with the lexer's own message at the shifted position; the two lexers' messages already match. A replacement that fails to lex gives E0 at the macro name.
- **Values.** Integer and character values come from the shared decoders: `LiteralDecoder` in `lexer.py`, and `IntegerLiteral` and `CharacterLiteral` in `syntax/Literals.btrc`. `0b` and `0o` constants are accepted as a documented btrc extension; gcc `-pedantic-errors` rejects `0b` in C11.
- **Keywords.** `true` and `false` are 1 and 0: C23 semantics, and C11's once `<stdbool.h>` is included. Any other keyword token is an identifier spelled the same way, except `sizeof` (E12). So `bool` classifies as foreign.
- **Wide characters.** An `L`, `u` or `U` identifier token immediately followed by a character constant is a wide character constant (E15). Once Stage 19 lexes wide literals, E15 keys on the token kind.

**Steps (C11 6.10.1p4).**
1. Resolve each `defined`. Errors: E13 and E14, or I2/I3 for a reserved or foreign operand.
2. Expand this file's object-like macros, recursively. A macro is never re-expanded inside its own expansion (I6). I4, I5, I7 and I8 are raised here. One budget per directive counts every resulting token and every macro invocation; past 4,096 it is E16, at the outermost macro being expanded (or at the token for an unexpanded one). Expansion keeps one active set and one stack of open expansions, so a deep chain neither recurses on the host stack nor copies per level.
3. Classify the remaining tokens in order: I2, I3, E7–E12, E15.
4. Parse (E1–E6).
5. Evaluate with short-circuiting. I1 and A1–A5 are raised only in evaluated operands.

Steps 1–4 apply to every operand, evaluated or not. C11 6.6p3 allows a comma in an unevaluated operand (`#if 0 && (1, 2)`), but btrc refuses it (E7) on purpose.

### Identifier classes

Classes are checked in this order:

| Class | Applies when | Bare use | `defined` / `#ifdef` |
|-------|--------------|----------|----------------------|
| target macro | the name is a predefined-macro row or is in `undefined_macro_names` | the selected target's value, or 0 | 1 or 0 |
| reserved | the name starts with `_` | I2 | I2 |
| this file | there is a live `#define` above it, not `#undef`'d since | object-like: expand (I4, I5, I7, I8 as above) | 1 |
| foreign | see the list below | I3 (the package form names the package) | I3 |
| absent | anything else | I1, when evaluated | 0 |

A name is foreign when it is:
- a hosted-ABI name from `[names]` or `[platform]`: functions, macros, objects, types and typedefs;
- a `foreign_macro_names` entry;
- a name with a compiler-reserved prefix (`btrc_`, `BTRC_`);
- a `[[native.defines]]` name of any package in the resolved package graph, for every target and before `for_sources` restriction.

The class order cannot hide one of the file's own definitions. Conditioning and the analyzer refuse `#define` of names starting with `_`, of hosted names, of foreign macro names and of reserved prefixes, so the environment never holds one. A file may `#define` a package's `-D` name, but the C build then sees a conflicting redefinition. The LSP's per-file environment has no package graph, so there a package define classifies as absent; compile diagnostics report it.

**Records.** Each of these appends `ConditionalTest(path, name, line, col, local)` to the file's result, with `local` true for a this-file name:
- every evaluated `defined`, `#ifdef` or `#ifndef` of an absent or this-file name;
- every evaluated expansion of a this-file macro.

The resolver carries the records, in resolution order, as `ResolvedSource.conditional_tests` (Python) and `FeResolvedSource.conditionalTests` (btrc).

### Values and arithmetic

A value is a 64-bit pattern plus an `unsigned` flag.

**Constants.**
- An integer constant is unsigned when it has a `u` suffix, or when it is not decimal and exceeds INTMAX_MAX. `l` and `ll` change nothing.
- E11 (`Invalid integer literal '…'`) covers a decimal constant without `u` above INTMAX_MAX, and any constant above UINTMAX_MAX. gcc's "so large that it is unsigned" is an error under `-pedantic-errors` too.
- A character constant must be 0–127 (E10), because `char`'s signedness differs by target: `__CHAR_UNSIGNED__` is defined only on linux-aarch64.

**Arithmetic.**
- **Conversions.** The usual arithmetic conversions apply to `* / % + - < > <= >= == != & ^ |` and to the arms of `?:`, even an arm that is not evaluated. If either operand is unsigned, the operation is unsigned. `&&`, `||`, `!` and the shifts' right operand convert nothing.
- **Wrapping and overflow.** Unsigned `+`, `-`, `*`, unary `-` and `<<` wrap. A signed result outside the 64-bit range is A2.
- **Division.** `/` and `%` truncate toward zero. A zero divisor is A1. `INTMAX_MIN / -1` and `INTMAX_MIN % -1` are A2.
- **Shifts.**
  - The result has the left operand's type.
  - A negative count, or a count of 64 or more, is A3.
  - A signed `<<` of a negative value is A4; an unrepresentable signed `<<` result is A2.
  - `>>` of a negative signed value is arithmetic. This is implementation-defined in C; gcc and clang agree.
- **Truth values.** Comparisons, `!`, `&&` and `||` yield signed 0 or 1.
- **Sign conversion.** An evaluated negative signed operand that a binary operator or `?:` converts to unsigned is A5. C converts it silently; clang warns by default.
- **btrc computes only on `unsigned long long` bit patterns.**
  - It never overflows a signed type, and never converts an out-of-range value to a signed type (6.3.1.3p3).
  - Signs are read from bit 63, and overflow is detected with magnitude comparisons.
  - An arithmetic right shift of a negative `u` is `~(~u >> n)`.
- **Python** checks ranges explicitly on its integers.

The `wf_926e5dfc-b6e` probes checked these semantics against gcc 15.2 and clang 21.1.8 with `-std=c11 -pedantic-errors -E`:
- truncating `/` and `%`;
- the 64-bit unsigned hex constant;
- `0 && (1/0)` accepted;
- the overflow and division errors;
- `#define X X` / `#if X` taking `#else`.

### Imports, includes and the graph

- **Discovery.** Imports and btrc includes are discovered on conditioned text. A dead `import` or `#include "X.btrc"` adds no `SourceDependencyGraph` edge and no composed source.
- **Native plan.** Package and native-plan selection derive from those sources (`sources.py:1261-1263`; `Pipeline.btrc:69-72`). A dead import therefore adds no native binding or link-plan source, and a dead `.c` import is not spliced.
- **Quoted includes.** Dead quoted includes are not C2 enum-tag evidence, because they are never parsed. Live `#include` lines are emitted as today, so `#if defined(_WIN32)` / `#include <windows.h>` selects headers per target.
- **btrc includes.** A btrc `#include "X.btrc"` is conditioned per file, like an import: X's `#define`s and `#undef`s do not reach the includer's `#if`. P1 and P4 refuse a test that would see a difference.

### Source macros, redefinition and `#undef`

- **Redefinition (M1).**
  - In hoisted program order, a `#define` of a name that is already defined must be identical (C11 6.10.3p1-2): the same kind (object-like or function-like), the same parameters and the same replacement.
  - Replacements are compared after normalization: comments become one space, runs of whitespace outside literals collapse to one space, and both ends are trimmed.
  - The analyzer refuses across the program. Conditioning refuses within the file, so the error comes before any `#if` that would read the new value.
  - Today both compilers emit both lines, and gcc and clang without `-pedantic-errors` only warn and use the last value (`wf_926e5dfc-b6e`). `#if` would have used the first.
- **`#undef` (M2).**
  - Accepted only for a name that a live `#define` in a non-stdlib btrc source of the program defines. Otherwise it is refused at the `#undef`.
  - btrc never undefines what its prologue, a header or a flag defines. C11 7.18p4 lets C programs `#undef bool`, which would break btrc's own generated code.
  - Stdlib sources contain no `#undef` (the generated-source check enforces this). The prebuilt stdlib archive records only `IRMacroDef` (`application/pipeline.py:285-289`, `:322-326`), and it never meets an `#undef`.
- **Names (M3, M4).** Neither `#define` nor `#undef` may name:
  - `defined` (C11 6.10.8p2);
  - a grammar keyword (row 20's message);
  - a `foreign_macro_names` entry;
  - a name with the `BTRC_` prefix. `BTRC_` is added to `_COMPILER_RESERVED_PREFIXES` (`declarations.py:723`) and uses that list's existing messages.
- **Emission.** A live `#undef NAME` lowers to `IRMacroUndef(name)` in Python and to `IRPreprocessorDecl.undef(name)` (kind `IR_PREPROCESSOR_UNDEF`) in btrc. It is emitted as `#undef NAME` in hoisted source order. Trailing tokens give U3.
- **Module units.**
  - Every unit's preprocessor list is the program's whole list in source order, as the declarations-only session lowers it. Today a unit has its own directives first, then the other groups'.
  - `translation_unit.py:456-457` no longer skips other groups' directives, and `merge_into` and `ModuleUnitDeclarations` no longer append them.
  - The existing rules stay: a `.c` include appears only in its importing group's unit, and native-binding includes are still trimmed.
  - Only identical `IRInclude`s may be deduplicated. `IRMacroDef` and `IRMacroUndef` never are.
  - This also fixes an existing bug: when a group's `#include "lib.h"` read a `#define` from an earlier group, that group's unit emitted the include first.
- **Code use (U1, U2).**
  - All directives are hoisted ahead of all code, so code sees each macro's final state.
  - Both `SourceMacroNamespace`s gain `undefined(name)`, which is true when some live `#undef` names it.
  - Using a declared source macro X in code is refused in two cases. U1: `undefined(X)` holds. U2: X's replacement reaches an `#undef`'d macro through the existing `expands_to_any`/`expandsToAny`.
  - The rule covers identifiers, macro calls, parameter defaults and constant contexts.
  - Testing a macro in `#if` stays allowed, so `#define F 1` … `#undef F` … `#ifdef F` works.
- **Later consumers.** A consumer that reads a source macro's value (C2's integer-constant owner) emits the folded value into C, never the macro's name. C code that btrc does not read therefore cannot change what the analysis used.

### Program checks after parsing

Both compilers run `verify_tests` / `verifyTests` over the records in order. The check runs after parsing, once native declarations are prepended, and before the strict-import visibility check. For each record it tries P1, P4, P2 and P3 in that order and reports the first match:

| | Applies to | Condition |
|-|------------|-----------|
| P1 | absent names | X has a live `#define` in another source file (the first in program order) |
| P4 | this-file names | X has a live `#undef` in another source file (the first in program order) |
| P2 | absent names | X names a declaration imported from a native header |
| P3 | absent names | the testing file has C evidence (listed below) |

C evidence for P3 is any of:
- a live quoted `#include "…"` of a non-`.btrc` file;
- an import edge to a `.c` file (C2's rule, `c-compatibility.md:313`);
- a `[[native.headers]]` entry of the selected plan whose `modules` names the file, or is empty while the file lies in that package;
- a `[[native.bindings]]` entry whose `module` is the file.

The checks run in strict and relaxed mode. They also run in every mode that parses: `--emit-ast`, `--emit-ir`, `--emit-optimized-ir` and C output. `--emit-tokens` parses nothing and skips them. File names in messages are basenames of the absolute `source_file`, and includes are spelled as written.

An angle `#include <…>` is not P3 evidence, as in C2:
- A system macro is classified through the hosted ABI's macro names (foreign, I3).
- 1,096 test sources contain a system include. Counting them would refuse the `#ifndef X` / `#define X …` default idiom in almost every file.
- A system macro outside the hosted ABI, tested with `defined`, therefore reads 0. known-language-gaps documents this.

### Caches and fingerprints

| Cache | Key today | Under C4 |
|-------|-----------|----------|
| Directive cache (Python `artifacts/cache.py:1029-1063`; btrc `cli/Driver.btrc:1478-1508`) | compiler identity plus the scanned text | It scans conditioned text. One raw file under two targets gives two entries, and a restore never brings back a dead import. No new component. |
| Stdlib AST cache (`sources.py:618-751`, `:1048-1067`) | schema, frontend version, composed stdlib text | The text is composed from conditioned files, and parsing is context-free. No new component. |
| Module units (`modules.py:767-782`, `:845-877`; `ModuleUnits.btrc:1095-1111`, `:1857-1866`) | target, per-group conditioned lines, program interface | No new component. The interface hashes every live directive, so editing any live directive re-lowers every group. An edit inside a dead group changes no key. |
| btrc `ValidationRecords` (`ModuleUnits.btrc:2709-2765`; `Pipeline.btrc:147-151`) | `userLines` text, `target=`, interface | `userLines` are conditioned. No new component. |
| btrc whole-program artifacts (`Compiler.btrc:30-41`) | raw root text, every read file's raw digest, target, link plan | Already covers raw content and target. |
| Python whole-program artifacts (`compiler.py:197-222`) | composed text plus `cache_identity()` | **Changed.** Blanked lines drop out of the composed text. So `#if 0 … #endif`, and an absent `#ifdef HAVE_X` beside a C include, compose identically, and a warm compile would skip P3. `cache_identity()` now appends the ordered records as canonical `path\0name\0line\0col\0local` text. |
| Prebuilt stdlib archive (`artifacts/stdlib.py:119-170`) | hash of the composed stdlib source | `build_stdlib_archive` (`application/pipeline.py:884`) conditions with its target (`options.target`, else the host). Consumers compare the hash of their own conditioned composition, as today. |
| LSP `UnitCache` (`devex/lsp/workspace/cache.py:150-159`) | schema, `FrontendFingerprint`, raw text | **Changed.** The key adds the target label and `ConditionalEnvironment.cache_identity()`, a digest of the selected macro rows, the undefined names and the foreign name set. `FrontendFingerprint` hashes no ABI data, and a `.btrc-cache` is shared by synced checkouts on different hosts. |

Toolchain fingerprints need no change:
- Python `ToolchainFingerprint('full')` already hashes `abi/generated.py`.
- btrcc's compiler identity already covers `Tables.btrc`.
- `src/language/*.toml` is already in the btrcc fixture fingerprint (`src/tests/conftest.py:34-48`) and in the flake source sets.
- Conditioning itself is never cached.

### LSP, formatter and tools

- **LSP** (`src/devex/lsp/workspace/units.py:145-176`).
  - `FileUnit.parse` LF-normalizes the buffer and conditions it with the host target. The environment is built lazily, as above; a workspace target setting is left to Stage 24.
  - The unit keeps `conditioned_source` beside `source`, and `defined_names` reads the conditioned text.
  - Dead lines have no tokens, semantic tokens, symbols, hovers, definitions or diagnostics.
  - A conditioning error is stored like a lexical error, at its file position.
  - Structural brace and scope queries read the conditioned text: `features/symbols.py:59`, `analysis/resolution.py:89-102`, `:195` and `:207`, and `features/completion.py:386`. The cursor-line helpers (`features/signature_help.py:197`, `:266`) stay raw.
  - P1–P4 and the package-define form of I3 are compile diagnostics only, because one file lacks the program.
  - There is no inactive-region shading: LSP has no standard request for it, and the TextMate grammar already colors every directive (`src/devex/vscode/config/grammar.json:82`).
- **Formatter** (`src/devex/formatter/engine.py:974-1000`). It has no target.
  - A conditional region runs from `#if…` through its `#endif`, nested regions included.
  - A region is formatted normally when every group, taken alone, is balanced in `{}`, `()` and `[]`. Each group is indented from the depth at the opening directive.
  - Otherwise the region is kept verbatim, and the depth after `#endif` adds the first group's net delta.
  - An unterminated region runs to end of file and is kept verbatim.
  - Directive lines stay at column 0, as every preprocessor line does today.
- **Tools.**
  - `FrontendMain` conditions with its `--target`. `LexMain` and `ParseMain` stay raw.
  - The verifier's selection regex (`tools/compiler_codegen/verification.py:1663-1666`) also skips a source with a candidate line. That regex is used by `test_lexer_corpus_parity.py:26-31` and `verify-lexer`. The skip is needed because the reference side is `--emit-tokens`, which now conditions, while `LexMain` stays raw.
  - `test_corpus_strict_imports.py` conditions each file with the host target before `Parser(Lexer(…))` (`:163`) and before the `glob_consumers` scan (`:145-153`).

## Refusals

The text is identical in both compilers, and positions follow the conventions.

**Directive structure and shape**

| # | Case | Diagnostic |
|---|------|------------|
| D1 | stray `#endif`, `#else` or `#elif` | `'#endif' without '#if'` (also `'#else'`, `'#elif'`) |
| D2 | `#elif` after `#else` | `'#elif' after '#else'` |
| D3 | second `#else` | `'#else' after '#else'` |
| D4 | unterminated | `'#if' without '#endif'` (spelled as opened: `'#ifdef'`, `'#ifndef'`) |
| D5 | `#ifdef`/`#ifndef` with no name, a non-identifier, `true` or `false` | `'#ifdef' needs a macro name` / `'#ifdef' needs a macro name, got '3'` |
| D6 | tokens after the name | `'#ifdef' takes one macro name; unexpected 'Y'` |
| D7 | operands on `#else` or `#endif` (`#else if X`) | `'#else' takes no operands; unexpected 'if'` |
| D8 | empty evaluated `#if` or `#elif` | `'#if' needs an expression` |
| D9 | C23 forms, at every level | `'#elifdef' is C23; write '#elif defined(NAME)'` / `'#elifndef' is C23; write '#elif !defined(NAME)'` |
| D10 | a splice where the shape checks forbid one | existing `multi-line preprocessor directives are unsupported` (now positioned) |
| D11 | trigraph in a conditional directive | existing `C11 trigraphs in preprocessor directives are unsupported` (now positioned) |
| D12 | live `#error` | `#error <payload>`, with comments replaced by one space and then trimmed; `#error` alone when empty |
| D13 | no target | `preprocessor conditionals need a target; this host is not a btrc target, so pass --target OS-ARCH` |
| D14 | `%:` or `??=` introducing a line | `'%:' is not supported as a spelling of '#'; write '#'` (or `'??='`) |
| D15 | unclosed `/*` | `a comment in a preprocessor directive must close on the same line` |
| D16 | comment between `#` and the name | `a comment between '#' and the directive name is unsupported` |
| D17 | `\f` or `\v` after the `#` | `only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)` |

**Expressions**

| # | Case | Diagnostic |
|---|------|------------|
| E0 | payload or replacement does not lex | the lexer's message (`Invalid digit '8' in octal literal`, `Unterminated string literal`, …) |
| E1 | adjacent operands | `Missing operator before 'X' in #if expression` |
| E2 | missing operand | `Expected an operand in #if expression, got ')'` |
| E3 | trailing operator | `#if expression ends after '+'; expected an operand` |
| E4 | `(` not closed | `Unmatched '(' in #if expression` |
| E5 | stray `)` | `Unmatched ')' in #if expression` |
| E6 | `?` without `:` | `'?' in #if expression needs ':'` |
| E7 | assignment, `++`, `--`, `,`, `.`, `->`, `?.`, `??`, `=>`, `[ ] { } ;`, `:` outside `?:`, `#`, `##`, `%:`, or an annotation | `'++' is not allowed in a #if expression` |
| E8 | string or f-string | `A string literal cannot appear in a #if expression` |
| E9 | floating constant | `Floating constant '1.5' in #if expression; #if needs integer constants` |
| E10 | character constant above 127 | `Character constant '\xff' in #if has a target-dependent value; write its integer value` |
| E11 | out-of-range integer | existing `Invalid integer literal '18446744073709551616'` |
| E12 | `sizeof` | `sizeof cannot be evaluated in #if; test a target macro such as __SIZEOF_INT__` |
| E13 | `defined` without a name, or with `true`/`false` | `'defined' needs a macro name` / `…, got '3'` |
| E14 | `defined(X` | `'defined(' needs a closing ')'` |
| E15 | wide character constant | `Wide character constant L'a' in #if; write its integer value` |
| E16 | expansion over 4,096 tokens and macro invocations | `#if expression expands to more than 4096 tokens` |

**Identifiers**

| # | Case | Diagnostic |
|---|------|------------|
| I1 | D20 | `Identifier 'X' in #if is not a macro defined earlier in this file or a target macro; test it with defined(X)` |
| I2 | reserved, not in the table (`__GNUC__`, `__LINE__`, `__has_include`) | `'__GNUC__' is reserved for the C implementation and is not a btrc target macro; #if cannot test it` |
| I3 | foreign (`PATH_MAX`, `isdigit`, `NDEBUG`, `TARGET_OS_IPHONE`, `bool`) | `'PATH_MAX' is defined by C headers or C compiler flags, not by btrc; #if is evaluated before C compilation and cannot test it`; for a package define: `'EXAMPLE_ABI' is a C compiler define of package 'example'; #if is evaluated before C compilation and cannot test it` |
| I4 | function-like macro | `Function-like macro 'VERSION' cannot be used in #if; btrc expands only object-like macros there` |
| I5 | empty replacement | `Macro 'FEATURE' expands to nothing in #if; test it with defined(FEATURE)` |
| I6 | self-reference, naming the macro that would be re-expanded | `Macro 'X' expands to itself in #if` |
| I7 | `defined` produced by expansion | `Macro 'X' expands to 'defined'; C11 leaves that undefined` |
| I8 | token pasting | `Macro 'X' uses '##', which #if does not evaluate` |

**Arithmetic** (evaluated operands only)

| # | Case | Diagnostic |
|---|------|------------|
| A1 | zero divisor | `Division by zero in #if expression` / `Remainder by zero in #if expression` |
| A2 | signed overflow | `Integer overflow in #if expression` |
| A3 | shift count | `Shift count 64 is out of range in #if expression` |
| A4 | negative left shift | `Left shift of negative value in #if expression` |
| A5 | negative value made unsigned | `#if expression converts negative value -1 to unsigned for '<'` (`'?:'` at `?`) |

**Program checks**

| # | Case | Diagnostic |
|---|------|------------|
| P1 | defined in another file | `'USE_FAST' is defined in Config.btrc, but #if in Main.btrc cannot see it; #if sees only target macros and #defines earlier in the same file` |
| P2 | native header name | `'X' comes from a native header; #if is evaluated before C compilation and cannot test it` |
| P3 | C evidence | `'HAVE_X' may come from C that btrc does not read ("config.h" in Main.btrc); #if is evaluated before C compilation and cannot test it`; the parenthesis may instead read `(helpers.c imported by Main.btrc)` or `(native header example.h for Main.btrc)` |
| P4 | `#undef`'d in another file | `'M' is #undef'd in X.btrc, but #if in Main.btrc cannot see that; #if sees only #defines and #undefs earlier in the same file` |

**Source macros and code**

| # | Case | Diagnostic |
|---|------|------------|
| M1 | non-identical redefinition | `Macro 'N' is redefined with a different replacement; #undef it first (C11 6.10.3p2)` |
| M2 | `#undef` of a name that no non-stdlib btrc source defines | `#undef of 'max' is not allowed; btrc undefines only macros that its own sources #define` |
| M3 | `#define`/`#undef` of `defined` | `'defined' cannot be #define'd or #undef'd (C11 6.10.8p2)` |
| M4 | `#define`/`#undef` of a foreign macro name | `'NDEBUG' is set by C headers or compiler flags; btrc sources cannot #define or #undef it` |
| — | keyword; `BTRC_` prefix | existing `'int' is a reserved word and cannot be used as a name`; existing `Macro name 'BTRC_X' uses the compiler-reserved 'BTRC_' prefix` / `Source #undef of compiler-owned C symbol 'BTRC_X' is not allowed` |
| U1 | code use of an `#undef`'d macro | `Source macro 'WRAP' cannot be used in code because it is #undef'd; btrc emits every #define and #undef before the program` |
| U2 | code use through another macro | `Source macro 'A' cannot be used in code because it expands to #undef'd macro 'WRAP'; btrc emits every #define and #undef before the program` |
| U3 | malformed `#undef` (lowering, unpositioned like its siblings) | `malformed #undef directive: #undef X Y` |
| B1 | a live directive anywhere but file scope | `Preprocessor directive '#define' must be at file scope`, at its `#`, in both parsers |

**Retired diagnostics:**
- `unsupported preprocessor directive '#…'` is no longer produced from source for the conditional names or for `#undef`. The lowering invariant keeps it reachable.
- The two divergent body parse errors are replaced by B1.
- The message stays for `#line`, `#warning` and the rest. The null directive `#` keeps `malformed preprocessor directive`.

**C that btrc rejects on purpose.** `docs/known-language-gaps.md` gains row 18. Each item gets a test in `test_c_compatibility_refusals.py`:
- I1 (C reads 0);
- I2 and I3 (including `__LINE__`);
- I4, I6 and I8;
- E7's comma in an unevaluated operand;
- E10 and E15;
- A4 and A5;
- P1–P4;
- M2;
- U1 and U2;
- D9, D10, D14, D16 and D17 in dead groups;
- dead groups that do not lex;
- the null directive.

Documented deviations sit beside them:
- `true`/`false` have their C23 values;
- `0b`/`0o` constants are accepted;
- `#include "X.btrc"` is not textual for `#if`;
- C that btrc does not read cannot change what `#if` read;
- a system macro outside the hosted ABI, tested with `defined`, reads 0.

## Spec commit (`ccompat-r18-spec`) and IR

**Status (2026-10-03).** The spec commit has landed on lane `stage16/c4-spec` (packet CL-C-03): `src/language/targets.toml`, `TargetManifest` and `TargetUnion` in `tools/compiler_codegen/hosted_abi.py`, the generated tables, test 3 (`test_target_macro_table.py`) and the spec-rule, generated-row, `PackageTarget` and width checks in `test_hosted_abi_contract.py`. No compiler behavior changed. `stdlib_symbols.py` and `builtins.py` merge per-target results through `TargetUnion`; since the behavior commit (`ccompat-r18-preprocessor-conditionals`) each target reads its own conditioned parse. That commit also added the union of `test_hosted_abi_contract.py`'s prototype scan, btrc's `ensureStdlibIndex` fallback and the generated-source check's per-target stdlib conditioning.

**No ASDL change.** The grammar gains only the `@syntax` comment block above.

**`src/language/targets.toml`.** Spec fields are spelled as the generated fields, so each is named once (AGENTS.md, Naming):

```toml
# Compilation targets shared by both compilers (PLAN.md D21). Generated
# catalogs are data-only; edit this file. PLAN.md Stage 24 adds ios and
# android rows, environments, triples, sysroots and data models.
schema_version = 1

[[targets]]                       # one row per (os, arch); six today
operating_system = "linux"
architecture = "x86_64"

# Target predefined macros (D20): with a file's own earlier #defines, the only
# names #if evaluates. Values are gcc's and clang's at -std=c11. An omitted
# selector selects every value; environments stays empty until Stage 24.
[[predefined_macros]]
name = "__linux__"
value = 1
operating_systems = ["linux"]

[conditionals]
undefined_macro_names = ["__ANDROID__", "__cplusplus"]   # reserved; no target defines them
foreign_macro_names = ["NDEBUG", "TARGET_OS_MAC", "bool", "..."]   # set by headers or flags
```

**Rows.** Every value is 1 unless stated. Each row was checked against clang 21.1.8 `-std=c11 --target=<triple> -dM -E` for the six triples (Windows as `*-w64-windows-gnu`), and against gcc 15.2 on the host.

| Name | Selection |
|------|-----------|
| `__linux__`, `__linux`, `__unix__`, `__unix`, `__ELF__` | linux |
| `__APPLE__`, `__MACH__` | macos |
| `_WIN32`, `_WIN64` | windows |
| `__x86_64__`, `__x86_64`, `__amd64__`, `__amd64` | x86_64 |
| `__aarch64__` | aarch64 |
| `__arm64__`, `__arm64` | macos and aarch64 |
| `__CHAR_UNSIGNED__` | linux and aarch64 |
| `__CHAR_BIT__`=8, `__SIZEOF_SHORT__`=2, `__SIZEOF_INT__`=4, `__SIZEOF_LONG_LONG__`=8, `__SIZEOF_POINTER__`=8, `__SIZEOF_SIZE_T__`=8, `__SIZEOF_PTRDIFF_T__`=8 | every target |
| `__ORDER_LITTLE_ENDIAN__`=1234, `__ORDER_BIG_ENDIAN__`=4321, `__ORDER_PDP_ENDIAN__`=3412, `__BYTE_ORDER__`=1234 | every target |
| `__STDC__`=1, `__STDC_VERSION__`=201112 | every target |

**Left out on purpose.** Each is I2 until a later stage adds it.
- **Toolchain or invocation identity:** `__GNUC__`, `__clang__`, `__MINGW32__`, `__MINGW64__`, `__STDC_HOSTED__`, `__OPTIMIZE__`, `__gnu_linux__`.
- **The data model:** `__SIZEOF_LONG__`, `__SIZEOF_WCHAR_T__`, `__LP64__` and `_LP64`.
  - Both analyzers take `long` from the host. In a Linux → windows-x86_64 cross compile, `#if __SIZEOF_LONG__ == 4` would select LLP64 code that the analyzer types as LP64.
  - Stage 24 adds data-model columns to `[[targets]]` and generates these four from them. It also switches `CIntegerWidths` and btrc's limits to the target row.
- **`__SIZEOF_LONG_DOUBLE__`:** MinGW and MSVC disagree on windows-x86_64.

**`foreign_macro_names`** holds:
- `bool`, `NDEBUG`, `WINAPI_FAMILY` and `TARGET_IPHONE_SIMULATOR`;
- the public `<TargetConditionals.h>` names:
  - `TARGET_OS_{MAC, OSX, IPHONE, IOS, MACCATALYST, TV, WATCH, VISION, BRIDGE, DRIVERKIT, SIMULATOR, EMBEDDED, UNIX, WIN32, LINUX, WINDOWS}`;
  - `TARGET_CPU_{ARM, ARM64, X86, X86_64, PPC, PPC64}`;
  - `TARGET_RT_{64_BIT, LITTLE_ENDIAN, BIG_ENDIAN, MAC_MACHO, MAC_CFM}`.

**Generator rules** (raised in the `HostedAbiManifestError` style):
- `(operating_system, architecture)` pairs are unique.
- Selector values name values that exist in `[[targets]]`. `environments` is absent or empty.
- A predefined-macro name is reserved: it starts with `__`, or with `_` and an uppercase letter.
- Values lie in [0, 2⁶³−1].
- Rows that share a name select disjoint targets.
- `undefined_macro_names` are reserved and appear in no row.
- `foreign_macro_names` are not reserved, and collide with no row and no hosted-ABI name.
- Lists are sorted and unique.

**Generated forms.**
- **Python:** the row classes `GeneratedTargetRow(operating_system, architecture)` and `GeneratedPredefinedMacroRow(name, value, operating_systems, architectures, environments)`. Also the tables `TARGET_ROWS`, `TARGET_PREDEFINED_MACRO_ROWS`, `TARGET_UNDEFINED_MACRO_NAMES`, `TARGET_FOREIGN_MACRO_NAMES` and `TARGET_SPEC_FINGERPRINT`.
- **btrc:** the same row classes with camelCase public fields; `value` is a `long long`. `GeneratedHostedAbiData` gains the memoized `targetRows()`, `predefinedMacroRows()`, `undefinedMacroNames()` and `foreignMacroNames()`, plus a `targetSpecFingerprint` field. They are emitted through small methods, like the existing tables.
- Selection and classification belong to the environment owners, never to generated data.

**Docs in this commit.** `targets.toml` joins PLAN.md's shared-spec list (`PLAN.md:1347`) and the "Shared specs" sections of AGENTS.md and CLAUDE.md.

**IR (in the behavior commit).**

| Python `ir/nodes.py` | btrc `ir/Model.btrc` | Meaning |
|----------------------|----------------------|---------|
| `IRMacroUndef(name: str)`; `preprocessor_decls: list[IRInclude \| IRMacroDef \| IRMacroUndef]` | `IR_PREPROCESSOR_UNDEF = 3`; `IRPreprocessorDecl.undef(name)`, reusing `name` | `#undef NAME` |

`IRVerifier` (`ir/verifier.py:228-236`) accepts the new node and checks that its name is a C identifier. The freestanding include checks (`c_emitter.py:434-445`) test `isinstance(…, IRInclude)` instead of "not an `IRMacroDef`".

## Consumers to update

**Spec and codegen** (serial; the only writer of `hosted_abi.py`):
- `src/language/targets.toml` (new);
- `tools/compiler_codegen/hosted_abi.py` (`TargetManifest`: load, validate, render);
- `tools/compiler_codegen/main.py`;
- `tools/compiler_codegen/stdlib_symbols.py` and `builtins.py` (union over targets);
- the generated `abi/generated.py` and `generated/hosted_abi/Tables.btrc`.

**Python:**
- **Frontend:**
  - `frontend/sources.py`: the owners and values; `PreprocessorConditionalError`; `ResolvedSource.conditional_tests` and `cache_identity()`; the environment, which `SourceResolver.resolve` builds from `packages.native_plan.target` and the package graph; the stdlib sites; `SourceFileReader`'s normalization as a class method.
  - `frontend/imports.py`: `_open_frame` conditions before `scan`.
  - `frontend/stage.py`: `verify_tests` after parse, before visibility.
- **Application:**
  - `application/compiler.py` and `pipeline.py`: map the error to a positioned `SYNTAX` failure; `build_stdlib_archive` conditions with its target.
  - `application/modules.py`: `SharedDeclarations.merge_into`, `trim_native_includes` and `runtime_module` use the whole directive list and never deduplicate macros.
- **Parser:** the `Parser._parse_*` body sites give B1.
- **Analyzer:**
  - `program.py`: `SourceMacroNamespace.undefined`;
  - `declarations.py`: `collect` (M1, M2, `#undef` records), `_validate_mutation` (M3, M4), the `BTRC_` prefix;
  - `expressions.py` identifier acceptance (`:855`, `:1590`);
  - `macros.py` `plan_call` (`:49`);
  - `calls.py` default arguments (`:1289`).
- **IR:**
  - `ir/nodes.py`;
  - `ir/verifier.py:228-236`;
  - `ir/optimizer.py`: the macro-replacement scans and `:720-746` skip undefs;
  - `ir/lowering/translation_unit.py:456-457`, and `:861-888` for `#undef`, U3 and the D15/D17 checks;
  - `backend/c_emitter.py:434-445`, `:1082-1115`.
- **LSP:** `workspace/units.py` (normalize, condition, `conditioned_source`), `workspace/cache.py` (key), `workspace/workspace.py` (lazy environment), `features/symbols.py`, `features/completion.py`, `analysis/resolution.py`.
- **Formatter:** `formatter/engine.py`.

**btrc:**
- **Frontend:**
  - `frontend/Models.btrc`: the values and `FeResolvedSource.conditionalTests`;
  - `frontend/Resolver.btrc`: the owners, `openFrame`, stdlib composition, and `FeFrontendResolver` taking the environment;
  - `frontend/Visibility.btrc`: the `ensureStdlibIndex` union.
- **Parser:**
  - `parser/Parser.btrc` (B1);
  - `parser/SourceMacros.btrc`: a public `replacement()` accessor and the identity comparison for M1.
- **Pipeline:**
  - `pipeline/Pipeline.btrc`: the environment from `options.target`, the package graph and `HostedAbiRepository`; `verifyTests` after parse, before visibility;
  - `pipeline/ModuleUnits.btrc:632-657`, `:698-699`, `:739-746`: the whole directive list, with no macro deduplication;
  - `tools/FrontendMain.btrc`;
  - `cli/Driver.btrc`: render conditioning errors.
- **Analyzer:**
  - `analyzer/SourceMacros.btrc`: `undefined`, M1–M4, `BTRC_`;
  - `analyzer/validation/Expressions.btrc:915-934`;
  - `analyzer/validation/Calls.btrc:1039-1043`, `:1124`.
- **IR:**
  - `ir/Model.btrc`;
  - `ir/lowering/Declarations.btrc:4447-4452`, `:4565-4605`;
  - `ir/Emitter.btrc:412-427`;
  - `ir/optimization/Optimizer.btrc:257`, `:459`, `:705`;
  - `ir/runtime/References.btrc:183`;
  - `ir/runtime/Catalog.btrc:215`.

**Docs:**
- this section;
- known-language-gaps row 18 and its deviations;
- the `grammar.ebnf` `@syntax` block;
- the owner descriptions for `sources.py` and `Resolver.btrc` in `docs/design/compiler-structure.md` (the inventory is unchanged);
- PLAN.md D20's row (the evaluated-operand reading).

## Test plan

1. **Corpus.** `src/tests/c_compat/PreprocessorConditionals.btrc` with `expected/PreprocessorConditionals.stdout`. Its output is the same on every target. It runs through `make test` in both compilers and through `make test-c11` (8 cells). It covers:
   - `#if 0` hiding a duplicate function;
   - `#ifdef`/`#else`, and `#ifndef`/`#define` defaults;
   - `#if`/`#elif`/`#else` chains on object-like macros;
   - `defined(__linux__) || defined(__APPLE__) || defined(_WIN32)`;
   - tests of `__CHAR_BIT__`, `__STDC_VERSION__` and `__BYTE_ORDER__`;
   - truncating `/` and `%`, the unsigned hex constant, `'A' == 65` and `true`;
   - conditionals inside a function body, a class body and a struct body, between operands, in a `switch`, and around a braceless body;
   - nested dead groups holding an `#elif` that would not evaluate;
   - an environment-only `#undef`;
   - an identical redefinition.
2. **`src/tests/btrc/test_preprocessor_conditionals.py`** (both compilers):
   - **Per-target selection.** One fixture × six targets. `FrontendMain --target T` must equal the reference's resolved `.source` byte for byte. Both emitted C files must contain exactly the selected functions and `#include` lines. This needs no C compile and no SDK.
   - **Dead imports.**
     - A dead `import ./Missing.btrc;` compiles.
     - A dead import of a file with conflicting symbols adds nothing.
     - The reference graph has no edge for it.
     - `--emit-link-plan` sources are identical in both compilers.
   - **Diagnostics.**
     - Every row above, with identical message, line and column.
     - A new multi-file helper beside `compile_diagnostic_pair` (`production_readiness_harness.py:149-157`) writes several files. It covers P1–P4, positions in imported files, and resolution order.
     - D13 runs through a unit seam with an empty target in btrcc. The reference's host error is pinned separately, because CI has no unsupported host.
   - **Fast path.** The fast and slow paths give identical text and messages over the corpus plus fixtures for every shape check: `#\`, `#/**/if`, `%:if`, `// …\` before `#else`, and `#define X 1 /* open`.
   - **C oracle.**
     - About 40 expressions, each written as `#if E` / `int s = 1;` / `#else` / `int s = 0;` / `#endif`.
     - Each must be accepted by `gcc` and `clang -std=c11 -pedantic-errors -E -P`, and each compiler's selection must equal theirs.
     - The shape cases (`gccprobe/comment.c`, `linecomment.c`, `digraph.c`, `formfeed.c` in `wf_926e5dfc-b6e`) must be refused.
     - `true`, `0b`, A4 and A5 are pinned separately.
   - **Macros.** M1 within a file and across files; M2–M4; U1 and U2 in every use position; the order of emitted `#undef`s.
   - **Module units.**
     - Group A holds `#define X 1` / `#undef X` / `#define X 2`. Group B holds its own `#undef X` and no code use of X.
     - Every unit's directive list must equal the whole-program list and build under strict C11.
     - A `#define CFG` / `#include "lib.h"` pair split across groups keeps its order.
   - **Caches.** Counters are Python `module_units_lowered`/`reused` and btrcc `{"lowered", "reused"}`, after `test_module_units.py:214`, `:316`.
     - A warm cache across a target switch equals a cold compile.
     - Editing a live non-directive line inside a conditional group re-lowers exactly that group.
     - Editing a live directive re-lowers every group.
     - An edit confined to a dead group gives a Python whole-program hit. In btrcc it is an artifact miss that reuses every unit. The C is byte-identical in both.
     - That dead-group edit combined with a live edit in another group lowers exactly the other group.
     - The whole-program cache misses on a target switch.
     - btrc `ValidationRecords` replay across a dead-group edit.
     - Two variants with identical conditioned text, where one has an absent `#ifdef` beside a C include: a warm compile of that variant still gives P3 in both compilers.
   - **Directive cache.** The `DirectiveCacheDriver.btrc` fixture gains a conditioned mode. One raw text under two targets gives two entries, and a restore never brings back a dead import.
   - **Lowering invariant.** A hand-built `PreprocessorDirective("#if 1")` still gets `unsupported preprocessor directive '#if'` in both lowerers. D15 and D17 in live `#define`s get the same text from lowering.
3. **`src/tests/python/test_target_macro_table.py`.**
   - For each target, the test takes every name in the table, in `undefined_macro_names` and in the "left out" list. Of those, `clang -std=c11 --target=<triple> -dM -E` must define exactly the ones the table selects for that target, with the table's values. `__BYTE_ORDER__` is resolved through its reference, and `L` suffixes are stripped.
   - The left-out names are only checked to be absent from the table.
   - Host gcc must agree on its own target.
   - The Windows triples are `x86_64-w64-windows-gnu` and `aarch64-w64-windows-gnu`. `x86_64-pc-windows-msvc` does not define `__STDC__`, so a switch to MSVC revisits that row.
   - The triples live in the test until Stage 24 puts them in the spec.
   - A missing clang is a classified skip in the skip ledger.
4. **Python units:** the expression battery, blanking, LF normalization in the LSP, the fast-path regex, the symbol-index union, and `test_hosted_abi_contract.py`'s spec rules and width check.
5. **Inventory** (`c3_c4.toml`, `test_c_compatibility_inventory.py`). The inventory compiles with the host target, so every r18 outcome must be target-independent.
   - `r18-if-zero` and `r18-ifdef-else` become `accepted`. They move into `c_compat/` as `corpus` references (`test_c_compatibility_inventory.py:34-37`).
   - `r18-undefined-identifier-in-if` becomes intent `positive` and status `refused-on-purpose`, with I1 at 1:5.
   - New probes:
     - target selection;
     - a body conditional;
     - `#ifdef __GNUC__`;
     - a function-like macro in `#if`;
     - a live `#error` (negative);
     - an unterminated conditional (negative);
     - an `#undef`'d macro used in code;
     - a negative left shift;
     - `#define N 1` / `#define N 2` (negative).
   - `REFUSAL_ROWS` gains `"18"`. The refusal tests gain the I, A, P, M and U rows and D9, D10, D14, D16 and D17.
6. **Flipped tests:**
   - `src/tests/btrc/test_parser_diagnostics.py:216-221` now expects D4 (`'#ifdef' without '#endif'` at 1:1) in the rendered form.
   - `src/tests/python/test_ir_declarations.py:289` becomes a U3 case.
   - `src/tests/btrc/test_source_macro_semantic_boundary.py:195-207` and its Python twin `src/tests/python/test_source_macro_semantic_boundary.py:112-118` now expect U1.
   - `src/tests/python/test_main.py:680-690` keeps testing "no traceback", now with `#line 1`, which lowering still refuses. Its old `#undef UNSUPPORTED` would now be M2.
7. **LSP and formatter.**
   - LSP (`src/tests/lsp/`):
     - a dead duplicate gives no diagnostic;
     - hover on a dead line is null;
     - symbols and brace scopes exclude dead declarations;
     - a D4 diagnostic sits at its position;
     - a CRLF buffer conditions like its LF form;
     - the unit-cache key includes the target and the environment identity;
     - an unsupported host does not crash a file without conditionals.
   - Formatter (`src/tests/formatter/`): balanced and unbalanced regions, with idempotence.
8. **Gates:**
   - the generated-source check, including the stdlib-for-every-target rule;
   - lint;
   - format, including `format-btrc-check` on the corpus file;
   - the full matrix;
   - the bootstrap fixed point;
   - zero analyzer warnings on the `BtrccMain`, `cli/WindowsMain` and `cli/MacOSMain` transpiles.

   Tests that need the native reader (P2, and P3's binding evidence) add their skips to `fixtures/expected-skips/{macos,linux-devcontainer,windows}.json`.

## Memory impact

- **btrc `Node`: 0 bytes.** There is no AST change.
- **IR.** btrc `IRPreprocessorDecl` gains a kind constant and no field. Python gains `IRMacroUndef`. Each module unit now carries the whole directive list: a few lines per unit for programs whose groups hold directives, and nothing for the compiler or BTRSmith.
- **Tables:** six target rows, about 40 macro rows and about 40 foreign names, built on first use.
- **Analysis:** the `undefined` set and the test records, which are empty for programs without conditionals.
- **Cost.** Compiler, stdlib and BTRSmith sources have no candidate line, so each file pays one indexed byte scan. Slow-path files pay one extra raw lex.
- **Evidence:**
  - Stage 15's method, at the behavior commit:
    1. Build btrcc from the parent and from the commit, naming the C compiler that built each.
    2. Run three alternating `--target linux-x86_64 --no-cache` compiles of `BtrccMain.btrc` with each.
    3. Measure peak RSS and user CPU through `wait4`.
  - On the Mac, the quiet M11 re-measure: Stage 3 `budget_bench`, no-op and edit, both frontends, instructions retired and peak footprint at `--jobs 1`.
  - ≤0.3% passes, per the standing approvals.

## Boundary records

The manifest holds 311 records, and none changes:
- **AST and tokens.** No boundary source contains a candidate line. `managed.source`'s `#include <assert.h>` takes the fast path, so its tokens and AST are unchanged.
- **IR and C.** No boundary program has an `#undef`, or directives in more than one group. So `preprocessor_decls` and the emitted directive order are unchanged. Python's widened list annotation does not render.
- **Diagnostics.** The boundary error sources contain no directive. `lexical_error.source` keeps the main lexer's error, because it takes the fast path.

Outside the manifest:
- The `c3_c4.toml` r18 entries flip, with `revision` set to the behavior commit's parent.
- `KNOWN_DIVERGENCES` is unchanged.
- btrcc's own C changes with the tables and the evaluator, so both commits re-prove the bootstrap fixed point.

## Lanes and merge order

1. **`ccompat-r18-spec`.** Serial; the spec owner writes it, with one parity reviewer.
   - Contents: `targets.toml`, the generator, the generated modules, test 3, the spec-rule and width parts of test 4, and the shared-spec list updates.
   - No behavior change.
   - Gates: the generated-source check, the btrcc fixture rebuild, the bootstrap fixed point, zero analyzer warnings.
2. **Module-unit directive order.**
   - One commit for both compilers, by the C4 lane agent, who holds the `pipeline/ModuleUnits.btrc` + `application/modules.py` hotspot for the stage.
   - Contents: the whole-list rule and its test, without `#undef`.
   - It fixes the existing `#define`/`#include` ordering bug on its own, so it lands and gates before the evaluator. Gates: `test_module_units.py` and the corpus under `--module-units`.
3. **`ccompat-r18-preprocessor-conditionals`.**
   - One lane: Python first, then the btrc port by the same agent, in one commit per D5.
   - Contents: everything else.
   - One parity reviewer covers semantics, positions, caches and the C oracle, reusing the lane's btrcc.
4. **Measurement record:** the memory run and the quiet M11 re-measure, in the PLAN progress log.

**Stage 16 C4 exit:**
- live branch selection per target is identical in both compilers (test 2, per-target selection);
- a dead-branch import adds no edge, and a dead duplicate no longer errors (test 2, dead imports; corpus);
- an unevaluable identifier gives the named diagnostic in both compilers (I1; inventory);
- caches invalidate correctly (test 2, caches and directive cache);
- the quiet M11 re-measure shows no regression (step 4);
- the full matrix passes on the final tree.

## Python half and the btrc port (CL-C-05 → CL-C-06)

**Status.** Both halves landed together in the construct commit `ccompat-r18-preprocessor-conditionals` (CL-C-05 and CL-C-06, lane `stage16/c4-conditionals`).

**Status (CL-C-06).** The btrc port matches every table above: `ConditionalExpressionDriver.btrc` runs the battery and conditions whole files (the directive rows, blanking, the shapes and the corpus program), and btrcc gives every `DIAGNOSTIC_CASES` row with the same message, file and `line:col`. Choices the port made where the languages differ:
- btrc has no exceptions in the compiler, so `FeConditionalExpression` keeps the first failure (`FeConditionalFailure`) and every step returns once one is recorded; the resolver prints it through `FeVisibilityDiagnostic.render()` and exits 1, like its other resolution errors, and `FeConditionalTestChecker` (P1-P4, `frontend/Visibility.btrc`) returns it to `CompilerPipeline`.
- `SourceMacroRules` lives in `parser/SourceMacros.btrc` beside `SourceMacroDefinition`, built by `CompilerPipeline` from the vocabulary, `HostedAbiRepository.ownedNameSet()` and the spec's foreign names; conditioning and `SourceMacroNamespace` share it. The namespace renders M1-M4 and U1/U2 at their own file's position, as the reference does.
- A record joins an evaluation once through `FeConditionalTest.recorded`, the btrc form of Python's identity check.
- The lowering invariant is driven by `LoweringInvariantDriver.btrc`, which hands `CompilerPipeline.compileResolved` a composed source that conditioning never saw.
- The generated-source check (`StdlibSymbolIndexGenerator.verify_conditions`) conditions every stdlib module for every target, and refuses an `#undef` or a test of an absent name.
- Two C11 gaps found by the CL-C-06 soundness review are closed in both compilers. A `\` or `??/` that only spaces and tabs separate from the newline is a splice to gcc and clang (they only warn), so the preceding-line rule and the dead-directive check give D10 for it too. A hexadecimal constant ending in `e`/`E` directly followed by `+`/`-` (`0x1e+1`) is one invalid preprocessing number in C (6.4.8), which btrc's lexer splits; `#if` refuses it as E11, spelled `'0x1e+'`.

**Where the diagnostics are pinned.** The port must reproduce every message and file-local `line:col` in these tables, which are the complete list:
- `src/tests/btrc/fixtures/conditional_expressions.tsv`: the expression battery (values and E, I and A errors), for `ConditionalExpressionDriver.btrc`.
- `src/tests/btrc/test_preprocessor_conditionals.py`: `DIRECTIVE_ERRORS` (D1–D17, the raw lex in a dead group, in-file M1, M3, M4, the keyword and `BTRC_` rules), `DIAGNOSTIC_CASES` (I1 and its imported-file position, resolution order, the package form of I3, P1, P3 for a quoted include and a C import, P4, cross-file M1, M2–M4, U1 in code, a call and a default, U2, B1), and the lowering invariant.
- `src/tests/python/test_source_macro_semantic_boundary.py`: M1 and U1/U2 through the analyzer.

**Choices the design left open, which the port copies.**
- *Shape checks.* A line takes part when the lexer's first token on it starts at its first non-`[ \t\f\v]` character. In line order: a line starting `%:` or `??=` gives D14 at that character. For a `PREPROCESSOR` token with no name, a `\` or `??/` there gives D10 and `/*` gives D16, at that character. For a conditional name: a preceding line ending in `??/` gives D10 at its first `?` (column `len - 2`), one ending in `\` at that `\`; then the first trigraph (D11); then a splice (D10 at the `\`, or the first `?` of `??/`, before the token's first newline); then the first `\f` or `\v` after the `#` (D17); then the first unclosed `/*` (D15).
- *Live `#define` and `#undef`.* The preceding-line splice check (D10) also applies to them, before their name rules: C would read such a directive as `//` comment text, so `#if` would see a macro C does not (review finding). Like every slow-path check, it is not applied in a file without a candidate line.
- *Dead groups.* During the walk a non-conditional directive whose enclosing groups are not all taking gets D10 and then D15. Conditional directives were checked above at every level. D9 is raised before the stack is consulted.
- *Payloads.* Every payload is pre-scanned first; a `#if`/`#elif` hit is E7 at it. For `#ifdef`, `#ifndef`, `#else` and `#endif`, the text before the hit is lexed and the hit becomes the next operand (`unexpected '#'`). D8 is raised when a pre-scanned payload lexes to nothing.
- *Positions left open.* E13 without a name and E14 sit at `defined`; the `got '…'` forms sit at the offending token. E3 sits at the operator after which the expression ends, including a unary one. E4 sits at the `(`, E5 at the `)`, E6 at the `?`, and a stray `:` is E7 at it. A token left over after a complete expression, or before a missing `)`, is E1.
- *Arithmetic order.* Both operands are evaluated before the operator's checks: A5 (left, then right), then A1, then `INTMAX_MIN / -1` (A2). For shifts the count (A3) is checked before A4. A `?:` arm's type is the usual arithmetic conversion of both arms, so `1 ? -1 : 0u` is A5 at the `?`.
- *E15 through a macro* is found while expanding: an `L`, `u` or `U` replacement token adjacent to a character constant gives E15 at the macro name. A5 for `?:` spells the operator `'?:'`, at the `?`.
- *Records.* A record belongs to the atom that produced it: `defined` and `#ifdef` results, and every token of a macro's expansion (each macro expanded, inner ones too, at the outermost name's position). An atom appends its records when it is evaluated, each record once, so the records keep evaluation order. Python's cache text is `path\0name\0line\0col\0` then `1` or `0`.
- *Name rules.* In order: `defined` (M3), a grammar keyword, a compiler-reserved macro prefix (the declaration prefixes plus `BTRC_`; declarations keep the old list, because stdlib enum values use `BTRC_`), except `#define` of the runtime's `#ifndef` hooks `BTRC_RT_GPU_HEADER` and `BTRC_RT_ARENA_BYTES`, a leading `_`, a hosted-ABI owned name, a `foreign_macro_names` entry (M4). One owner, `SourceMacroRules` in `frontend/sources.py`, serves conditioning and the analyzer.
- *M2* allows `#undef` of a name that any non-stdlib `#define` in the program defines, before or after it. *U2* names the first `#undef`'d identifier in breadth-first order over replacement identifiers. *U1* is reported once, at the identifier, also for a call, a default and a constant context such as an enum initializer.
- *B1* fires in two places: when the parser consumes a `PREPROCESSOR` token outside an item start, and when any parse error is raised while the current token is a `PREPROCESSOR` token. The name is the longest identifier after `#` and spaces.
- *P3 evidence order.* A quoted include in the file (a `.c` import is spliced as a quoted include of its absolute path and is excluded), then the first `.c` import by path, then a selected `[[native.headers]]` row (named `modules`, or none while the file lies in the package), then a binding.
- *Positions of P1–P4.* At the tested name, in the testing file; the reference prints them through `CompilerDiagnostic.local`.
- *LSP.* A conditioning error becomes the unit's `lex_error`. The formatter validates a candidate file by parsing it as each spec target conditions it, skipping a target whose conditioning stops at a live `#error` (D12): such a guard refuses that target on purpose. The file fails when no target conditions, or on any other conditioning error.

**Done in CL-C-06** (the list CL-C-05 handed over). Everything btrc; the `ensureStdlibIndex` union over targets; the generated-source check that every stdlib module conditions for every target, holds no `#undef` and records no test of an absent name; the inventory (`c3_c4.toml` r18 rows and the new probes), `REFUSAL_ROWS` and the refusal rows, which the recorder observes through both compilers; the cache cases in both compilers; the directive-cache driver's conditioned mode; P2 and the binding form of P3, which need the native reader; the expected-skip manifests.

## What later stages rely on

- **C2 (Stage 17).**
  - Every `PreprocessorDirective` that reaches the analyzer is live for the selected target, and `undefined(name)` exists.
  - C2's integer-constant owner may fold an object-like source macro that is never `#undef`'d, by parsing its replacement with the language parser. It emits the folded digits, never the macro name.
  - C4 itself evaluates no language constant.
- **Stage 19.**
  - The `...` token stays outside the `#if` token set (E7).
  - `_Alignof` and `_Static_assert` classify as reserved (I2).
  - Wide literal tokens turn E15 into a token-kind check.
- **Stage 20.** A label inside a dead group does not exist; `goto` diagnostics see conditioned text.
- **Stage 24 (`platforms-p1-target-spec`)** extends `targets.toml`, as designed in [platform-target-contract.md](platform-target-contract.md):
  - ios and android rows, triples and sysroots;
  - the `environments` axis (gnu, msvc, simulator);
  - data-model columns that restore `__SIZEOF_LONG__`, `__SIZEOF_WCHAR_T__`, `__LP64__` and `_LP64`, and that drive both analyzers' widths;
  - `__ANDROID__` moves into a row with `operating_systems = ["android"]`;
  - a decision on `__ANDROID_API__`: a value from the API floor, or refused;
  - a decision on whether `TARGET_OS_*` become per-triple rows or stay foreign;
  - the `__STDC__` row, if MSVC is adopted;
  - the iOS and Android triples in test 3;
  - an LSP target setting;
  - `PackageTarget` reading `TARGET_ROWS`.

## Rejected alternatives

| Alternative | Reason |
|-------------|--------|
| Combined, program-order macro environment (C's textual model) | A file's live branches would depend on which file imported it first, and the include guard composes each file once. Per-file caching and module-unit reuse would become context-dependent. |
| Environment from imported files | Imports would have to resolve before their importer's conditionals, cycles would leave half-built environments, and every cache would need the imported environment in its key. P1 and P4 refuse the silent miss instead. |
| A tolerant line scanner for directives (GCC skip mode) | It would be a third implementation of comment, string, f-string and splice structure, needing its own parity proof. The real lexer already has one in both compilers, and C11 requires skipped groups to be valid preprocessing tokens. |
| The macro table in `hosted_abi.toml` | D21 makes the target spec its own file, and Stage 24 would have had to move the table. |
| Target and environment in the directive, stdlib-AST and module-unit keys (the item's step 5) | Redundant: those keys hash conditioned text, which is a pure function of raw text and target. Only the LSP cache hashes raw text, and only Python's whole-program key misses the program checks derived from raw text. |
| Conditioning in `LexMain`/`ParseMain` | They are stage-inspection tools pinned by boundary records. `FrontendMain` already inspects composed text. |
| Function-like macro expansion in `#if` | No consumer, and it would need a full C macro expander in both compilers. I4 can be relaxed later. |
| C's silent 0 for undefined identifiers, compiler macros and header macros | D20, and btrc cannot see what the C compiler or its headers define. |
| Keeping `#undef` refused | The item and the C1 row list it. With hoisted emission it is sound once three things are refused: code use (U1, U2), undefining what btrc did not define (M2), and redefinition (M1). |
| Angle includes as P3 evidence | See the program checks: hosted-ABI macro names already cover system headers, and counting system includes would refuse the default idiom almost everywhere. |
| `_Static_assert`/`#error` cross-checks emitted into C for every value and definedness that `#if` read | Branch selection emits no C that depends on the macro. A definedness check would need a conditional IR node, and Stage 19 owns the `_Static_assert` IR (D20). The one consumer that bakes a value into C (C2) emits the folded value instead. |
| A new owner file for the evaluator | It would change the exact inventories for no ownership gain: `sources.py` and `Resolver.btrc` already own per-file source directives. |

## Review resolutions

`wf_926e5dfc-b6e` had two reviewers: implementability (I) and semantic soundness against C11 (S).

| Finding | Resolution |
|---------|------------|
| (I, blocking) Module units put a unit's own directives first and drop equal duplicates, so `#undef` sequences break under `--module-units` | Accepted. Every unit carries the program's whole list in source order, and only identical `IRInclude`s are deduplicated. It lands first as its own commit, because it also fixes an existing `#define`/`#include` ordering bug. |
| (I) "Editing a guarding `#define` re-lowers exactly its group" fails, because the interface hashes every directive | Accepted. A directive edit re-lowers every group, and "exactly its group" is tested with a live non-directive edit. The dead-group edit is tested per compiler (a Python whole-program hit; full unit reuse in btrcc) and combined with a live edit. |
| (I) Lexing the payload can fail, and no diagnostic is defined | Accepted. E0 reports the lexer's message at the shifted position. `#`, `##` and `%:` are found textually before lexing (E7, I8). A textual pre-scan replaces the proposed sentinel: it needs no column correction and also serves replacement lists. |
| (I) btrcc cannot report file positions for imported files | Accepted. Conditioning errors and P1–P4 render through `FeVisibilityDiagnostic.render()` (checked: `Models.btrc:848-870`; probed `7:22` against `Other.btrc:4:22`). Slow-path files report raw-lex failures themselves. The claim for deferred lexical errors is limited to the root file. |
| (I) Package `[[native.defines]]` are not classified | Accepted. Every define name in the resolved package graph, for every target, is foreign, with an I3 form that names the package (`packages.py:576-582`, `:1343-1355`). |
| (I) P2/P3 miss empty and function-like macros of bound headers | Accepted. Native headers and bindings that the plan selects for the file are P3 evidence, and the message names the header (`native_abi.asdl:25-26` exports only constants). |
| (I) The LSP unit cache would go stale when the table changes | Accepted. The key adds the target label and the environment's identity. `FrontendFingerprint` hashes no ABI data (`sources.py:564-573`). |
| (I) Corpus, catalog and contract scanners raw-parse files | Accepted. `test_corpus_strict_imports.py` conditions with the host target. `builtins.py` and `test_hosted_abi_contract.py` take the union over targets. The `Lexer(` contract covers `tools/compiler_codegen` and both tests. |
| (I) Two flipped tests are wrong or missing | Accepted. `test_main.py` moves to `#line 1`. The Python `test_undef_removes_the_final_active_definition` flips to U1, together with its btrc twin. |
| (I) btrc's frontend would have to import the analyzer for hosted names | Accepted. `CompilerPipeline` passes `HostedAbiRepository`'s names, and the frontend imports only generated data (`Resolver.btrc:3-15`; `HostedAbi.btrc:7-11`). |
| (I) `ValidationRecords` is missing from the cache table | Accepted: listed and tested. It needs no new key component. |
| (I) LSP lexical helpers match braces inside dead groups | Accepted. `FileUnit` keeps conditioned text for structural queries; text before the cursor stays raw. |
| (I) The LSP's eager environment crashes on an unrecognized host | Accepted. The LSP and btrcc both complete the environment only when the walk first evaluates a conditional. D13 therefore appears only for files with conditionals, at that directive. |
| (I) CRLF is unspecified, and "a live `#define` in a CRLF file already fails" | Rejected as stated. Both readers normalize CR to LF (`sources.py:538`; `SourceIo.btrc:205-233`), so lowering's `\r` check is unreachable from files. Resolved with S's rule instead: the LSP normalizes buffers, and conditioning needs no `\r` rule. |
| (I) Columns are code points in Python and bytes in btrc | Accepted. Columns agree on ASCII lines, and the parity batteries are ASCII-only. |
| (I) D10 for an unclosed block comment needs a rule at dead levels | Accepted, as D15, with one textual rule in both compilers. The draft's claim that the check already exists was wrong (`translation_unit.py:861-870`). |
| (I) Several evaluation-order and spelling rules are open | Accepted. The step order fixes the error order. I6 names the macro that would be re-expanded. `#ifdef true` and `defined(false)` give D5 and E13. A directive name is the longest identifier. `#error` comments become a space. `0b`/`0o` are a documented extension. |
| (I) "The analyzer refuses `#define` of fourth-class names" is false | Accepted (`NDEBUG` is not hosted-owned). M4 and the `BTRC_` prefix make the claim true for the spec's names. Package defines conflict in the C build. "This file" deliberately stays ahead of "foreign". |
| (I) The prebuilt stdlib archive ignores `#undef` and composes without a target | Accepted. Stdlib sources contain no `#undef`, M2 forbids undefining stdlib-only macros, and `build_stdlib_archive` conditions with its target. |
| (I) Conditional directives could still reach lowering | Accepted, as an invariant test. The cited path is closed, because slow-path conditioning reports raw-lex failures itself. |
| (I) The test plan has harness gaps | Accepted: a multi-file diagnostic helper; skip-ledger entries for native-reader tests; target-independent inventory probes; accepted probes as corpus references; `ConditionalExpressionDriver.btrc` for the battery. |
| (I) Spec naming would churn in Stage 24, and INT64_MIN cannot be spelled in btrc | Naming accepted: spec fields equal generated fields, `environments` is reserved, and `targets.toml` is added to PLAN.md, AGENTS.md and CLAUDE.md. INT64_MIN is moot: no target predefined macro is negative, so values lie in [0, 2⁶³−1]. |
| (I) `#undef` of native macros escapes U1, and P messages name files ambiguously | Superseded by M2: an `#undef` must name a btrc-defined macro. Messages use the basename of `source_file`, and includes as written. |
| (S, blocking) A redefined value lets `#if` select code for a value the code never sees | Accepted. M1 refuses non-identical redefinition across the program and, earlier, within the file. Today `declarations.py:275` silently overwrites it. |
| (S, blocking) `#undef` is accepted for names the generated C depends on, and `#define defined` transpiles | Accepted: M2, M3, M4, `bool` as a foreign name, and `BTRC_` as a reserved prefix. The emitter's `BTRC_INCLUDE_*` guards and `BTRC_RT_*` features confirm the prefix (`c_emitter.py:1104-1109`, `optimizer.py:720-746`). Conditioning applies the same per-directive predicates to its file, so its environment never holds a refused name. Both owners exclude package `-D` names from those rules, which keeps the fast path unobservable. |
| (S, blocking) Python's whole-program cache skips P1–P3 | Accepted. `cache_identity()` appends the ordered records. btrcc's identity already hashes raw contents (`Compiler.btrc:30-41`). Tested with identical conditioned text. |
| (S) Directive recognition ignores translation phases 2–3 | Accepted. The shape checks (D10, D14–D17 and the preceding-line splice rule) apply at every level, scoped so that the fast path stays unobservable. Lowering gains D15 and D17 for live directives. |
| (S) The fast path is observable through `#\` | Accepted. Candidates include `#` followed by `\`, `??/` or `/*`, and lines starting with `%:` or `??=`. A contract test compares both paths. |
| (S) Payload lex failures have no diagnostic | Accepted, merged with (I)'s finding. Payloads are lexed only when evaluated, which matches gcc and clang on `#elif` after a taken group. |
| (S) The foreign class is too narrow | Accepted. Foreign covers every hosted-ABI name, the spec list (including `bool`), compiler-reserved prefixes and package defines. |
| (S) P3 misses native imports and angle includes | Native headers and bindings are accepted. Angle includes are rejected: C2's evidence rule excludes them for the same reason, hosted-ABI macro names cover system headers, and counting them would refuse the default idiom almost everywhere. The residual is documented. |
| (S) A cross-file `#undef` reaches `#if` silently | Accepted as P4. The records now include this-file names. |
| (S) C that btrc does not read can change macro values btrc consumed | Partly accepted. C4 emits no cross-check, because branch selection bakes nothing into C, and Stage 19 owns the `_Static_assert` IR. The memory-safety half is closed by an obligation on C2: a consumer of a macro's value emits the folded value, never the name. The `#if` view is a documented deviation. |
| (S) There are two representations of target integer widths | Accepted, and extended to `__LP64__` and `_LP64`, which encode the same data model. All four leave the table until Stage 24's data-model columns. A contract test pins the remaining widths to both analyzers. |
| (S) D20's wording conflicts with suppressing I1 in unevaluated operands; comma | Accepted. The evaluated-operand reading is decided here (nothing is read, so nothing is silently 0) and recorded in D20's row. E7's comma refusal is listed. |
| (S) Several valid-C refusals are missing from the list | Accepted. Now listed: I6; E15 (a new targeted message instead of E1); `__LINE__`/`__FILE__` (I2 reworded so it is true for them); the null directive; digraph directives. `__cplusplus` joins `undefined_macro_names`, and `0b`/`0o` are documented. `1.` keeps E7 at `.`: C rejects a floating constant in `#if` too, so only the wording differs. |
| (S) Whitespace inside directives | Accepted. D17 refuses `\f`/`\v` in conditional directives, and lowering refuses them in live ones. The `\r` rule is dropped. |
| (S) State where D9 applies | Accepted: at every level, because clang `-pedantic-errors` rejects a skipped `#elifdef`. |
| (S) Specify directive-name matching | Accepted: the name is the longest identifier after `#` and spaces. |
| (S) Macro expansion is unbounded | Accepted: E16 at 4,096 tokens. |
| (S) btrcc's evaluator must avoid implementation-defined C | Accepted: bit-pattern arithmetic on `unsigned long long`, with the formulations stated. |
| (S) Tighten the oracles | Accepted. `-pedantic-errors` is required, the Windows triples are pinned to `*-w64-windows-gnu`, and the MSVC `__STDC__` note goes to Stage 24. |
| (S) Emit modes, stdlib checks and the body-directive message are unspecified | Accepted. P1–P4 run in every mode that parses. The generated-source check requires every stdlib module to record no test of an absent name for any target. B1 unifies the body-directive refusal. |
