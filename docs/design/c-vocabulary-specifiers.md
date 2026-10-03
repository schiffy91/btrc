# C3 vocabulary and specifiers (Stage 19)

PLAN.md Stage 19 opens with one serial vocabulary commit, `ccompat-c3-schema-vocabulary`. It is the only commit that touches these artifacts:
- `src/language/grammar.ebnf` and `src/language/ast.asdl`;
- the generated `Node` and dataclasses, both canonical renderers and both IR models;
- the C3 columns of `src/language/targets.toml`, the target spec C4 creates;
- `src/language/hosted_abi.toml` and `src/language/intrinsic_effects.toml`;
- the VS Code grammar and the LSP keyword tables.

Those artifacts, and six boundary records, change once. Two serial shared-owner commits follow. After them, the lanes add semantics only.

One drafter and two adversarial reviewers produced this section in workflow `wf_926e5dfc-b6e` on 2026-10-02. One reviewer checked implementability in both compilers; the other checked semantic soundness against C11. The reviews are cited as I-n (implementability) and S-n (semantics). Every finding and its resolution is listed at the end.

The fat `Node` gains no byte. The generator's field planner (`BtrcAstRenderer._build_declarations`) was re-run on the base, C2 and C3 schemas, and `sizeof(Node)` is 760 bytes for all three. The seven new bools fill existing padding, and every other new field reuses existing storage. The 88-file Python inventory and the 97-file btrc inventory do not change: every new owner is a class or method in an existing file.

D19 approves every row, including r14 and Stage 20's r11. D20 is applied as written:
- `auto` is a block-scope no-op;
- `inline` follows C11 under split compilation;
- `_Static_assert` on `sizeof` is evaluated in the front end, refused when no layout is known, and asserted again in the emitted C.

The principles of C1, C2 and C4 carry over:
- one representation per C concept;
- kinds fail closed;
- positions are identical in both parsers;
- every deliberate refusal is documented and tested in both compilers;
- C2's record-member owner, initializer-slot owner and three-way integer-constant query are reused, never duplicated;
- btrc evaluates, but C compiles: whatever btrc cannot see is refused, never guessed (C4).

C3 adds two:
- **A specifier has one home.** Storage classes and base-type qualifiers are `TypeExpr` bools. Per-level pointer qualifiers and `_Alignas` are entries of `TypeExpr.parts`. Function specifiers are `FunctionDecl` bools. Nothing else records them.
- **A constant btrc folds is the constant C folds.** Integer constants are evaluated with C's types at the target's widths. Every layout value btrc consumes is asserted again in the emitted C.

**Depends on:**
- `ccompat-c2-integrate` and Stage 18: C2's `type_name`, `CompoundLiteral`, `TypeExpr.elements`, the record-member owner and the three-way query;
- C4's `ccompat-r18-spec`: `targets.toml` and its `[[targets]]` rows;
- C1 r04 and r05 (character-array initialization and `StringConcat`), which r16 and r15c extend.

## Current state and defects found

Each defect below was either reproduced or read from the code at `c7f785e`. Probe sources live in the workflow scratchpad; "probe" names the file.

| # | Defect | Evidence | Fixed by |
|---|--------|----------|----------|
| D-1 | A btrc `volatile int* p` means C's `int* volatile p`. Both compilers analyze the qualifier as the object's (`StorageModel.volatile_qualifier_depths`, `analyzer/storage.py:330-353`, documents "btrc's explicit volatile qualifies the represented storage object"). Both emit it after the `*` (`CType.qualify_volatile_object`, `ir/nodes.py:76-81`). `test_ir_declarations.py:183-221` and `test_qualifier_provenance_contracts.py:35-43` pin this. No btrc, stdlib or example source writes `volatile T*`: grep finds it only in C text inside `generated/runtime/Catalog.btrc`. | probe `volatile.btrc` through both compilers | r15a |
| D-2 | Integer `/` and `%` in C constant contexts lower through `__btrc_div`/`__btrc_mod`. These are `_Generic` calls to `static inline` helpers (`src/runtime/c/core.c:53-58`). Both compilers emit `static int table[((int)__btrc_div(((int)12), ((int)4)))];` and `case ((int)__btrc_div(...)):`. btrcc also emits an enum value this way; Python emits plain `/` there. gcc `-pedantic-errors` rejects all three forms, and a constant-bounded local silently becomes a VLA. | probe `constdiv.btrc` | shared owner B (constant lowering) |
| D-3 | The constant evaluators are untyped `long long` (`analyzer/expressions.py:1477-1600`; `validation/Constants.btrc:151-240`). `1u - 2 < 0` is 1 in btrc and 0 in C. `'\xff'` is 255 in both compilers (`LiteralDecoder.decode_character`, `lexer/lexer.py:126`; `ConstantValidator.characterConstant`, `Constants.btrc:65`), but it is -1 on every target where `char` is signed. | source reading | shared owner B (typed evaluator) |
| D-4 | Literal typing and cast ranges use the host's widths: `CIntegerWidths.native()` (`analyzer/types.py:117-126`), btrc `IntegerLiteral.typeName` (`syntax/Literals.btrc:98-145`), and `builtinCastRange`/`abiCastRange` (`Constants.btrc:296-408`). A Linux compile with `--target windows-x86_64` types `long` as 64 bits. | source reading | shared owner B (`TargetLayout`) |
| D-5 | `1.f` lexes as `1` `.` `f`. Both analyzers accept member `f` on an `int` literal, and the text reaches C, which reads a float. `.5` and `1.` are refused, with different wording in each compiler. `5.toString()` is valid btrc today and must stay valid. | `--emit-tokens`; probe `lit.btrc` | stragglers |
| D-6 | Row 21 refuses `sizeof(int) == 4` in both compilers. This is expected; C3 tests write `sizeof(int) == (size_t)4`. | probe | documented |
| D-7 | The two compilers word four diagnostics differently: const modification, const discard, missing return, and lambdas. Messages and citations follow this table. | probes | r15a (first two), r15b (last two) |
| D-8 | `<assert.h>`'s `static_assert(...)` is a hosted macro (`hosted_abi.toml:3571`). Both compilers accept it as an expression statement and emit `(void)(static_assert(...));`, which gcc and clang reject. | probe `sassert.btrc` | r15c |
| D-9 | The constant query resolves names by spelling before scope. Python's `_is_constant_macro_name` treats any `name.isupper()` as a macro (`expressions.py:1589-1590`). btrc uses `isCIntegerIdentifier` (`analyzer/Types.btrc:120`, called at `Constants.btrc:176-178`), which also admits `errno`. `sizeof` is "cannot evaluate" whatever its operand, VLAs included (`expressions.py:1494`; `Constants.btrc:200-202`), and `_validate_array_bound` records such bounds as constant (`statements.py:509-511`). Both compilers accept, and gcc rejects, `int LIMIT = 4; int arr[LIMIT] = {1, 2}; … case LIMIT:`, and `char w[sizeof(v)] = {0}` where `v` is a VLA. | probes `caps.btrc`, `vla.btrc` | shared owner B |
| D-10 | `sizeof` of an expression lowers to `sizeof(<btrc type>)` (`ir/lowering/expressions.py:2109-2131`; btrcc does the same). `sizeof('a')` becomes `sizeof(char)`, and `sizeof(true)` and `sizeof(x == 2)` become `sizeof(bool)`, where C would measure `int`. This is btrc's existing meaning. C3 keeps it and makes the layout model measure the same thing. | probes `szs.btrc`, `szs2.btrc` | documented; shared owner B |
| D-11 | Lowering takes the address of plain locals; this is harmless today but fatal for `register`. The two forms are described after this table. | probes | r15a |
| D-12 | Qualified generic arguments through typedefs: `typedef const int CI; Vector<CI> v;` is accepted by the reference compiler and rejected by gcc. btrcc refuses it ("generic arguments cannot be const-qualified", `syntax/Identity.btrc:1086-1088`). Separately, `Vector<struct S>` where `S` has a `const int` member is accepted, and gcc rejects the element stores. | probes `typedefconst.btrc`, `cm4.btrc` | r15a |
| D-13 | There are three termination predicates, and the btrc lambda one lacks switch and loop rules. They are listed after this table. | source reading | the btrc lambda-termination parity commit (`CL-C-02`, before C3); r15b then owns the completion table |

**D-7, wording differences:**
- **Const modification.** Python says "Cannot modify const-qualified storage" (`expressions.py:785`). btrc says "Cannot modify const storage of type 'const int'" (`validation/Storage.btrc:844`).
- **Const discard.** The reference compiler uses its generic `Cannot assign 'const int*' to variable 'q' …` (`statements.py:1992`). btrc says "… would discard const storage qualification at pointer depth 1" (`Storage.btrc:1318`). The volatile form already matches (`storage.py:116` and `Storage.btrc:1304`).
- **Missing return.** Python says "… but no return statement" (`statements.py:1466`, `:1596`). btrc says "Callable 'f' … does not return on every path" (`validation/Declarations.btrc:802`).
- **Lambdas.** Python says "does not return a value on every path" (`statements.py:819`); btrc uses different wording (`validation/Expressions.btrc:776`).

**D-11, the two address-taking forms:**
- **btrc compound assignment.** btrc lowers every compound assignment through `lowerDirectCompound` (`ir/lowering/Expressions.btrc:3853-3862`, `:1250-1281`). For an `int a` it emits `int volatile* __btrc_lvalue_1; … (__btrc_lvalue_1 = (&a))` (probe `plain.btrc`). Python uses value temporaries there.
- **Python's ternary store adapter.** Python emits `__btrc_store_1((&x), next(4))` (`ir/lowering/expressions.py:662-715`, `ownership.py:214-249`; probe `tern2.btrc`). btrcc emits the plain `(x = next(4)) ? x : 0`, which gcc 15.2 and clang 21.1.8 accept under the strict flags (probe `seq.c`).

**D-13, the three termination predicates:**
- Python `ControlFlowAnalyzer.statement_must_terminate` (`analyzer/flow.py:249-306`);
- btrc `ControlFlowValidator.statementTerminates` (`validation/ControlFlow.btrc:157-260`);
- btrc `ExpressionTypeResolver.statementTerminates` (`analyzer/Expressions.btrc:86-118`), which has no switch or loop rule and serves btrc's lambda checks (`validation/Expressions.btrc:775`, `validation/ControlFlow.btrc:63`).

As a result, Python accepts `() => { while (true) { return 1; } }` and btrcc refuses it.

**D-13's owner.** The third predicate does not wait for r15b. It is deleted first, in its own both-compiler parity commit (`CL-C-02`, `src/tests/btrc/test_lambda_termination_parity.py`), which leaves btrc one lambda termination check, on `ControlFlowValidator`'s statement-analysis path, as Python has one (`_analyze_lambda`). `ExpressionValidator.validateLambda` drops its duplicate check, because `validation/Expressions.btrc` cannot import `ControlFlowValidator` without the self-hosted compiler's first import cycle. The goto design needs that commit before Stage 20 (`c-goto-labels.md`, review M3). r15b then replaces the two remaining predicates with the completion owner below, and unifies the missing-return and lambda wording (D-7).

The vocabulary commit records D-1, D-2, D-3, D-5, D-8, D-9 and D-12 as `known-divergence` probes. Each owner flips its probe in the commit that fixes it. D-13 is not a C construct, so the parity commit's test, extended by the completion owner, covers it instead of a probe.

## Decisions

| Row | Representation | Schema / IR change |
|-----|----------------|--------------------|
| Vocabulary | `@keywords` gains seven C11 words and `va_arg`; `@operators` gains `"..."`. The details follow this table. | TokenKind `INLINE, RESTRICT, _ALIGNAS, _ALIGNOF, _NORETURN, _STATIC_ASSERT, _THREAD_LOCAL, VA_ARG, DOT_DOT_DOT`. The names come from `keyword.upper()` and `operatorTokenName`; Python's `Enum` accepts names with a leading underscore (checked). |
| r15a qualifiers, storage classes | C11 6.7.3: `TypeExpr.is_const`, `is_volatile` and the new `is_restrict` qualify the **base type**, whether written before or after it. Qualifiers written after the k-th `*` form one `PointerQualifiers(pointer_depth=k, …)` entry in `TypeExpr.parts`, present only for a qualified level. This retires D-1. Storage classes extend the `is_static`/`is_extern` convention with `is_register`, `is_auto` and `is_thread_local`. | `TypeExpr.is_restrict`, `is_register`, `is_auto`, `is_thread_local` and `parts`; a new sum type, `type_part`; IR flags listed below |
| r15b `inline`, `_Noreturn` | `FunctionDecl.is_inline` and `is_noreturn`. `extern inline` is `is_extern` plus `is_inline`. It means the same as `inline`, because btrc always chooses the owning unit. | `is_inline` and `is_noreturn` on `IRFunctionDef`/`IRFunctionDecl`. Calls to noreturn functions reuse `IRCall.never_returns` (`ir/nodes.py:210`). |
| r15c `_Static_assert` | Three kinds with identical fields, `(expr condition, expr* parts)`, one per position: `StaticAssertDecl`, `StaticAssertStmt` and `StaticAssertMember` (the `field_def` constructor C2 reserved). `parts` holds the message pieces under C1 r05's `StringConcat` rule. | `IRStaticAssert`; `IRModule.static_asserts` |
| r15d `_Alignas`, `_Alignof` | `_Alignas(...)` is an `AlignmentSpecifier(type_expr? type, expr? value)` entry in `TypeExpr.parts`, in source order. The strictest one wins (C11 6.7.5p6). `_Alignof(T)` is `AlignofExpr(type_expr type)`. The IR carries the folded effective alignment as an integer, as C2 folds bit widths. | `alignment` on `IRVarDecl`, `IRGlobalDecl` and `IRStructField`; `IRAlignof` |
| r16 wide and UTF literals, `long double` | The prefix stays in the token's raw text (`L"ab"`, `u'x'`), so `StringLiteral` and `CharLiteral` are unchanged. `1.5L` is a `FLOAT_LIT` whose raw text keeps the suffix. `char16_t`/`char32_t` are emitted as `uint_least16_t`/`uint_least32_t`, which C11 7.28p2 makes the same types, so no `<uchar.h>` is needed. | none |
| Stragglers | `sizeof unary`; hex floats; the decimal forms `.5`, `1.`, `1.f` and `1.e3` (D-5); pointer `+=`/`-=`; `sizeof (T){…}`. | none |
| r14 variadic definitions | `FunctionDecl.is_variadic`; `VaArgExpr(expr expr, type_expr type)`. Managed variadic arguments are borrowed for the call, as hosted variadic calls already treat them. | `is_variadic` on `IRFunctionDef`/`IRFunctionDecl`; `IRVaArg` |
| Target layout | C4's `[[targets]]` rows gain the data model, char and `wchar_t` signedness, and the `long double`/`max_align_t` cells. A `[target_layout]` table holds the cells all targets share, and `[[layout_typedefs]]` holds the C11 standard typedefs. The analyzer types literals, casts and constants at the selected target's widths. | spec columns only |
| Constants | One typed evaluator per compiler gives C2's three kinds of answer, each with the value's C type. Proven constants lower to plain C operators. Every layout value the analysis consumes is asserted again in C. | none (uses `IRStaticAssert`) |
| Stage 20 reservation | `GotoStmt(identifier name, int name_line, int name_col)` and `LabelStmt(identifier name)` are added now, at zero bytes, so `ast.asdl` changes once. The schema is the goto design's (`c-goto-labels.md`, "Schema commit"): a label owns no sub-statement. Stage 20 owns their semantics and their grammar rules. | `IRGoto(name)` and `IRLabel(name, falls_through)`, which the verifier refuses until Stage 20 |

**The vocabulary row in detail:**
- **New keywords.** `inline restrict _Alignas _Alignof _Noreturn _Static_assert _Thread_local`, plus `va_arg`.
- **Why `va_arg` is a keyword.** C11 7.16.1.1 gives it a type-name argument, which no expression parser can read. Keying a parser branch on an identifier spelling would amount to a hardcoded keyword.
- **What stays as it is.** `va_start`, `va_copy` and `va_end` stay hosted macros. `_Atomic`, `_Complex`, `_Bool`, `_Generic` and `_Imaginary` stay identifiers:
  - `_Bool` is `bool` (D20);
  - `_Atomic` and `_Complex` keep row 24's refusal;
  - `_Generic` passes through inside source macros (`c_compat/GenericSelection.btrc`).
- **No identifier collides.** `C11_RESERVED_NAMES` (`analyzer/declarations.py:674`) and `c11ReservedName` (`validation/Names.btrc:108`) already refuse the seven C11 words as names. `va_arg` is not in those lists, but it is a hosted-owned macro name (`hosted_abi.toml:3594`, `:8033`) that no source can declare, and grep finds it in no btrc source.

## Shared owners

The main session lands the vocabulary commit and then two serial shared-owner commits before the lanes fork. Each owner gets a contract test in both compilers.

**Commit A** changes the behavior of no program.

