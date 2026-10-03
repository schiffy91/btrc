# Design: Stage B consulted-fact reuse keys and the skip-unchanged journal

Status: **approved design (CL-R-04)**, under the standing design-approval rule
(section 10). It changes no compiler source. It is written against
`main-kn9jxh` at `6c90ad8`, and every `file:line` below is on that tree.

PLAN.md Stage 6 asks for this spec before Stage 9 implements it
(`perf-stageb-slice4`, `perf-stageb-skip-unchanged`):

- CL-R-18 implements the keys.
- CL-R-19 implements the journal and then **freezes** sections 6 and 7. Any
  later memo cache (Stage 12) extends them.
- CL-R-09 turns every row of section 9 into a test, run through both
  compilers. The defects of section 2.3 go to the fixer that packet names.

The spec depends on none of the experiments in
`docs/design/compile-performance.md` ("Performance changes already measured
and rejected"):

- it shares no managed object widely (the rejected shared empty list);
- it adds no pointer-keyed cache;
- it keys everything by structural position, declaration path or value, never
  by an address.

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

`docs/design/separate-compilation.md` (Stage B: slices 1–3 and the
per-instance closure records) describes what exists.

**Validation records.**
- `ValidationRecords` (`pipeline/ModuleUnits.btrc:2642`) keys each group by
  `context + group + group source digest + program interface digest`
  (`:2713-2722`).
- The interface digest is assembled per group, cached under the group's
  source digest, and sorted by group name (`:2731-2781`).
- It renders every declaration position-free, with non-template callable
  bodies elided to `defined consumed=<indices>` (`ModuleUnitInterfaceSummary`,
  `:20-31`; `syntax/Identity.btrc:217,335,353`).

**Record sections.**
- Four phases per function or class: discover, validate, close and realtime
  (`analyzer/Models.btrc:66-71`).
- They hold 13 fact kinds (`:47-61`), warnings and deferred generated-symbol
  references among them.
- Per-template instance sections (`validation-instances-v2`,
  `ModuleUnits.btrc:2893-2989`).

**Positions and dependencies.**
- `ValidationRecordCodec` (`:2348`) names a node by its 12-hex file tag,
  top-level ordinal, pre-order index and node kind.
- A record that names a node in another group carries `dep <group> <key>`
  lines (`:3004-3019`), checked at load (`:2813-2815`).

**Lowering records.**
- `ModuleUnitRecord` keys each group by
  `module-unit-v5 + context + group + source digest + programDigest()`
  (`:1815-1823`).
- `programDigest` (`:1007-1044`) is the interface digest plus `usesTrycatch`,
  the ordered generic class and method instance lists, and the reached stdlib
  declarations and mentioned names.
- After a key matches, five checks run per group:
  - the consulted setjmp summaries (`:1892-1903`);
  - summary cycles (`:1904-1909`);
  - the entry unit's cyclable-release fact (`:1870`);
  - realtime proofs (`:1912-1923`);
  - kept instance members (`:1926-1936`).

**Counters today.**
- `BtrccPhaseTimer` prints `module-units=lowered:N,reused:M` (`:2058`),
  `relowered-<reason>=N` (`:1269-1290`), `a-records-stored(replayed=R,journaled=J)`
  and `a-instances(replayed=N)` (`pipeline/Pipeline.btrc:192-193`).
- `moduleUnitsLowered` and `moduleUnitsReused` are result fields
  (`pipeline/Models.btrc:98-99`).

Analysis is still entered for every group. Registration, the program-wide
pre-passes and the fixed points run live, and a replayed declaration still
costs a decode. That is what the journal removes.

### 2.2 Reference compiler

The Python compiler has module units with the same Stage A key shape
(`application/modules.py:840-884`). Its facts digest (`:789-826`) also covers
`generic_class_callable_instances` and `realtime_safe_callables`, which
btrcc's does not.

It has **no analysis records**:
- `ProgramInterface` drops `source_file` (`modules.py:43`).
- Analysis keeps one `node_types` table keyed by `id()`
  (`analyzer/program.py:417`). Its values alias other declarations' type nodes
  (`analyzer/calls.py:738,801,856`).

PLAN.md Stage 8 adds the reference slices; slice 4 and the journal land paired
in Stage 9. The only counters are the result fields `module_units_lowered`
and `module_units_reused` (`application/results.py:152-153`). The
`btrcpy timing:` line (`cli/compiler.py:716`) carries no module-unit marks.

Both compilers form the same compilation groups (`frontend/sources.py:71,195`;
`frontend/Models.btrc:267`). The parity reviewer built the M11a fixture in
both: 6 groups each, with identical unit names. Under strict imports, which
module units require (`pipeline/Pipeline.btrc:183,196`), each stdlib module is
an **ordinary group**. Neither compiler inlines the stdlib in strict mode
(`frontend/Resolver.btrc:736`, `frontend/sources.py:1251`). Native
declarations belong to the program unit (`frontend/sources.py:112-113`).

### 2.3 Defects that exist today

The audit and the review found nine defects on `6c90ad8`. Each was
reproduced on Linux, a stand-in that makes no Mac claim, with `btrcpy` and
the test-harness `btrcc`:

- **Stale reuse:** a cold build, one edit, then an incremental build compared
  unit by unit, and diagnostic by diagnostic, with a clean build in a fresh
  cache. The output directory is the same throughout, because debug keys
  include it.
- **Miscompile:** the program was run.

| Id | Edit | btrcpy | btrcc | Cause |
| --- | --- | --- | --- | --- |
| SB-D1 | body of a `@gpu` kernel in group B, dispatched from group A | A reused with the old WGSL | same | every session registers every kernel and builds WGSL from its body (`ir/gpu/Pipeline.btrc:821-839`, `ir/lowering/gpu.py:2053-2057`); the dispatcher embeds it (`ir/Emitter.btrc:187-189,380-390`, `backend/c_emitter.py:1133-1141`); kernel bodies are elided from the interface |
| SB-D2 | body of `Base.__del__` in B, inherited by `Derived` in A | `Derived_destroy` keeps the old body | same | `classMethod(child, "__del__")` returns the nearest ancestor's (`analyzer/Declarations.btrc:108-130`); its body is lowered into the child's hook (`ir/lowering/Declarations.btrc:3531-3546`) |
| SB-D3 | `--debug`: lines inserted above a function or method with a default argument | unaffected (helper at `<btrc-generated>`) | caller keeps the old `#line` | btrcc positions the helper at the callee's default (`ir/lowering/Functions.btrc:486-491`) |
| SB-D4 | `--debug`: lines inserted above `Base`, whose `__del__` `Derived` inherits | `Derived`'s unit keeps `#line 8` where a clean build has `#line 10` | same | SB-D2's copy carries the parent's positions |
| SB-D5 | `fail()` changes from `exit(1)` to `return`; a caller stores a nullable after calling it | (no records) | caller replays without the warning a clean build gives | "never returns" is a body fact (`analyzer/validation/ControlFlow.btrc:1471-1504`) outside the interface summary; warnings are journaled (`analyzer/Models.btrc:479-483`) |
| SB-D6 | the root swaps two imports | relowers all, correct | `lowered:0,reused:3`; all three units differ (directive and prototype order) | the group digest hashes `resolved.userLines`, which hold no import lines (`ModuleUnits.btrc:2680-2696`); groups are sorted (`:2769-2773`) |
| SB-D7 | a body-only edit in `Lib` adds a `(int, bool)` local | `Use` reused with its tuple structs in the old order | same | tuple shapes are ordered by discovery across all bodies (`ir/lowering/Declarations.btrc:3935-4013`; `ir/lowering/translation_unit.py:557-619`) |
| SB-D8 | `Use` swaps its first `Box<int>` and `Box<float>` uses | `Lib` reused with its instances in the old order | correct | the facts digest sorts instances (`modules.py:798-801`); lowering emits them in discovery order |
| SB-D9 | `Other`, which `Use` does not import, adds a global `int count = 9`; `Use` has a local `count` captured by a lambda | prints 5 (correct) | **prints 10**: the capture is dropped and `extern int count` emitted, in a whole-program build too | `captureNames`/`lexicalIdentifier` skip any name in `globalVarTypes` (`ir/lowering/Callables.btrc:167,231`) |

These are compiler defects, not open spec questions. Each needs a paired
fixer commit (or a btrc-internal one for SB-D6 and SB-D9) before CL-R-09's
tests can pass. Each is a row of section 9.

#### 2.3.1 How the defects were fixed

CL-REQ-05 fixed SB-D9. CL-REQ-07 fixed SB-D1 to SB-D8 against today's Stage A
keys, without the logs of section 5. Each case is tested through both
compilers in `src/tests/python/test_module_unit_staleness.py`: a cold build,
one edit, an incremental build, and a clean build in a fresh cache into the
same output directory. Units and diagnostics must be equal, and the test
asserts how many groups relowered.

- **SB-D1 to SB-D4: copied bodies and positions.** The lowering session logs
  each foreign source file whose body or positions it copies into its unit:
  - an inherited `__del__` (SB-D2, SB-D4);
  - each `#line` marker (SB-D3, SB-D4);
  - a `__LINE__` or `__FILE__` in a default argument.

  The worker adds the files of the kernels whose WGSL the finished unit
  embeds (SB-D1). `ModuleUnitRecord` stores each such group with the source
  digest it had. A record whose groups' digests moved is a miss
  (`relowered-consulted-source`).

  This answers the `body` and `subtree` namespaces of 5.2 per group, not per
  declaration. Any edit to the copied-from group relowers the copier, which is
  sound but coarser than a body digest. The relowered sets match SB-01, SB-02,
  SB-03 and SB-27. btrcpy positions its default helpers at
  `<btrc-generated>`, so SB-03 relowers only `Lib` there (Q3).
- **A tenth case, release mode.** A `__LINE__` default is frozen at the
  callee's line, in a release build too. Lines added above `int where(int
  line = __LINE__)` left a caller's unit stale in both compilers. The
  `__LINE__` log above fixes it. Section 5.4's claim that release builds are
  unaffected by foreign positions did not hold for this case.
- **SB-D5.** btrcc journals each "never returns" answer that body validation
  relied on, as a `VALIDATION_DIVERGENCE` fact (`validation-record-v5`).
  Replay asks every answer again before installing anything. A moved answer
  validates the declaration live and voids the record. This is
  `summary.diverges` with early cutoff, logged per declaration.
  - Only an answer that reads a callable's body is journaled. An answer that
    follows from the hosted ABI or the interface alone, such as a call to
    `print`, is already covered by the key.
  - Verify mode treats a stored record whose answers moved as one a replay
    rejects, not as a disagreement.

  btrcpy keeps no analysis records.
- **SB-D6.** btrcc's facts digest covers the program's file order. btrcpy's
  ordered interface digest already did. Every group relowers, as SB-12
  expects.
- **SB-D7 and SB-D8.** Both facts digests cover:
  - the order of the shared declarations each unit draws from (each entry's
    kind and names). Tuple shapes are declared there in body-discovery
    order, and in btrcpy span and atomic shapes too; the review found the
    span case stale when only tuple shapes were covered. btrcc declares
    spans in each unit's own session;
  - in btrcpy, the class and method specializations in discovery order.
    btrcc's instance lists were already ordered.

  A discovery-order change therefore relowers every group.

  **Conflict with G12.** G12 prescribes canonical orders, which would relower
  only the edited group (SB-28, SB-29). They also change clean output, and
  CL-REQ-07 had to keep clean output byte-identical. The canonical orders
  stay CL-R-18 groundwork; the key covers the order until then.

### 2.4 Groundwork slice 4 needs first

Each item is a prerequisite of CL-R-18 and lands paired:

- **G1. Record positions computed after the defaults merge.**
  - btrcc caches a declaration's positions at the discover phase
    (`ModuleUnits.btrc:2455`).
  - `mergeCallableDefaults` later attaches a prototype's default subtrees to
    the definition (`analyzer/validation/Names.btrc:383-393,550`).
  - The pre-order walk visits defaults before the body
    (`syntax/Identity.btrc:31-40`).
  - So a replay build that first resolves the definition after the merge
    shifts every body index, and only the node-kind check guards it.
  - This is suspected, not reproduced. The corpus case that has the shape
    (`src/tests/c_compat/VoidAndUnnamedParameters.btrc:13,28`) records no body
    facts. Row SB-04 reproduces it.
- **G2. Positions by member path.**
  - A position becomes (declaration path, member path, pre-order index within
    the member, node kind).
  - A member path carries an ordinal among same-named members (constructors,
    accessors).
  - Today's whole-declaration index (`ModuleUnits.btrc:2365-2382`) moves when
    an earlier member's body changes.
- **G3. Order-independent reference analysis.** The reference analyzer
  depends on program order where btrcc does not. All three items were
  reproduced with probes on the reference analyzer:
  - a consuming parameter's omitted default is checked against the callee's
    `node_types` (`analyzer/ownership.py:490-497,672`);
  - a `var` global is typed in the body pass
    (`analyzer/statements.py:2112-2164`), where btrcc infers it up front
    (`analyzer/Expressions.btrc:173-188`);
  - `node_types` values alias whichever type object existed first
    (`analyzer/types.py:1952`).

  Defaults and `var` globals move to pre-passes, and Python facts key by
  position and value.
- **G4. One raw-borrow summary.**
  - Python proves raw borrows after every body
    (`analyzer/analyzer.py:143-144`).
  - btrcc proves them at the call (`analyzer/validation/Borrows.btrc:680`),
    under the asking caller's type parameters (`:630-657`, read at `:146`),
    and skips calls in some subexpressions.
  - It becomes one per-callee summary, defined once.
- **G5. Realtime edges check their target.** Replay checks only the caller
  (`analyzer/Realtime.btrc:1216`), and an unknown target counts as safe
  (`:1286`).
- **G6. Callee-scope defaults in btrcc.**
  - Owned-default and realtime-default checks infer the callee's default in
    the caller's scope (`analyzer/validation/Ownership.btrc:978`,
    `analyzer/Realtime.btrc:745`), so a caller local can shadow a name in it.
  - Rich-enum defaults are evaluated per call site (`Ownership.btrc:937`).
  - All three become per-declaration summaries, evaluated in the callee's
    scope.
- **G7. One rendering contract.**
  - Python's interface digest is computed after analysis and omits native
    contracts; btrcc's is computed before analysis and includes them.
  - Byte-identical renderings across compilers are not needed: each
    compiler reads only its own journals, framed by its toolchain
    fingerprint.
  - What is required is that the same edit changes the same answers in both,
    so both render the same fields: interface, native contracts, and defaults
    after the merge.
- **G8. One array-bound pre-pass.**
  - btrcc's pre-pass covers fields, structs, rich-enum payloads, typedefs and
    globals (`analyzer/validation/Validator.btrc:107-132`).
  - Python's also covers parameters, returns, properties and interface
    methods (`analyzer/statements.py:1341-1508`).
  - btrcc widens, so constant-bound verdicts are known before bodies in both.
- **G9. Deferred generated-symbol references in Python.**
  - Python's generated-symbol check re-walks every declaration
    (`analyzer/generated_symbols.py:200-235`), which would enter journaled
    groups.
  - It moves to a deferred list, as btrcc's already is
    (`analyzer/validation/Names.btrc:1054,1071`).
- **G10. One source stage for `releases_cyclable`.**
  - Python takes it from the lowered unit (`application/modules.py:1610`),
    btrcc from the optimized unit (`ModuleUnits.btrc:2296`).
  - They must agree, or the entry group relowers in one compiler only.
- **G11. Python's realtime-safe emptiness check** (`application/pipeline.py:625-629`)
  either goes, as in btrcc, or becomes an `exists` query in both.
- **G12. Canonical orders.** Whatever a unit emits in an order decided
  outside its group is emitted in a canonical order instead:
  - tuple structs (SB-D7);
  - generic instances of an owned template, sorted by instance key (SB-D8);
  - the shared declarations a unit pulls in, which stay in dependency order
    with ties broken by name, not by program order (`ir/optimization/Optimizer.btrc:1301`).

  This removes order from the `shared` and `generic` answers, so a body edit
  elsewhere cannot cut off early only to leave a stale order. Output changes
  once, in a paired commit, with every frozen boundary record re-captured.

- **G13. Member-level instance demand in both compilers** (6.4).

## 3. Pass audit: every pass and the facts it consults

Four read-only auditors listed every lookup each pass makes into another
declaration or group. Each row below names the pass, where it is invoked, and
the facts it consults outside its own declaration. **body** marks a fact that
changes when only its owner's body changes. The last column gives the query
namespace of section 5.2.

### 3.1 btrcc analysis (`SemanticAnalyzer.analyze`, `analyzer/Analyzer.btrc:40-73`)

| Pass (owner, definition) | Invoked | Consults outside the declaration | Namespace |
| --- | --- | --- | --- |
| `stampProgramSources` (`analyzer/HostedAbi.btrc:359`) | `pipeline/Pipeline.btrc:142` | file path to stdlib marker | fixed input |
| `setNativeDeclarations`, `configureUnmodeledIncludes` (`analyzer/Models.btrc:176`, `analyzer/Analyzer.btrc:87`) | `Pipeline.btrc:176-177` | native imports; unmodeled include lines | `native`, `macro` |
| `DeclarationRegistry.registerProgram` (`analyzer/Declarations.btrc:42`) | `Analyzer.btrc:50` | every header; `funcTable` last writer, `interfaceTable` and enum owners first writer, member indexes through ancestors (`:47-131`) | `name` (its ordered answer carries the writer order) |
| `ExpressionTypeResolver.inferGlobals` (`analyzer/Expressions.btrc:173`) | `Analyzer.btrc:52` | callee and constructor signatures an initializer reaches | `global-type` |
| `GenericSpecializer.discover`: argument upgrade, `collectGenericsDecl`, transitive closure, method-generic scan (`analyzer/Generics.btrc:50-73,234,654,711,957`) | `Analyzer.btrc:53` | whole class table (upgrade); template signatures and **template bodies**; callee signatures; global types | `exists`, `name`, `generic` |
| `SourceMacroNamespace` (`analyzer/SourceMacros.btrc:14,129`) | `validation/Validator.btrc:45` | every `#define`/`#undef`, final state | `macro` |
| type, interface, inheritance, enum-constant, aggregate, mutex and struct-layout pre-passes (`validation/Types.btrc:611,974`; `validation/Declarations.btrc:436,477,934`; `validation/Constants.btrc:297`; `validation/Ownership.btrc:470`) | `Validator.btrc:61-75` | parents, interfaces, transitive struct/rich-enum/typedef chains, enum values program-wide, the instance list | `name`, `subtree`, `enum-value`, `generic` |
| names, duplicates, defaults merge, storage, overrides (`validation/Names.btrc:211,477,586,605`; `validation/Storage.btrc:456`) | `Validator.btrc:77-78` | all top-level names; prototype defaults written onto the definition; inherited members | `name` (prototype and definition as one), `subtree` |
| `publishKnownGeneratedSymbols` (`validation/Names.btrc:817`) | `Validator.btrc:80` | every class, enum, interface and instance; visitor need (field types of ancestors); `__del__` **presence** | `name`, `cycle` |
| `validateNativeInvocations` (`validation/Borrows.btrc:96`) | `Validator.btrc:82` | **callee bodies**, transitively (`:33-67`); every typedef a type node names (`:72-94`) | `summary.local-invocation`, `name` |
| callable shapes, class contracts, rich-enum defaults (`validation/Declarations.btrc:309,466,847`) | `Validator.btrc:84-103` | parent chain, merged methods, consumed parameters of requirement and implementation | `name`, `summary.consumed` |
| `NullableFlow.computeNonreturning` (`validation/ControlFlow.btrc:1471`) | `Validator.btrc:105` | **every callable body**; hosted noreturn; `subclassesOf` for dispatch (`:1575-1587`) | `summary.diverges`, `descendants` |
| array-bound pre-pass (`validation/Storage.btrc:827`) | `Validator.btrc:107-132` | enum constants, rich-enum ordinals, macro string lengths | `enum-value`, `macro`, `bound` |
| body validation (`validation/Declarations.btrc:562,717`) | `Validator.btrc:133-228` (V section) | call resolution, signatures and defaults; **callee bodies** for raw-borrow proofs (`validation/Borrows.btrc:483-520,630-658`); callee leading statements (`analyzer/Declarations.btrc:265-292`); callee defaults (`validation/Ownership.btrc:978`); hosted classification; enum ambiguity and the `known` verdict (`validation/Expressions.btrc:940-965`); macro existence (`validation/Calls.btrc:769-806`); constant bounds on foreign nodes (`Calls.btrc:250`); ancestors and interfaces; callee divergence and subclasses (`ControlFlow.btrc:1456,1575`) | `name`, `subtree`, `summary.*`, `enum-value`, `macro`, `exists`, `bound`, `descendants` |
| top-level `var` (`validation/ControlFlow.btrc:647`) | `Validator.btrc:140-144` | other globals' types | `global-type` |
| `closeExpressionGraph`, native callback instances, instance closure (`analyzer/Generics.btrc:168,175,1430,1503`) | `Analyzer.btrc:59` (C and I sections) | validation's side tables; template bodies under substitution; everything their inference reaches; native contracts; stdlib `Bytes`/`Callback*` | `name`, `subtree`, `generic`, `native` |
| `RealtimeAnalyzer.validate` (`analyzer/Realtime.btrc:209`) | `Analyzer.btrc:61-63` (R section; fixed point live) | any `@realtime` root; callee signatures; **callee defaults** (`:713-750`); transitive managed-type facts (`:1108-1151`); native contracts | `name`, `subtree`, `native` |
| `validateCompletedGeneratedSymbols` (`validation/Names.btrc:1071`) | `Analyzer.btrc:64` | final generated symbols; runtime catalog; preprocessor references | `generic`, `name`, `macro` |
| `CycleSemantics` (`analyzer/ownership/Cycles.btrc:58-309`) | from the claims, the end check and lowering | **every subclass** of a type; every instance implementing an interface | `cycle`, `descendants` |

