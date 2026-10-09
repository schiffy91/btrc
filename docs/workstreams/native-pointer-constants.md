# Typed native pointer constants

The fresh Windows Toolhelp prerequisite fails in both current-equivalent frontends for x64 and ARM64 because `INVALID_HANDLE_VALUE` is a pointer-valued SDK macro. Baseline result `e22228e4` and independent audit `4192c100` remain under `/private/tmp/btrc-audit-repair/windows-toolhelp-current-5aa/results/baseline1`. All four projections reject the macro before C emission; downstream Toolhelp record/function projection and native Windows behavior remain unproved.

This packet adds `NativePointerConstant` to the shared native ABI schema. The reader retains the SDK type and symbol and reports target pointer width plus a canonical unsigned decimal address for semantic identity. Importers project a readonly, value-only native reference with no initializer or generated storage. Emission uses the existing SDK identifier path. Qualifiers and typedef identity remain intact; assignment, increments and taking the constant's address remain prohibited.

Admission is limited to side-effect-free constant void/object pointer sentinels with no object or string base and no pointer arithmetic. The reader derives width from Clang's target, accepts 32/64-bit representations, and uses Clang Sema for direct pointer casts and qualification. Function pointers, unsupported address spaces, runtime values and effects fail closed. Existing integer/string negative contracts are retained. API details were checked against the exact LLVM 21.1.8 `clang/AST/APValue.h`, `clang/AST/Expr.h` and `clang/Sema/Sema.h` sources.

Handwritten source and test preparation is complete; no generator, reader, compiler, behavioral test or native program has run for this repair. Generated catalogs must come from the existing unified generator in a separate derived commit. Qualification must rebuild the reader, exercise focused reference codec/import cases and both unchanged genuine Toolhelp reference projections before the fresh selfhost build. Paired focused tests and all four original Toolhelp projections remain required. Test source defines 41 new macro rows and paired malformed-codec coverage; this is not an executed collection or pass count.

No provider, public API, runtime, worker pool or emitter change is included. This is a compiler prerequisite packet, not completion of `ProcessThreads.count` or reproduction of the historical SDK codec failure.

## Follow-up: neutral native type sugar

The catalogs were generated through the existing renderer and canonical generate/check, then committed separately as `414db329`. Reader build/install/fixup passed after the build directory was separated from its installed output. Reference qualification on the fixture-only include-guard correction `de4009d9` passed all99 selected macro/codec cases (56+43). It then failed actual Windows x64 Toolhelp projection with `native function semantics do not match its signature`; ARM64 projection was not reached. These are reference-only results; fresh selfhost acceptance remains outstanding.

Raw-reader diagnostic result `3c6f400b6fee4e5b27a4b13b302bb8559668671a8262bf2bd3a3752591be522c` retained genuine SDK documents for both targets. All six selected functions have a neutral `qualified` wrapper around a function, matching semantic/signature parameter counts and C calling convention. This establishes a reader/type representation mismatch with the existing codec contract, not a parameter mismatch or historical eight-case reproduction.

The follow-up changes only the existing reader's generic single-step desugaring fallback: a layer with no Clang qualifiers or nullability returns its underlying typed representation directly. Meaningful qualifier wrappers, typedef identity, function calling-convention checks and nested return/parameter qualifiers remain unchanged. The codec remains strict. Focused reader regressions and unchanged Toolhelp projections must run against a freshly built reader before any acceptance claim.

## Follow-up: const-pointer diagnostic contract

Reference qualification of `b04309d8` retained the two intended old-reader failures,
then passed103 macro/codec cases and both genuine Windows x64/ARM64 Toolhelp
projections (result `fa626924`, independent audit `bb63f5bd`). The fresh selfhost
build succeeded. Its paired gate passed92 codec and62 macro cases, then failed
one macro diagnostic assertion; the four paired Toolhelp projections were not
run. Failed result `2516f6ed` and independent failure audit `6fab672a` remain
immutable in `windows-pointer-selfhost-b04309d8-attempt-1`. All source/tool inputs
closed unchanged and all eight owned groups closed.

Both compilers reject `unsigned char* bytes = PTR_CONST;` without publishing C or
a link plan. The Python analyzer uses its established generic assignment error
(`test_analyzer_qualifier_contracts.py` already requires that wording); the
selfhost storage validator reports const loss at pointer depth1 before generic
assignment compatibility. This is a mistaken new test expectation, not an
accepted invalid conversion or evidence requiring a production change.

The repair preserves all six invalid scenarios. The const-loss row now requires
the exact existing message from each frontend and compiles an ordinary
`const unsigned char*` to `unsigned char*` control with the same variable name,
requiring that frontend's identical rejection and no outputs. The other five
rows retain exact cross-frontend diagnostic equality. The control is inside the
existing case: the paired selection remains155 tests. Source review and focused
qualification remain required; no new pass or native Windows behavior is claimed.