**Commit B** changes behavior only in these ways:
- the listed fixes: D-2, D-3, D-4 and D-9;
- the `#pragma pack` diagnostics move into the analyzer;
- the emitted C gains the cross-check assertions;
- three relaxations:
  - `sizeof`/`_Alignof` of a known layout now evaluates in C2's constant contexts;
  - `&&`, `||` and `?:` evaluate only the operand C evaluates, so `0 && (1 / 0)` is a constant (gcc 15.2 and clang 21.1.8 accept it under `make test-c11`'s flags, checked for this section);
  - implementation-defined conversions and right shifts evaluate as gcc and clang define them.

### Commit A: declaration specifiers

**1. The parse.** One specifier loop in Python `Parser._parse_type_expr` (`parser.py:410`) and btrc `Parser.parseType` (`Parser.btrc:958`) reads these into the new AST:
- storage classes and function specifiers;
- qualifiers on either side of the base type;
- `* qualifier…` levels;
- `_Alignas(...)`.

**Function specifiers** are not part of the type.
- The loop accepts them only when its caller is the top-level declaration path (`_parse_top_level_item`, `parser.py:603`; `parseTopLevelItem`, `Parser.btrc:168`). That path passes a flag and stores the specifiers in a parser slot: `_pending_function_specifiers` in Python, `pendingFunctionSpecifiers` in btrc.
- `_parse_function_or_var_decl` (`parser.py:1117`) and `parseFunctionOrVarDecl` (`Parser.btrc:762`) consume the slot at once.
- Everywhere else, the loop refuses function specifiers at the specifier token. A top-level variable that took them refuses them there too.
- `_parse_type_expr` asserts that the slot is empty on entry, so `struct S { inline int x; }; int f() {…}` can never make `f` inline.

**Lookahead.** One recognizer serves declarations, casts and `sizeof`: Python `_scan_type_expr` (`parser.py:358-397`) and btrc `scanTypeEnd` (`Parser.btrc:928`). In Python it is used by `_lookahead_is_var_decl` (`:1268`), `_is_cast` (`:1724`) and `_is_sizeof_type` (`:1754`).
- In every mode it skips every specifier keyword (before or after the base, and after each `*`) and every balanced `_Alignas(...)` group. This matches how `_QUALIFIERS` (`parser.py:219-226`) already lets `(static int)x` scan as a cast.
- `restrict` joins `TYPE_KEYWORDS` (`tokens.py:529`) and btrc's `isTypeKeyword`/`isTypeQualifier` (`Parser.btrc:152`, `:850`).
- The analyzer's position table (owner 2) owns every refusal of a storage class in a type name. `(register int)x`, `sizeof(register int)` and `Vector<register int>` therefore all reach one diagnostic.

**`auto` as inference.** When `auto` is followed by an identifier and `=` (no base type), the parser refuses it at `auto` with the targeted message under Refusals.

**Pending refusals.** Until a construct's lane lands, its token is refused at its own position with ``C11 '{spelling}' is not supported yet``.
- **Tables.** There is one table per parser, keyed by token kind, beside Stage 14's `_DEFERRED_C_SPECIFIERS` (`parser.py:252-257`) and `deferredCSpecifierMessage` (`Parser.btrc:81`). The tables hold the nine new tokens plus `auto` and `register`. They hold no `goto` entry: until Stage 20, both parsers keep today's `goto` errors with no interim message, so the `goto` probes in `c3_c4.toml` change only once, in Stage 20 (`c-goto-labels.md`, "Schema timing").
- **Hooks.** The pending check reuses Stage 14's call sites, extended from identifier spellings to token kinds. Those are the calls to `_refuse_deferred_c_specifier` (`parser.py:162-164`) from `_expect`, from the `_parse_type_expr` base fallback and from `_parse_primary`, plus their btrc twins. The specifier loop and each parser's unexpected-token constructor also check the table.
- **Not pending.** East-position qualifiers and `* qualifier` levels need no entry; they keep today's diagnostics until r15a.
- **Contract test.** The two tables must be equal.
- **Cleanup.** Each lane deletes its own entries, and `ccompat-c3-integrate` deletes the tables. Stage 20 never touches them.
- **Stability.** The vocabulary commit already carries both tables with the same hooks, so commit A does not change any recorded probe diagnostic again.

**2. Positions and value types.**

**The position table.** Python `TypeSystem.validate_declaration_specifiers(type_expr, position)` (`analyzer/types.py`) and btrc `TypeValidator.validateDeclarationSpecifiers` (`validation/Types.btrc`) hold the one table of what each position allows. Every specifier-position refusal in the r15a, r15d and r14 tables comes from it.

| Position | Storage classes | Outer pointer qualifiers | `_Alignas` |
|----------|-----------------|--------------------------|------------|
| block object (block statement, case body) | `static`, `extern`, `register`, `auto`; `_Thread_local` with `static` or `extern` | yes | yes, but not with `register` |
| C-for initializer | `register`, `auto` (C11 6.8.5p3) | yes | yes |
| file-scope object | `static`, `extern`, `_Thread_local` | yes | yes |
| top-level function | `static`, `extern` | no (the existing return refusal) | no |
| parameter of a function, method or lambda | `register` | yes; ignored when signatures are compared (C11 6.7.6.3p15) | no |
| struct or union member | none | yes | yes, but not on a bit-field or under `#pragma pack` |
| class field, property | none (class `static` is an access modifier) | `volatile` and `restrict`; `const` only without an initializer | no |
| typedef target | none | yes | no |
| `sizeof`/`_Alignof` type name, compound-literal head | none | yes | no |
| cast target | none | no † | no |
| `va_arg` type, generic argument, tuple element, `new`, catch type, rich-enum payload | none | no | no |

**Value types.** Python `TypeSystem.value_type` and btrc `TypeShape.valueType` (`syntax/Types.btrc`) return the type of an object's value (C11 6.3.2.1p2). Commit A lands the storage half: it removes every storage class and every `AlignmentSpecifier`. It replaces these storage strip sites:
- Python: `analyzer/types.py:1118`, `analyzer/expressions.py:1291`, `analyzer/gpu.py:358`, `analyzer/declarations.py:803-804`;
- btrc: `CallableSignature.component` (`syntax/Types.btrc:160-167`), `ir/lowering/Callables.btrc:327-328`, `analyzer/Expressions.btrc:334-335`, `validation/Types.btrc:449-450`, `validation/Expressions.btrc:138-139`, `validation/Names.btrc:380-381`.

Some sites also clear `is_const`/`is_volatile`. Those call `value_type` and keep clearing the qualifiers as they do today, because before the D-1 flip that clearing is the existing meaning. r15a replaces those clears with the qualifier half (the owner is listed under r15a).

**Contract test.** It fails on any site outside the owners that clears a storage flag or reads `parts`.

### Commit B: constants and layout

**3. `TargetLayout`.** This is an immutable owner over the generated target rows: in Python, in `abi/hosted.py` beside `HostedAbiRepository`; in btrc, in `analyzer/HostedAbi.btrc`. The compilation's `PackageTarget` (`frontend/packages.py:159-193`) selects the row.
- **Widths.** `CIntegerWidths.native()` becomes `CIntegerWidths.for_target(layout)`. It is injected where `NumericLiteralSemantics` is built (`application/pipeline.py:470`, `analyzer/analyzer.py:40`). btrc's `IntegerLiteral.typeName` takes the widths as an argument, and `builtinCastRange`/`abiCastRange` read the same row (D-4).
- **No `--target`.** A compile without `--target` uses `PackageTarget.parse(None)`, the host; this includes the LSP. On a host outside the six targets, btrcc keeps C4's empty target: widths fall back to the host's C limits as they do today, and every layout query answers that no layout is known.

**4. `LayoutModel`.** Python's `LayoutModel` lives in `analyzer/aggregates.py`, btrc's `SemanticLayoutModel` in `validation/Constants.btrc`. `layout(type)` returns either `Layout(size, alignment)` or `NoLayout(subject)`, where the subject is the type's display name.

**Known layouts:**
- scalars and `bool`, from the target row;
- plain btrc enums, 4/4;
- native enums, from `NativeEnumType.underlying` (`native_abi.asdl:35`);
- every pointer: raw pointers, `T?`, `CFunction`, and values of `string`, class, interface and collection types (these values are references);
- fixed arrays;
- tuples, laid out as the struct of their elements in order (the lowered `btrc_Tuple_*`);
- btrc structs and unions, by C11 placement, with these rules:
  - C2's FAM rule;
  - inline anonymous members;
  - the union rule (largest size, strictest alignment);
  - `#pragma pack` capping member alignment;
  - member `_Alignas`;
- typedef chains, and the C11 standard typedefs in `[[layout_typedefs]]`;
- native records and typedefs, from the reader's Clang `size_bits`/`alignment_bits` (`native_abi.asdl:31`, `:48-52`).
  - These are exposed as a per-target index in `AnalyzedProgram`/`Analyzed`.
  - When headers are imported, a check asserts that the target row's cells equal the reader's `NativeBuiltin` bits and `character_bits` (`native_abi.asdl:5-6`, `:31`).

**No layout:**
- class, interface and collection types named as types: `sizeof(Box)` lowers to the struct, ARC header included (probe `szc.btrc`);
- rich enums, `Span`, `Atomic<T>`, `Mutex`, `Thread` and closures;
- any record with a bit-field (C2), or with a member that has no layout;
- opaque, incomplete or unimported foreign records;
- hosted typedefs outside the table (`time_t`, `off_t`, …);
- `int_fast16_t`, `int_fast32_t` and their unsigned forms, on which glibc, musl, Apple and MinGW disagree;
- `va_list`, which is an array type on linux-x86_64, so a parameter of that type is a pointer;
- every cell a target row omits.

**Incomplete while in progress.** A record whose layout is being computed counts as incomplete, just as C treats a record as incomplete inside its own body. This covers an assertion in `B` that measures `A` when `A` holds `B` by value, and it bounds the recursion.

**`sizeof` and `_Alignof` operands** are measured exactly as lowering emits them. One shared owner does this: Python `SizeofOperand.emitted_type` and btrc `SizeofOperand.emittedType`. `_lower_sizeof` (`ir/lowering/expressions.py:2109-2131`) and btrc's `ExpressionLowerer` call it too.
- A type operand is measured as that type.
- An expression operand that is neither an array nor a string literal is measured at its btrc type: `'a'` is `char`, and `true` and comparisons are `bool` (D-10).
- An array designator is measured at its declared array type, except that an array **parameter** is a pointer (C11 6.7.6.3p7).
- A string literal is its element type times its code units plus one (r16).
- A VLA type or a VLA designator is **not constant** (C11 6.5.3.4p2, 6.6p6).

**5. Typed integer constants.** In Python, a new `IntegerConstantEvaluator` class in `analyzer/expressions.py` owns evaluation, and `ExpressionAnalyzer.integer_constant_expression` (`expressions.py:1477`) delegates to it. In btrc, `ConstantValidator.integerConstant` (`Constants.btrc:151`) stays the owner, and `SemanticIntegerConstant` (`:11`) gains the type.

**The answer** keeps C2's three kinds: a value; not a constant expression; a constant expression btrc cannot evaluate. It adds the value's C type as (bits, signedness), and, for the third kind, the blocking subexpression and the reason. (bits, signedness) is enough, because equal-width rank ties never change a C11 6.3.1.8 result: it does not matter that glibc's `int64_t` is `long` while Apple's is `long long`.

**Identifiers resolve in this order** (D-9):
1. A name bound in scope (a local, parameter, global or field) is not a constant, whatever its spelling.
2. Enum constants.
3. Source macros.
4. Native constants with values.
5. Hosted macro and object names. Objects such as `errno` and `stdin` are not constants; macros are "cannot evaluate".
6. An undeclared upper-case name stays a presumed foreign macro ("cannot evaluate"), as today.

**Semantics** follow C11 6.4.4, 6.3.1.1, 6.3.1.8, 6.5 and 6.6 at the target's widths.
- **Literal and constant types.**
  - Literals take C's type tables (`NumericLiteralSemantics._integer_candidates`, `types.py:219`).
  - Character constants are `int`, with the target's char signedness (D-3).
  - Enumeration constants are `int`; `sizeof` and `_Alignof` are `size_t`.
  - Comparisons and logical operators yield `int` 0 or 1 (C11 6.5.8p6), whatever btrc's static type is.
- **Conversions.** Integer promotions and the usual arithmetic conversions apply. Unsigned results reduce modulo 2^N.
- **Not constant** (C11 6.6p4, 6.5.5p5, 6.5.7p3-p4):
  - signed overflow;
  - division by zero, and `INT_MIN / -1`;
  - a shift count outside [0, width);
  - a left shift of a negative value;
  - a left shift whose result E1×2^E2 is not representable. `1 << 31` for a 32-bit `int` is the common case; gcc 15.2 and clang 21.1.8 both accept it as an extension (re-run of probe `sc.c`), so write `1u << 31`;
  - a floating-to-integer conversion out of range.
- **Evaluated as gcc and clang define them:**
  - an out-of-range conversion to a signed type wraps (C11 6.3.1.3p3);
  - a right shift of a negative value is arithmetic (6.5.7p5).

  Both are recorded in known-language-gaps as implementation-defined behavior btrc assumes.
- **Short-circuit.** `&&`, `||` and `?:` evaluate only the operand C evaluates. Every operand must still satisfy C11 6.6p6's operand rule, so a variable in the dead arm still makes the expression not constant; gcc and clang refuse `0 && y`.

**"Cannot evaluate" blockers:**
- `sizeof`/`_Alignof` of a `NoLayout` type: "btrc knows no layout for 'T'";
- a source macro without a value, or a presumed foreign macro: "btrc cannot resolve the value of macro 'X'".

**Consumers** keep C2's diagnostics. This table shows which kinds each one accepts:

| Consumer | value | cannot evaluate |
|----------|-------|-----------------|
| enum value, case label, outermost array extent (fixed, static, file scope) | accepted | accepted. C computes the value, and btrc records none, so there is no for-in capacity and no duplicate-case check for it. |
| inner extent (Stage 18), bit-field width (C2), designator index (C2), `_Static_assert`, `_Alignas` | accepted | refused with the consumer's "cannot evaluate" diagnostic |

**6. Constant lowering.** Python `ExpressionLowerer.lower_constant_expression` and btrc `ExpressionLowerer.lowerConstantExpression` lower an expression into plain C operators, with no `__btrc_div`/`__btrc_mod`. They do this when the evaluator answered either "value" or "cannot evaluate".
- **Why plain operators are safe.** Both kinds are C constant expressions, so the C compiler itself re-checks C11 6.6p4: a division by zero is a translation error, not a run-time one. The checked helpers guard run-time values only.
- **Sites** (D-2): enum values, case labels, file-scope, `static` and constant-bounded array extents, static initializers, and `_Static_assert` conditions.
- **Unchanged.** VLA bounds keep the checked helpers. A presumed foreign macro that is not a constant in C still makes a block-scope array a VLA, as it does today.

**7. Layout cross-check.** Each `sizeof`/`_Alignof` whose folded value the analysis consumed emits `IRStaticAssert(<lowered query> == N, "btrc layout")`. Consuming means using the value for an extent, enum value, case value, width, index, `_Static_assert` or `_Alignas`.
- **Placement.** The assertion goes into `IRModule.static_asserts` when its operand names no local; otherwise it goes in place, before the consuming statement. Duplicates are dropped per scope.
- **Effect.** A wrong table cell then fails the C compile instead of diverging silently. This is D20's cross-check, applied to every value btrc relies on.

**8. `#pragma pack` moves to the analyzer** (I-9). Today pack interpretation lives in lowering, out of the layout model's reach: `TranslationUnitLowerer.declaration_pack_alignments` (`ir/lowering/translation_unit.py:826-852`) and btrc `ir/lowering/Declarations.btrc:81-138`.
- **New owner.** Python's and btrc's `DeclarationRegistry` record each record's pack alignment in `AnalyzedProgram`/`Analyzed`; btrc keys it by `AstIdentity.key`. Both lowerers read it.
- **Forms.** The recognized forms stay `#pragma pack(push[, N])` and `#pragma pack(pop)`.
- **Messages.** Their three messages become analyzer diagnostics at the directive, and are re-recorded.

## Conventions both parsers keep identical

**Positions** are canonical AST data:
- `StaticAssert*` sit at `_Static_assert`; each message part sits at its token.
- `AlignofExpr` sits at `_Alignof`, `VaArgExpr` at `va_arg`, and `AlignmentSpecifier` at `_Alignas`.
- A parsed `PointerQualifiers` entry sits at the first qualifier token after its `*`. An entry synthesized by typedef composition sits at the `TypeExpr` it qualifies.
- A `TypeExpr` starts at the first token its parser consumes, leading storage-class and function specifiers included. This is today's rule for `static` (`parser.py:411`).
- A `FunctionDecl` starts at the first token after annotations and `keep` (`parser.py:1121`), so `static inline int f()` starts at `static`.
- `GotoStmt` sits at `goto`, and its `name_line`/`name_col` sit at the label identifier. `LabelStmt` sits at its identifier.
- Parser refusals sit at the offending token. Specifier-position refusals sit at the `TypeExpr`. Use refusals sit at the operator, call or access, as in C2.

**Grammar.** The vocabulary commit writes every C3 rule; the lanes touch no grammar text.

```
type_expr  = { declaration_specifier } base_type [ generic_args ]
             { type_qualifier | alignment_specifier }
             [ "[" "]" ] { "*" { type_qualifier } } [ "?" ]
             (* Storage-class and function specifiers precede the base type.
                Qualifiers may not follow "?" or a "*" that follows "[]". *)
declaration_specifier = storage_class | function_specifier
                      | type_qualifier | alignment_specifier
storage_class       = "static" | "extern" | "register" | "auto" | "_Thread_local"
function_specifier  = "inline" | "_Noreturn"     (* top-level functions only *)
type_qualifier      = "const" | "volatile" | "restrict"
alignment_specifier = "_Alignas" "(" ( type_name | expr ) ")"
param_list    = [ param { "," param } [ "," "..." ] ]
static_assert = "_Static_assert" "(" expr "," string_literals ")" ";"
                (* top level, statement, struct or union member *)
unary        += "sizeof" unary | "sizeof" "(" type_name ")"
              | "_Alignof" "(" type_name ")"
primary      += "va_arg" "(" assignment "," type_name ")"
```

- `type_name` is C2's rule, and `string_literals` is C1 r05's.
- A rule whose lane has not landed carries `(* refused until <item> lands *)`; each lane deletes its own marker.
- The `goto` and label rules are not C3's. They land with Stage 20's construct commit, together with the parsers (`c-goto-labels.md`, "Schema commit"), so this commit writes no `goto` rule.
- The `@lexical` reserved-keyword comment (`grammar.ebnf:23-33`) is rewritten. `override` is the only keyword without a rule, along with `goto` until Stage 20. `_Atomic`, `_Bool`, `_Complex`, `_Generic` and `_Imaginary` are identifiers, handled as the vocabulary row describes.

**Disambiguation:**
- **Specifier order.** Storage-class and function specifiers precede the base type.
  - That is where today's parser reads `static`/`extern`. `const static int` is accepted today, through the `_QUALIFIERS` loop, and stays accepted.
  - `int static x` and `int inline f(void)` are refused †.
  - Qualifiers and `_Alignas` may stand on either side of the whole base type, but never inside a multi-word base: `unsigned const int` keeps today's parse error.
- **Repetition.** Repeated qualifiers and function specifiers are idempotent (C11 6.7.3p5, 6.7.4p5). Repeated storage classes are refused (6.7.1p2).
- **Placement limits.** Qualifiers after `?` are refused, as are qualifiers after a `*` that follows btrc's prefix `T[]`. Qualifiers or `static` inside array-parameter brackets (`int a[restrict static 4]`) are refused †.
- **`_Alignas(IDENT)` and `_Alignof(IDENT)`** parse in the type form, as `sizeof(IDENT)` does today (`_is_sizeof_type`, `parser.py:1754-1757`). The analyzer then reinterprets:
  - for `_Alignas`, an identifier naming a constant becomes the value form;
  - for `_Alignof`, an identifier naming an object is refused, because C11 allows only a type name.
- **`sizeof (`.** After `sizeof (`, three cases apply:
  - a parenthesized type name followed by `{` is a compound-literal operand;
  - a parenthesized bare `IDENT` or `IDENT[expr]` followed by a postfix operator (`[ . -> ++ --`) is an expression operand;
  - anything else is the type form.

  `sizeof x + 1` is `(sizeof x) + 1`.
- **Numbers and dots.** A `.` never joins a number when another `.` follows it. So `0...2` lexes as `0` `...` `2`, and C2's range refusal fires.
  - **Leading dot.** A `.` followed by a digit starts a floating constant unless the previous significant token can end an operand. Tokens that can end an operand are an identifier, a literal, `self`, `super`, `true`, `false`, `null`, `)`, `]`, `}`, `++` and `--`. Tuple access `t.0` is unchanged.
  - **Trailing dot.** Digits directly after `.`, `?.` or `->` lex exactly as today, so `t.0.f` keeps working. Elsewhere, a `.` after decimal digits joins the number when the next character is:
    - a digit;
    - `e` or `E` followed by an optional sign and a digit;
    - one of `f F l L` not followed by an identifier character;
    - any character that is neither an identifier character nor `.`.

    So `1.`, `1.f`, `1.L`, `1.e3` and the `1.` in `x = 1.;` are floats, while `5.toString()` and `1.equals(1)` stay member calls on an integer.
  - **Hex floats.** After hex digits, a `.` joins the number when the next character is a hex digit or `p`/`P`; a hex float then requires a `p` exponent. A member call on a hex literal whose name starts with a hex digit (`0x10.equals(16)`) needs parentheses; this is documented.
  - **`?.` and a digit.** Longest match keeps `?.`, so `c?.5:1` is an optional access. C's `c ? .5 : 1` needs its spaces. This is documented and tested in both lexers.
- **Prefixed literals.** A prefixed literal starts when `L`, `u`, `U` or `u8` is immediately followed by `"`, or when `L`, `u` or `U` is immediately followed by `'`. Its raw text keeps the prefix. `u8'…'` is a lexer error.

**Rendering:** new fields render in ASDL order. The btrc `AstCanonicalRenderer` adds one line per new field and one branch per new kind, and the generator contract checks them.

**Copies:**
- btrc's `TypeShape.copy`, `copyTree` and `copyWithArguments` copy the four new bools.
- They copy `parts` only when `partsStorage != null`, cloning each `type_part` node, and never store a reader's result in a field.
- Python's `dataclasses.replace` shares the list, so a `parts` list is never mutated once built.
- C2's copy contract test covers the new fields.

**The `parts` invariant.** Each `PointerQualifiers` entry satisfies `1 ≤ pointer_depth ≤ TypeExpr.pointer_depth`, and the entries' depths strictly increase.
- **Owners.** Every helper that adds or removes pointer levels maintains the depths: Python's `strip_outer_storage`, `add_outer_pointer` and `compose_type_expr` (`types.py:2599-2640`); btrc's `withoutOuterPointers`/`withoutOuterArray` (`syntax/Types.btrc:40-80`) and `TypeComposition.compose`.
- **Behavior.**
  - Dereference drops the outermost entry.
  - `add_outer_pointer` shifts no entry.
  - Composing `const IP` for a pointer typedef yields a `PointerQualifiers` entry at the argument's depth. Today's typedef layering is already C-correct (probe `constip2.btrc`).
- **Contract test.** It runs each transformer in both compilers.

**Several declarators (C1 r03).** The copier copies storage classes, base qualifiers and `AlignmentSpecifier` entries. Each declarator contributes its own `PointerQualifiers`, so `int * const a, b;` makes `b` a plain `int`.

**Type identity.** Both compilers use one extended encoding: Python's `TypeIdentity.shape_key` and `_encode_type` (`types.py:425-437`, `:798-807`), and btrc's `qualifierBits`/`appendEncoded`/`decode` (`syntax/Identity.btrc:876-940`).
- **Format.** `restrict` is qualifier bit 16. Each `PointerQualifiers` entry appends `v<depth>c<bits>` after the qualifier field.
- **Byte stability.** Neither appears for an unqualified type, so every existing encoding, symbol and row-typedef name stays byte-identical.
- **Not encoded.** Storage-class bools and `AlignmentSpecifier` entries are left out, because only `value_type` results reach identity. btrc's `TypeIdentity.encodable` returns false for a type that carries one, so module units (`pipeline/ModuleUnits.btrc:2474-2478`) never replay a type that would lose it.

**Type equality.** Both compilers compare `value_type` results by that encoding.
- btrc's `aliasTypesSame` (`validation/Types.btrc:583-590`) already compares `shapeKey`, and `globalTypesSame`/`callableSignatureSame` (`validation/Names.btrc:374-393`) call it.
- `sameTypeShape` and `callableComponentSameTypeShape` (`validation/Types.btrc:605-607`) compare fields directly; they switch to the encoding.
- A contract test lists every `TypeExpr` field and requires each one to be encoded, stripped by `value_type`, or position-only.

**Kind coverage** (extends C1 and C2):
- **`AlignofExpr`, `VaArgExpr`.**
  - Each lane audits every btrc switch that handles `NK_SIZEOF_EXPR` or `NK_CALL_EXPR`, and every Python file that names `SizeofExpr`.
  - A contract test requires each such site to name the new kind or to sit on a reasoned allow-list.
  - Both kinds yield plain C values, so ownership predicates may answer false for them.
- **`StaticAssert*`.**
  - They declare no name and complete normally.
  - They are reachability roots for the types they name.
  - In module units, they belong to their file's group.
  - The record-member owner skips `StaticAssertMember` (C2), and realtime ignores all three kinds.
  - `@gpu` bodies refuse them.
- **`StaticAssert*` and strict imports.** Strict-import checking visits these kinds:
  - Python adds `StaticAssertDecl` to `_REFERENCE_DECLS` (`frontend/imports.py:390-396`, filtered at `:693`). btrc adds it to the declarations `Visibility.btrc:542` accepts, beside `isNamedDeclaration` (`:315`).
  - Both `TypeExpr` branches (`imports.py:477-482`, `Visibility.btrc:123-129`) also visit `parts`, so `_Alignas(struct P)` and `_Alignas(IMPORTED)` need their import.
- **`type_part`.** Only these reach it, and a contract test checks this:
  - the parsers, the renderers and `AstStructure.children`;
  - frontend visibility;
  - the specifier validator, `value_type` and the qualifier owner;
  - the identity encoders, the type-shape transformers and the declarator copier;
  - the layout model and `CTypeLowerer`.
- **`GotoStmt`, `LabelStmt`.** The parsers keep today's `goto` errors until Stage 20 and never build either kind; their coverage test lists them as "refused before analysis".

## Rules by row

### r15a qualifiers and storage classes (the declarator lane)

**Qualifier owner.** Python's `TypeSystem.qualifiers_at(type_expr, depth)` and btrc's `TypeShape.qualifiersAt` answer (const, volatile, restrict) per storage depth, through typedef layering.
- **Depths.** Depth 0 is the object, and the base is at `pointer_depth + rank`.
- **Arrays.** An array's qualifiers are its elements' (C11 6.7.3p9). In `int* const a[3]`, the `const` therefore belongs to the elements: `a[0] = q` is refused, `value_type` keeps the qualifier, and the IR flags apply to the element declarator.
- **Views.** `StorageModel.volatile_qualifier_depths` (`storage.py:330`), `const_qualifier_depths` (`:355`) and `TypeSystem.declaration_const_depths` (`types.py:2297`) become views of it.
- **Typedefs.** A typedef-inherited qualifier still shifts below the use site's pointer and array layers.

**The D-1 flip.** `volatile int* p` points to a volatile `int`; `int* volatile p` is a volatile pointer.
- Every reader of `is_volatile` (97 Python and 92 btrc references) goes through `qualifiers_at`.
- So does every IR flag taken straight from the AST, such as `translation_unit.py:821` (`is_volatile=bool(type_expr.is_volatile)`).
- The strip contract test bans direct clears (`is_const=False`/`is_volatile=False`; btrc `isConst = false`/`isVolatile = false`) and raw `is_volatile` reads outside the owners.

**`value_type`, qualifier half.** It removes the object's own qualifiers:
- the base bools, for a non-pointer;
- the `PointerQualifiers` entry at `pointer_depth`, for a pointer;
- a qualifier inherited from a typedef, by composing the alias first.

It replaces these clearing sites:
- Python: `ir/lowering/types.py:925`, `ir/lowering/calls.py:2629-2630`, `analyzer/calls.py:267`;
- btrc: `ir/lowering/Concurrency.btrc:164-167`, `Calls.btrc:907-910`, `ownership/Operands.btrc:219-222`, `Expressions.btrc:2594-2595`, `validation/Calls.btrc:150-151`.

Pointee qualifiers now survive these sites. Any site that wrote through a temporary whose pointee qualifiers had been stripped is fixed, not hidden.

**Conversions** (C11 6.5.16.1p1). One check per compiler covers all three qualifiers:
- an implicit pointer conversion may add qualifiers at depth 1;
- deeper levels must match;
- dropping a qualifier is refused.

These merge into it: Python's `StorageModel._const_conversion_allowed` (`storage.py:206`), `TypeSystem._const_conversion_allowed` (`types.py:2285`) and `validate_volatile_reference_conversion` (`storage.py:101`). The two message families unify (D-7).

**Outer qualifiers** follow the position table.
- **Refused** on:
  - returns, with the existing template (`types.py:1484` / `validation/Types.btrc:806`) extended to `restrict`;
  - cast targets †;
  - `va_arg` types, generic arguments and tuple elements.
- **Dropped** by `value_type`, so `int* const p; int* q = p;` is valid.
- **Ignored** when comparing a prototype with its definition, along with `register`, for top-level parameter qualifiers (C11 6.7.6.3p15).

**Const members and fields** (S-5). `_aggregate_has_const_member` (`expressions.py:800-813`) and the class-field initializer refusal (`statements.py:559-567`) test `is_const and not is_pointer_value`. They move to `qualifiers_at(type, 0)`, so they see members like `char* const p`. Whole-record assignment of such a record is refused.

**Generic arguments** (D-12). Generic arguments, tuple elements, rich-enum payloads and collection element types refuse:
- any qualifier written in them, at the base or at a pointer level;
- any object qualifier inherited through a typedef;
- a record with a const member, transitively.

The first two use the existing `generic arguments cannot be {const|volatile|restrict}-qualified` text that both compilers already emit (`types.py:449-470`; `syntax/Identity.btrc:1086-1097`). The record case reads `generic arguments cannot be records with const-qualified members ('S.x')`.

**`restrict`** qualifies only a pointer whose referenced type is an object type or an incomplete type (C11 6.7.3p2, 6.2.5p1).
- `void* restrict` is accepted, and so is `restrict IP p` for a pointer typedef.
- Non-pointers and function pointers are refused.
- `restrict` never qualifies a managed reference.

**Managed references** take neither `volatile` nor `restrict`.
- After the flip, a base `volatile` on `Box` would qualify the struct behind the reference, and no ARC path can carry that.
- No source in the tree writes either qualifier on a managed type (grep).
- The setjmp planner already makes managed locals volatile across `try` on its own.

**`register`:**
- It is allowed on block-scope objects and on the parameters of functions, methods and lambdas.
- The object must hold a scalar plain C value: an integer, floating type, `bool`, `char`, plain enum or raw pointer †.
- These are refused: `&r` (C11 6.5.3.2p1), capture by a lambda or `spawn`, and `register` together with `_Alignas`.
- It is emitted as `register`.

**No lowering may take a `register` object's address** (D-11):
- **btrc.** `lowerDirectCompound` and `lowerDirectStore` use the value-temporary form, as Python does, whenever the root is an identifier. For other roots, `directLvaluePointerType` (`ir/lowering/Expressions.btrc:1238-1248`) adds the object's `restrict` and `volatile` from `qualifiersAt(type, 0)`. `int* restrict p; p += 1;` therefore no longer discards `restrict`.
- **Python.** The ternary store adapter skips register targets and emits btrcc's plain form instead.
- **Backstop.** A post-optimization rule refuses any `IRAddressOf`, array decay, out-parameter adapter, cleanup-slot registration or synthesized lvalue pointer rooted at an `is_register` declaration. Python's `IRVerifier` and btrc's `CEmitter` enforce it, as C2 does for bit-fields.

**`auto`** (D20) is accepted on block-scope objects and in C-for initializers, and dropped at lowering; it reaches no IR. `auto x = 1;` gets the parser's targeted refusal.

**`_Thread_local`:**
- **Placement.** It is allowed at file scope, and at block scope only together with `static` or `extern` (C11 6.7.1p3).
- **Type.** The type must be a plain C value, because btrc has no thread-exit ARC teardown.
- **Initializer.** The initializer follows the static-initializer rules. `&t`, or the decay of a thread-local array, is **not** an address constant (C11 6.6p9), so `_is_static_storage_initializer` (`statements.py:171`) and its btrc twin refuse it in static and thread-local initializers.
- **Realtime.** A thread-local access is a realtime effect in the `allocation` category, because the first access on a thread may allocate (`_tlv_get_addr` on Darwin, emutls under MinGW gcc). It is reported through the existing witness template (`realtime.py:877-888`), so a helper reached from `@realtime` is refused too.
- **`@gpu`.** Refused.
- **Module units.** The extern declarations carry `_Thread_local`. `IRGlobalDecl.is_thread_local` survives `_partition_module_unit`, which mutates globals in place (`translation_unit.py:248-255`).
- **Cost.** The emulated-TLS cost of gcc on macOS is documented, as in AGENTS.md.

**Emission:**
- **The C type text.** `CTypeLowerer.render` (`ir/lowering/types.py`, `ir/lowering/Types.btrc:20`) renders base and inner-level qualifiers into the `CType` text. The text still ends in `*` or a type name, so the `endswith("*")` sites (10 in Python, 4 in btrc) stay correct.
- **IR flags.** The outermost pointer level's qualifiers become IR flags. `is_const` and `is_restrict` are new; `is_volatile` exists.
- **What stays in the text.**
  - A non-pointer object's `const`, as today.
  - Qualifiers on a typedef-named or `CFunction`-named outer type, as `const IP p` does today. The new flags have no `effective_` twin.
- **Emitter helper.** `CType.qualify_volatile_object` becomes `qualify_object(text, const, volatile, restrict)`. One emitter helper per compiler writes `int* const volatile restrict name`.

**Messages that call layered qualifiers unsupported** are reworded, because r15a supports them:
- the discard message (`storage.py:116`, `Storage.btrc:1304`) drops its advice to use a typedef;
- the setjmp alias refusal (`ir/lowering/exceptions.py:839`, `ir/optimization/setjmp/Safety.btrc:51`) becomes `storage object 'x' is modified across try/throw and must be volatile; declare it volatile and point to it with 'volatile T*'`.

**Native imports** keep refusing `volatile` and `restrict` (`frontend/native_imports.py:2692-2726`). Lifting that is a separate commit after r15a, with a reader cross-check.

**Before landing**, grep BTRSmith for `volatile <type>*` and review every hit, because its meaning changes.

### r15b `inline`, `static inline`, `_Noreturn`

**Function specifiers** apply only to top-level `FunctionDecl`s.
- The parser refuses them at the specifier on methods, lambdas, interface signatures, rich-enum variants and `@gpu` functions.
- `main` is refused (C11 6.7.4p4).
- A prototype and its definition must agree on both specifiers †.
- `inline` together with `...` is refused †.
- Generic free functions do not exist (`FunctionDecl` has no type parameters, `ast.asdl:37-40`), so there is no generic case.

**Linkage (D20):**
- **`static inline`.** Whole-program mode emits it as written. In module units, its definition is a shared declaration, copied with internal linkage into every unit that references it. It is never made external, unlike today's owned `static` functions (`translation_unit.py:229`).
- **`inline` and `extern inline`.**
  - The inline definition is a shared declaration that every referencing unit sees, with `inline` on every declaration there and no `extern`.
  - The owning group's unit and the whole-program translation unit emit the definition plus a non-inline prototype.
  - Exactly one external definition therefore exists (C11 6.7.4p7).

**The inline subset.** Any inline body, `static` or not, is checked against a whitelist. A copied definition cannot carry session-counted helpers, whose names collide across units, or per-unit state, which would make module units behave differently from whole-program mode.

An inline body may contain these statements:
- blocks;
- declarations of plain-C-value locals, and `static const` locals of plain C value with constant initializers;
- `if`, `while`, `do`, C-`for`, `switch`, `break`, `continue` and `return`;
- expression statements and `_Static_assert`.

It may contain these expressions:
- literals; a narrow string literal is allowed only as a direct argument to a hosted parameter of type `char*` or `const char*`;
- identifiers naming plain-C-value parameters, locals, globals and enum constants;
- unary and binary operators, assignment and compound assignment on plain C values;
- casts between plain C types;
- `sizeof`, `_Alignof` and `?:`;
- indexing of raw pointers and fixed arrays;
- `.` and `->` on plain records;
- compound literals of plain types;
- calls to **inline-callable** functions, with every argument written.

**Inline-callable** means a top-level btrc function, or a hosted ABI function from `hosted_abi.toml`'s `[[functions]]`. These are not inline-callable:
- native imports, whose call contracts may need generated adapters (`ir/lowering/functions.py:1286-1293`, `:1433-1440`, `:1595-1606`);
- runtime helpers;
- methods and dispatch thunks (`ir/lowering/classes.py:154-245`).

**Plain `inline` and `extern inline` bodies** have two further limits †:
- they may not reference a `static` function or object (C11 6.7.4p3);
- they may not use `/`, `%`, `/=` or `%=`, which btrc lowers through `static inline` helpers (`core.c:53-58`). The diagnostic suggests `static inline`.

**Everything else is refused**, with one template:
- managed values, `print` and f-strings;
- lambdas, `spawn` and `parallel for`;
- `try`/`catch`/`finally`/`throw`;
- `new`/`delete`/`keep`/`release`;
- `@gpu` dispatch, for-in, `?.`, `??` and tuples;
- calls that omit a defaulted argument;
- modifiable `static` or `_Thread_local` locals. For plain `inline` this is C11 6.7.4p3. For `static inline` the reason is the per-unit copies †.

**Lowering inline bodies:**
- Python's ternary store adapter (D-11) is skipped inside inline bodies.
- **Contract test.** It lists every lowering site that emits a session-local static: each `is_static=True` definition (69 in Python's `ir/lowering`), each `ensure_*` adapter and each `require_helper`. For each one, it names either the whitelist rule that keeps it out of inline bodies or an explicit refusal.
- **Backstop.** A post-optimization check raises an internal error for any inline definition that references a session-local static. For plain `inline`, a reference to a runtime helper or a `static` function also raises it. Python's `IRVerifier` and btrc's `CEmitter` implement the check.

**Module units:**
- `SharedDeclarations._FIELDS` (`application/modules.py:578-587`) and btrc's `ModuleUnitDeclarations` (`pipeline/ModuleUnits.btrc:375`, entry kind 8) gain inline definitions.
- The declarations-only session lowers inline bodies.
- The unit's name closure and its helper rematerialization run after the copies are merged.
- Python's `ProgramInterface` (`modules.py:488`, body elision at `:556-563`) and btrc's `ModuleUnitInterfaceSummary.callableBody` (`ModuleUnits.btrc:23-30`) stop eliding inline bodies, as they already keep template bodies. Editing an inline body therefore invalidates every unit that copies it.
- `_partition_module_unit` (`translation_unit.py:233-241`) and btrc's `Lowerer.btrc:257-277` rebuild prototypes of other groups' functions. Those prototypes now copy `is_noreturn` and `is_variadic` (I-11). Prototypes of inline functions come from the shared inline declaration instead.
- The setjmp solver uses the owner's summary for copies.

**Completion owner** (D-13).
- **Python.** `ControlFlowAnalyzer.can_complete_normally` (`analyzer/flow.py`) replaces `statement_must_terminate`/`block_must_terminate` (`:249-306`).
- **btrc.** `ControlFlowValidator.canCompleteNormally` replaces `statementTerminates`/`blockTerminates` (`validation/ControlFlow.btrc:157-260`). `ExpressionTypeResolver`'s copy (`blockTerminates`, `statementTerminates` and `elseTerminates`) is already gone: the D-13 parity commit (`CL-C-02`) deleted it and left one btrc lambda check, on the validator's statement-analysis path, so r15b changes only the validator's predicate.
- **Callers.** The function, method, lambda, getter, `_Noreturn` and `va_list` checks call it, as do Stage 20 and both lowering sites (`ir/lowering/exceptions.py:1563`, `ir/lowering/Statements.btrc:1043`).

The rules below say when a statement can complete normally. The infinite-loop rule is btrc's, as in Java, not C's: C makes a missing return undefined only when the caller uses the value (6.9.1p12).

| Statement | Can complete normally |
|-----------|-----------------------|
| `return`, `throw`, `break`, `continue` | no (the enclosing loop or switch accounts for `break` and `continue`) |
| expression statement | yes, unless it is a direct call to a `_Noreturn` btrc function or to a hosted function marked `noreturn` |
| declaration, `_Static_assert`, `delete`, `keep`, `release` | yes |
| block, case body | only if every statement in it can. Statements after a call or loop that does not complete stay legal (`exit(1); return 0;`). |
| `if` | without `else`: yes. With `else`: only if either branch can. |
| `switch` | no, when it has `default`, no `break` targets it, and no case body can complete normally (today's rule) |
| `while (true)`, `for (;;)`, `do … while (true)` | only if a `break` targets it. Today's rule also required the body to terminate. |
| `do body while (c)`, where `c` is not the literal `true` | only if a `break` targets it, the body can complete normally, or a `continue` targets it |
| other `while`, C-`for`, for-in, `parallel for` | yes |
| `try` | only if the `finally` block (when present) can, and the `try` block or the `catch` block (when present) can |

- "Infinite" is syntactic: a `BoolLiteral(true)` condition, or an absent C-for condition.
- A parity test runs every row in both compilers.
- The "Unreachable code after return/throw/break/continue" check (`statements.py:1717-1729`) is unchanged.
- Lowering marks calls to noreturn functions `IRCall.never_returns`, which `IRBlock` fall-through analysis already reads (`ir/nodes.py:998`). The C of existing programs changes only by the dead code after `exit`/`abort`.

**Missing return** keeps its rule and unifies its text (D-7): `{Function 'f'|Method 'C.m'|Lambda|Property getter 'C.p'} has non-void return type but does not return on every path` †.

**`_Noreturn` bodies:**
- A `_Noreturn` function must return `void` †, contains no `return` †, and its body cannot complete normally †.
- A `throw` out of one is allowed.
- Managed locals that are live at a call to it are not released before the process ends; this is documented.

**Hosted `noreturn`.** The key marks exactly the existing typed rows `abort`, `exit`, `_Exit` and `quick_exit`. `longjmp` and `pthread_exit` have no typed rows today, and adding rows would change how their calls are typed, so they wait for their own commit.

**Realtime.** There is no new rule: the body's own effects classify the function.

### r15c `_Static_assert` (with a constant-evaluator parity reviewer)

**Where:**
- **Allowed** at file scope, in statement position (blocks, and case bodies, which btrc emits braced) and in struct or union bodies.
- **Refused** in class and interface bodies, in C-for initializers †, as a braceless sole body (C1's declaration-as-body rule), and in `@gpu` bodies.
- **Generic bodies.** Inside one, an assertion may not depend on a type parameter.

**Condition:**
- It is an integer constant expression of any integer type, `bool` included.
- It is compared with 0, not converted to `bool` (C11 6.7.10p2), so row 22 does not apply and row 21 does.
- It is evaluated in the body pass, after every declaration is registered, by the typed evaluator and the layout model. Inside a record body, that record is incomplete.

**Message.**
- One or more narrow string literals, or source macros that resolve to one (C1 r05). A prefixed message is refused †.
- The failure diagnostic quotes the message's C spelling, so escapes never reach a diagnostic line.

**Emission (D20):**
- File-scope and member assertions go to `IRModule.static_asserts`. They are emitted after all type definitions and before prototypes, and they are optimizer roots.
- Block-scope assertions stay in place.
- The condition goes through constant lowering.

**Module units:**
- File-scope assertions are emitted in their file's group, and both module-unit closures follow them: Python's `SharedDeclarations` (`modules.py:568-600`), and btrc's `ModuleUnitGraph.references` and `ModuleUnitDeclarations.collectNode` (`ModuleUnits.btrc:37-66`, `:506-530`).
- btrc's `IRK_STATIC_ASSERT` keeps its message in `text`. `ModuleUnitDeclarations.collectText` (`:486-497`) skips `text` for that kind.

**`static_assert(...)`** (D-8). A call whose callee resolves to `<assert.h>`'s hosted macro is refused at the callee with `Use _Static_assert; btrc does not expand <assert.h>'s static_assert macro` †. `alignas`, `alignof`, `noreturn` and `thread_local` are not hosted names, so they stay ordinary identifiers; refusing them everywhere would break user names. Known-language-gaps tells users to write the keywords.

**Corpus.** r15c's corpus uses `sizeof`, not `_Alignof`, because r15c merges before r15d.

### r15d `_Alignas`, `_Alignof`

**Value:**
- `_Alignas(N)` takes an integer constant with a known value. `_Alignas(T)` means `_Alignas(_Alignof(T))` (C11 6.7.5p5).
- Each specifier must be 0 or a power of two, within the limits below (6.7.5p3).
- The **combined** effective alignment, which is the strictest one (p6), must be at least the declared type's natural alignment (p4). Checking this needs that type's layout.
- `_Alignas(2) _Alignas(8) int x;` is valid (probe `al.c`).

**Limits.** These are deliberate and portable; extended alignment is implementation-defined (C11 6.2.8p3) †.
- **At most 16 for struct and union members.** Heap storage comes from `calloc`/`realloc` (`core.c:13-25`): class objects, collections and rich-enum payloads. Every supported platform aligns those allocations to 16, although C11 7.22.3p1 promises only `_Alignof(max_align_t)`, which is 8 on macos-aarch64.
- **At most 16 for automatic and thread-local objects.** MinGW gcc does not realign the stack beyond 16 (GCC PR 54412).
- **At most 4096 for static-storage objects.**

**Positions** follow the table. `_Alignas` is not allowed on:
- typedefs, parameters or functions;
- bit-fields (C2's reserved message);
- `register` objects;
- class fields or type names;
- members under `#pragma pack` †;
- `@gpu` buffer element types.

**Agreement** (C11 6.7.5p7). Declarations of one object must agree:
- a definition with a specifier admits only declarations with an equivalent specifier or none;
- a definition without one admits only declarations without one.

Module-unit externs carry exactly the definition's alignment, which the verifier checks.

**Member effect.** A member's alignment changes its record's layout in the layout model.

**`_Alignof(T)`:**
- It is `size_t`, so row 21 applies.
- It needs a complete object type.
- It evaluates in constant contexts, and is emitted as `_Alignof(T)` elsewhere, as `sizeof` is.

### r16 wide and UTF literals, `long double`

**Types** (C11 6.4.4.4, 6.4.5p6):

| Literal | Type |
|---------|------|
| `"…"`, `u8"…"` | `string` |
| `L"…"` | `wchar_t[N]`, decaying to a pointer |
| `u"…"` | `char16_t[N]`, decaying to a pointer |
| `U"…"` | `char32_t[N]`, decaying to a pointer |
| `L'x'` | `wchar_t` |
| `u'x'` | `char16_t` |
| `U'x'` | `char32_t` |
| `1.5L` | `long double` (`FloatLiteral.typeName`, `syntax/Literals.btrc:260`; `NumericLiteralSemantics.float_type`, `types.py:192`) |

Writing through a wide literal is undefined, as in C and as for narrow literals today; this is documented.

**Extents** count code units of the prefix's encoding (C11 6.4.5p6):
- **Encodings.** Narrow literals and `u8` use UTF-8, `u` uses UTF-16, and `U` uses UTF-32. `L` uses UTF-16 on `windows-*` and UTF-32 elsewhere. A UCN counts as the character it names.
- **Examples.**
  - `u8"é"` has 3 bytes plus the terminator.
  - `u"😀"` has 2 units, and `U"😀"` has 1.
  - `L"😀"` has 2 units on Windows and 1 elsewhere.
- **Owner.** One decoder per compiler (Python `LiteralDecoder.code_units`, `lexer/lexer.py:19`; btrc `StringLiteral.codeUnits` in `syntax/Literals.btrc`) feeds inferred extents, r04's fit check and the layout model.
- **Slicing.** Every site that slices a literal's value uses `LiteralDecoder.string_prefix` in Python, or `StringLiteral.prefix` and `body` in btrc.

**Integer classes:**
- `wchar_t` stays ABI-dependent (row 21; `types.py:917`).
- `char16_t` and `char32_t` join the portable unsigned set in both compilers.
- They are emitted as `uint_least16_t`/`uint_least32_t`, from `<stdint.h>`, which is always included. `<uchar.h>`, whose availability varies across SDKs, is never required.

**Character constants** accept one printable ASCII character, one escape, or one UCN whose value fits the target type (C11 6.4.4.4p9). The analyzer checks the fit, because `wchar_t` is 16 bits on Windows.

**Initialization.** A `wchar_t`, `char16_t` or `char32_t` array is initialized only from a literal with the matching prefix (C11 6.7.9p15). r04's exact-fit refusal extends to these arrays.

**Concatenation** (C11 6.4.5p2, p5):
- An unprefixed piece takes the other pieces' prefix.
- `u8` with `L`, `u` or `U` is refused; C makes it a constraint violation.
- Two different wide prefixes are refused †. C leaves this implementation-defined, and gcc and clang refuse it.

**Formatting.** `print` and f-strings refuse wide strings, and wide strings never convert to `string`.

**Range.** `long double` literals are limited to the finite `double` range on every target, because macos-aarch64's `long double` is `double` †.

### Stragglers (the r16 agent, because they share the lexer)

- **`sizeof unary`.** `sizeof x + 1` is `(sizeof x) + 1`. `sizeof int` is refused at the type.
- **Hex floats** use the exact `float.fromhex`/`strtod` value and the existing float32 narrowing check (`LiteralDecoder.float_problem`, `lexer.py:100`).
- **Decimal forms** follow the disambiguation rules above.
- **`p += n`, `p -= n`** on a raw pointer are accepted exactly when `p = p + n` is, and lower to the C compound operator. `p *= 2` stays refused; btrcc adopts the reference compiler's capitalized `Operator '*=' …`.
- **`sizeof (T){…}`** takes the compound-literal operand that C2 left a parse error.

### r14 variadic definitions (its own batch, last)

**Declaration:**
- `, ...` may end the parameter list of a top-level function (a definition or a prototype), after at least one named parameter.
- The parser refuses it, at `...`:
  - on methods, lambdas, `CFunction` and `@gpu` functions;
  - when no named parameter precedes it.
- A variadic function may not declare defaults, and calls to it may not use named arguments.
- It cannot be used as a value †, because `CFunction` cannot spell `...`.

**Arguments** follow the existing hosted-variadic rule: managed values are borrowed for the call. C performs the default argument promotions.

**The last named parameter** may not be `register`, an array or function type, or a type that promotion changes (C11 7.16.1.4p4).

**`va_list` objects** are locals or parameters.
- Their address may not be taken †.
- They may not be assigned or copied; use `va_copy`.
- They may not be stored in a field †, a global or a collection, returned, or captured.
- `sizeof` of one has no layout.

**`va_arg(ap, T)`:**
- It needs a complete plain-C-value type that default argument promotion leaves unchanged: no `bool`, `char`, `short` (signed or unsigned) or `float`, and no managed type.
- Its type is emitted as a single name, so that a `*` can be appended (C11 7.16.1.1p2). A `CFunction` type is emitted through its registered typedef.

**States** are a flow rule in the completion owner. A local `va_list` is unstarted, started, indeterminate or ended; a parameter is borrowed.

| Operation | Allowed when | Afterwards |
|-----------|--------------|------------|
| `va_start(ap, last)` | only inside the variadic function, with `last` its last named parameter; `ap` an unstarted or ended local | started |
| `va_copy(dst, src)` | `dst` an unstarted or ended local; `src` started or borrowed | `dst` started |
| `va_arg(ap, T)` | `ap` started or borrowed | unchanged |
| passing `ap` to a function | `ap` started or borrowed | indeterminate (C11 7.16p3); only `va_end` may follow |
| `va_end(ap)` | `ap` a started or indeterminate local | ended |

- A parameter takes neither `va_start` nor `va_end` (7.16.1.3p2).
- Every path to a `return` or to the end of the function must leave each local unstarted or ended.
- States must agree where paths merge and at each loop back-edge.

**Exceptions:**
- **`try`.** A `try` statement is refused in any function that declares or receives a `va_list`, for two reasons:
  - the setjmp planners would make the list volatile (`markVisible`, `ir/optimization/setjmp/Safety.btrc:426-479`; `ir/lowering/exceptions.py:1507-1541`), which gcc and clang reject (probe `vva.c`);
  - a non-volatile list is indeterminate after `longjmp` (C11 7.13.2.1p3).
- **`throw`.** Refused while a local list is started or indeterminate.
- **Callees.** An exception thrown by a callee skips `va_end`. That is a no-op on all six targets, and it is documented.

**Operands.** The evaluation-order planners never hoist a `va_list` operand: Python's `CallableProvenance.plan_evaluation` (`ir/lowering/calls.py:1264`, temporaries at `:293`) and btrc's `ir/lowering/ownership/Calls.btrc:94`. Hoisting would write `__btrc_call_operand_N = ap`, which assigns an array on linux-x86_64 and copies without `va_copy` elsewhere (probes `hoist.btrc`, `vp.c`).
- A call that passes `ap` and has another operand that acts on it, such as `va_arg(ap, …)` or a call that receives `ap`, is refused.
- The arguments of `va_*` macros are emitted verbatim and must name a `va_list` object.

**Realtime and headers.** `va_start`, `va_copy` and `va_end` are `safe` intrinsic rows, and `VaArgExpr` is safe by kind. Lowering requires `<stdarg.h>`.

## Lowering invariants

Python's `IRVerifier` checks these after optimization; in btrc, `CEmitter`, which runs after the optimizer, raises internal errors for violations:
- `is_const` and `is_restrict` on a declaration require a pointer `CType` (text ending in `*`); `is_restrict` also requires an object or incomplete pointee.
- `alignment` is 0 or a power of two, and appears only where the position table allows `_Alignas`. Extern declarations carry their definition's alignment.
- No `IRAddressOf`, array decay, out-parameter adapter, cleanup-slot registration or synthesized lvalue pointer is rooted at an `is_register` declaration.
- A `va_list` value appears only as an uninitialized declaration, a direct call argument or a `va_*` operand, and it is never volatile.
- `IRStaticAssert` appears only in a block or in `IRModule.static_asserts`.
- No inline definition references a session-local static. No plain-inline definition references a runtime helper or a `static` function.
- `IRGoto` and `IRLabel` are refused until Stage 20, whose V1–V4 replace the refusal (`c-goto-labels.md`).

## Refusals

Each refusal has the same text and position in both compilers. The C11 column says what C makes of the source:
- **invalid**: a constraint violation, a syntax error, or undefined behavior that btrc detects. It gets a negative probe in `c3_c4.toml` or a refusal-parity test.
- **valid †**: valid or implementation-defined C11 that btrc refuses on purpose. It gets a row in known-language-gaps' "C that btrc rejects on purpose" and a test in `test_c_compatibility_refusals.py`.
- **btrc**: no C counterpart. It gets a parity test.

**r15a**

| Case | Diagnostic | C11 |
|------|------------|-----|
| `restrict` on a non-pointer or a function pointer | `'restrict' can only qualify a pointer to an object type, not 'int'` | invalid |
| `volatile` or `restrict` on a managed reference | `'volatile' cannot qualify managed reference type 'Box'` (also `restrict`) | btrc |
| Qualifier after `?` | `Pointer qualifiers cannot follow '?'; write the nullable pointer without them` | btrc |
| Qualifier after btrc's prefix `T[]` | `Pointer qualifiers cannot follow btrc's T[] array type; declare the extent after the name` | btrc |
| Qualifiers or `static` in array-parameter brackets | `Qualifiers and 'static' inside array parameter brackets are not supported; write 'int* restrict a'` | valid † |
| Outer qualifier on a return | existing `{subject} cannot carry an outer const/volatile qualifier; C discards qualifiers on returned values`; for `restrict`, `{subject} cannot carry an outer restrict qualifier; C discards qualifiers on returned values` | valid † |
| Outer qualifier on a cast | `Cast type cannot carry an outer {q} qualifier; C discards qualifiers on cast results` | valid † |
| Qualified generic argument, including one inherited through a typedef | existing `generic arguments cannot be {const\|volatile\|restrict}-qualified` | btrc |
| Record with a const member as a generic argument | `generic arguments cannot be records with const-qualified members ('S.x')` | btrc |
| Modifying a const object (unified) | `Cannot modify const storage of type 'int* const'` | invalid |
| Discarding a qualifier (unified) | `{Subject} would discard {const\|volatile\|restrict} qualification at pointer depth {n}` | invalid |
| Outer `const` class field with an initializer | the existing template without "scalar": `{subject} cannot initialize a const class field after allocation` | btrc |
| Storage class or function specifier after the base type | `'static' must come before the type in a declaration` (also `inline`, `_Noreturn`) | valid † (6.11.5, for storage classes) |
| Two storage classes | `Declaration of 'x' has more than one storage class ('static' and 'register')` | invalid |
| A storage class the position table refuses. `static`/`extern` on parameters and fields keep the existing `{subject} cannot carry static/extern storage qualifiers`. | `'register' is not allowed {at file scope\|on struct member 'S.x'\|on class field 'C.x'\|on function 'f'\|in a typedef\|in a for initializer}` (also `_Thread_local`, and `static`/`extern` in a for initializer) | invalid |
| `register` on a non-scalar | `Register variable 'x' must hold a scalar C value, not 'int[4]'` | valid † (arrays, records) |
| `&` of a register object (`r15-register-address`, at 3:17) | `Cannot take the address of register variable 'counter'` | invalid |
| Capture of a register object | `Register variable 'x' cannot be captured; its address cannot be taken` | btrc |
| Storage class in a type name | `'register' is a storage class; it cannot appear in a type name` | invalid |
| `auto` where the position table refuses it (`r15-auto-file-scope`, at 1:1) | `'auto' is not allowed {at file scope\|on parameter 'x'\|on struct member 'S.x'\|on function 'f'}; C11 auto declares a block-scope object` | invalid |
| `auto x = 1;` | `'auto' is C11's storage class, not type inference; write 'var x = ...' or give a type` | invalid |
| Block-scope `_Thread_local` without `static`/`extern` | `Block-scope _Thread_local variable 'x' must also be static or extern` | invalid |
| Managed `_Thread_local` | `_Thread_local variable 'x' must hold a plain C value; 'string' is managed` | btrc |
| Address of a thread-local in a static initializer | `The address of _Thread_local variable 't' is not a constant; it cannot initialize a static or thread-local object` | invalid |
| Thread-local access reached from `@realtime` | existing witness: `@realtime callable 'f' reaches forbidden allocation operation 'thread-local access 'x'' via f -> g` | btrc |

**r15b**

| Case | Diagnostic | C11 |
|------|------------|-----|
| Function specifier off the top-level function path (at the specifier) | `'inline' can only declare a top-level function` (also `_Noreturn`) | invalid for objects; btrc for methods and lambdas |
| `main` | `'main' cannot be declared inline` / `'main' cannot be declared _Noreturn` | invalid |
| `@gpu` | `@gpu function 'k' cannot be inline` (also `_Noreturn`) | btrc |
| Declarations that disagree | `Declarations of 'f' disagree about inline` (also `_Noreturn`) | valid † |
| Inline and variadic | `Variadic function 'f' cannot be inline` | valid † |
| Declared, never defined | `Inline function 'f' is declared but never defined` | invalid |
| Outside the whitelist | `Inline function 'f' cannot use {managed type 'string'\|a lambda\|spawn\|parallel for\|a try statement\|throw\|new\|delete\|keep\|release\|print\|an f-string\|a @gpu dispatch\|a for-in loop\|'?.'\|'??'\|a tuple\|native function 'g'\|method 'C.m'\|the default of parameter 'x' of 'g'\|static local 'n'}; inline bodies are limited to plain C values` | btrc; valid † for a modifiable static local in `static inline` |
| External linkage and a static entity | `Inline function 'f' has external linkage and cannot use static function 'helper' (C11 6.7.4p3); declare it static inline` (also `static variable 'g'`, `static local 'n'`) | invalid |
| External linkage and `/` or `%` | `Inline function 'f' has external linkage and cannot use '/', which btrc checks through a unit-local helper; declare it static inline` | valid † |
| `_Noreturn` with a non-void result | `_Noreturn function 'fail' must return void` | valid † |
| `return` in a `_Noreturn` function, at the return | `_Noreturn function 'fail' cannot contain a return statement` | valid † (undefined if executed) |
| `_Noreturn` function that can complete | `_Noreturn function 'fail' can reach the end of its body; end every path with a call to a _Noreturn function, a throw or an infinite loop` | valid † (undefined if it does) |
| Missing return (unified, D-7) | `{Function 'f'\|Method 'C.m'\|Lambda\|Property getter 'C.p'} has non-void return type but does not return on every path` | valid † (6.9.1p12) |

**r15c**

| Case | Diagnostic | C11 |
|------|------------|-----|
| False (`r15-static-assert-false`, at 1:1) | `Static assertion failed: "never"` | invalid |
| Not constant, at the condition | `_Static_assert condition must be an integer constant expression` | invalid |
| Non-integer | `_Static_assert condition must have an integer type, not 'double'` | invalid |
| No layout (D20), at the `sizeof`/`_Alignof` | `Cannot evaluate _Static_assert: btrc knows no layout for 'struct timespec'` | valid † |
| Unresolved macro | `Cannot evaluate _Static_assert: btrc cannot resolve the value of macro 'PAGE_SIZE'` | valid † |
| Record inside its own body, or with its layout in progress | `sizeof cannot measure 'struct S' inside its own body; the struct is incomplete until its closing brace` | invalid |
| One-argument form | `_Static_assert needs a message string in C11` | invalid (C2x) |
| Prefixed message | `_Static_assert message must be a narrow string literal` | valid † |
| Position | `_Static_assert cannot appear {in a class body\|in a for initializer\|in @gpu function 'k'}`; as a sole body, C1's declaration-as-body refusal | btrc; valid † in a for initializer; invalid as a sole body |
| Generic dependency | `_Static_assert in a generic body cannot depend on type parameter 'T'` | btrc |
| `static_assert(...)` (D-8), at the callee | `Use _Static_assert; btrc does not expand <assert.h>'s static_assert macro` | valid † |

**r15d**

| Case | Diagnostic | C11 |
|------|------------|-----|
| Not constant / cannot evaluate | `_Alignas value must be an integer constant expression` / `_Alignas value is a constant expression btrc cannot evaluate; write its integer value` | invalid / valid † |
| Not a power of two | `_Alignas(12) is not a power of two` | invalid |
| Combined alignment weaker than natural | `_Alignas(2) is weaker than the natural alignment 4 of 'int'` (names the strictest specifier) | invalid |
| Over a limit | `_Alignas(64) exceeds the 16-byte alignment btrc guarantees for {struct members\|automatic variables\|thread-local variables}`; `_Alignas(8192) exceeds the 4096-byte limit for static objects` | valid † (implementation-defined) |
| Unknown natural alignment | `_Alignas cannot check 'struct timespec': btrc knows no layout for it` | valid † |
| Position | `_Alignas cannot apply to {typedef 'T'\|parameter 'x'\|function 'f'\|bit-field 'S.f'\|register variable 'x'\|class field 'C.x'\|a type name}` (the bit-field text is C2's reserved message) | invalid; btrc for class fields |
| Packed struct | `_Alignas cannot apply to a member of a struct under #pragma pack` | valid † |
| Declarations that disagree | `Declarations of 'g' disagree about its alignment ({16} and none)` | invalid (6.7.5p7) |
| `_Alignof(expression)` (`x-alignof-expression`) | `_Alignof needs a type name; 'value' is a variable` | invalid (a GNU extension) |
| `_Alignof` of an incomplete type | `_Alignof cannot measure incomplete type 'struct X'` (also `void` and function types) | invalid |

**r16 and stragglers**

| Case | Diagnostic | C11 |
|------|------------|-----|
| `u8'c'` (lexer, `x-utf8-character-literal`, at 2:16) | `u8 character constants are C2x, not C11` | invalid |
| Character too wide (analyzer, target-aware) | `Hex escape '\x1F600' does not fit in wchar_t on windows-x86_64 (16 bits)`; `Character constant does not fit in char16_t` | invalid |
| `u8` with a wide prefix | `Adjacent string literals with prefixes 'u8' and 'L' cannot be concatenated` | invalid |
| Two different wide prefixes | `Adjacent string literals with prefixes 'L' and 'u' cannot be concatenated` | valid † (implementation-defined) |
| Narrow literal into a wide array | `Cannot initialize 'wchar_t[3]' from a narrow string literal; write L"..."` | invalid |
| `print` / f-string | `print cannot format a wide string ('wchar_t*'); convert it first` / `f-string cannot format a wide string ('wchar_t*')` | btrc |
| Prefixed import path | `An import path must be a plain string literal` | btrc |
| `long double` literal beyond the `double` range | `long double literal '1e400L' is outside the finite double range btrc guarantees on every target` | valid † |
| Hex float without an exponent (`x-hex-float-without-exponent`) | `Hexadecimal floating literal '0x1.8' needs a binary exponent ('p')` | invalid |
| `0x.p1`, `0x1p` | `Invalid hex float literal: no hex digits` / existing `Invalid float literal: no digits in exponent` | invalid |
| `sizeof int` (`x-sizeof-type-without-parentheses`, at 2:23) | `sizeof needs parentheses around a type name: write sizeof(int)` | invalid |
| `p *= 2` (`x-pointer-multiply-assignment`, at 4:2) | `Operator '*=' is not defined for 'int*' and 'int'` | invalid |

**r14**

| Case | Diagnostic | C11 |
|------|------------|-----|
| No named parameter (`r14-variadic-without-named-parameter`, at 1:9) | `A variadic function needs at least one named parameter before '...'` | invalid |
| Method, lambda or `CFunction`, at `...` | `Only top-level functions can be variadic` | btrc |
| Defaults / named arguments | `Variadic function 'f' cannot declare default parameter values` / `Variadic function 'f' cannot be called with named arguments` | btrc |
| Used as a value | `Variadic function 'sum' cannot be used as a value; CFunction cannot express '...'` | valid † |
| `va_start` outside a variadic function | `va_start can only be used in a variadic function` | invalid |
| Wrong last argument | `va_start's second argument must be 'fmt', the last named parameter of 'log'` | invalid |
| Last named parameter | `va_start cannot use parameter 'x' of type 'float'; default argument promotion changes it (C11 7.16.1.4)` (also `register`, arrays, functions) | invalid |
| Promoted `va_arg` type | `va_arg cannot read 'float': variadic arguments are promoted, so read 'double'` | invalid |
| Managed `va_arg` type | `va_arg cannot read managed type 'string'; read 'char*' and copy it` | btrc |
| States | One message per state violation; they are listed after this table. | invalid |
| `try` / `throw` | `A try statement cannot appear in a function that declares or receives a va_list` / `Cannot throw while va_list 'ap' is started; call va_end(ap) first` | btrc |
| Shared operand | `va_list 'ap' cannot be passed in a call that also reads it` | invalid (unsequenced) |
| Escapes | `Cannot take the address of va_list 'ap'` (valid †); `va_list values cannot be assigned or copied; use va_copy`; `va_list 'ap' cannot be {stored in a field\|stored in a global\|stored in a collection\|returned\|captured}` (a field is valid †) | as noted |
| `@gpu` | `@gpu function 'k' cannot be variadic` / `@gpu function 'k': va_arg has no WGSL lowering` | btrc |

**The state messages:**
- `va_list 'ap' is still started at this return; call va_end(ap) first`, and the same `… at the end of 'sum'`;
- `va_list 'ap' is already started; call va_end(ap) before starting it again`;
- `va_list 'ap' is not started here`;
- `va_list 'ap' is indeterminate after it was passed to 'vprintf'; only va_end(ap) may follow`;
- `va_list parameter 'ap' belongs to the caller; va_start and va_end apply only to a local`;
- `va_list 'ap' is started on some paths into this point and not others`;
- `va_list 'ap' must be in the same state at the end of each loop iteration as at its start`.

**`@gpu`** (S-29). `@gpu` functions refuse every C3 construct: `inline`, `_Noreturn`, `...`, `register`, `restrict`, outer pointer qualifiers, `_Thread_local`, `_Alignas`, `_Static_assert`, `_Alignof`, `va_arg`, `long double` and prefixed literals. They use:
- the r15b and r14 messages above for function specifiers and `...`;
- C2's template, `@gpu function 'k': {construct} has no WGSL lowering`, for the rest;
- or the existing type refusal.

The pending refusals are transient and documented nowhere: ``C11 'inline' is not supported yet``, and the same message for each pending token.

## Schema and vocabulary commit (`ccompat-c3-schema-vocabulary`)

The main session is the only owner. One read-only pre-drafter prepares the delta, and two read-only adversarial reviewers check it before it lands. The parsers produce none of the new syntax in this commit.

**1. `grammar.ebnf`.**
- **`@keywords`.** The seven C11 words go on the C line. `va_arg` goes on its own commented line ("C11 `<stdarg.h>` form whose second argument is a type name").
- **`@operators`.** `"..."` goes on the 3-character line.
- **`@literals`:**
  ```
  FLOAT_LIT  = /[0-9]+\.[0-9]*([eE][+-]?[0-9]+)?[fFlL]?/
             | /\.[0-9]+([eE][+-]?[0-9]+)?[fFlL]?/
             | /[0-9]+[eE][+-]?[0-9]+[fFlL]?/
             | /0[xX]([0-9a-fA-F]+(\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)[pP][+-]?[0-9]+[fFlL]?/
  STRING_LIT = /(u8|u|U|L)?"([^"\\\r\n]|\\.)*"/
  CHAR_LIT   = /(u|U|L)?'([^'\\\r\n]|\\.)*'/
  ```
  A comment states the leading-dot, trailing-dot and `...` rules above, and that a wide character literal may hold one UCN.
- **Comments and rules.** The reserved-keyword comment is rewritten. Every `@syntax` rule in the Conventions section is written, with each pending rule marked.

**2. `ast.asdl`.** This is on top of C2; the comments do not reach the generated files.

```asdl
    decl = ...
         | TypedefDecl(type_expr original, identifier alias,
                       int name_line, int name_col)
         -- C11 6.7.10 at file scope; parts are the message's string-literal
         -- pieces under StringConcat's rule.
         | StaticAssertDecl(expr condition, expr* parts)
    -- FunctionDecl gains three specifiers after keep_return:
         | FunctionDecl(type_expr return_type, identifier name,
                        param* params, block? body, bool is_gpu,
                        bool is_realtime, bool keep_return,
                        bool is_inline, bool is_noreturn, bool is_variadic,
                        int name_line, int name_col)

    -- is_const/is_volatile/is_restrict qualify the base type (C11 6.7.3),
    -- before or after it. parts holds one PointerQualifiers per qualified
    -- '*' (pointer_depth strictly increasing, 1..pointer_depth) and the
    -- AlignmentSpecifiers, in source order. Field order fills padding.
    type_expr = TypeExpr(identifier base, type_expr* generic_args,
                         int pointer_depth, bool is_array,
                         bool is_register, bool is_auto, bool is_thread_local,
                         expr? array_size, expr* elements, bool is_const,
                         bool is_nullable, int nullable_outer_depth,
                         bool is_static, bool is_extern, bool is_volatile,
                         bool is_restrict, int array_pointer_depth,
                         type_part* parts)
                attributes(int line, int col)

    field_def = FieldDef(type_expr type, identifier name, expr? value)
              | AnonymousMember(bool is_union, field_def* fields)
              | StaticAssertMember(expr condition, expr* parts)
              attributes(int line, int col)

    stmt = ...
         | StaticAssertStmt(expr condition, expr* parts)
         -- Stage 20 owns both (c-goto-labels.md, whose comments these are);
         -- no parser builds them until then.
         -- `goto name;` (C11 6.8.6.1). line/col mark `goto`; name_line and
         -- name_col mark the label identifier.
         | GotoStmt(identifier name, int name_line, int name_col)
         -- `name:` as a statement-list item (C23 6.8.2): it marks the position
         -- before the next item, or the end of the list, and owns no statement.
         -- line/col mark the identifier. Each callable and lambda body is one
         -- label scope; labels have their own name space.
         | LabelStmt(identifier name)

    expr = ...
         | CompoundLiteral(type_expr target_type, expr initializer)
         | AlignofExpr(type_expr type)
         | VaArgExpr(expr expr, type_expr type)

    -- after C2's designator. PointerQualifiers qualifies the pointer type
    -- formed by the base and its first pointer_depth '*'s.
    type_part = PointerQualifiers(int pointer_depth, bool is_const,
                                  bool is_volatile, bool is_restrict)
              | AlignmentSpecifier(type_expr? type, expr? value)
              attributes(int line, int col)
```

**Where each new field lives in the btrc `Node`.** These offsets are the generator's plan, re-run on this schema.

| Field | Storage | Offset |
|-------|---------|--------|
| `FunctionDecl.is_inline`, `is_noreturn`, `is_variadic` | new bools | 187, 188, 189: the padding after `keepReturn` |
| `TypeExpr.is_register`, `is_auto`, `is_thread_local` | new bools | 309, 310, 311: after `isArray` |
| `TypeExpr.is_restrict` | new bool | 339: after `isVolatile`, before C2's `arrayPointerDepth` |
| `TypeExpr.parts`, `StaticAssert*.parts` | `partsStorage` (lazy) | moves to 248, because `StaticAssertDecl` is now its first appearance |
| `StaticAssert*.condition` | `condition` | moves to 240 |
| `PointerQualifiers.*` | `pointerDepth`, `isConst`, `isVolatile`, `isRestrict` | existing |
| `AlignmentSpecifier.type`, `.value` | `type`, `valueNode` | existing |
| `AlignofExpr.type`; `VaArgExpr.expr`, `.type` | `type`, `expr` | existing |
| `GotoStmt.name`, `name_line`, `name_col`; `LabelStmt.name` | `name`, `nameLine`, `nameCol` | existing |

`sizeof(Node)` stays 760, and `Node()` gains seven `= false` stores. The two moves keep every existing kind's child order:
- every kind that has `condition` and another child already orders `bodyNode` (176) before `condition`;
- no existing kind has `parts` beside another child list.

`test_ast_structure_contract.py` moves its `partsStorage` and `condition` lines.

**Nine new kinds:**
- `NK_STATIC_ASSERT_DECL`, after `NK_TYPEDEF_DECL`;
- `NK_STATIC_ASSERT_MEMBER`, after `NK_ANONYMOUS_MEMBER`;
- `NK_STATIC_ASSERT_STMT`, `NK_GOTO_STMT` and `NK_LABEL_STMT`, after `NK_RELEASE_STMT`;
- `NK_ALIGNOF_EXPR` and `NK_VA_ARG_EXPR`, after `NK_COMPOUND_LITERAL`;
- `NK_POINTER_QUALIFIERS` and `NK_ALIGNMENT_SPECIFIER`, after `NK_INDEX_DESIGNATOR`.

Kinds render by name. Renumbering reaches only the module-unit validation records, which the toolchain fingerprint invalidates because it includes `ast.asdl`.

**Python dataclasses** gain:
- `FunctionDecl.is_inline`, `is_noreturn` and `is_variadic`;
- `TypeExpr.is_register`, `is_auto`, `is_thread_local` and `is_restrict` (all `False`), and `TypeExpr.parts` (a list);
- the nine new classes.

Regenerate `syntax/ast/generated.py` and `generated/ast/Node.btrc`, and update `AstCanonicalRenderer` and `AstStructure.children`. `AstJsonCodec` and the Python renderer are generic.

**3. IR**, in both compilers. New fields default to false, 0 or empty.

| Python `ir/nodes.py` | btrc `ir/Model.btrc` |
|---|---|
| `IRFunctionDef` (`:691`) and `IRFunctionDecl` (`:409`): `is_inline`, `is_noreturn`, `is_variadic` | `IRFunction` (`:737`; the bools fill the padding after `cLinkage`) and `IRFunctionDecl`: `isInline`, `isNoreturn`, `isVariadic` |
| `IRVarDecl` (`:754`): `is_const`, `is_restrict`, `is_register`, `is_thread_local`, and `alignment: int` | The `IRNode` scalar tail (`:130-147`; 26 bytes after C2's `bitField`) gains `isConst`, `isRestrict`, `isRegister`, `isThreadLocal` and `alignmentShift`, one `unsigned char`. `alignmentShift` is 0 for none; otherwise the alignment is `1 << (alignmentShift - 1)`. The tail then uses 31 of its 32 bytes. |
| `IRGlobalDecl` (`:617`): `is_const`, `is_restrict`, `is_thread_local`, `alignment` | `IRGlobalDecl` (`:714`): the same, with `alignment` an `int` |
| `IRParam` (`:681`): `is_const`, `is_restrict`, `is_register` | `IRParam` (`:608`): the same |
| `IRStructField` (`:491`): `is_const`, `is_restrict`, `alignment` | `IRStructField` (`:624`): the same |
| `IRTypedefDef` (`:591`): `is_const`, `is_restrict` | `IRTypedefDef` (`:683`): the same |
| `IRStaticAssert(IRStmt)`: `condition: IRExpr = None`, `message: str = ""`; the verifier enforces non-null, as for C2's `IRDesignation`. `IRModule.static_asserts`. | `IRK_STATIC_ASSERT` in the statement group (`kind >= IRK_VAR_DECL`), reusing `condition` and `text`; `IRModule.staticAsserts` |
| `IRAlignof(IRExpr)`: `c_type`. `IRVaArg(IRExpr)`: `va_list`, `c_type`. | `IRK_ALIGNOF` and `IRK_VA_ARG`, before `IRK_VAR_DECL`, reusing `cType` and `expr` |
| `IRGoto(IRStmt)`: `name: str = ""`. `IRLabel(IRStmt)`: `name: str = ""`, `falls_through: bool = False`. | `IRK_GOTO` and `IRK_LABEL`, appended after `IRK_LINE_MARKER` so both stay `>= IRK_VAR_DECL`, reusing `name` and (for the label) `fallsThrough`; built by `IRNode.gotoStatement(name)` and `IRNode.labelStatement(name, fallsThrough)` |

The shape invariants are the "Lowering invariants" above. This commit lands the checks that need no lane: the flags' types, the shape of `alignment`, where `IRStaticAssert` may appear, and the refusal of `IRGoto`/`IRLabel`.

**4. `targets.toml`.** This is C4's file and generator (`tools/compiler_codegen/hosted_abi.py`, `TargetManifest`), which outputs `abi/generated.py` and `generated/hosted_abi/Tables.btrc`. Sizes and alignments are in bytes, and spec fields are spelled as the generated fields.

```toml
[target_layout]                 # cells every target shares
short = { size = 2, alignment = 2 }
int = { size = 4, alignment = 4 }
long_long = { size = 8, alignment = 8 }
float = { size = 4, alignment = 4 }
double = { size = 8, alignment = 8 }
pointer = { size = 8, alignment = 8 }
bool = { size = 1, alignment = 1 }

[[targets]]                     # C4's row, with the C3 columns
operating_system = "linux"
architecture = "x86_64"
data_model = "lp64"             # lp64: long 8/8; llp64: long 4/4
char_is_signed = true
wchar = { bits = 32, is_signed = true }
long_double = { size = 16, alignment = 16 }   # omitted: no layout
max_align_t = { size = 32, alignment = 16 }   # omitted: no layout

[[layout_typedefs]]             # C11 standard typedefs with one layout everywhere
name = "size_t"
bits = 64
is_signed = false
```

| target | data model | char | `wchar_t` | `long double` | `max_align_t` |
|---|---|---|---|---|---|
| linux-x86_64 | LP64 | signed | 32, signed | 16/16 | 32/16 |
| linux-aarch64 | LP64 | **unsigned** | 32, **unsigned** | 16/16 | 32/16 |
| macos-x86_64 | LP64 | signed | 32, signed | 16/16 | 16/16 |
| macos-aarch64 | LP64 | signed | 32, signed | 8/8 | 8/8 |
| windows-x86_64 | LLP64 | signed | 16, unsigned | — | — |
| windows-aarch64 | LLP64 | signed | 16, unsigned | 8/8 | — |

**`[[layout_typedefs]]`**, as (bits, signedness):
- `size_t`, `uintptr_t`, `uintmax_t` and `uint_fast64_t`: 64, unsigned;
- `ptrdiff_t`, `intptr_t`, `intmax_t` and `int_fast64_t`: 64, signed;
- `intN_t`/`uintN_t` and the `least` types, at their widths;
- `int_fast8_t`/`uint_fast8_t`: 8;
- `char16_t`: 16, unsigned; `char32_t`: 32, unsigned.

`int_fast16_t`, `int_fast32_t`, their unsigned forms, and `va_list` are deliberately absent.

**Omitted cells.** A cell is present only when every toolchain PLAN.md D21 allows for the target agrees on it. MinGW and MSVC disagree on three cells:

| Target and cell | MinGW | MSVC |
|-----------------|-------|------|
| windows-x86_64 `long double` | 16/16 | 8/8 |
| windows-x86_64 `max_align_t` | 32/16 | 8/8 |
| windows-aarch64 `max_align_t` | 16/8 | 8/8 |

C4 left `__SIZEOF_LONG_DOUBLE__` out for the same reason.

**Verified for this section.** Every present cell above matches clang 21.1.8 (`-std=c11 -ffreestanding`) on ten triples: `x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`, `x86_64-apple-macos11`, `arm64-apple-macos11`, `x86_64-w64-windows-gnu`, `aarch64-w64-windows-gnu`, both `*-pc-windows-msvc` triples and both musl triples.

**Generator rules:**
- every C4 row has every C3 column, except the two optional cells;
- `data_model` is `lp64` or `llp64`;
- sizes are powers of two and at least their alignment;
- typedef names are hosted typedef names;
- lists are sorted and unique.

C4 omitted `__SIZEOF_LONG__`, `__SIZEOF_WCHAR_T__`, `__LP64__` and `_LP64` because the analyzers took `long` from the host. Commit B removes that reason, but restoring the four macros stays with Stage 24, which owns the predefined-macro table.

**5. `hosted_abi.toml`** (generator `tools/compiler_codegen/hosted_abi.py`):
- `va_list`, `char16_t` and `char32_t` join `[names] types`, `typedefs` and `owned`.
- `va_arg` leaves `macros` and `owned` (`:3594`, `:8033`), because it is now a keyword.
- An optional function key, `noreturn = true` (default false), is set on the existing rows for `abort`, `exit`, `_Exit` and `quick_exit`.

**6. `intrinsic_effects.toml`** moves to `schema_version = 2` and adds a sorted `[[functions]]` table.
- **Rows.** `va_copy`, `va_end` and `va_start`, each with `realtime_effect = "safe"` and no `c_callee`. `IRModule.realtime_intrinsic_targets`, and so the IR dumps, are unchanged.
- **No `va_arg` row.** `VaArgExpr` is safe by kind.
- **Generator.** `tools/compiler_codegen/intrinsic_effects.py`:
  - accepts the new root key (`_ROOT_KEYS`) and the new version;
  - checks that every function row names a hosted macro and no hosted function row;
  - generates `GeneratedIntrinsicFunctionRow` into `runtime/generated.py` and `generated/runtime/Catalog.btrc`.
- **Consumers.** `RuntimeHelperCatalog` (`runtime/catalog.py`) and btrc's `SourceRuntimeSymbols` (`analyzer/HostedAbi.btrc:13`) index the rows. Both realtime analyzers' external-call classification consults them after the runtime catalog and before hosted functions (Python's is `_external_call`, `analyzer/realtime.py:695-716`).

**7. Vocabulary code.**
- `TokenKind` (`tokens.py:20`) gains the nine tokens, and `TYPE_KEYWORDS` (`:529`) gains `RESTRICT`.
- btrc's `isTypeKeyword` and `isTypeQualifier` gain the same.
- Both parsers gain the pending-refusal tables and hooks.

**8. Devex and tests.**
- **VS Code grammar** (`src/devex/vscode/config/grammar.json`):
  - the specifiers go in `storage.modifier`;
  - `_Alignof` sits beside `sizeof`;
  - `_Static_assert` and `va_arg` are `keyword.other`;
  - `...` is punctuation;
  - prefixed string and character patterns;
  - hex, leading-dot, trailing-dot and `[fFlL]` float patterns.

  `test_extension_assets.py:51-68` gains the keywords and a literal-pattern test.
- **LSP** (`completion.py:18`):
  - `_RESERVED_WITHOUT_SYNTAX`, which today holds `auto`, `goto`, `override` and `register`, gains the eight new keywords.
  - Each lane removes its own entries: r15a removes `auto` and `register`, and Stage 20 removes `goto`.
  - `_KEYWORD_DOCS` gains an entry for each new keyword.
- **Lexer tests.** The keyword lists in `test_lexer.py:145-165`.

**9. Probes.**
- **Re-recorded.** Every `c3_c4.toml` entry (and `c1`/`c2`/`c5` entry) whose outcome changes is re-recorded, with `revision` set to the parent commit. The new keyword tokens change the recorded diagnostics of the r14, r15 and `x-alignof*` probes.
- **New gaps.** Each gets a positive and a negative program and is added to `EXTRA_GAPS` (`test_c_compatibility_inventory.py:63`):
  - `x-volatile-pointee` (D-1);
  - `x-east-const`;
  - `x-decimal-float-forms` (D-5);
  - `x-constant-context-division` (D-2);
  - `x-typed-constant-evaluation` (D-3): `1u - 2 < 0` against a designated extent, which is target-independent. The evaluator parity test covers char signedness instead, because it runs on the host target;
  - `x-static-assert-macro` (D-8);
  - `x-constant-identifier-scope` (D-9, probes `caps` and `vla`);
  - `x-qualified-generic-argument` (D-12).
- **Divergences.** `KNOWN_DIVERGENCES` gains the seven entries named in the defects table.

**10. Gate:**
- the generated-source check;
- the six boundary re-captures;
- AST and parser parity;
- the corpus through both compilers;
- the bootstrap fixed point;
- zero analyzer warnings on the `BtrccMain`, `cli/WindowsMain` and `cli/MacOSMain` transpiles;
- the extension and LSP tests;
- the memory measurement.

## Consumers to update (Python first, then the btrc port in the same commit)

**Shared owners, commit A:**
- **Parsers.**
  - Python: `Parser._parse_type_expr`, `_scan_type_expr`, `_QUALIFIERS`, `_DEFERRED_C_SPECIFIERS` and `_refuse_deferred_c_specifier`, `_parse_top_level_item` (`parser.py:603`), `_parse_function_or_var_decl` (`:1117`), `_lookahead_is_var_decl` (`:1268`), `_parse_param_list` and `_parse_param` (`:570`, `:579`), `_is_cast`, `_is_sizeof_type`.
  - btrc: `parseType`, `scanTypeEnd`, `deferredCSpecifierMessage`, `parseTopLevelItem`, `parseFunctionOrVarDecl`, `lookaheadIsVarDecl`, `parseParamList`, `parseParam`, `isCast`, `isSizeofType`.
- **Specifier owners.** `TypeSystem`, `TypeValidator` and `TypeShape`, plus the storage strip sites listed under owner 2.

**Shared owners, commit B:**
- **Layout.**
  - `abi/hosted.py` and `analyzer/HostedAbi.btrc`.
  - `CIntegerWidths` and `NumericLiteralSemantics` (`types.py:108-230`), and their construction sites (`application/pipeline.py:470`, `analyzer/analyzer.py:40`).
  - `IntegerLiteral.typeName` (`syntax/Literals.btrc:98`) and `builtinCastRange`/`abiCastRange` (`Constants.btrc:296-408`).
  - The native importer's layout index (`native_imports.py`, `NativeImports.btrc`), and `AnalyzedProgram`/`Analyzed`.
- **Evaluator.** `ExpressionAnalyzer.integer_constant_expression` and `_apply_constant_binary` (`expressions.py:1477-1640`); `_validate_array_bound` (`statements.py:509-511`); btrc's `ConstantValidator` and `SemanticIntegerConstant` (`Constants.btrc:11`).
- **`sizeof` operands.** `_lower_sizeof` (`ir/lowering/expressions.py:2109-2131`) and btrc's sizeof lowering in `ExpressionLowerer` both call `SizeofOperand`.
- **Constant lowering and cross-check:**
  - enum values in `TranslationUnitLowerer` and btrc's `DeclarationLowerer`;
  - case labels in `ControlFlowLowerer` and `ir/lowering/ControlFlow.btrc`;
  - array extents and static initializers in `StorageLowerer`, `TranslationUnitLowerer` and `DeclarationLowerer.emitGlobalVar`;
  - `IRStaticAssert` emission in both `CEmitter`s;
  - `IROptimizer` roots.
- **Pack owner.** `DeclarationRegistry` in both compilers. `translation_unit.py:826-852` and btrc's `ir/lowering/Declarations.btrc:81-138` read the recorded value.

**r15a:**
- **Python analyzer:**
  - `storage.py` (`:101-130`, `:206-228`, `:330-420`);
  - `types.py`: `declaration_const_depths` (`:2297`), the outer-qualifier check (`:1478-1484`), `format_type`, `TypeIdentity.shape_key`/`_encode_type`, `generic_argument_problem`, `compose_type_expr`, `strip_outer_storage`, `add_outer_pointer`;
  - `declarations.py` (`_signature_types`);
  - `expressions.py` (`&`, assignment, `_aggregate_has_const_member`);
  - `statements.py` (`:171` static initializers, `:559-567` class fields);
  - `analyzer/ownership.py` (capture), `analyzer/realtime.py` (the thread-local effect) and `analyzer/gpu.py`.
- **Python lowering and emission:**
  - the qualifier-clearing sites listed under r15a;
  - `CTypeLowerer`;
  - `ir/lowering/storage.py`, `functions.py` (parameters) and `expressions.py:662-715` (the store adapter);
  - `exceptions.py:839`;
  - `CType.qualify_object`, `IRVerifier` and `CEmitter`;
  - `SharedDeclarations` (thread-local externs).
- **btrc analyzer and syntax:**
  - `validation/Storage.btrc`, and `validation/Types.btrc` (`:583-607`, `:806`);
  - `analyzer/Types.btrc` (typedef layering);
  - the validation files `Ownership.btrc`, `Borrows.btrc`, `Calls.btrc`, `Realtime.btrc` and `GPU.btrc`;
  - `syntax/Types.btrc`;
  - `syntax/Identity.btrc` (`qualifierBits`, `appendEncoded`, `decode`, `encodable`, `genericArgumentProblemInner`).
- **btrc lowering and emission:**
  - `ir/lowering/Types.btrc` (`:20`) and `Expressions.btrc` (`:1238-1290`, `:3853-3862`);
  - `Declarations.btrc`, `Functions.btrc`, `Concurrency.btrc`, `Calls.btrc` and `ownership/Operands.btrc`;
  - `ir/optimization/setjmp/Safety.btrc:51`;
  - `ir/Emitter.btrc` and `pipeline/ModuleUnits.btrc`.
- **Tests.** Flip these to C semantics: `test_ir_declarations.py:183-221`, `test_qualifier_provenance_contracts.py:35-43`, `test_array_storage_codegen_contract.py:177-197`, `test_exception_codegen_contracts.py:296,407`, `test_setjmp_continuation_contract.py:164,198` and `test_emitter_whitebox.py:94`.
- **LSP.** `symbols.py` and `hover.py` render qualifiers.

**r15b:**
- **Python:**
  - the parser's function prologue;
  - `analyzer/flow.py` (the completion owner);
  - `statements.py` (`:763`, `:817-819`, `:1462-1466`, `:1491`, `:1593-1596`), `declarations.py` and `realtime.py`;
  - `ir/lowering/translation_unit.py` (`:210-258`, `:336-345`), `functions.py` and `exceptions.py:1563`;
  - `application/modules.py` (`SharedDeclarations`, `ProgramInterface`, the setjmp solver);
  - `CEmitter` and `IRVerifier`.
- **btrc:**
  - `validation/ControlFlow.btrc`, `validation/Expressions.btrc:775` and `validation/Declarations.btrc:802`;
  - `analyzer/Expressions.btrc:86-118` (deleted) and `analyzer/Realtime.btrc`;
  - `ir/lowering/Declarations.btrc`, `Functions.btrc`, `Statements.btrc:1043` and `Lowerer.btrc:257-277`;
  - `pipeline/ModuleUnits.btrc` and `ir/Emitter.btrc`.

**r15c:**
- **Python:**
  - `parser.py`: top-level, statement and record-body dispatch;
  - `analyzer/statements.py`, `declarations.py`, `aggregates.py` and `calls.py` (the `static_assert` refusal);
  - `frontend/imports.py`;
  - `translation_unit.py` and `application/modules.py`;
  - `optimizer.py` (roots) and `c_emitter.py`.
- **btrc:**
  - `Parser.btrc`: `parseTopLevelItem`, `parseStatement` (`:1178`) and `parseStructField` (`:582`);
  - `validation/Declarations.btrc`, `Constants.btrc` and `Calls.btrc`;
  - `frontend/Visibility.btrc`;
  - `ir/lowering/Declarations.btrc` and `Statements.btrc`;
  - `pipeline/ModuleUnits.btrc` (the closure and `collectText`);
  - `ir/optimization/Optimizer.btrc` and `ir/Emitter.btrc`.
- **Kind coverage.** Stdlib reachability in both compilers.

**r15d:**
- **Python:**
  - `_parse_unary` (`:1655`);
  - `aggregates.py` (member layout), `expressions.py` (`AlignofExpr`), `storage.py`, `declarations.py` (agreement) and `gpu.py`;
  - `ir/lowering/expressions.py`, `CTypeLowerer` and `CEmitter`.
- **btrc:**
  - `parseUnary` (`:1782`);
  - `validation/Storage.btrc`, `validation/Expressions.btrc`, `validation/Names.btrc` and `GPU.btrc`;
  - `ir/lowering/Expressions.btrc` and `ir/Emitter.btrc`.

**r16 and stragglers:**
- **Python:**
  - `lexer.py`: `read_number` (`:447`), `_read_identifier` (`:774`), `read_string` (`:349`), `read_char` (`:416`) and `LiteralDecoder` (`:19-160`);
  - the parser: `_parse_sizeof` (`:1744`), `_parse_primary` (`:1811`) and the import-path parser;
  - the analyzer: `analyzer/expressions.py` (including the pointer `+=` operator rule), `types.py` (literal types; the char16/32 sets near `:885-985`), `aggregates.py` (r04), `statements.py`, and `calls.py` (`print`, f-strings);
  - `CTypeLowerer` (`uint_least16_t`).
- **btrc:**
  - `Lexer.btrc` (`:194`, `:443`, `:555`, `:644`) and `syntax/Literals.btrc` (`:204-351`);
  - `parseSizeof` (`:1857`) and `parsePrimary` (`:2039`);
  - `analyzer/Expressions.btrc`, `Operators.btrc` and `validation/Expressions.btrc`;
  - `ir/lowering/Types.btrc`.
- **Formatter** (I-17):
  - `src/devex/formatter/lexing.py:84-123` mirrors the prefix, leading-dot, trailing-dot and hex-float rules.
  - `engine.py:754-800` (`_needs_space`) keeps a prefix attached to its quote, as it already does for `f`. Today `L"ab"` is reformatted to `L "ab"`, which lexes as an identifier followed by a string.
- **Tests.** `test_lexer_literals_extra.py`, `btrc/test_lexer_diagnostics.py`, and the formatter tests.

**r14:**
- **Python:**
  - `_parse_param_list` (`:570`);
  - `analyzer/calls.py`, `flow.py` (`va_list` states), `realtime.py` and `gpu.py`;
  - `ir/lowering/functions.py`, `calls.py` (`plan_evaluation`, `:293`) and `exceptions.py` (the planner assertion);
  - `CEmitter`;
  - the formatter fixture for `, ...`.
- **btrc:**
  - `parseParamList` (`:1124`);
  - `validation/Calls.btrc`, `ControlFlow.btrc` and `Realtime.btrc`;
  - `ir/lowering/Functions.btrc`, `Calls.btrc` and `ownership/Calls.btrc:94`;
  - `ir/optimization/setjmp/Analysis.btrc` and `Safety.btrc`;
  - `ir/Emitter.btrc`.
- **Unchanged.** `test_native_variadic_calls.py` stays green.

## Tests

Each lane:
- flips its `c3_c4.toml` rows to `corpus` references;
- turns its known divergences into accepted or rejected entries;
- adds its † refusals to `test_c_compatibility_refusals.py` and known-language-gaps.

One parity reviewer per construct checks semantics, diagnostics and ARC witnesses, reusing the lane's btrcc.

**Commit A:**
- `test_c3_pending_refusals.py`: the two tables are equal, and each pending token is refused at its position in top-level, statement, member, parameter, cast and `sizeof` contexts.
- A parse-parity test runs every specifier through the cast, `sizeof`, generic-argument, lambda-parameter, compound-literal-head, struct-member, class-member and parameter positions.
- The position-table, `value_type` and `parts`-reader contract tests.

**Commit B:**
- **`test_target_layout_table.py`.**
  - It generates `_Static_assert(sizeof(T) == N && _Alignof(T) == A, "T")` for every present cell, and runs `clang -target <triple> -std=c11 -ffreestanding -fsyntax-only` for all six triples.
  - It spells `char16_t`/`char32_t` as `__CHAR16_TYPE__`/`__CHAR32_TYPE__`, because freestanding clang has no `<uchar.h>`.
  - It skips the `int_fast` types, because freestanding headers differ from the libcs.
  - It also checks the host row with the host gcc and its hosted headers.
  - It is skipped, with a skip-ledger entry, when clang is absent.
- **`basics/ConstantContextDivision.btrc`.** Enum values, case labels, and global, local and `static` bounds, through both compilers under gcc and clang `-pedantic-errors -Werror`.
- **`test_integer_constant_evaluator_parity.py`.** About 120 expressions, printed as enum values on the host target and compared with gcc and clang. They cover:
  - unsigned wrap and char signedness;
  - shifts: `1 << 31` is refused and `(-1) >> 1` is evaluated;
  - short-circuit and ternary operators;
  - literal types;
  - scope-bound upper-case names, which are not constant;
  - `sizeof` of a VLA, which is not constant.
- **D-4.** A front-end-only case analyzes `long value = 2147483648;` with `--target linux-aarch64` (where the literal is `long`) and with `--target windows-x86_64` (where it is `long long`). The outcomes are identical in both compilers.
- **Cross-target gates** (I-18):
  - a `--target windows-x86_64` transpile of `cli/WindowsMain.btrc` with no new diagnostic;
  - the stdlib Windows transpile;
  - BTRSmith's Windows frontend check.
- **Layout cross-check.** `char buf[sizeof(struct P)]`, a FAM struct, a union, an anonymous member, a tuple and `size_t`. Each emits `_Static_assert(... == N, "btrc layout")`, which gcc and clang accept.

**r15a:**
- **Corpus `c_compat/PointerQualifiers.btrc`:**
  - const pointers and east const;
  - `const char* const*`;
  - `restrict` parameters, including `void* restrict`;
  - a volatile pointee against a volatile pointer;
  - a typedef-layered qualifier;
  - `int* const a[3]`.
- **Corpus `c_compat/StorageClasses.btrc`:**
  - a `register` local and a `register` parameter, used with `+=`, with `++`, and inside a function containing `try`;
  - block-scope `auto`;
  - a `_Thread_local` counter across two `Thread`s, each seeing its own copy.
- Negative programs for every r15a refusal.
- `--module-units` with a `_Thread_local` global used from two groups.
- `test_type_identity_contract.py`: encodings stay byte-identical for unqualified types, and `int* const g[2][3]` and `int* h[2][3]` get distinct row typedefs.

**r15b:**
- **Corpus `c_compat/FunctionSpecifiers.btrc`:**
  - `static inline` and plain `inline` helpers used from two modules, under `--module-units --emit-units` and in whole-program mode, linked with gcc and clang at `-O0` and `-O2`;
  - a `_Noreturn fatal()` that lets `int f(int x) { if (x) return 1; fatal(); }` compile in another group's unit;
  - a `_Noreturn` body that ends in `exit()`.
- Negative programs for each r15b refusal.
- A module-unit reuse test in which editing an inline body invalidates its copies.
- `test_completion_owner_parity.py` over every row of the completion table, lambdas included.
- The inline-site contract test.

**r15c:**
- **Corpus `c_compat/StaticAssert.btrc`:**
  - the file, block and member positions;
  - btrc structs, unions, anonymous members, a FAM, tuples and `size_t`;
  - a native record from a reader fixture.
- **Negative programs:**
  - a false assertion, checking its message and position;
  - a condition that is not constant;
  - a type with no layout;
  - a macro;
  - a record measured inside its own body;
  - `static_assert(...)`.
- A struct whose only use is an assertion, under strict imports and under `--module-units`.
- `test_layout_model_parity.py`: both compilers emit assertions for every layout kind, and gcc and clang accept the C.

**r15d:**
- **Corpus `c_compat/Alignment.btrc`:**
  - `_Alignof(double)`;
  - `_Alignas(16)` locals, globals and members;
  - `_Alignas(2) _Alignas(8)`.

  These are checked by address modulo, and by `sizeof`/`_Alignof` of aligned structs, under gcc and clang on each host.
- Negative programs for each r15d refusal.

**r16:**
- **Corpus `c_compat/WideAndLongDoubleLiterals.btrc`**, all target-neutral:
  - `1.5L` arithmetic and printing;
  - `wcslen(L"abc") == (size_t)3`;
  - `wchar_t w[] = L"hi"`;
  - `u8` strings and `u`/`U` arrays;
  - extents of non-ASCII, UCN and non-BMP literals.
- Front-end-only extent cases for windows and linux targets.
- Negative programs for each r16 refusal.

**Stragglers:**
- **Corpus `c_compat/SizeofAndFloatForms.btrc`:**
  - `sizeof x == sizeof(int)` and `0x1p3 == 8.0`;
  - `.5`, `1.`, and `1.f` typed `float`;
  - `5.toString()`, which is still a call;
  - `p += 3; p -= 1`;
  - `sizeof (struct P){1, 2}`.
- Lexer diagnostics for `0x1p`, `0x.p1` and `0x1.8`.
- Both lexers on `c?.5:1` and on `0...2`.

**r14:**
- **Corpus `c_compat/VariadicDefinitions.btrc`:**
  - `sum(int n, ...)`;
  - a logger that takes a `va_list` parameter and calls `vfprintf(stderr, prefix(), ap)`;
  - `va_copy`;
  - float-to-double and char-to-int promotion;
  - a borrowed `string` read as `char*`.
- Negative programs for each r14 refusal. They include a list declared before a `try`, a `va_list` parameter in a function with a `try`, and `va_start` inside a `try`.
- A cross-group `--module-units` call to a variadic function.
- The realtime classification tests, extended.

**`ccompat-c3-integrate`:**
- every C3 row is PASS or refused on purpose;
- `KNOWN_DIVERGENCES` holds no C3 entry;
- `test_c_compatibility_inventory.py` is green;
- the full matrix passes, including the Mac's `test-c11`;
- the extension and LSP tests pass;
- memory is re-measured;
- BTRSmith's `application-frontend-check` and the library smoke run on both frontends.

## Memory impact

- **btrc `Node`: 0 bytes.**
  - The generator's plan gives 760 bytes for the base, C2 and C3 schemas.
  - The seven new bools sit in padding: after `keepReturn`, after `isArray`, and before `arrayPointerDepth`.
  - `condition` and `partsStorage` move earlier with no size change.
  - `Node()` gains seven stores.
- **btrc `IRNode`: 0 bytes.**
  - Four bools and one `unsigned char` join the scalar tail, which then uses 31 of its 32 bytes.
  - The small IR classes gain bools that fit their padding, and `IRGlobalDecl`/`IRStructField` gain an `int`; these exist per declaration.
- **Analysis data.** The target rows, one layout per measured record, one evaluator type per constant, and the pack table: well under 1 MB in total.
- **The self-compile.** btrc's own source uses no C3 construct. It pays only the seven stores, the table rows, the typed evaluator's per-constant work, and one cross-check assertion in its C per folded layout use. The delta is expected to be within noise.
- **Python.** Every `TypeExpr` gains an empty `parts` list and four attributes, on top of C2's `elements`; every `FunctionDecl` gains three attributes. This is measured against D13's 2 GiB peak.

  If the Python peak grows by more than 1%, the fallback below lands before the commit (the standing approvals say to optimize before landing above 1%):
  - the generator gives `TypeExpr.parts` and `elements` an immutable `()` default;
  - every producer (the parser, `AstJsonCodec` and the copies) stores `()` for an empty list, and a list only when it is non-empty;
  - a contract test asserts that no `TypeExpr` holds `[]`, so equality and rendering see one representation.
- **Method.** Stage 15's method, run at the vocabulary commit and again at `ccompat-c3-integrate`:
  1. Build btrcc from the parent and from the commit, naming the C compiler that built each.
  2. Run three alternating `--target linux-x86_64 --no-cache` compiles of `BtrccMain.btrc` with each, measuring peak RSS and user CPU through `wait4`.
  3. On the Mac, record the BTRSmith `--jobs 1` row under `/usr/bin/time -l` (instructions retired, peak memory footprint).

  A delta of at most 0.3% passes. Up to 1% is accepted with the delta recorded.

## Boundary records

The manifest (`manifest.toml`) holds 311 records; C2 changes two and adds none. Exactly six change, once, in the vocabulary commit, all with one reason: "C3 vocabulary: function specifiers, per-level qualifiers, storage classes and alignment on the AST and their IR flags".

**`surface.python.ast.artifact` and `surface.btrc.ast.artifact`** stay equal:
- each `FunctionDecl` gains `is_inline=false is_noreturn=false is_variadic=false` after `keep_return`;
- each `TypeExpr` gains `is_register=false is_auto=false is_thread_local=false` after `is_array`, `is_restrict=false` after `is_volatile`, and `parts=[]` after `array_pointer_depth`.

**The four Python IR records** (`surface` and `managed`, raw and optimized):
- `IRFunctionDef` gains three fields in all four records, and `IRFunctionDecl` gains them in the two surface records.
- `IRVarDecl` gains five fields; it appears only in the managed records.
- `IRModule` gains `static_asserts` in all four.
- The artifacts contain no `IRParam`, `IRGlobalDecl`, `IRStructField` or `IRTypedefDef` (checked).
- `realtime_intrinsic_targets` is unchanged, because the `va_*` rows have no `c_callee`.

**Unchanged:**
- tokens: no boundary source contains a new token;
- C artifacts, diagnostics and behavior;
- the runtime source, metadata and order records. The runtime metadata channel reads `src/runtime/c/manifest.toml`, not `intrinsic_effects.toml`.

Neither shared-owner commit nor any lane changes a boundary record: the boundary sources contain no constant context, `sizeof`, qualifier, specifier or `exit` call.

## Lanes, merge order and gates

1. **Batch 0, serial, main session.**
   - `ccompat-c3-schema-vocabulary`, with 1 pre-drafter and 2 reviewers.
   - Then commit A.
   - Then commit B, with 1 constant-evaluator parity reviewer.

   One D5 gate runs after commit B, plus commit B's cross-target gates.

   *Scheduling, pending owner approval (WORKSTREAMS.md Q5):* commit B lands as two serial commits, B1 (target widths, the typed evaluator and constant lowering: D-2, D-3, D-4, D-9) then B2 (the layout model, the `SizeofOperand` owner, the cross-check assertions and `#pragma pack`). The D5 gate runs after B2. Outside this section, the same plan keeps C2's schema commit serial after C4's behavior commit and splits C2's r10 into designators, then compound literals; those belong to the C2 design.
2. **Lanes, at most 4 writers.** Each construct is one commit: Python first, then the btrc port by the same agent. Each lane builds its own btrcc under the `btrcc-build` semaphore.
   - **Wave 1:** r15b; r15c (with the evaluator parity reviewer); r15d; and r16 followed by the stragglers, done by one agent because they share the lexer.
   - **r15a**, the declarator lane, takes the first free slot. r07 and r17 have already merged.
   - **r14** takes the next free slot and merges as its own batch.
   - **Stage 20** may start once r15b, which owns the completion owner, has merged. It may overlap r15c, r15d and r16, because its AST and IR nodes already exist. *Scheduling, pending owner approval (WORKSTREAMS.md Q5):* Stage 20's construct commit merges after r15a and r14, so r11 still merges last; its implementation may still overlap r15c, r15d and r16. This section leaves Stage 20 three notes:
     - the completion owner gains labels and `goto`;
     - the `va_list` flow rule must follow `goto`;
     - a label before a declaration is C23 placement (C11 6.8.1 requires a statement). The goto design accepts it as a documented extension and always emits `lbl: ;`, so `lbl: int x;` and `lbl: _Static_assert(...)` stay strict C11.
3. **Merge order:** r15b, r15c, r15d, r16, stragglers, r15a, then r14. This is the item spec's order. Each batch gets a D5 gate.
   - Batch 1: r15b, r15c.
   - Batch 2: r15d, r16, stragglers.
   - Batch 3: r15a, with a BTRSmith rerun for the D-1 flip.
   - Batch 4: r14.
4. **`ccompat-c3-integrate`:**
   1. Delete the pending tables. They never held `goto`.
   2. Complete known-language-gaps:
      - every † row;
      - row 20's note on `va_arg`;
      - the new meaning of `volatile`;
      - the inline subset;
      - the `_Alignas` limits and the platform `malloc` guarantee;
      - the `register` scalar rule;
      - D-10's `sizeof` meaning;
      - `?.` before a digit;
      - member access on hex literals;
      - the implementation-defined behavior btrc assumes: char signedness per target, wrapping signed conversion, arithmetic right shift, and signed plain-`int` bit-fields (from C2).
   3. Run the full matrix, the memory re-measure and BTRSmith.

**The item specs' blockers, resolved:**

| Blocker | Resolution |
|---------|------------|
| `auto` policy (r15a) | D20: a block-scope no-op, refused at file scope, on parameters and on members, never inference. It is kept as `TypeExpr.is_auto` for position checks and the LSP, and dropped at lowering. |
| Plain or `extern inline` under split units (r15b) | D20, implemented as above. C11 6.7.4p3's consequences (the whitelist, and no `/` or `%` in external-linkage bodies) are documented refusals. |
| `sizeof` conditions btrc cannot evaluate (r15c) | D20: the front-end layout model plus a refusal naming the type. The condition, and every layout value the analysis consumes, are asserted again in C. |
| r14 go/no-go | D19 approves it; its consumer is the probe battery plus mined headers. |
| Managed variadic arguments | Borrowed for the call, as hosted variadic calls already are; `va_arg` reads plain C types only. |
| `goto`/label fields (c3-schema) | Carried in this commit at zero bytes, with the goto design's schema (`GotoStmt(name, name_line, name_col)`, `LabelStmt(name)`, `IRGoto`, `IRLabel`); Stage 20 owns the semantics, the grammar rules and the parsers. |

**Outside Stage 19:**
- `x-pointer-to-array` stays rejected, as C2 decided; Stage 21 lands it or records a refusal.
- `x-braceless-do` belongs to C1 r02.
- Lifting native `restrict`/`volatile`, and native `noreturn` attributes, are separate commits after r15a and r15b.
- Typed `longjmp`/`pthread_exit` rows with `noreturn` get their own commit.
- iOS and Android rows join the layout columns in Stage 24, under the same clang verification.

## Review resolutions

| Finding | Resolution |
|---------|------------|
| I-1 (blocking): btrc compound assignment takes the address of every target, plain locals included, which breaks `register` and outer `restrict`. | Accepted (probe `plain.btrc`: only btrcc emits `int volatile* __btrc_lvalue_1 = &a`). btrc uses value temporaries for identifier roots. `directLvaluePointerType` adds `restrict`/`volatile` from `qualifiersAt`. A post-optimization rule forbids taking a `register` object's address. The corpus covers `+=`, `++` and `try`. |
| I-2 (blocking) and S-7: hoisted call operands copy a `va_list`. | Accepted (probe `hoist.btrc`: both compilers copy a struct operand into a temporary). The planners never hoist a `va_list`, and a call that also reads `ap` is refused. `va_*` arguments are emitted verbatim. A verifier rule limits where a `va_list` value may appear. The corpus includes `vfprintf(stderr, prefix(), ap)`. |
| I-3: `_Static_assert` and `parts` are invisible to strict imports and to the module-unit closures. | Accepted (`imports.py:390-396`, `:477-482`, `:693`; `Visibility.btrc:123-129`, `:315`, `:542`; `modules.py:568-600`; `ModuleUnits.btrc:37-66`, `:506-530`). `StaticAssertDecl` joins both filters, both `TypeExpr` branches visit `parts`, and both closures follow `static_asserts`. Probes run under strict imports and `--module-units`. |
| I-4: there is a third termination predicate, and the draft states only leaf rules. | Accepted (D-13). One completion owner per compiler, with a full rule table, serves every check and both lowering sites. `ExpressionTypeResolver`'s copy is deleted first, in its own parity commit (`CL-C-02`). A parity test covers the table. |
| I-5: the lookahead rules contradict each other, function specifiers have no refusal stage, and the pending slot leaks. | Accepted. `_scan_type_expr` does serve `_is_cast` and `_is_sizeof_type`, and `_QUALIFIERS` already scans `(static int)` as a cast. The scanner skips every specifier in every mode, and the analyzer's table owns storage-class refusals. The parser refuses function specifiers off the top-level path. The slot is filled only there and asserted empty on entry. A parse-parity test covers the positions. |
| I-6: type equality and the type-identity encodings diverge and lose qualifiers. | Accepted, with a correction: `aliasTypesSame` already compares `shapeKey` (`validation/Types.btrc:583-590`), so extending the encoding fixes it and its callers. `sameTypeShape` and `callableComponentSameTypeShape` move to the encoding. Both compilers use one encoding (a restrict bit and `v<depth>c<bits>` segments), byte-identical for unqualified types. `encodable` stays true for qualifiers and becomes false for storage bools and alignment. |
| I-7: the D-1 flip changes every `is_volatile` reader, and the strip-site list is incomplete. | Accepted. Every reader and IR flag goes through `qualifiers_at`. `value_type` lands its storage half in commit A, with the missing sites added, and its qualifier half in r15a. A contract test bans direct clears and raw reads. |
| I-8: helpers that add or remove pointer levels must own the depths in `parts`. | Accepted: the `parts` invariant, transformer ownership, immutable lists, cloned btrc nodes, and a contract test. |
| I-9: `#pragma pack` is computed in lowering. | Accepted (`translation_unit.py:826-852`). An analyzer owner records it and both lowerers read it. Its messages become analyzer diagnostics. Only the `push`/`pop` forms are recognized, as today. |
| I-10 and S-3: inline bodies reach generated statics, and the plain-value rule refuses string literals. | Accepted. The fixes are a whitelist subset with an inline-callable predicate; narrow literals allowed as hosted `char*` arguments; the store adapter skipped in inline bodies; a contract test over every session-local static emitter (69 `is_static=True` sites in Python lowering); and a backstop that also covers `static inline`. S-3's question about generic functions is moot, because `FunctionDecl` has no type parameters. |
| I-11: prototypes of other groups' functions drop `variadic` and `noreturn`. | Accepted (`translation_unit.py:233-241`; `Lowerer.btrc:257-277`). Both flags are copied, with cross-group tests in r14 and r15b. |
| I-12: `static_assert(...)` is accepted and emits invalid C (D-8). | Accepted (probe `sassert.btrc`), as a known-divergence probe and an r15c refusal. Rejected in part: `alignas`, `alignof`, `noreturn` and `thread_local` are not hosted names, so they stay identifiers, because refusing them everywhere would break user names. `_Generic` stays as it is, because `c_compat/GenericSelection.btrc` passes it through a source macro. |
| I-13 and S-6: a `va_list` interacts badly with setjmp. | Accepted. `try` is refused in any function that declares or receives a `va_list`. The planners assert that they never qualify one. Three negative probes cover it. |
| I-14 and S-11: the `_Thread_local` realtime rule bypasses the witness model. | Accepted. A thread-local access is an `allocation` effect, reported through the existing witness template. Tests cover direct and transitive access. |
| I-15: the advice to use a typedef for generic arguments leads into an existing divergence. | Accepted (probe `typedefconst.btrc`, D-12). The existing "generic arguments cannot be X-qualified" refusal now applies at pointer levels and through typedefs, with btrcc's wording in both compilers. The typedef advice is dropped. |
| I-16: multi-declarator copies must not copy pointer qualifiers. | Accepted. The copier copies storage classes, base qualifiers and alignment only. A parse-parity probe covers `int * const a, b;`. |
| I-17: the formatter splits prefixed literals. | Accepted (`lexing.py:84-123`, `engine.py:754-800`). The formatter mirrors the lexer's literal rules, and is added to the r16 consumers and tests. |
| I-18: D-4 changes the analysis of existing cross-target transpiles and depends on C4. | Accepted, with a correction: C4's design puts target rows in `src/language/targets.toml`, not `hosted_abi.toml`, so the C3 columns go there and depend on `ccompat-r18-spec`. Commit B gains the WindowsMain, stdlib and BTRSmith Windows checks. Compiles without a target use the host. |
| I-19: `va_arg` is not already refused as a name. | Accepted (`C11_RESERVED_NAMES` lacks it). The vocabulary row is reworded, `va_arg` leaves the hosted macro and owned lists, and row 20's note mentions it. |
| I-20: the intrinsic `[[functions]]` table has no consumer. | Accepted. There is no `va_arg` row, the generator checks the rows are disjoint from hosted function rows, and both realtime analyzers consult them. |
| I-21: a static-assert message stored in btrc's `text` field pollutes the module-unit closure. | Accepted (`collectText`, `ModuleUnits.btrc:486-497`). `collectText` skips `IRK_STATIC_ASSERT`. |
| I-22: trailing-dot floats break unspaced GNU ranges. | Accepted. A `.` followed by another `.` never joins a number. |
| I-23 and S-16: `sizeof` of a `va_list` parameter is a pointer on x86_64. | Accepted. `va_list` has no layout (its column is dropped from the table), and array parameters measure as pointers. |
| I-24: the layout check needs adjustments. | Accepted: `__CHAR16_TYPE__`/`__CHAR32_TYPE__`, a host gcc check, and no `<uchar.h>` dependency at all (S-26). |
| I-25: the vocabulary commit's pending refusals need hook points; east-position qualifiers need their own wording; pending grammar rules need marking. | Accepted in part. The hooks are Stage 14's call sites, extended to token kinds, plus the unexpected-token constructors, and pending `@syntax` rules are marked. East-position and `* qualifier` forms get no pending entry: they keep today's diagnostics until r15a, which removes the need for separate wording. |
| I-26: a `FunctionDecl`'s start position needs restating. | Accepted (`parser.py:1121`): the first token after annotations and `keep`. |
| I-27: an empty-tuple fallback breaks equality and rendering. | Accepted. If the fallback is needed, it stores `()` everywhere an empty list would otherwise appear, with a contract test. |
| I-28 and S-10: a thread-local's address is not an address constant. | Accepted (C11 6.6p9). It is refused in static and thread-local initializers. |
| I-29 and S-19: `restrict` must accept `void*`, incomplete pointees and typedefs. | Accepted (C11 6.2.5p1, 6.7.3p2), with positive probes. |
| I-30 and S-18: citation errors. | Accepted. `TYPE_KEYWORDS` is at `tokens.py:529` and `LiteralDecoder` at `lexer.py:19`. Repetition is C11 6.7.3p5 and 6.7.4p5. The grammar comment no longer claims that every C11 keyword has a rule. The infinite-loop rule is btrc's, not C's (6.9.1p12). |
| I-31: the order in which the pending tables are cleaned up. | Accepted. r15a removes `auto` and `register`, and integrate deletes the tables. Superseded in part by the goto design: the tables never hold `goto`, because the parsers keep today's `goto` errors until Stage 20. |
| I-32 and S-28: a label before a declaration. | Accepted as a Stage 20 note (C11 6.8.1). The goto design resolves it: C23 placement, emitted as `lbl: ;`. |
| I-33: the new flags have no `effective_` twin. | Accepted. Qualifiers on a typedef-named or `CFunction`-named outer type stay in the C text. |
| S-1 (blocking): the layout model's `sizeof` operand typing contradicts the C that lowering emits. | Accepted (probes `szs.btrc`, `szs2.btrc`; D-10). One `SizeofOperand` owner serves the evaluator and lowering in both compilers, so btrc measures what it emits. The deviation from C is documented, and every layout value the analysis consumes is asserted again in C. |
| S-2 (blocking): the evaluator's constant "proof" is unsound. | Accepted (probes `caps.btrc`, `vla.btrc`; D-9): identifiers resolve scope-first, `sizeof` of a VLA is not constant, a per-consumer table decides which kinds each accepts, and negative probes cover it. Rejected in part: limiting constant lowering to known values would keep D-2 for `sizeof(T) / 2`. Plain operators are safe for every C constant expression, because the C compiler re-checks C11 6.6p4. |
| S-4: lowering takes the address of `register` objects. | Accepted (probe `tern2.btrc`; D-11). The store adapter skips register targets; btrcc's plain form passes gcc 15.2 and clang 21.1.8 (probe `seq.c`). The verifier rule backs this up. |
| S-5: outer `const` on struct members and class fields bypasses the existing const checks. | Accepted. Both checks use `qualifiers_at`. Outer-const class fields with initializers are refused. Records with const members are refused as generic or collection elements, which is D-12's second half. |
| S-8: the `va_list` pairing states are incomplete. | Accepted (C11 7.16p3, 7.16.1.3p2, 7.16.1.4p4, 7.16.1.1p2): borrowed parameters, the indeterminate state, rules on the last parameter's type, and single-name `va_arg` types. |
| S-9: signed left-shift overflow is not addressed. | Accepted, with corrected evidence: gcc 15.2 and clang 21.1.8 both accept `enum { D = 1 << 31 }` under `make test-c11`'s flags (re-run of `sc.c`). btrc therefore refuses undefined behavior that both compilers tolerate, consistent with C2's signed-overflow rule. The parity battery covers it. |
| S-12: `_Alignas` is checked per specifier, which refuses valid C. | Accepted. Each specifier is checked only for being a power of two and within the limits; "weaker than natural" applies to the combined alignment. The citation is corrected to C11 6.7.5p4 and p6. |
| S-13: alignment agreement between declarations is missing. | Accepted (C11 6.7.5p7): disagreeing declarations are refused, and module-unit externs carry the definition's alignment. |
| S-14: wide and UTF literal extents are not specified. | Accepted. One code-unit owner per compiler, per (prefix, target `wchar_t` width), with front-end tests for windows and linux targets. |
| S-15: refusals of valid C11 are not identified. | Accepted. Every refusal table has a C11 column, and every † row gets a known-language-gaps row and a refusal test. |
| S-17: the specifier-order rationale is wrong, and the rule is inconsistent. | The rationale correction is accepted: btrc emits canonical order, so `-Wold-style-declaration` is irrelevant. The rule is kept: storage-class and function specifiers precede the base type, which is where today's parser reads them, and `const static int` is accepted today and must stay accepted. `int static x` is refused as obsolescent (C11 6.11.5) and marked †. |
| S-20: arrays of qualified pointers need a stated rule. | Accepted. An array's qualifiers apply to its elements (C11 6.7.3p9); the qualifier owner states this. |
| S-21: native enums, and drift against real SDKs. | Accepted. Native enums use `NativeEnumType.underlying`, and imported headers cross-check the target cells. |
| S-22: records whose layout is in progress. | Accepted. They count as incomplete while in progress, which also bounds the recursion. |
| S-23: the 16-byte heap limit is a platform guarantee, not C11. | Accepted. It is stated as the platform `malloc` guarantee, citing C11 7.22.3p1 and 6.2.8p3, with an address-modulo test on each host. |
| S-24: implementation-defined cases are handled inconsistently, and one relaxation is unlisted. | Accepted. Signed conversions wrap and negative right shifts are arithmetic, as gcc and clang define them. The short-circuit relaxation is listed (gcc and clang accept `0 && (1 / 0)`). |
| S-25: type wide literals as `const`. | Rejected. C11 6.4.5p6 types `L"…"` as `wchar_t[N]`. Typing it `const` would refuse the C11-valid positive probe `r16-wide-string-literal` (`wchar_t* text = L"ab";`). Writing through a wide literal is undefined, documented as for narrow literals. |
| S-26: `<uchar.h>` may not be available. | Accepted, with the reviewer's alternative: `char16_t`/`char32_t` are emitted as `uint_least16_t`/`uint_least32_t` (C11 7.28p2). |
| S-27: `?.` followed by a digit. | Accepted. Longest match keeps `?.`; this is documented and tested in both lexers. |
| S-29: GPU coverage. | Accepted. `@gpu` refuses every C3 construct listed under Refusals. |
| S-30: the setjmp alias message becomes false after the flip. | Accepted. r15a rewords both "unsupported layered pointer qualifiers" messages. `volatile int count; volatile int* p = &count;` is the sanctioned spelling. |
| Draft: the target layout lives in `hosted_abi.toml`, with a `va_list` column. | Corrected. The columns go to C4's `targets.toml`, and `va_list` has no layout. The Windows `long double`/`max_align_t` cells are omitted where MinGW and MSVC disagree (verified with clang 21.1.8 on all ten triples). |
| Draft: one shared-owner commit. | Split into commit A (specifiers, behavior-neutral) and commit B (constants and layout, with the behavior fixes), so a regression in either bisects to one owner. |
| Draft: hosted `noreturn` on new `longjmp`/`pthread_exit` rows. | Deferred. Neither has a typed row, and the spec has no `parameters_known = false` row to model one; adding rows would change how existing calls are typed. |
| Draft: "12 `endswith("*")` sites". | Corrected to 10 in Python and 4 in btrc. |
| Draft: the boundary manifest holds 310 records. | Corrected: it holds 311 today, and C2 adds none. |