### 3.2 btrcc lowering (`IRLowerer.lower`, `ir/lowering/Lowerer.btrc:127-239`, one session per group)

| Owner / site | Consults outside the group | Namespace |
| --- | --- | --- |
| program facts (`Lowerer.btrc:130-175`; `ir/lowering/Context.btrc:40-54`) | stdlib reachability (all bodies); `#pragma pack` state in program order (`Declarations.btrc:105-141`); `usesTrycatch` (any body) | `program` |
| `GpuPipeline.registerKernels` (`ir/gpu/Pipeline.btrc:821`) | every kernel's **body** | `body` |
| owned generic instances (`Lowerer.btrc:190-224`; `ir/lowering/Functions.btrc:183-316`) | demanded instances; type arguments' layout, ARC and cyclability; the receiver class of an inherited generic method | `generic`, `cycle`, `name` |
| `emitEnums`, `emitDeclarations` (`ir/lowering/Declarations.btrc:2508-2588`) | every group's directives in program order; every C native import; `globalHasDefinition` (`:2496,2553-2556`) | `program`, `native`, `name` |
| class lowering (`Declarations.btrc:3192-3837`) | ancestor fields, initializers and methods; interface tables; visitor need; **inherited `__del__` body** (`:3531-3546`); `runtimeTypeMayCycle` (`:3696,3710`) | `name`, `subtree`, `body`, `cycle` |
| calls (`ir/lowering/Calls.btrc:163-169,298-355,393,424,549-559,747-879`) | callee signatures and body presence; native contracts; `print`/`Mutex` only if nothing else has the name; **callee default expressions**, lowered into the caller | `name`, `exists`, `native`, `subtree` |
| callables (`ir/lowering/Callables.btrc:167-231,824,847-857`) | `lexicalBindingConflictsType`, i.e. any type or generic parameter name (`analyzer/Models.btrc:529-571`). Globals named like a local (SB-D9) are a defect to fix, not a query | `exists` |
| functions (`ir/lowering/Functions.btrc:375-386,453-517`) | every global's type; default helpers positioned at the callee's default | `global-type`, `body` (debug) |
| ownership (`ir/lowering/ownership/*`) | cyclability by subclass (`Lifetime.btrc:302,376-378,480`); consumed parameters (`Calls.btrc:342`); enum-value ownership count (`Operands.btrc:178`); global definitions (`ManagedTypes.btrc:314`) | `cycle`, `summary.consumed`, `enum-value`, `name` |
| `ModuleUnitDeclarations.mergeInto` (`pipeline/ModuleUnits.btrc:618-707`), planner (`ir/optimization/Optimizer.btrc:1295-1318`) | shared declarations by name closure plus every macro replacement (`:656`); tuple shapes | `shared` |
| setjmp solve, realtime composition, instance demand (`ModuleUnits.btrc:917-964,1444-1752`) | other units' effect summaries, proofs and reference graphs | today's post-plan checks |
| the group's own analysis output: `constantArrayBoundKeys`, `realtimeBoundedLoopKeys`, `arrayIterationCapacityKeys`, `hostedCallKeys`, `genericConstructorTypes` (`ir/lowering/Statements.btrc:414,1435,1500`; `Expressions.btrc:2608`; `Aggregates.btrc:162`) | — | `journal` (fixed lowering input, 5.1) |

