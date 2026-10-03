# Design: Stage B consulted-fact reuse keys and the skip-unchanged journal

Status: **draft under review (CL-R-04)**. This is a design only: it changes no
compiler source. It is written against `main-kn9jxh` at `6c90ad8`; every
`file:line` below is on that tree. PLAN.md Stage 6 asks for this spec before
Stage 9 implements it (`perf-stageb-slice4`, `perf-stageb-skip-unchanged`).
CL-R-18 implements the keys, CL-R-19 implements the journal and then **freezes**
the journal section of this document. Any later memo cache (Stage 12) extends
it. CL-R-09 turns every row of the invalidation table (section 8) into a test
run through both compilers.

The spec assumes the groundwork in section 2.3 lands first. It depends on
none of the rejected experiments in `docs/design/compile-performance.md`
("Performance changes already measured and rejected"). In particular it shares
no managed object widely (the one-shared-empty-list rejection), adds no
pointer-keyed cache, and keys everything by structural position or by
declaration path, never by an address.

Paths are relative to `src/compiler/btrc/` for `.btrc` files and to
`src/compiler/python/` for `.py` files, unless a path starts with `docs/`,
`src/` or `tools/`.

## 1. What Stage B has to deliver

PLAN.md Stage 9's exit, for each fixed body-edit fixture, in both compilers:

- exactly **one** changed source group is analyzed and lowered;
- **no** unchanged group is re-lowered;
- only dependency-justified native compiles happen, plus one link;
- shared specialization or registration changes are counted and explained;
- a missing or incomplete journal falls back to full analysis, visibly in
  the counters, and the edit-sequence harness stays green.

Two mechanisms get there.

1. **Consulted-fact keys (slice 4).** A group's records are reused while every
   fact the group *consulted* outside itself has the same answer, instead of
   while the whole program's interface is unchanged. A signature edit then
   invalidates only the groups that asked about it.
2. **The skip-unchanged journal.** An unchanged group's body analysis is not
   run at all. Its journal replays the side tables, demand, diagnostics and
   summaries that analysis would have left. Its lowered unit is reused under
   the lowering key.

## 2. Where Stage B stands on `6c90ad8`

### 2.1 Self-hosted compiler

`docs/design/separate-compilation.md` (Stage B, slices 1–3 and per-instance
closure records) describes what exists. In brief:

- **Validation records.** `ValidationRecords` (`pipeline/ModuleUnits.btrc:2642`)
  keys each group by
  `context + group + group source digest + program interface digest`
  (`:2713-2722`). The interface digest is assembled per group, cached under
  the group's source digest, and sorted by group name (`:2731-2781`). It
  renders every declaration position-free with non-template callable bodies
  elided to `defined consumed=<indices>` (`ModuleUnitInterfaceSummary`,
  `:20-31`; `syntax/Identity.btrc:217,335,353`).
- **Record sections.** Four phases per function or class (discover, validate,
  close, realtime; `analyzer/Models.btrc:66-71`) holding 13 fact kinds
  (`:47-61`, including warnings and deferred generated-symbol references), and
  per-template instance sections (`validation-instances-v2`,
  `ModuleUnits.btrc:2893-2989`).
- **Positions.** `ValidationRecordCodec` (`:2348`) names a node by
  (12-hex file tag, top-level ordinal, pre-order index, node kind).
- **Dependencies.** A record that names another group's node carries
  `dep <group> <key>` lines (`:3004-3019`), checked at load (`:2813-2815`).
- **Lowering records.** `ModuleUnitRecord` keys each group by
  `module-unit-v5 + context + group + source digest + programDigest()`
  (`:1815-1823`). `programDigest` (`:1007-1044`) is the interface digest plus
  `usesTrycatch`, the ordered generic class and method instance lists, and the
  reached stdlib declarations and mentioned names. After the key matches, five
  checks run per group: consulted setjmp summaries (`:1892-1903`), summary
  cycles (`:1904-1909`), the entry unit's cyclable-release fact (`:1870`),
  realtime proofs (`:1912-1923`) and kept instance members (`:1926-1936`).
- **Counters today.** `BtrccPhaseTimer` prints `module-units=lowered:N,reused:M`
  (`:2058`), `a-records-stored(replayed=R,journaled=J)` and
  `a-instances(replayed=N)` (`pipeline/Pipeline.btrc:192-193`);
  `moduleUnitsLowered`/`moduleUnitsReused` are result fields
  (`pipeline/Models.btrc:97-98`).

Analysis is still entered for every group: registration, the program-wide
pre-passes and the fixed points run live, and a replayed declaration still
costs a decode. That is what the journal removes.

### 2.2 Reference compiler

