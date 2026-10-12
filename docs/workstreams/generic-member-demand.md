# Generic member demand: implementation request and regression packet

Status: designed, not implemented. Base: `5be0800466ae3b5937033f39dd92042b5f82683f`.
The latest human-supplied AGENTS.md reserves compiler production owners to the
integrator. This packet may change narrowly assigned tests, its claim and report;
it must not change compiler sources, generated files, runtime, manifests or gates.

```text
REQUEST(src/compiler/btrc/ir/lowering/{Lowerer,Generics,Declarations,Functions}.btrc and src/compiler/btrc/pipeline/ModuleUnits.btrc): Materialize ordinary nongeneric members of generic-class instances only when demanded, using the existing typed lowering and module-unit owners.
Repro: The authenticated c822 Linux phase workload has 9,982 graph instance members but retains only 3,132; Vector accounts for 8,718 members, of which 2,106 survive. The current emitGenericInstance lowers ordinary method bodies before global demandInstances removes unused members.
Expected / actual: Required members lower once in their existing group session before effect/realtime solving; presently all selected generic members lower before that demand is known. Preserve complete semantic validation, structured IR, output bytes/order, incremental invalidation and eager no-DCE/inspection behavior.
Blocks: Demonstrating reduced lowering work and a new paired product performance result. Existing semantic regression tests alone cannot establish this optimization.
Workaround in this branch: none. Python remains eager; no raw-C/IR serialization, alternate compiler, comparator normalization or production mirror is introduced.
```

## Evidence and scope

The counts come from all 459 authenticated module-unit records in phase run
38182812913, not from source estimates. There are 6,850 discarded instance
members, including 6,612 Vector members. These are function counts, not an
attribution of memory or a prediction of savings. Phase current RSS rises from
1,022,382,080 bytes after program lowering to 2,118,062,080 after unit lowering.
Before finish, recorded maximum RSS is already 2,233,065,472 bytes. Removing
finished units alone cannot establish the 1.5 GiB target.

The full retained phase audit is
`compact-ir-flow-linux-phase-success-38182812913/independent-audit.json`, SHA256
`e5c477b97cd9b03bc09f1f8176500c0bf218f16e9ff120758561b874100bbcf7`.
The source of `StdlibReachability` uses unqualified method names and broad implied
roots and scans instantiated declarations; it is not a concrete-specialization
executable reachability proof. Do not replace it with another heuristic.

## Required implementation contracts

1. Keep analyzer validation, declarations, layouts, signatures and available
   provider identities complete. Initially defer only ordinary nongeneric
   generic-class methods. Retain lifecycle constructors/init/new/destructors,
   visitors, properties, generic-method instances and realtime-annotated methods
   eagerly, together with the existing mandatory roots.
2. Retain a typed member plan in the existing lowerer session: instance/member,
   substitutions, source owner and original definition position. Invoke the same
   method-body lowering exactly once when demanded. Restore the existing instance,
   ownership, class/return/type-map, lexical binding and collection boundary state.
   Do not rerun a group's complete lowering to add another method.
3. Extend the existing module demand traversal to distinguish available providers
   from materialized graph nodes. Follow actual CALL/FUNCTION_REF references;
   materialize missing required members on the worker already owning their group;
   add their actual edges and close the fixed point before setjmp/realtime solves.
   A body that has not been lowered has no fabricated empty effect summary.
4. Finish callable/default closure, referenced interfaces, function-pointer and
   realtime typedefs, cleanup-slot finalization, memo shutdown and module partition
   only after demand closure. Any newly discovered callable/helper references
   participate in that same closure.
5. Preserve canonical definition placement. Existing `renumberTemporaries`
   explicitly removes dependence on dead-function lowering and covers cleanup
   slots/storage roots. Existing `renumberAdapters` handles four adapter families
   but retains their occupied definition positions. Use these owners unchanged;
   do not append bodies in discovery order or invent a naming prepass.
   `placeLifted` already sorts by depth/identity and must see the complete set.
6. Cached records must distinguish available providers, materialized edges and
   kept members. Newly required absent bodies invalidate their provider once;
   later demand expansion grows that same session. Version changed record
   semantics through the existing owner. Warm unchanged groups must not lower;
   existing effect-summary invalidation must remain exact.

## Regression preparation

Use existing `test_module_unit_staleness.py` for add/remove demand, unchanged warm
reuse and exact clean-vs-incremental C. Keep original lower-count assertions;
do not accept repeated lowering merely because output agrees. Use existing
`test_generic_instance_closure.py` for transitive lifecycle/member references and
strict native execution, including an eager no-DCE control. Original baselines
must run before claiming these new cases pass. Source-only preparation is not a
baseline execution.

The complete later qualification must also retain existing constructor/field,
destructor/cycle visitor, interface, method-value/function-pointer, operator,
collection-release, realtime and setjmp tests. Include recursive cross-group
demand and an effect-changing edit with exact lowering counts. Generic lambda
and spawn restrictions already have paired diagnostic tests; do not silently
turn those invalid programs into accepted unused bodies.

No new telemetry API is presumed by these regression additions. A later
implementation-specific proof must demonstrate absent dead-body materialization
and at-most-once materialization separately from output DCE. Keep the original
strict C/ordered-plan comparator and eight-run performance protocol unchanged.

## Current execution state

No production implementation, compiler build, test collection, behavioral test,
measurement or publication has run for this packet. Regression source additions are prepared in the two existing test owners.
They have not been collected or executed; their expected counts remain unverified.