### 3.3 Python analysis (`SemanticAnalyzer.analyze`, `analyzer/analyzer.py:124-207`)

| Pass (owner, definition) | Invoked | Consults outside the declaration | btrcc counterpart / parity |
| --- | --- | --- | --- |
| `AnalysisSession.begin`, `OwnershipAnalyzer.begin` (`program.py:440`, `ownership.py:266`) | `analyzer.py:127-128` | — | `Analyzed()` |
| `DeclarationRegistry.register` (`declarations.py:1218-1260`) | `:129` | every header; prefers the bodied definition (`:394-396`); **merges prototype default nodes** (`:1027-1030`) | the merge runs later in btrcc (`Names.btrc:550`) |
| `configure_unmodeled_includes` (`generated_symbols.py:92`) | `:130` | directives | same |
| `TypeSystem.normalize_declarations` (`types.py:1956-2007`) | `:131` | whether any class or interface has a name (`:1940`) | no pointer auto-upgrade in btrcc |
| `validate_declarations` (`statements.py:1341-1394`) | `:132` | every declaration array bound | G8 |
| interface parents, hierarchy (`declarations.py:494-693,1284-1316`) | `:133-134` | parents, interfaces, parent methods' leading statements | same |
| `compute_cyclable_flags` (`ownership.py:507-541`) | `:135` | every class's storage | btrcc computes on demand |
| aggregates (`aggregates.py:381-479`) | `:136` | aggregate and typedef cycles | same |
| `compute_nonreturning_callables` (`flow.py:77-116`) | `:137` | **every callable body** | same |
| rich-enum defaults (`statements.py:1830-1883`) | `:138-140` | variant defaults, once per enum | G6 |
| body pass `analyze_declaration` (`statements.py:1540-2164`), with `ExpressionAnalyzer`, `CallAnalyzer`, `GenericAnalyzer` demand, `GpuAnalyzer` and `SourceMacroAnalyzer` | `:141-142` | as btrcc's body validation, plus `node_types` values aliasing callee, field, global and interface types (`calls.py:738,801,856`; `expressions.py:1453,1485`); lambda captures (`statements.py:962`) | demand inline, not in three phases |
| `settle_raw_borrow_obligations` (`ownership.py:1514-1521`) | `:144,151` | **callee bodies and callee `node_types`**, transitively | G4 |
| native callback instances (`generics.py:68-157`) | `:145` | native contracts; stdlib callback classes | same |
| `close_generic_instance_graph` (`generics.py:159-192,340-573`) | `:146` | template bodies and their `node_types` | same |
| `validate_native_invocations` (`ownership.py:548-669`) | `:147` | every tree after `var` inference; callee bodies | btrcc runs it before bodies |
| `RealtimeAnalyzer.analyze` (`realtime.py:118-133,425,829`) | `:148` | as btrcc; callee defaults in the callee's scope | G6 |
| `validate_generic_type_facts` (`ownership.py:543-546`) | `:149` | resolved specializations | `validateConcreteMutexInstances` |
| `validate_program_symbols` (`generated_symbols.py:200-235,494-520`) | `:150` | claims; final instances; a re-walk of every declaration | G9 |

### 3.4 Python lowering and module units (`application/modules.py`, `ir/lowering/*.py`)