The Python compiler has module units with the same Stage A keys
(`application/modules.py:840-884`; facts digest `:789-826`, which also covers
`generic_class_callable_instances` and `realtime_safe_callables`, unlike
btrcc's). It has **no analysis records**: `ProgramInterface` drops
`source_file` (`modules.py:43`) and analysis keeps one `node_types` table keyed
by `id()` (`analyzer/program.py:417`) whose values alias other declarations'
type nodes (`analyzer/calls.py:738,801,856`). PLAN.md Stage 8 adds the
reference slices; slice 4 and the journal land paired in Stage 9.

The only counters are the result fields `module_units_lowered` and
`module_units_reused` (`application/results.py:152-153`). `btrcpy timing:`
(`cli/compiler.py:716`) carries no module-unit marks.

### 2.3 Defects and groundwork found by this audit

Three stale reuses exist **today**, under the Stage A whole-program keys.
Each was reproduced on Linux with both compilers (a cold build, one edit, an
incremental build compared unit by unit with a clean build in a fresh cache;
the probe is described in section 8.1):

| Id | Edit | btrcpy | btrcc | Cause |
| --- | --- | --- | --- | --- |
| SB-D1 | the body of a `@gpu` kernel in group B, dispatched from group A | A reused with the old WGSL string | same | every session registers every kernel and generates WGSL from its body (`ir/gpu/Pipeline.btrc:821-839`, `ir/lowering/gpu.py:2053-2057`); the dispatching unit embeds it (`ir/Emitter.btrc:187-189,380-390`, `backend/c_emitter.py:1133-1141`); kernel bodies are elided from the interface digest |
| SB-D2 | the body of `Base.__del__` in group B, inherited by `Derived` in group A | `Derived_destroy` keeps the old body | same | `classMethod(child, "__del__")` returns the nearest ancestor's method (`analyzer/Declarations.btrc:108-130`) and its body is lowered into the child's hook (`ir/lowering/Declarations.btrc:3531-3546`) |
| SB-D3 | a line inserted above a function with a default argument (`--debug`) | not affected: the helper is positioned at `<btrc-generated>` | the caller's reused unit keeps `#line 1 "Lib.btrc"` where a clean build has `#line 3` | btrcc positions the default helper at the callee's default (`ir/lowering/Functions.btrc:486-491`); no key covers foreign positions |

They are compiler defects, not spec questions: each needs a paired fixer
commit before CL-R-09's tests can pass, and each is an invalidation row below
(SB-01, SB-02, SB-03). SB-D3 also shows a parity difference in debug output.

The audit also found groundwork that slice 4 needs before it can be sound.
Each item is a prerequisite of CL-R-18, landed paired:

- **G1. Record positions computed after the defaults merge.** btrcc caches a
  declaration's positions at the discover phase (`ModuleUnits.btrc:2455`), but
  `mergeCallableDefaults` later attaches a prototype's default subtrees to the
  definition (`analyzer/validation/Names.btrc:383-393,550`), and the pre-order
  walk visits defaults before the body (`syntax/Identity.btrc:31-40`). A replay
  build that first resolves the definition after the merge shifts every body
  index; only the node-kind check guards it. Suspected, not reproduced; the
  verify gate never saw it because the corpus case
  (`src/tests/c_compat/VoidAndUnnamedParameters.btrc:13,28`) records no body
  facts. CL-R-09 row SB-04 reproduces it.
- **G2. Positions by member path.** A foreign position today is a pre-order
  index over the whole top-level declaration (`ModuleUnits.btrc:2365-2382`).
  A body edit in an earlier member of class `C` shifts the indices of `C`'s
  later members' signature and default nodes. Under slice 4, where a foreign
  reference no longer pins the foreign group's whole source, a position must
  be (declaration path, member path, pre-order index within the member).
- **G3. Order-independent reference analysis.** The reference analyzer
  depends on program order where btrcc does not:
  - a consuming parameter's omitted default is checked against the callee's
    `node_types`, which exist only once the callee's body pass ran
    (`analyzer/ownership.py:490-497,672`);
  - a `var` global is typed in the body pass (`analyzer/statements.py:2112-2164`),
    where btrcc infers it up front (`analyzer/Expressions.btrc:173-188`);
  - `node_types` values alias whichever type object existed first
    (`analyzer/types.py:1952`).
  All three were reproduced with probes on the reference analyzer. Defaults and
  `var` globals move to pre-passes, and Python facts key by structural position
  and value, never by object identity.
- **G4. One raw-borrow summary for both compilers.** Python proves raw borrows
  after every body (`analyzer/analyzer.py:143-144`) over the callee's recorded
  types. btrcc proves them at the call (`analyzer/validation/Borrows.btrc:680`),
  under the asking caller's type parameters (`:630-657`, read at `:146`), and
  skips calls in some subexpressions. The two can answer differently, and the
  btrcc cache depends on which caller asks first. Slice 4 needs one definition,
  computed as a per-callee summary.
- **G5. Realtime edges check their target.** Replay checks only that the
  calling callable exists (`analyzer/Realtime.btrc:1216`), and the fixed point
  treats an unknown target as safe (`:1286`).
- **G6. `sourceKnown` re-derived at replay.** A deferred generated-symbol
  reference stores the program-wide "identifier is known" verdict
  (`analyzer/validation/Names.btrc:1054-1061`) and the end check trusts it
  (`:1046`).
- **G7. One interface rendering.** Python's interface digest is computed after
  analysis and omits native contracts; btrcc's is computed before analysis and
  includes them. The export digests of section 4 are defined once and rendered
  identically by both.

## 3. Pass audit: every pass and the facts it consults

Four read-only auditors listed every lookup each pass makes into another
declaration or group. Their full reports are summarized here; each row names
the pass, where it is invoked, and the facts it consults outside its own
declaration. **body** marks a fact that changes when only its owner's body
changes. The key namespace in the last column is defined in section 5.

### 3.1 btrcc analysis (`SemanticAnalyzer.analyze`, `analyzer/Analyzer.btrc:40-73`)

| Pass (owner, definition) | Invoked | Consults outside the declaration | Key |
| --- | --- | --- | --- |
| `stampProgramSources` (`analyzer/HostedAbi.btrc:359`) | `pipeline/Pipeline.btrc:142` | file path to stdlib marker | context |
| `setNativeDeclarations`, `configureUnmodeledIncludes` (`analyzer/Models.btrc:176`, `analyzer/Analyzer.btrc:87`) | `Pipeline.btrc:176-177` | native imports; unmodeled include lines | `native`, `macro` |
| `DeclarationRegistry.registerProgram` (`analyzer/Declarations.btrc:42`) | `Analyzer.btrc:50` | every header; `funcTable` last writer, `interfaceTable` and enum owners first writer, member indexes through ancestors (`:47-131`) | `name` (all same-named, in order) |
| `ExpressionTypeResolver.inferGlobals` (`analyzer/Expressions.btrc:173`) | `Analyzer.btrc:52` | callee and constructor signatures an initializer reaches | `global-type` |
| `GenericSpecializer.discover`: argument upgrade, collection, transitive closure, method-generic scan (`analyzer/Generics.btrc:50-73,654,711,957,234`) | `Analyzer.btrc:53` | whole class table (upgrade); template signatures and **template bodies**; callee signatures; global types | `name`, `export`, `generic` |
| `SourceMacroNamespace` (`analyzer/SourceMacros.btrc:14,129`) | `validation/Validator.btrc:45` | every `#define`/`#undef`, final state | `macro` |
| type, interface, inheritance, enum-constant, aggregate, mutex, struct-layout pre-passes (`validation/Types.btrc:611,974`; `validation/Declarations.btrc:436,477,934`; `validation/Constants.btrc:297`; `validation/Ownership.btrc:470`) | `Validator.btrc:61-75` | parents, interfaces, transitive struct/rich-enum/typedef chains, enum values program-wide, instance list | `name`, `enum-value`, `generic` |
| names, duplicates, defaults merge, storage, overrides (`validation/Names.btrc:211,477,586,605`; `validation/Storage.btrc:456`) | `Validator.btrc:77-78` | all top-level names; prototype defaults (written onto the definition); inherited members | `name` (prototype and definition as one unit) |
| `publishKnownGeneratedSymbols` (`validation/Names.btrc:817`) | `Validator.btrc:80` | every class, enum, interface, instance; visitor need (field types of ancestors); `__del__` **presence** | `name`, `cycle` |
| `validateNativeInvocations` (`validation/Borrows.btrc:96`) | `Validator.btrc:82` | **callee bodies** transitively (`:33-67`); every typedef a type node names (`:72-94`) | `summary.local-invocation`, `name` |
| callable shapes, class contracts, rich-enum defaults (`validation/Declarations.btrc:309,466,847`) | `Validator.btrc:84-103` | parent chain, merged methods, consumed parameters of requirement and implementation | `export` |
| `NullableFlow.computeNonreturning` (`validation/ControlFlow.btrc:1471`) | `Validator.btrc:105` | **every callable body**; hosted noreturn; `subclassesOf` for dispatch (`:1575-1587`) | `summary.diverges`, `descendants` |
| array-bound pre-pass (`validation/Storage.btrc:827`) | `Validator.btrc:107-132` | enum constants, rich-enum ordinals, macro string lengths | `enum-value`, `macro`, `bound` |
| body validation (`validation/Declarations.btrc:562,717`) | `Validator.btrc:133-228` (replayed in V) | call resolution, signatures and defaults, **callee bodies** for raw-borrow proofs (`validation/Borrows.btrc:483-520,630-658`), callee leading statements (`analyzer/Declarations.btrc:265-292`), callee defaults inferred in the caller's scope (`validation/Ownership.btrc:978`), hosted classification, enum ambiguity and the `known` verdict (`validation/Expressions.btrc:940-965`), macro existence (`validation/Calls.btrc:769-806`), constant bounds on foreign nodes (`Calls.btrc:250`), ancestors and interfaces, callee divergence and subclasses (`ControlFlow.btrc:1456,1575`) | `name`, `export`, `summary.*`, `enum-value`, `macro`, `exists`, `bound`, `descendants` |
| top-level `var` (`validation/ControlFlow.btrc:647`) | `Validator.btrc:140-144` | other globals' types | `global-type` |
| `closeExpressionGraph`, native callback instances, instance closure (`analyzer/Generics.btrc:168,175,1430,1503`) | `Analyzer.btrc:59` (C and I sections) | validation's side tables, template bodies under substitution, every declaration their inference reaches; native contracts; stdlib `Bytes`/`Callback*` | `name`, `export`, `generic`, `native` |
| `RealtimeAnalyzer.validate` (`analyzer/Realtime.btrc:209`) | `Analyzer.btrc:61-63` (R section; fixed point live) | any `@realtime` root; callee signatures; **callee defaults** (`:713-750`); transitive managed-type facts (`:1108-1151`); native contracts | `exists`, `name`, `export`, `native` |
| `validateCompletedGeneratedSymbols` (`validation/Names.btrc:1071`) | `Analyzer.btrc:64` | final generated symbols, runtime catalog, preprocessor references | `generic`, context |
| `CycleSemantics` (`analyzer/ownership/Cycles.btrc:58-309`) | from 5j, 8 and lowering | **every subclass** of a type, every instance implementing an interface | `cycle`, `descendants` |

### 3.2 btrcc lowering (`IRLowerer.lower`, `ir/lowering/Lowerer.btrc:127-239`, one session per group)

| Owner / site | Consults outside the group | Key |
| --- | --- | --- |
| program facts (`Lowerer.btrc:130-175`; `ir/lowering/Context.btrc:40-54`) | stdlib reachability (all bodies), `#pragma pack` state in program order (`Declarations.btrc:105-141`), `usesTrycatch` (any body) | `program` |
| `GpuPipeline.registerKernels` (`ir/gpu/Pipeline.btrc:821`) | every kernel's **body** (WGSL) | `export` (kernel body) |
| owned generic instances (`Lowerer.btrc:190-224`; `ir/lowering/Functions.btrc:183-316`) | the ordered demanded instance list; type arguments' layout, ARC and cyclability; a subclass reaching an inherited generic method | `generic`, `cycle` |
| `emitEnums`, `emitDeclarations` (`ir/lowering/Declarations.btrc:2508-2588`) | every group's directives in program order; every C native import; `globalHasDefinition` (`:2496,2553-2556`) | `program`, `native`, `name` |
| class lowering (`Declarations.btrc:3192-3837`) | ancestor fields, initializers, methods; interface tables; visitor need; **inherited `__del__` body** (`:3531-3546`); `runtimeTypeMayCycle` (`:3696,3710`) | `name`, `export`, `cycle` |
| calls (`ir/lowering/Calls.btrc:163-169,298-355,393,424,549-559,747-879`) | callee signatures and body presence; native contracts; `print`/`Mutex` only if nothing else has the name; **callee default expressions**, lowered into the caller | `name`, `exists`, `native`, `export` |
| callables (`ir/lowering/Callables.btrc:167-231,824,847-857`) | absence of a same-named global; `lexicalBindingConflictsType` (any type or generic parameter name, `analyzer/Models.btrc:529-571`); session counters after owned instances | `exists`, `generic` |
| functions (`ir/lowering/Functions.btrc:375-386,453-517`) | every global's type; default helpers positioned at the callee's default | `global-type`, `position` |
| ownership (`ir/lowering/ownership/*`) | cyclability by subclass (`Lifetime.btrc:302,376-378,480`); consumed parameters (`Calls.btrc:342`); enum-value ownership count (`Operands.btrc:178`); global definitions (`ManagedTypes.btrc:314`) | `cycle`, `summary.consumed`, `enum-value`, `name` |
| `ModuleUnitDeclarations.mergeInto` (`pipeline/ModuleUnits.btrc:618-707`), planner (`ir/optimization/Optimizer.btrc:1295-1318`) | shared declarations by name closure, every macro replacement, in program order; tuple shapes in discovery order (`Declarations.btrc:3935-4013`) | `shared` |
| setjmp solve, realtime composition, instance demand (`ModuleUnits.btrc:917-964,1444-1752`) | other units' effect summaries, proofs, reference graphs | existing post-plan checks |

### 3.3 Python analysis (`SemanticAnalyzer.analyze`, `analyzer/analyzer.py:124-207`)

| Pass (owner, definition) | Invoked | Consults outside the declaration | btrcc counterpart / parity |
| --- | --- | --- | --- |
| `AnalysisSession.begin`, `OwnershipAnalyzer.begin` (`program.py:440`, `ownership.py:266`) | `analyzer.py:127-128` | — | `Analyzed()` |
| `DeclarationRegistry.register` (`declarations.py:1218-1260`) | `:129` | every header; prefers the bodied definition (`:394-396`); **merges prototype default nodes** (`:1027-1030`) | merge happens later in btrcc (`Names.btrc:550`) |
| `configure_unmodeled_includes` (`generated_symbols.py:92`) | `:130` | directives | same |
| `TypeSystem.normalize_declarations` (`types.py:1956-2007`) | `:131` | whether any class or interface has a name (`:1940`) | no pointer auto-upgrade in btrcc |
| `validate_declarations` (`statements.py:1341-1394`) | `:132` | all declaration array bounds, including parameters, returns, properties, interface methods | btrcc's bound pre-pass covers fewer sites (`Validator.btrc:108-132`) |
| interface parents, hierarchy (`declarations.py:494-693,1284-1316`) | `:133-134` | parents, interfaces, parent methods' leading statements | same |
| `compute_cyclable_flags` (`ownership.py:507-541`) | `:135` | every class's storage | btrcc computes on demand |
| aggregates (`aggregates.py:381-479`) | `:136` | aggregate and typedef cycles | same |
| `compute_nonreturning_callables` (`flow.py:77-116`) | `:137` | **every callable body** | same |
| rich-enum defaults (`statements.py:1830-1883`) | `:138-140` | variant defaults, precomputed once | btrcc re-evaluates per call site (`Ownership.btrc:937`) |
| body pass `analyze_declaration` (`statements.py:1540-2164`) with `ExpressionAnalyzer`, `CallAnalyzer`, `GenericAnalyzer` demand, `GpuAnalyzer`, `SourceMacroAnalyzer` | `:141-142` | as btrcc's body validation, plus `node_types` values aliasing callee, field, global and interface types (`calls.py:738,801,856`; `expressions.py:1453,1485`) | demand inline, not in three phases |
| `settle_raw_borrow_obligations` (`ownership.py:1514-1521`) | `:144,151` | **callee bodies and callee `node_types`**, transitively | G4 |
| native callback instances (`generics.py:68-157`) | `:145` | native contracts; stdlib callback classes | same |
| `close_generic_instance_graph` (`generics.py:159-192,340-573`) | `:146` | template bodies and their `node_types` | same |
| `validate_native_invocations` (`ownership.py:548-669`) | `:147` | every tree after `var` inference; callee bodies | btrcc runs it before bodies |
| `RealtimeAnalyzer.analyze` (`realtime.py:118-133,425,829`) | `:148` | as btrcc; callee defaults use the callee-scope type | btrcc infers with the caller's variables (`Realtime.btrc:745`) |
| `validate_generic_type_facts` (`ownership.py:543-546`) | `:149` | resolved specializations | `validateConcreteMutexInstances` |
| `validate_program_symbols` (`generated_symbols.py:200-235,494-520`) | `:150` | claims, final instances, a re-walk of every declaration | `Names.btrc:817,1054,1071` |

### 3.4 Python lowering and module units (`application/modules.py`, `ir/lowering/*.py`)

| Owner / site | Consults outside the group | btrcc counterpart |
| --- | --- | --- |
| `TranslationUnitLowerer` program facts (`ir/lowering/translation_unit.py:147-164,701-737`) | generic instance tables, stdlib reachability, try/catch use | `Lowerer.btrc:130-175` |
| GPU kernels (`ir/lowering/gpu.py:2053-2057`; `backend/c_emitter.py:1133-1141`) | every kernel's body | SB-D1 |
| classes and ownership (`ir/lowering/classes.py`, `ownership.py:353-661,875,2192`) | layouts, parents, interface tables, cycle closure over the class table | same |
| calls (`ir/lowering/calls.py:2301-2303`; `functions.py:4050-4063`) | callee defaults (helper positioned at `<btrc-generated>`), consumed parameters | SB-D3 |
| realtime-safe set (`application/pipeline.py:625-629`) | only whether it is empty | not in btrcc's digest |
| `ModuleUnitRecord` checks (`application/modules.py:74-218`) | setjmp consulted effects, summary cycles, `effects_solved`, entry release, realtime roots and proofs | the same five checks |

Session counters (lambdas, temporaries, spawn ids, default helpers, cleanup
adapters) are per session in both compilers. In btrcc, lambda, spawn and GPU
helper names are **not** renumbered per unit (`ir/optimization/Optimizer.btrc:941`
covers only the adapter families), so they depend on how many owned instances
other groups demand.

## 4. Terms

- **Group.** A compilation group (`separate-compilation.md`, "Compilation
  groups"). The inline standard library and the native declarations are each
  one **durable** group: their key is the stdlib source digest and the native
  identity, and nothing in a user edit changes it.
- **Declaration path.** (file identity, name path, ordinal among same-named
  declarations in that file). It never contains a line number or a combined
  line: btrcc's `declaration.line` counts the inline stdlib and every earlier
  user file (`pipeline/ModuleUnits.btrc:2700-2705`), so it moves whenever an
  unrelated file grows.
- **Position.** (declaration path, member path, pre-order index within the
  member, node kind) (G2). Members are the class members, the parameter list,
  and the body.
- **Exports of a declaration**, `X(d)`: the digest of
  - its interface rendering (today's `interfaceRenderer`, G7);
  - its **summaries**: consumed parameter indices, `diverges`, per-parameter
    raw-borrow results, native-invocation locality, whether each omitted
    default produces an owned value, rich-enum unsafe defaults, and (for
    lowering) its setjmp effect;
  - its **exported bodies**, the body text other groups copy: a `@gpu`
    kernel's body (SB-D1), a `__del__` body (SB-D2), and template bodies,
    which the interface already keeps.
  Summaries are compared by value, so a body edit that leaves them unchanged
  stops there (early cutoff).
- **Query.** A question a pass asks outside its group, with its **answer**.
  The ordered, de-duplicated list of a group's queries is its **consulted-fact
  log**: one for analysis, one for lowering.

## 5. The per-group keys

Each group has two keys. Each is a hash of fixed inputs plus a consulted-fact
log. The log itself is stored in the group's journal (section 6); the key
check re-asks every logged query against the current build and compares the
answers.

### 5.1 Fixed inputs

| Input | Analysis key | Lowering key |
| --- | --- | --- |
| schema (`stage-b-v1`) and compiler identity (the artifact cache's toolchain fingerprint) | yes | yes |
| options: target, strict imports, include stdlib (`ModuleUnits.btrc:2713`) | yes | yes |
| lowering context: debug, DCE, target, and in debug mode the units prefix and output path (`ModuleUnits.btrc:1817`) | no | yes |
| the group's own source digest (resolved lines with their file and line, `:2680-2696`) | yes | yes |
| durable tier: stdlib source digest and native identity | yes | yes |

The group's own positions stay in both keys, because its own diagnostics and
`#line` directives carry them. **No other group's positions are a fixed
input.** Where another group's position reaches a group's output, it is a
logged `position` query (5.2).

### 5.2 Query namespaces

Every lookup in section 3 that leaves the group is logged in one of these
namespaces. An answer is a digest; `ABSENT` is an answer, so negative lookups
are logged too.

| Namespace | Query | Answer | Covers |
| --- | --- | --- | --- |
| `name` | (kind, name) for kind in function, global, class, generic class, interface, struct, typedef, enum, rich enum, member-of-`C` | the ordered list of every declaration with that name and kind, as (declaration path, `X(d)`); `ABSENT` | callee and type resolution; last- and first-writer tables (M14); prototype/definition pairs as one unit (M8); member lookup through ancestors |
| `export` | `X(d)` of a declaration reached other than by name (an ancestor, a type argument, a callee's default expression and everything it reaches) | `X(d)` | transitive type facts (M6); default closure (C7); inherited `__del__` (SB-D2); kernel bodies (SB-D1) |
| `summary.<kind>` | (declaration path, parameter) for `consumed`, `diverges`, `raw-borrow`, `local-invocation`, `owned-default`, `rich-enum-default` | the summary value | callee body facts with early cutoff |
| `enum-value` | a bare value name | (owner path or `AMBIGUOUS`, owner count) | M1 |
| `macro` | a macro name, including each name its expansion reaches | (declared anywhere, final active definition text) | M2; unmodeled includes |
| `exists` | an existential question: any method named `m`; any type or generic parameter named `x`; any global named `x`; any `@realtime` root; `print`/`Mutex` shadowed | yes/no | M4; K2, K4, C6 |
| `descendants` | a class or interface | the ordered set of (declaration path, `X(d)`) of every subclass or implementing instance | M5; dispatch divergence |
| `cycle` | a runtime type | (may cycle, needs visitor) | O1, D7: cyclability set by subclasses anywhere |
| `global-type` | a global name | its inferred type, rendered | M7 |
| `bound` | a foreign array-bound node | constant or not, and its value | M10 |
| `generic` | for a template the group owns: the ordered list of demanded instances; for a consumer: nothing (its demand is an output) | the ordered instance list with each type argument's `X(d)` | L5, L7, F2, D11 |
| `program` | try/catch use; stdlib reachability of the names the group mentions; `#pragma pack` state at the group's first declaration; the program's directive list | values, in program order | L1, L8, L9, L10 |
| `native` | a native declaration or contract the group consulted, and the program's native header list | its contract digest; the list | L2, C5 |
| `shared` | lowering only: the shared declarations the unit pulled in | (name, rendered digest) in the order the unit emits them | L3; tuple discovery order |
| `position` | lowering, debug mode only: a foreign node whose position the unit's text carries | (file identity, line) | SB-D3 |

Queries are logged at the lookup site, through one owner per compiler: the
analysis tables (`Analyzed`, `analyzer/Models.btrc`; `AnalysisSession`,
`analyzer/program.py`) and `LoweringContext` (`ir/lowering/Context.btrc`;
`ir/lowering/session.py`). A lookup that bypasses the logging owner is a
defect, and the verify mode (6.6) is what finds it.

### 5.3 Key checks and when each runs

Answers are known at different times, so a key is checked in three steps.
A group that fails any step is **live**: analyzed (or lowered) as in a clean
build.

1. **Plan, after registration.** Registration and the interface rendering run
   live for every group. They are cheap, and the rendering is already cached
   per group source digest (`ModuleUnits.btrc:2731-2781`). All of `name`
   (interface part), `export` (interface part), `enum-value`, `macro`,
   `exists`, `descendants`, `global-type`, `native`, `program` (except
   reachability) and `durable` answers are known here and are checked here.
   The live set `L0` is: changed groups, groups without a valid journal, and
   groups whose plan-time answers differ.
2. **Analysis, at summary publication.** Summaries of live groups are known
   only once those groups are analyzed. A summary is published when its
   declaration finishes; a journaled group whose logged `summary.*`, `bound`
   or `cycle` answer then differs is **invalidated late**. Summaries that form
   a fixed point (divergence, raw-borrow cycles) are solved as the setjmp
   solve already is: the least fixed point restricted to live groups, with
   journaled groups' exported values held fixed, and any summary cycle that
   joins a journaled group to a live group makes the journaled group live
   (`separate-compilation.md`, "Stage A as implemented", step 4).
3. **Restart.** If any group was invalidated late, analysis restarts with
   `L1 = L0 ∪ invalidated`. Live sets only grow, so this terminates; after
   **two** restarts the build falls back to full analysis (6.5). Each restart
   is a counter.

The lowering key adds `generic`, `shared`, `position` and the remaining
`program` answers, which exist once the declarations session and the instance
lists exist, and it keeps today's five post-plan checks. A group analyzed live
is lowered unless its lowering key still matches: an analysis that reproduces
the same journal leaves the unit reusable (early cutoff at the unit).

### 5.4 Source locations of unrelated modules

- No key and no record holds a line, column or combined line of a declaration
  outside its group. Records name nodes by position (section 4).
- Replayed diagnostics and witnesses take their line and column from the node
  the position resolves to in the current build, as realtime events already do
  (`separate-compilation.md`, slice 3). A line shift in another group
  therefore changes no key and still reports correct locations.
- The only exception is text that copies a foreign position into a unit: in
  debug mode, btrcc's default-argument helper (SB-D3). It is a `position`
  query. Python positions the helper at `<btrc-generated>`; the paired fix for
  SB-D3 either makes both compilers position it at the callee's default,
  logging the query, or both at `<btrc-generated>`. The default is the latter
  (open question Q3), which needs no query.

## 6. The skip-unchanged journal

### 6.1 What a journal records

One journal per group, written by the owner process only after a build that
passed (errors abort, so no journal records a failure), stored in the
artifact cache like today's records (checksummed, framed by the toolchain
fingerprint; `separate-compilation.md`, "Stage A in the self-hosted
compiler"). Schema `stage-b-journal-v1`, sections in this order:

1. **Header**: schema, compiler identity, the fixed key inputs (5.1), and a
   digest of the rest.
2. **Exports**: for each declaration of the group, in program order, its
   declaration path and `X(d)` with each summary value. Consumers' queries are
   answered from here when the group is not live.
3. **Program-fact contributions**: whether the group's bodies use try/catch;
   the stdlib names it mentions; its realtime roots; whether it releases
   cyclable values; the tuple shapes it discovered, in discovery order; its
   directives. Program facts are recomputed from live groups plus these, so no
   journaled group's bodies are scanned.
4. **Analysis log** (5.2), then **lowering log**.
5. **Per declaration, in program order**, today's four phases plus what the
   audit found missing:
   - discover, validate, close, realtime facts (all 13 kinds), unchanged;
   - the generic **demand events** in order, before de-duplication
     (slice 2), never the resulting lists;
   - warnings with their site positions;
   - deferred generated-symbol references **without** the `sourceKnown` bit,
     which replay re-derives (G6);
   - the declaration's contributions to the `globals` map;
   - Python only: `node_types` entries as (position, rendered type), and the
     AST patches body analysis makes (G3).
6. **Instance sections**: today's per-instance closure journals
   (`validation-instances-v2`), with dependencies taken from the analysis log
   instead of `@` positions (M11).

### 6.2 What replay reproduces

At a journaled declaration's place in program order, the analyzer:

- resolves each position and installs the facts into the same side tables a
  live pass writes, so later live groups and lowering read them unchanged;
- re-runs only each demand event's de-duplication check and push, so the
  instance lists, their order and the last-writer call arguments come out as
  a live scan leaves them;
- reports the warnings at their current positions;
- queues the deferred references for the end-of-analysis check;
- extends the `globals` map;
- publishes the declaration's exports as its summaries.

Registration, the defaults merge (`Names.btrc:550`; `declarations.py:1027`),
the generic-argument upgrade and source stamping stay live for every group:
they are idempotent, cheap, and other groups' queries read their results.
The program-wide fixed points stay live, over journaled values (5.3, step 2).

A journaled group is **not entered** by any body pass: the native-invocation
walk, the nonreturning fixed point's body scan, the raw-borrow proof, the
array-bound pre-pass for its own nodes and the realtime scan all take its
journaled results. That is the difference from today's replay, which still
runs these over every group.

### 6.3 Lowering

A group whose lowering key matches is not lowered; its unit text, reference
graph, exported setjmp summaries and realtime proofs come from its
`ModuleUnitRecord`, as today. A live group is lowered in a fresh session over
the analyzed program, whose side tables are complete because journaled groups
were replayed.

### 6.4 Shared specialization and registration changes

An instance newly demanded by an edited group is lowered in its template's
group. That group is then lowered even though its source did not change,
because its `generic` answer moved. The counters report it as
`lowered-for=generic` and name the instance, so a fixture's "exactly one
group lowered" check can tell it apart (PLAN.md Stage 9: "counted and
explained"). The same holds for a group lowered because a `descendants` or
`cycle` answer moved: a new subclass in a consumer re-lowers the base's group
(`lowered-for=cycle`).

### 6.5 Fall-back

Any of these makes the whole build analyze live, as without journals, and
names its reason in the counters:

| Reason | Trigger |
| --- | --- |
| `no-store` | module units without a cache, or not strict imports (`pipeline/Pipeline.btrc:183`) |
| `verify` | the verify mode is on (6.6) |
| `dirty-share` | more than half of the groups are live after the plan step (Q2) |
| `restarts` | a third restart would be needed (5.3) |
| `native-unknown` | the native identity is empty (`ModuleUnits.btrc:2741`) |

Any of these makes **one group** live and does not stop the others from
replaying:

| Reason | Trigger |
| --- | --- |
| `missing` | no journal, or a void one |
| `schema` | a different schema or compiler identity |
| `corrupt` | a checksum, framing or decode failure |
| `source` | the group's own source digest changed |
| `answer` | a logged answer differs (with the namespace) |
| `position` | a position fails to resolve, or resolves to another kind |
| `unrecordable` | a fact with no encoding (today: a type with an array size) |
| `late` | invalidated at summary publication (5.3, step 2) |

A journal that replays only partly is never left half-installed: as today
(`ModuleUnits.btrc:2991-2999`), the group is abandoned, its close-phase and
after-validation instance sections go live, and `persist` voids its journal.
A void journal is rewritten by the next passing build.

### 6.6 Verify mode

`BTRC_VERIFY_VALIDATION_RECORDS` keeps its name and widens. It analyzes and
lowers every group live and then requires:

- every stored journal section to equal the live one, and to round-trip
  through decode and encode;
- every logged answer to equal the live answer;
- every query the live build made to be in the stored log, which catches a
  lookup that bypasses the logging owner;
- every reused unit to equal the live unit.

It never takes a stored result. CL-R-09 runs it over the corpus, the
self-hosted compiler's source and BTRSmith.

## 7. Counters

Both compilers expose the same counters, under the same names, in two places:

- a line on stderr under `BTRC_TIMING`, after the timing line:
  `<compiler> stage-b: groups=N analyzed=A replayed=R lowered=L reused=U
  restarts=K fallback=<reason|none> live-for=<reason>:n,... lowered-for=<reason>:n,...
  instance-scans=live:x,replayed:y`
  (`btrcc` or `btrcpy`; the reasons are those of 6.4 and 6.5);
- result fields: `stageB` on `BtrccCompilationResult`
  (`pipeline/Models.btrc`) and `stage_b` on the compile result
  (`application/results.py`), holding the same names, plus the group names
  in each category.

Definitions:

- **analyzed**: a group any of whose declarations ran any body phase live
  (discover, validate, close, realtime, native-invocation walk). Registration
  and the interface rendering are not analysis.
- **replayed**: a group with a journal installed in full.
  `analyzed + replayed = groups`, the two durable groups included.
- **lowered** and **reused**: as `module-units=lowered:N,reused:M` today
  (`ModuleUnits.btrc:2058`).
- **Native compiles and links** are not compiler counters. The native plan
  reports them, for either compiler's link plan: `compiled_units`,
  `reused_units` and `links` (`tools/native_plan.py:561-600`,
  `NativeBuildReport.as_dict`). A body edit's fixture expects
  `compiled_units` to equal the units whose bytes changed and `links == 1`.

The existing `module-units=` and `a-records-stored(...)` marks stay until the
tests that read them (`src/tests/python/test_module_units.py:302-316,367,377`)
move to the new line.

## 8. Invalidation rows (Stage 7, CL-R-09)

Each row is an edit the spec must not reuse unsoundly, a fixture sketch, and
the expected **rebuild set** in both compilers: the groups analyzed (A) and
lowered (L), and the native compiles (N; units whose bytes change) and links.
Unless a row says otherwise, the fixture is three groups, `Lib`, `Use`
importing `Lib`, and `Main` importing `Use`, built cold, edited once, and
built again with the same cache and the same output directory; the
incremental units must equal a clean build's in a fresh cache. "Program unit"
is always lowered and is not counted.

### 8.1 The probe

The rows marked **reproduced** were run on Linux (a stand-in; no Mac numbers)
with `btrcpy` and the test-harness `btrcc` at `6c90ad8`, through a scratch
script that performs exactly the cycle above with `--module-units --jobs 1`
and compares every unit. CL-R-09 turns it into `m11_edit_sequence.py`.

### 8.2 Rows from the audit

| Id | Edit | Unsound reuse it guards against | Fixture sketch | Expected rebuild set |
| --- | --- | --- | --- | --- |
| SB-01 | body of `@gpu` kernel `twice` in `Kernel`, dispatched from `Use` | `Use` reused with old WGSL (SB-D1, **reproduced**, both compilers) | `Kernel`: `@gpu float[] twice(float[] a)`; `Use`: `values = twice(values)`; edit `* 2.0` → `* 3.0` | A: Kernel. L: Kernel, Use (`export`). N: 2. Links: 1 |
| SB-02 | body of `Base.__del__` in `Base`; `Derived extends Base` in `Derived` | `Derived_destroy` keeps the old body (SB-D2, **reproduced**, both) | edit `freed = freed + 1` → `+ 2` | A: Base. L: Base, Derived. N: 2. Links: 1 |
| SB-03 | `--debug`: a comment line above `int scale(int x, int factor = 3 + 4)` in `Lib`; `Use` calls `scale(2)` | `Use`'s helper keeps `#line 1` (SB-D3, **reproduced** in btrcc; btrcpy unaffected) | same output directory for every build | A: Lib. L: Lib (and Use only if Q3 keeps foreign positions). N: as L. Links: 1 |
| SB-04 | prototype `int f(int a, int b = 1);` in `Lib`, definition `int f(int a, int b) { printf(...); }` in `Impl`; edit a later statement of `f` | a replayed position shifted by the merged default (G1) | build under `BTRC_VERIFY_VALIDATION_RECORDS` after a normal build | A: Impl. L: Impl. Verify passes |
| SB-05 | `fail()` in `Lib` changes from `exit(1)` to `return`; `Use` stores a nullable after calling `fail()` | `Use` replays a stale warning set ("never returns", M9) | caller warning differs (probe in the reference analyzer) | A: Lib, Use (`summary.diverges`). L: Lib, Use. Warnings equal a clean build's |
| SB-06 | a new `enum Paint { RED }` in `Other`, which `Use` does not import, while `Use` writes bare `RED` from `Lib`'s `enum Color { RED }` | `Use` keeps resolving `RED` (M1); a clean build rejects it as ambiguous | `Main` imports `Other` | the build fails like a clean build |
| SB-07 | `#undef LIMIT` added in `Other`, while `Use` uses `LIMIT` from `Lib` | `Use` replays `sourceKnown = true` (M2, M3, G6) | | same result as a clean build (failure or new constant) |
| SB-08 | `class Leaf extends Node` with a field of type `Node` added in `Use`, which imports `Lib`'s `Node` | `Lib`'s unit keeps acyclic release helpers (O1, M5) | | A: Use. L: Use, Lib (`lowered-for=cycle`). N: 2 |
| SB-09 | a global `int count` added in `Other`, while `Use` has a lambda capturing a local `count` | `Use`'s lambda keeps capturing (K2) | | A: Other. L: Other, Use. Units equal a clean build |
| SB-10 | `class value {}` (or a generic parameter named `value`) added in `Other`, while `Use` has a local `value` | `Use` keeps the local's C name instead of `__btrc_source_value` (K4) | | A: Other. L: Other, Use |
| SB-11 | `Other` starts demanding `Box<Gadget>` of `Lib`'s generic `Box<T>`, ahead of `Use`'s `Box<int>` in program order | `Lib`'s lambda names shift (L7) and its instance order changes | `Lib` owns `Box<T>` and a function with a lambda | A: Other. L: Other, Lib (`lowered-for=generic`). Units equal a clean build |
| SB-12 | the root swaps two imports | directive and shared-declaration order changes without any group's source changing except the root's (L1, L3) | two groups each with `#define` lines | L: the groups whose `shared` answer moved; units equal a clean build |
| SB-13 | `var g = make();` in `Lib`; `make()` in `Other` changes its return type; `Use` reads `g` | `Use` keeps `g`'s old type (M7) | | A: Lib, Other, Use (`global-type`). L: as A |
| SB-14 | a realtime callee in `Lib` is renamed; `Use`'s `@realtime` caller is fixed to the new name in the same edit | replayed edges to the vanished target read as safe (G5) | two-step edit sequence | the build equals a clean one |
| SB-15 | a typedef added in `Other` renames a capability that `Use`'s native invocation names | the skipped native-invocation type walk misses it (M15) | | same result as a clean build |
| SB-16 | a field bound in `Lib` stops being constant because a macro in `Other` changes; `Use` calls `Span(array)` on it | `Use` keeps the accepted `Span` (M10) | | same result as a clean build |
| SB-17 | a body-only edit of `Lib.process` that leaves every summary unchanged | over-invalidation: `Use` re-analyzed | the Stage 9 counter fixture | A: Lib. L: Lib. N: 1. Links: 1 |
| SB-18 | the same edit with `Lib`'s journal deleted, then corrupted, then of an old schema | fall-back | three builds | A: Lib only (`live-for=missing`/`corrupt`/`schema`), units equal a clean build |
| SB-19 | more than half the groups edited | `dirty-share` fall-back | | A: all, `fallback=dirty-share` |
| SB-20 | a native header's contract changes (same declarations) | a consulted contract outside the interface digest (Python's `ProgramInterface` drops it) | the CoreAudio or Linux call-shape fixture | the consumers of that native, and the program unit |

Rows SB-21 onward come from the adversarial review (section 9).

## 9. Review

Under the standing design-approval rule: two adversarial reviewers and one
parity reviewer, with no unresolved blocking finding. Their findings and the
resolutions are recorded below.

(Filled in by the review.)

## 10. Open questions, each with its default

| Id | Question | Default in force |
| --- | --- | --- |
| Q1 | Should the plan step re-render interfaces of unchanged groups? | No: cached per group source digest, as today |
| Q2 | The `dirty-share` threshold | half the groups, live after the plan step |
| Q3 | Debug default helpers: position at the callee's default (btrcc) or `<btrc-generated>` (btrcpy)? | `<btrc-generated>` in both, so no `position` query is needed |
| Q4 | Renumber lambda, spawn and GPU-helper names per unit, or key on the ordered instance list? | renumber per unit by first use, like the adapter families; the `generic` answer stays for instance order |
| Q5 | Python `node_types`: journal the entries, or move consumers to re-inference? | journal the entries by position (G3) |

## 11. What only the Mac can measure

Nothing in this document is a measurement. The Linux runs above are
correctness probes only. These need the owner's Mac (MAC-R-04 to MAC-R-06):

- the edit and cold instructions retired with journals, at `--jobs 1`, on
  the BTRSmith copy pinned by CL-R-01;
- the cold-build cost of logging queries and writing journals (records cost
  about 5% today, `separate-compilation.md`, slice 3);
- the peak memory of a replayed build against a live one;
- the native compile and link counts on the product build.