| Owner / site | Consults outside the group | btrcc counterpart |
| --- | --- | --- |
| `TranslationUnitLowerer` program facts (`ir/lowering/translation_unit.py:147-164,701-737`) | generic instance tables, stdlib reachability, try/catch use | `Lowerer.btrc:130-175` |
| tuple shapes (`translation_unit.py:557-619`) | discovery order across bodies | SB-D7, G12 |
| GPU kernels (`ir/lowering/gpu.py:2053-2057`; `backend/c_emitter.py:1133-1141`) | every kernel's body | SB-D1 |
| classes and ownership (`ir/lowering/classes.py`; `ownership.py:353-661,875,2192`) | layouts, parents, interface tables, `__del__` of ancestors, cycle closure over the class table | SB-D2 |
| calls (`ir/lowering/calls.py:2301-2303`; `functions.py:4050-4063`) | callee defaults (helper at `<btrc-generated>`); consumed parameters | SB-D3 |
| realtime-safe set (`application/pipeline.py:625-629`) | only whether it is empty | G11 |
| `ModuleUnitRecord` checks (`application/modules.py:74-218`) | setjmp consulted effects, summary cycles, `effects_solved`, entry release, realtime roots and proofs | the same checks, minus kept instances |

Session counters (lambdas, temporaries, spawn ids, default helpers and
cleanup adapters) are per session in both compilers. Temporaries and adapters
are renumbered per unit (`ir/optimization/Optimizer.btrc:127-128,940-1146`).
Lambda, spawn and GPU helper names are not. They would depend on other
groups' demand only if a lambda could sit in a generic member, and both
compilers reject that today (reviewer B, reproduced). Q4 records this.

## 4. Terms

- **Group.** A compilation group (`separate-compilation.md`, "Compilation
  groups"), including each stdlib module. The program unit and the runtime
  unit are lowered every build and are not counted as groups.
- **Declaration path.** (file identity, name path, ordinal among same-named
  declarations in that file). It never holds a line number or combined line.
  btrcc's `declaration.line` counts every earlier file
  (`pipeline/ModuleUnits.btrc:2700-2705`), so it moves whenever an unrelated
  file grows.
- **Position.** (declaration path, member path, pre-order index within the
  member, node kind), as defined in G2.
- **Interface digest of a declaration**, `I(d)`: its interface rendering (G7)
  with defaults after the merge. It holds no summary and no body.
- **Summary** of a declaration: one of `consumed` (parameter indices),
  `diverges`, `raw-borrow` (per parameter), `local-invocation`,
  `owned-default` (per parameter), `rich-enum-default`, and, for lowering
  only, its setjmp effect. Summaries are compared by value, so a body edit
  that leaves them unchanged stops there (early cutoff).
- **Subtree digest** of a member: the position-free rendering of the member's
  subtree, such as a default expression, a field initializer or a typedef
  target. In debug mode the digest includes positions.
- **Body digest** of a declaration: its body's rendering. In debug mode it
  includes positions.
- **Query.** A question a pass asks outside its group, together with its
  **answer**. The ordered, de-duplicated list of a group's queries is its
  **consulted-fact log**. Each group has one log for analysis and one for
  lowering.

## 5. The per-group keys

Each group has an analysis key and a lowering key. Each is a hash of fixed
inputs plus a consulted-fact log. The log is stored beside the key's record;
the key check re-asks every logged query against the current build and
compares the answers.

### 5.1 Fixed inputs

| Input | Analysis key | Lowering key |
| --- | --- | --- |
| schema (`stage-b-v1`) and compiler identity (the artifact cache's toolchain fingerprint) | yes | yes |
| options: target, strict imports, include stdlib (`ModuleUnits.btrc:2713`) | yes | yes |
| the group's own source digest: resolved lines with their file and line (`:2680-2696`), **plus its ordered import and include list** (SB-D6) | yes | yes |
| lowering context: debug, DCE, target, and in debug mode the units prefix and output path (`:1817`) | no | yes |
| the digest of the group's own journal fact sections (6.1, items 5–6, without warnings), as installed by live analysis or replay | no | yes |

Debug and DCE stay out of the analysis key, as in today's records (`:2713`),
so alternating debug and release builds do not void each other's journals.

**No other group's positions are a fixed input.** Where another group's
position reaches a group's output, it does so through a debug-mode `subtree`
or `body` answer in the **lowering** log (5.2). Analysis answers are
position-free in every mode.

The native identity (`ModuleUnits.btrc:2741`) is **not** a per-group input.
It hashes the reader's parsed contracts, so a contract change would void every
group. It stays the key of the native-declaration cache. Groups consult
natives through the `native` namespace, which also answers the program's
header list.

### 5.2 Query namespaces

Every lookup in section 3 that leaves the group is logged in one of these
namespaces. An answer is a digest, and `ABSENT` is an answer, so negative
lookups are logged too.

| Namespace | Log | Query | Answer | Covers |
| --- | --- | --- | --- | --- |
| `name` | both | (kind, name) for kind in function, global, class, generic class, interface, struct, typedef, enum, rich enum, member-of-`C` (through ancestors) | the ordered list of every declaration with that name and kind, as (declaration path, `I(d)`); or `ABSENT` | callee and type resolution; last- and first-writer tables; prototype and definition as one unit; inherited members |
| `subtree` | both | a foreign member subtree the group walks or encodes a position into: a callee's default, a field initializer, a typedef target, a struct field list | subtree digest: position-free in the analysis log; with positions in the lowering log of a debug build | defaults closure (including debug default helpers, SB-D3); facts placed on prototype-owned nodes (review A1); transitive type facts |
| `summary.<kind>` | analysis (`setjmp`: today's lowering check) | (declaration path, parameter) | the summary value | callee body facts, with early cutoff |
| `enum-value` | both | a bare value name | (owner path or `AMBIGUOUS`, owner count) | enum ambiguity |
| `macro` | both | a macro name, including each name its expansion reaches | (declared anywhere, final active definition text) | macro existence, values and string lengths |
| `exists` | both | any method named `m`; any type or generic parameter named `x`; `print`/`Mutex` shadowed | yes/no | existential lookups over program-wide tables |
| `descendants` | both | a class or interface | the ordered set of (declaration path, `I(d)`) of every subclass or implementing instance | dispatch divergence; cycle facts |
| `cycle` | both | a runtime type | (may cycle, needs visitor) | cyclability set by subclasses anywhere |
| `global-type` | both | a global name | its inferred type, rendered | `var` globals |
| `bound` | both | a foreign array-bound node | constant or not, and its value | foreign constant bounds |
| `generic` | lowering, and analysis for the closure's instance sections | for a template the group owns: the set of demanded instances (canonical order, G12), each with its type arguments' and receiver class's `I(d)` | that set | instances lowered in the template's group; inherited generic methods |
| `program` | both | try/catch use; stdlib reachability of the names the group mentions; `#pragma pack` state at the group's first declaration; the program's directive list | values | program-wide facts |
| `native` | both | a native declaration or contract the group consulted; the program's native header list | contract digest; the list | contracts outside the interface |
| `body` | lowering only | a foreign declaration whose body text the unit copies: a `@gpu` kernel the unit dispatches, an inherited `__del__` | body digest, with positions in a debug build | SB-D1, SB-D2, SB-D4 |
| `shared` | lowering only | the unit's shared-declaration roots | the shared entries the unit pulls in, as (name, rendered digest), in canonical order (G12) | shared declarations |

Two consequences shape the rows of section 9:

- **Analysis answers carry interfaces, not bodies.** A body-only edit of a
  kernel or a `__del__` moves only a lowering `body` answer, so the
  dispatcher is lowered but not analyzed (SB-01, SB-02).
- **Every macro replacement is a root of every unit** (`ModuleUnits.btrc:656`),
  so adding or changing a `#define` anywhere moves every unit's `shared`
  answer and relowers every group. That is today's behavior too, and the
  counters report it (`lowered-for=answer.shared`).
- **Order needs no namespace of its own.** A `name` answer lists every
  same-named declaration in program order, which carries all the first- and
  last-writer order analysis reads. The order lowering reads is the directive
  list, a `program` answer. A whole-program "group order" answer would make
  every group live whenever any import moves.
- **Queries are logged against the group of the declaration they are asked
  for**, whichever pass asks. The claims pass asking `cycle(Node)` for `Node`
  logs it in `Node`'s group (SB-08).
- **A merged default stays foreign.** The defaults merge (`Names.btrc:383-393`;
  `declarations.py:1027-1030`) marks each merged default with the prototype's
  declaration path. Any walk of it through the definition then logs a
  `subtree` query, with or without a fact recorded on it.

Queries are logged at the lookup site through one owner per compiler: the
analysis tables (`Analyzed` in `analyzer/Models.btrc`, `AnalysisSession` in
`analyzer/program.py`) and the lowering context (`ir/lowering/Context.btrc`,
`ir/lowering/session.py`). These tables become private to their owners, and a
structural test (CL-R-18) forbids reading them, or a foreign declaration's
subtree, except through the logging accessors. Every stale reuse found so far
read foreign AST directly (`dtor.bodyNode`, kernel bodies, default nodes), so
this test is what guards against a bypassing lookup. The verify mode (6.6)
cannot see one: a lookup missing from the live log is missing from the stored
log too.

The stdlib groups are no exception. They consult user facts: enum counts,
`lexicalBindingConflictsType` for their own locals (`src/stdlib/Vector.btrc:246`
has a local `end`), and instance scans of user type arguments. So they keep
logs like every other group (SB-22).

### 5.3 Key checks and when each runs

Answers become known at different times, so a key is checked in steps. A
group that fails a step is **live**: it is analyzed, or lowered, exactly as in
a clean build.

1. **Plan, after registration.**
   - Registration, the defaults merge, the generic-argument upgrade, global
     inference and the interface rendering run live for every group. They are
     cheap, and the rendering is already cached per group source digest
     (`ModuleUnits.btrc:2731-2781`).
   - The answers to `name`, `subtree`, `enum-value`, `macro`, `exists`,
     `global-type`, `bound` (after G8), `native`, and `program` (except
     reachability) are all known here, and are checked here.
   - `descendants` and `cycle` include instances, so they are checked after
     the generic sweeps instead (step 2b). Whatever phase asks, the logged
     answer is computed on the **final** instance list, after the close
     sweep, in both compilers. btrcc's claims pass sees a partial list today
     (`validation/Names.btrc:817`) and Python's the final one
     (`analyzer/analyzer.py:150`); a phase-dependent answer would make a group
     late in one compiler only (SB-37).
   - When several journals of a group share the fixed inputs (6.1), they are
     tried newest first, and the first whose answers all match is taken.
   - The live set `L0` is: the changed groups, groups without a valid journal,
     and groups with a plan-time answer that differs.
2. **Pre-pass summaries.**
   - `diverges` and `local-invocation` are solved before any body, in btrcc
     (`Validator.btrc:82,105`) and in Python after G3.
   - They are settled with an in-pass worklist. Live groups' declarations are
     recomputed, and journaled groups' exported values are held fixed.
   - A journaled group whose logged answer moves joins the live set before
     the body pass starts. So a chain of divergence edits never needs a
     restart.
   - A summary cycle that joins a journaled group to a live group makes the
     journaled group live, as the setjmp solve does (`separate-compilation.md`,
     "Stage A as implemented", step 4).
   - `consumed` and `owned-default` can move here once G3 and G6 make them
     pre-pass facts. Both compilers must make the move together, because the
     step decides whether a change restarts.
   - **2b.** After the generic sweeps (discover and close), `descendants` and
     `cycle` are checked as in step 1. A group whose answer moves joins the
     live set as a late invalidation (step 3).
3. **Body-pass summaries.**
   - `raw-borrow`, `consumed` and `owned-default` are published as live
     declarations finish.
   - A journaled group whose logged answer then differs is **invalidated
     late**.
   - Analysis restarts with `L1 = L0 ∪ invalidated`, from a fresh analysis
     state and a freshly parsed AST, so no installed fact, warning or AST
     patch survives.
   - Live sets only grow, so restarts terminate. A restart is allowed only
     after a whole round has published its summaries. After **two** restarts
     the build falls back to full analysis (6.5).
4. **Lowering.**
   - The lowering key adds the `generic`, `shared`, `body` and remaining
     `program` answers. These exist once the declarations session and the
     instance lists exist.
   - Today's five post-plan checks stay.
   - A group analyzed live is lowered unless its lowering key still matches.
     That happens when analysis reproduces the same journal facts and every
     answer is unchanged (early cutoff at the unit).

**Errors.** Today a record exists only for a build that passed, and btrcc
stops at its first error (`TypeValidator.fail`). A build that replayed any
group and then meets an error **reruns analysis fully live** before reporting
(`fallback=error`). The diagnostics, their order and Python's accumulated set
then equal a clean build's, whatever was replayed.

### 5.4 Source locations of unrelated modules

- No key and no record holds a line, column or combined line of a declaration
  outside its group. Records name nodes by position (section 4).
- Replayed diagnostics and witnesses take their line and column from the node
  the position resolves to in the current build, as realtime events already do
  (`separate-compilation.md`, slice 3). A line shift in another group
  therefore changes no key, and the locations reported are still right.
- Foreign positions reach a unit only through copied foreign subtrees:
  default helpers (SB-D3), inherited `__del__` bodies (SB-D4) and kernel
  bodies. In debug mode the lowering log's `subtree` and `body` answers
  include positions, so a line shift above such a subtree relowers exactly the
  units that copy it, without re-analyzing them. Release builds are
  unaffected.

## 6. The skip-unchanged journal

### 6.1 What a journal records

The journal is one per group and per analysis key. It is written by the
owner process only, after a build that passed (6.5 covers errors). It is
stored in the artifact cache like today's records: checksummed and framed by
the toolchain fingerprint (`separate-compilation.md`, "Stage A in the
self-hosted compiler").

The store key is the analysis key's fixed inputs (5.1). Several journals per
group may coexist, content-addressed, so two programs that share a group do
not evict each other. At most four are kept per group; the oldest is evicted
first. The lowering log lives in `ModuleUnitRecord`, not in the journal, and
each record names the digest of the journal's **fact sections** (items 5–6,
the same digest as the lowering key's input, 5.1) that it was lowered
against. A change confined to the journal's log therefore keeps the record.
A record whose fact digest matches no installed journal is a miss for that
group only.

Schema `stage-b-journal-v1` has these sections, in order:

1. **Header.** Schema, compiler identity, fixed analysis inputs, and a digest
   of the rest.
2. **Exports.** For each declaration of the group, in program order: its
   declaration path, `I(d)`, each summary value, and the subtree digests of
   its members. Other groups' queries are answered from here when this group
   is not live.
3. **Program-fact contributions.**
   - whether the group's bodies use try/catch;
   - the stdlib names it mentions;
   - its realtime roots;
   - whether it releases cyclable values (one source stage, G10);
   - the tuple shapes it discovered;
   - its directives.

   Program facts are recomputed from live groups plus these, so no journaled
   group's bodies are scanned.
4. **Analysis log** (5.2).
5. **Per declaration, in program order**, every fact a pass writes:
   - the pre-pass phases the audit found unjournaled: array-bound keys the
     bound pre-pass writes for the group's fields, typedefs and globals
     (`Validator.btrc:107-131`, `Storage.btrc:836`), and the top-level `var`
     phase (`Validator.btrc:140-144`) with its `globals` contribution;
   - generic demand events **per sweep** (`collectGenericsDecl`, the first
     closure, the method-generic scan, the second closure, the close scan),
     recorded before de-duplication and replayed in their own sweep, never
     merged into one list (review A5);
   - discover, validate, close and realtime facts (all 13 kinds);
   - warnings, with their site positions;
   - deferred generated-symbol references, each with its recorded `known`
     bit. The bit's global inputs (the `name`, `macro`, `enum-value` and
     `native` lookups behind it, `validation/Expressions.btrc:964`) are in
     the log, so a removal elsewhere invalidates the group. The local-scope
     part needs no query;
   - for Python only, `node_types` entries as (position, rendered type) and
     the AST patches the body pass makes (G3).

   Every `record*` call runs under a journal (CL-R-18 asserts it), so no
   fact can be written outside one.
6. **Instance sections.** Today's per-instance closure journals
   (`validation-instances-v2`). Their dependencies come from their own query
   log instead of `@` positions (the auditors' M11), so each instance is
   invalidated by what it read.

A realtime section is either **absent** (the scan never ran, because no
`@realtime` root existed: `analyzer/Realtime.btrc:210-228,278-280`) or
present and possibly empty. The two are distinct. When a root first appears,
a journaled group without a realtime section is scanned live for realtime
only. Its other facts replay, but it counts as **analyzed**, with
`live-for=realtime`, and also in `realtime-scans`, so
`analyzed + replayed = groups` still holds. The gate itself is
not logged per group: logging it would make every group live as soon as the
first root appears anywhere.

### 6.2 What replay reproduces

Each fact is installed at the place its pass runs:
- pre-pass facts (array-bound keys) at the pre-pass, before any live body reads
  them;
- demand in its own sweep;
- body facts at the declaration's place in program order.

At that place, the analyzer:

- resolves each position and installs the facts into the same side tables a
  live pass writes, so later live groups and lowering read them unchanged;
- re-runs only each demand event's de-duplication check and push, so the
  instance lists and the last-writer call arguments come out as a live scan
  leaves them;
- reports the warnings at their current positions;
- queues the deferred references for the end-of-analysis check;
- extends the `globals` map;
- publishes the declaration's exports as its summaries.

A journaled group is **not entered by any body pass**. That covers:

- the generic collection and closure scans of its declarations;
- the native-invocation walk;
- the nonreturning fixed point's body scan;
- raw-borrow proofs;
- the array-bound pre-pass for its own nodes;
- the realtime scan.

Each takes the journaled result instead. This is the difference from today's
replay, which still runs most of these over every group.

The program-wide fixed points stay live, over journaled values (5.3). So do
the claims pass and the end-of-analysis symbol check, which run over the
recorded claims and references and walk no journaled body (G9).

### 6.3 Lowering

A group whose lowering key matches is not lowered. Its unit text, reference
graph, exported setjmp summaries and realtime proofs come from its
`ModuleUnitRecord`, as today.

A live group is lowered in a fresh session over the analyzed program. That
program's side tables are complete, because journaled groups were replayed.

Forked workers (Stage C) log their lowering queries in their own
`LoweringContext`. They return the log in the `lower` and `finish` replies,
and only the owner writes records. Program facts are filled lazily in
whichever session asks first (`ir/lowering/session.py:36-52`,
`ir/lowering/Context.btrc:40-54`), so a query is logged at every lookup, not
only where a fact is computed. The logs are then byte-identical for every
`--jobs` count and for an inline pool.

### 6.4 Shared specialization and registration changes

A group may be lowered even though its source did not change: an instance
newly demanded in its template, a moved `descendants` or `cycle` answer, or
the entry unit gaining `__btrc_flush_cycles`. Such a group is counted under a
closed set of reasons, so a fixture's "exactly one group" check can tell it
apart (PLAN.md Stage 9: "counted and explained").

`lowered-for` reasons, in **precedence order**. A group that qualifies for
several is counted once, under the first that applies, so the counts sum to
`lowered` in both compilers:

| # | Reason | Meaning |
| --- | --- | --- |
| 1 | `source` | own source changed |
| 2 | `missing` | no record, or no record matching the journal fact digest |
| 3 | `analysis` | analyzed live and the journal facts moved |
| 4 | `answer.<namespace>` | a lowering answer moved; with several, the first namespace in 5.2's table order |
| 5 | `kept-instances` | the instance members other units reference moved |
| 6 | `consulted-summary` | today's consulted setjmp summary check |
| 7 | `summary-cycle` | a summary cycle joins a lowered group |
| 8 | `entry` | the entry unit's cyclable-release fact |
| 9 | `realtime` | a proof needs an unproven function |

These cover today's `relowered-<reason>` marks (`ModuleUnits.btrc:1874-1934`).

**G13, member-level instance demand.**
- btrcc lowers every member of a demanded instance and keeps the members other
  units reference (`ModuleUnits.btrc:917-964,1925-1937`).
- Python emits demanded instance views without that cross-unit pass
  (`ir/lowering/translation_unit.py:147-151`; `application/modules.py:1648-1656`).
- So a new call to an existing instance's method relowers the template group
  in btrcc only.
- The paired rule: both compilers compute the referenced member set from the
  units' reference graphs and apply `kept-instances` alike. This is CL-R-18
  groundwork, and SB-35 tests it.

### 6.5 Fall-back

Any of these makes the **whole build** analyze live, as without journals, and
names its reason in the counters:

| Reason | Trigger |
| --- | --- |
| `no-store` | module units without a cache, or without strict imports (`pipeline/Pipeline.btrc:183`) |
| `verify` | the verify mode is on (6.6) |
| `dirty-share` | more than half of the groups are live after the plan step (Q2) |
| `restarts` | a third restart would be needed (5.3) |
| `native-unknown` | the program has native bindings, and the compiler has no cache identity for them. btrcc derives its identity from the header reader (`frontend/NativeImports.btrc:3182,3214-3216`) and today **fails the compile** when bindings exist without a reader (`frontend/Packages.btrc:2012`). That stays, so this reason fires only in btrcpy, whose identity is its own (`frontend/sources.py:1275`). The fixtures run with the reader set, where neither compiler falls back |
| `artifact-hit` | the whole-artifact cache served the build; nothing is grouped, so the line prints `groups=0` and zero counts |
| `error` | an error was met in a build that replayed anything (5.3) |
| `position` | a recorded position fails to resolve, or resolves to another kind. With the keys sound, this means a key defect, so nothing is half-installed |

Any of these makes **one group** live and does not stop the others from
replaying. They are listed in **precedence order**: a group is counted under
the first that applies, so the `live-for` counts sum to `analyzed`.

| # | Reason | Trigger |
| --- | --- | --- |
| 1 | `source` | the group's own source digest changed |
| 2 | `corrupt` | a checksum, framing or decode failure |
| 3 | `schema` | a different schema or compiler identity |
| 4 | `missing` | no journal, or a void one |
| 5 | `answer.<namespace>` | a logged answer differs; with several, the first namespace in 5.2's table order |
| 6 | `prepass` | a pre-pass summary moved (5.3, step 2) |
| 7 | `late` | invalidated after the generic sweeps or by a body-pass summary (5.3, steps 2b and 3) |
| 8 | `unrecordable` | a fact with no encoding (today: a type with an array size) |
| 9 | `realtime` | realtime scan only (6.1) |

Today's replay is not all-or-nothing. When a raw-borrow re-proof fails,
`replay` (`Validator.btrc:193-228`) undoes only the deferred references, and
leaves the warnings, side-table writes and demand events already installed.
The journal replaces this with the late-invalidation restart (5.3), which
starts from a fresh state. A void journal is rewritten by the next build that
passes.

Concurrent or interrupted builds share the cache safely:
- journals and records are content-addressed and written atomically, as
  today's records are;
- a record names the journal it was built against;
- a pair from two different builds is a miss, never a mixed reuse.

### 6.6 Verify mode

`BTRC_VERIFY_VALIDATION_RECORDS` keeps its name and widens. It analyzes and
lowers every group live, and then requires:

- every stored journal section to equal the live one, and to round-trip
  through decode and encode;
- every logged answer to equal the live answer;
- every reused unit to equal the live unit, and the diagnostics to be equal.

It never takes a stored result. Verify mode analyzes everything live, so the
check that a journaled group is **not entered** runs in the harness's normal
incremental builds instead: they count body-pass entries per group and
require zero for every replayed group.

Verify mode on unedited sources compares a unit with itself, so it cannot
find a bypassing lookup. The structural test (5.2) does that. Under it, the
edit-sequence harness (CL-R-09) runs verify mode **after every edit**, plus
per-group differential mutations:
- an edit to each group that preserves `I(d)` and every summary;
- one edit per namespace that moves exactly one answer.

Each compares units, diagnostics and exit status against a clean build.

## 7. Counters

Both compilers expose the same counters, under the same names, in two places:

- **A stderr line under `BTRC_TIMING`**, printed by the owner process only:
  after the timing line and the worker lines, and before Python's profile
  block (`pipeline/Pipeline.btrc:214`, `cli/compiler.py:708-718`).

  ```text
  <compiler> stage-b: groups=N analyzed=A replayed=R lowered=L reused=U restarts=K
    fallback=<reason|none> live-for=<reason>:n,... lowered-for=<reason>:n,...
    instance-scans=live:x,replayed:y realtime-scans=n
  ```

  The line is printed as one line; it is wrapped here only for width.
  `<compiler>` is `btrcc` or `btrcpy`. An empty list is written `none`.
- **Result fields**, with the same names and the group names in each
  category: `stageB` on `BtrccCompilationResult` (a counter class beside
  `pipeline/Models.btrc:98-99`), and `stage_b` on the compile result
  (`application/results.py`).

Definitions:

- **groups**: `CompilationGroups.names()`. Stdlib modules are included; the
  program and runtime units are not.
- **analyzed**: a group any of whose declarations entered a body pass live.
  The normative per-compiler list of body passes is section 3's rows for the
  body phases, the generic collection, the native-invocation walk, the
  nonreturning body scan, raw-borrow proofs, the rich-enum default pass
  (`validation/Declarations.btrc:847`; `statements.py:1830`), the array-bound
  pre-pass on the group's own nodes, and the realtime scan.
  - **Not** analysis: registration, the defaults merge, the generic-argument
    upgrade, global inference, normalization, cyclable flags, the interface
    rendering, the claims pass and the end-of-analysis check (G9). Their
    queries still go into the log of the group they are asked for (5.2), so a
    moved answer makes that group live.
  - Instance scans of a journaled template group count only in
    `instance-scans` and do not make the group analyzed. Program-wide fixed
    points count against no group.
- **replayed**: a group with its journal installed in full.
  `analyzed + replayed = groups` always. Each group has exactly one
  `live-for` reason, so the `live-for` counts sum to `analyzed`.
- **lowered** and **reused**: as `module-units=lowered:N,reused:M` today
  (`ModuleUnits.btrc:2058`). The `lowered-for` counts sum to `lowered`.
- **instance-scans**: one per distinct class or method instance key scanned,
  whether live or replayed. Python's closure has no sections today
  (`analyzer/generics.py:535-573`); CL-R-18 gives it per-instance logs with
  the same keys. If Python cannot, this counter is excluded from parity checks
  (Q6).
- **Fall-back.** Under `fallback=<reason>`, `replayed=0`, and every group's
  `live-for` is that reason.
- **Whole-artifact hit.** A build that hits the whole-artifact cache prints
  `fallback=artifact-hit`, `groups=0` and zero counts (6.5). Tests that need
  counters bypass that cache.

**Native compiles and links** are not compiler counters. The native plan
reports them for either compiler's link plan, independent of the compiler
that wrote it: `compiled_units`, `reused_units` and `links`
(`tools/native_plan.py:561-604`, `NativeBuildReport.as_dict`).

The existing `module-units=` and `a-records-stored(...)` marks stay until the
tests that read them (`src/tests/python/test_module_units.py:302-316,367,377`)
move to the new line.

## 8. Expected rebuild sets: the oracle

A row's expected native compiles are **not** "the units whose bytes changed".
That would be circular for an incremental build. They are the units whose
bytes differ between a **clean build before** the edit and a **clean build
after** it. That set:

- includes the primary `p.c`, the runtime unit and native adapter units
  (`pipeline/Pipeline.btrc:205-209`) whenever their bytes change;
- is identical in both compilers' link plans only in its group part, not in
  byte counts.

A row passes when the incremental build:
- analyzes and lowers exactly its A and L sets (with the `lowered-for`
  reasons given);
- equals the after-clean build unit for unit and diagnostic for diagnostic;
- compiles exactly the oracle's units natively and links once.

## 9. Invalidation rows (Stage 7, CL-R-09)

Unless a row says otherwise, the fixture has three groups: `Lib`, `Use`
importing `Lib`, and `Main` importing `Use`. It is built cold, edited once,
and built again with the same cache and output directory. A = analyzed,
L = lowered, N = the oracle's native compiles (8). **Reproduced** means
reproduced today on Linux with both compilers; the scratch probes become
`src/tests/python/m11_edit_sequence.py`.

| Id | Edit | Unsound reuse it guards against | Fixture sketch | Expected |
| --- | --- | --- | --- | --- |
| SB-01 | body of `@gpu twice` in `Kernel`; `Use` dispatches it | old WGSL in `Use` (SB-D1, **reproduced**, both) | `Kernel`: `@gpu float[] twice(float[] a)`; `Use`: `values = twice(values)`; `* 2.0` → `* 3.0` | A: Kernel. L: Kernel, Use (`answer.body`). N: Kernel, Use. 1 link |
| SB-02 | body of `Base.__del__`; `Derived extends Base` in `Derived` | old destroy hook (SB-D2, **reproduced**, both) | `freed + 1` → `freed + 2` | A: Base. L: Base, Derived (`answer.body`). N: Base, Derived. 1 link |
| SB-03 | `--debug`: lines above `int scale(int x, int factor = 3 + 4)` and above a method with a default | stale helper `#line` (SB-D3, **reproduced**, btrcc) | same output directory every build | A: Lib. L: Lib, Use (`answer.subtree`). N: Lib, Use |
| SB-04 | prototype `int f(int a, int b = 1);` in `Lib`, definition with a body fact in `Impl`; edit a later statement of `f` | a replayed position shifted by the merged default (G1) | then build under verify mode | A: Impl. L: Impl. Verify passes |
| SB-05 | `fail()` changes from `exit(1)` to `return`; `Use` stores a nullable after calling it | stale warning set (SB-D5, **reproduced**, btrcc) | compare diagnostics | A: Lib, Use (`prepass`). L: Lib, Use. `restarts=0` |
| SB-06 | `Other`, which `Use` does not import, adds `enum Paint { RED }`; `Use` writes bare `RED` from `Lib`'s `Color` | `Use` keeps resolving `RED` | `Main` imports `Other` | fails as a clean build does (`fallback=error`) |
| SB-07 | `Lib` removes `#define LIMIT 4`, which `Use` uses (`#undef` is rejected in lowering, `ir/lowering/Declarations.btrc:4651`, so it cannot be the edit) | `Use` replays `known = true` | | fails as a clean build does |
| SB-08 | `Use` adds `class Leaf extends Node` with a `Node` field (`Node` in `Lib`) | acyclic release helpers kept in `Lib` | | A: Use (`source`), Lib (`late`: its `cycle(Node)` answer, logged by the claims pass, moved after the sweeps; `restarts=1`). L: Use, Lib (`analysis`: re-analysis moves `Lib`'s visitor and release facts, which precede `answer.cycle`), Main (`entry`). N: Lib, Use, Main, `p.c`, runtime (**measured**, clean before/after) |
| SB-09 | `Other` (not imported by `Use`) adds a global `int count = 9`; `Use` captures a local `count` | SB-D9 (**reproduced**, btrcc prints 10). A correctness row: after the fix, no unit depends on it | run the program | A: Other. L: Other. Output `5` in both compilers |
| SB-10 | `Other` adds `class value {}`; `Use` has a local `value` | `Use` keeps the local's C name | | A: Other. L: Other, Use (`answer.exists`). N: Other, Use, `p.c`, runtime (**measured**) |
| SB-11 | `Other` demands `Box<Gadget>` of `Lib`'s generic `Box<T>` | stale instance set in `Lib` | | A: Other (`instance-scans=live:1`). L: Other, Lib (`answer.generic`), Main (`entry`). N: Lib, Other, Main, `p.c`, runtime (**measured**) |
| SB-12 | the root swaps two imports of groups that each `#define` | stale directive and prototype order (SB-D6, **reproduced**, btrcc) | | A: Main (`source`, the ordered import list). L: every group (`answer.program`: every unit carries the directive list, whose order moved). Units equal the after-clean build |
| SB-13 | `var g = make();` in `Lib`; `make()` in `Other` changes its return type; `Use` reads `g` | `Use` keeps `g`'s old type | | A: Other, Lib, Use (`answer.global-type`). L: as A |
| SB-14 | a realtime callee in `Lib` is renamed, and `Use`'s `@realtime` caller follows in the same edit | replayed edges to a vanished target read as safe (G5) | | equals a clean build |
| SB-15 | `Other` adds a typedef renaming a capability that `Use`'s native invocation names | the skipped native-invocation walk misses it | | equals a clean build |
| SB-16 | a field bound in `Lib` stops being constant because `Other`'s `#define` changes; `Use` calls `Span(array)` on it | `Use` keeps the accepted `Span` | | equals a clean build |
| SB-17 | a body-only edit of `Lib.process` that leaves every summary unchanged | over-invalidation | the Stage 9 counter fixture | A: Lib. L: Lib. N: Lib. 1 link (**measured**: only Lib lowered and compiled, in both compilers) |
| SB-18 | SB-17's edit with `Use`'s journal deleted, then corrupted, then of another schema | fall-back per group | three builds | A: Lib, Use (`live-for=missing`/`corrupt`/`schema`). L: Lib (`Use` lowers only if its journal facts moved) |
| SB-19 | more than half the groups edited | `dirty-share` | | `fallback=dirty-share`, `replayed=0` |
| SB-20 | a native header's contract changes, with the same declarations | a consulted contract outside the interface | the Linux call-shape fixture | A and L: the consumers of that native (`answer.native`) |
| SB-21 | `Lib` has `string? maybe(); string sure(); void f(string s = maybe());`, `Impl` defines `f`, `Use` calls `f()`; the default becomes `sure()` | facts on prototype-owned nodes with no dependency (review A1) | | A: Lib, Impl (`answer.subtree`). L: Lib, Impl, Use. Warnings equal a clean build |
| SB-22 | `Other` adds `class end {}` | the stdlib `Vector` unit keeps its local `end` (`src/stdlib/Vector.btrc:246`) | | A: Other. L: Other, `Vector` (`answer.exists`) |
| SB-23 | `Use` demands `Vector<Gadget>` for a new class `Gadget` | a stdlib instance scan reading a user type | | A: Use (`instance-scans=live:1`). L: Use, `Vector` (`answer.generic`) |
| SB-24 | `Use` has `Box<int>` in a body and a method generic whose closure demands `Box<float>`; `Main` adds `Box<char>` | demand replayed in one place instead of per sweep | | A: Main. L: Main, Lib (`answer.generic`). Instance order equals a clean build's |
| SB-25 | `Use` adds the program's first `try`/`catch` | `usesTrycatch` changes every unit | | A: Use. L: every group (`answer.program`). N: every unit, `p.c`, runtime (**measured**) |
| SB-26 | `Child extends Parent` in `Use` calls an inherited generic method of `Parent` in `Lib`; `Child`'s interface changes | the `generic` answer must carry the receiver's `I(d)` (`Lib`'s unit holds `Child_pick_int`) | | A: Use (`instance-scans=live:1` for `Lib`'s template). L: Use, Lib (`answer.generic`) |
| SB-27 | `--debug`: lines above `Base`, whose `__del__` `Derived` inherits | stale inherited `#line` (SB-D4, **reproduced**, both) | | A: Base. L: Base, Derived (`answer.body`) |
| SB-28 | a body-only edit of `Lib` that adds a `(int, bool)` local | stale tuple order (SB-D7, **reproduced**, both) | | A: Lib. L: Lib (under G12 the tuple order no longer depends on `Lib`'s body) |
| SB-29 | `Use` swaps its first `Box<int>` and `Box<float>` uses | stale instance order (SB-D8, **reproduced**, btrcpy) | | A: Use. L: Use; `Lib` unchanged under G12 |
| SB-30 | `Use`'s journal deleted, `Use`'s unit record kept; then the reverse | a record reachable without its journal, and the reverse | two builds | first: A: Use (`missing`), L: none if facts equal. Second: A: none, L: Use (`missing`) |
| SB-31 | alternate `--debug` and release builds with no edit, in a program where `Use` calls a defaulted `Lib` function | each mode voiding the other's journals; debug positions leaking into analysis answers | four builds | after the first two: A: none in either mode; L: none |
| SB-32 | SB-17's edit plus an unrelated error in `Other` | first-error order after replay | | `fallback=error`; diagnostics equal a clean build's |
| SB-33 | divergence chain `fail` → `wrap` → `wrap2` → caller across four groups; edit `fail` | restart exhaustion on pre-pass summaries | | A: all four (`prepass`). `restarts=0` |
| SB-34 | SB-17 built with `--jobs 1` and `--jobs 4` | logs depending on the worker count | | identical logs, records and counters |
| SB-35 | `Use` starts calling a method of an existing `Box<int>` it never called before | member-level demand differing between compilers (G13) | | A: Use. L: Use, Lib (`kept-instances`) in both compilers |
| SB-36 | `Main` imports a new group `Extra` that has no directives | a whole-program order answer making every group live | | A: Main, Extra (`source`). L: Main, Extra; no other group (no directive or shared answer moves); no `dirty-share` |
| SB-37 | `Use` adds a call whose only effect is a new instance demanded in the close sweep, implementing an interface declared in `Lib` | a `descendants` answer that differs by phase between the compilers | | the same A, L and `restarts` in both compilers |

## 10. Review

Under the standing design-approval rule: two adversarial reviewers and one
parity reviewer, with no unresolved blocking finding.

- **Reviewer A** probed analysis-side reuse.
- **Reviewer B** probed lowering-side reuse and the journal's robustness.
- **The parity reviewer** checked that both compilers can expose identical
  counters.

All three read the draft (`f65d64c`) and probed today's compilers. Every
"reproduced" claim was re-run by the integrator before it was recorded. Every
finding is resolved in this text; none is open.

| Finding | Severity | Resolution |
| --- | --- | --- |
| A1 facts on prototype-owned nodes lose their dependency | blocking | `subtree` namespace (5.2); SB-21 |
| A2 the stdlib consults user facts | blocking | no durable tier; stdlib groups keep logs (4, 5.2); SB-22, SB-23 |
| A3 one export digest contradicts SB-01/02 | major | `I(d)` in answers, separate `summary.*`, lowering-only `body` (4, 5.2) |
| A4 `sourceKnown` cannot be re-derived without a scope | major | keep the bit, log its global inputs (6.1); G6 of the draft dropped |
| A5 generic demand not journaled per sweep | major | per-sweep demand (6.1); SB-24 |
| A6 the lowering key omits the group's own analysis output | major | journal fact digest is a fixed lowering input (5.1) |
| A7 verify mode cannot catch a bypassing lookup | major | private tables plus a structural test (5.2); verify after every edit and differential mutations (6.6) |
| A8 stale warnings after a divergence edit, reproduced | major | SB-D5; SB-05 |
| A9 import swap stale, reproduced | major | SB-D6; ordered imports in the source digest (5.1); SB-12 |
| A10 error diagnostics after replay | major | `fallback=error` (5.3); SB-32 |
| A11 pre-pass summary chains exhaust restarts | major | in-pass worklist (5.3, step 2); SB-33 |
| A12 "never half-installed" false today | minor | stated as today's behavior; restart from fresh state; `position` is whole-build (6.5) |
| A13 realtime sections absent vs empty | minor | distinguished; gate not logged per group (6.1) |
| A14 SB-07 cannot use `#undef` | minor | SB-07 removes the `#define` instead |
| A15 rows' expected sets | minor | SB-05, SB-08, SB-09 corrected |
| A16 owned defaults evaluated in the caller in btrcc | minor | G6 |
| A17 member ordinals; restart state | minor | G2; restart from fresh analysis and AST (5.3) |
| B1 inherited `__del__` debug `#line`, reproduced in both | blocking | SB-D4; debug digests include positions (4, 5.4); SB-27 |
| B2 lambda capture dropped for an unrelated global, reproduced (btrcc) | blocking | SB-D9 is a compiler defect; removed from the key; SB-09 is a correctness row |
| B3 tuple order from other bodies, reproduced in both | major | SB-D7; canonical order (G12); SB-28 |
| B4 instance order, reproduced (btrcpy) | major | SB-D8; canonical order (G12); SB-29 |
| B5 import swap, reproduced (btrcc) | major | as A9 |
| B6 pre-pass and top-level `var` facts never journaled | blocking | journaled (6.1, item 5); every `record*` under a journal |
| B7 `X(d)` with bodies and setjmp in analysis answers | major | as A3; setjmp stays in today's check |
| B8 store keys; lowering log placement; debug/release voiding; concurrency | major | 6.1 store rules; 5.1 (debug out of the analysis key); SB-30, SB-31 |
| B9 Stage C has no channel for lowering logs | major | logs in worker replies; logged at every lookup (6.3); SB-34 |
| B10 verify cannot catch bypasses | major | as A7 |
| B11 counters not computable as defined | major | instance scans and fixed points do not make a group analyzed; closed `lowered-for` set (6.4, 7) |
| B12 rows' rebuild sets wrong; N circular | major | the oracle (8); SB-08, SB-10, SB-11 measured; SB-18 corrupts `Use`; SB-25 |
| B13 inherited generic method needs the receiver's interface | minor | `generic` answer carries the receiver's `I(d)`; SB-26 |
| B14 `shared` needs roots; macros relower every unit | minor | stated (5.2) |
| B15 the stdlib still consults user facts | minor | as A2 |
| B16 lambda-counter premise unverified | minor | Q4 records it |
| B17 method defaults show SB-D3 too | minor | SB-03 covers methods |
| P1 the "durable" groups do not exist under strict imports | blocking | groups are `CompilationGroups.names()`; native identity is a fixed input (2.2, 4, 5.1, 7) |
| P2 `X(d)` contradicts rows | major | as A3 |
| P3 which group instance scans count against | major | 7: they do not make a group analyzed |
| P4 "analyzed" defined only in btrcc's phase names | major | 7's normative list; G9 |
| P5 `cycle` and `bound` timing differs | major | both plan-time (5.3); G8 |
| P6 three summaries computed per caller in btrcc | major | G6 |
| P7 the `generic` order is compiler-specific | major | canonical order and set answers (G12, 5.2) |
| P8 `lowered-for` not a shared set; `releases_cyclable` stage differs | major | closed set (6.4); G10 |
| P9 `instance-scans` not comparable | major | per instance key; Q6 |
| P10 `native-unknown` conditions differ | major | one condition (6.5) |
| P11 worker pools change what is logged | major | as B9 |
| P12 line placement, empty lists, artifact hits | minor | 7 |
| P13 Python's realtime-safe emptiness check | minor | G11 |
| P14 N must include program and runtime units | minor | the oracle (8) |
| P15 byte-identical rendering stronger than needed | minor | G7 relaxed |

**Round 2** (on `79a94eb`). Reviewer A confirmed A1–A17 resolved. Reviewer B
confirmed 14 of 17, with B11 and B12 open. The parity reviewer confirmed 11
of 15, with P3, P8, P10 and P12 partly open. The round raised these, all now
resolved:

| Finding | Severity | Resolution |
| --- | --- | --- |
| A-N1, B-N2 `program.order` undefined; it would make every group live | major | dropped; `name` answers carry writer order, and the directive list carries lowering order (5.2); SB-12 fixed; SB-36 |
| A-N2, B-N1 debug positions in analysis answers break SB-03 and SB-31 | major | analysis answers position-free in every mode; positions only in the lowering log (5.1, 5.2, 5.4); SB-31 extended |
| A-N3 `cycle`/`descendants` not known at plan time | minor | checked after the generic sweeps, per asking phase (5.3, step 2b) |
| A-N4, B8 rest: journal choice; verify-mode entry check | minor | newest first, first full match, at most four kept (5.3, 6.1); the entry check moves to normal builds (6.6) |
| A-N5 merged default walked with no fact recorded | minor | merged defaults keep the prototype's path and log `subtree` on any walk (5.2) |
| B11, P-N2 no precedence; `generic` vs `answer.generic` | major | precedence-ordered reason lists; `kept-instances` (6.4, 6.5) |
| B12 rest: SB-08, SB-12, SB-26, SB-28 not exact | major | exact sets given |
| B6 rest: where pre-pass facts install | minor | at the pre-pass (6.2) |
| B8 rest: record names the fact digest | minor | 6.1 |
| B17 rest: default helper under `body` or `subtree` | minor | `subtree` (5.2) |
| B2 rest: 3.2 still lists globals under `exists` | minor | removed |
| P3 rest: where not-analysis queries land | major | logged against the group they are asked for (5.2, 7); SB-08 |
| P4 rest: rich-enum default pass unclassified | minor | analysis (7) |
| P5 rest: `consumed`/`owned-default` could be pre-pass | minor | allowed once G3 and G6 land, in both compilers together (5.3) |
| P8 rest, P-N1 member-level demand differs | major | G13; SB-35 |
| P10 rest: `native-unknown` predicate | minor | one predicate; btrcc's compile failure stays (6.5) |
| P12 rest: `artifact-hit` missing from 6.5 | minor | added |
| P-N3, B-N3 native identity as a per-group input contradicts SB-20 | major | removed from the fixed inputs; natives through the `native` namespace (5.1) |
| P-N4 realtime-only scan's counter state | minor | analyzed, `live-for=realtime`, and in `realtime-scans` (6.1) |

**Round 3** (on `7bbd252`). All three reviewers confirmed every round-2 item
resolved and **no unresolved blocking finding**. Their last notes are applied:

| Finding | Severity | Resolution |
| --- | --- | --- |
| A: SB-08 should state its restart | minor | `restarts=1` |
| B: SB-08's `Lib` reason not single; SB-36 not exact | minor | `analysis` by precedence; `Extra` has no directives, so L is Main and Extra only |
| P: claims-pass `cycle`/`descendants` see different instance lists in the two compilers | minor | answers computed on the final instance list in both (5.3); SB-37 |
| P: `native-unknown` appears only in btrcpy, since btrcc fails the compile | note | the parity checks skip that environment (6.5) |

**Parity verdict.** Both compilers can expose identical counters once the
groundwork lands: G3, G4 and G6 to G13. The native counts come from one
compiler-independent tool. Before that groundwork, these rows may differ
between the compilers: SB-08, SB-11, SB-16, SB-17 (until G4), SB-20, SB-28,
SB-29 and SB-35.

## 11. Open questions, each with its default

| Id | Question | Default in force |
| --- | --- | --- |
| Q1 | Re-render the interfaces of unchanged groups in the plan step? | no: cached per group source digest, as today |
| Q2 | The `dirty-share` threshold | half the groups live after the plan step; Stage 9 tunes it on the Mac |
| Q3 | Debug default helpers: at the callee's default (btrcc) or at `<btrc-generated>` (btrcpy)? | keep each compiler's choice; debug-mode digests include positions, so both are sound. Unifying them is a separate parity decision |
| Q4 | Can lambda, spawn or GPU-helper names depend on other groups' demand? | no evidence: lambdas are rejected in generic members. Renumber them per unit only if CL-R-09 reproduces a dependency |
| Q5 | Python `node_types`: journal the entries, or move consumers to re-inference? | journal them by position (G3) |
| Q6 | Python per-instance closure logs | CL-R-18 adds them; otherwise `instance-scans` leaves the parity checks |

## 12. What only the Mac can measure

Nothing in this document is a measurement. The Linux runs above are
correctness probes, not timings. These need the owner's Mac (MAC-R-04 to
MAC-R-06):

- the edit and cold instructions retired with journals, at `--jobs 1`, on the
  BTRSmith copy pinned by CL-R-01;
- the cold-build cost of logging queries and writing journals. Records cost
  about 5% today (`separate-compilation.md`, slice 3), and G12's canonical
  orders change output once;
- the peak memory of a replayed build against a live one;
- the `dirty-share` threshold (Q2);
- the native compile and link counts on the product build.
