# Known language gaps

These are language features the grammar/spec permits (or the docs imply) but the
reference Python compiler and self-hosted compiler do not yet implement safely.
The historical numbering is retained so fixes and tests can refer to a stable
gap ID.

## Open gaps

| # | Feature | Symptom | Where |
|---|---------|---------|-------|
| — | Generic class inheritance | A generic class cannot extend another class, and inherited generic properties are not lowered. Both analyzers reject these declarations before code generation. | `python/analyzer/declarations.py`, `btrc/analyzer/validation/declarations.btrc`, `btrc/analyzer/validation/storage.btrc` |
| — | Static storage on generic classes | Static fields and properties do not yet have a per-definition versus per-specialization storage model. Both backends reject them explicitly. | `python/analyzer/storage.py`, `btrc/analyzer/validation/storage.btrc` |
| — | Static methods on generic classes | A class-qualified static method call or method value has no specialization target for the class type parameters. Both analyzers reject the declaration instead of emitting an ambiguous unspecialized symbol. | `python/analyzer/declarations.py`, `btrc/analyzer/validation/storage.btrc` |
| — | Lambda expressions inside generic declarations | Generic-body lowering does not yet lift lambda declarations and their capture environments for each specialization. Inline lambdas passed to an ordinary generic method are supported; a lambda declared inside a generic class or method body is rejected. | `python/analyzer/expressions.py`, `btrc/analyzer/validation/expressions.btrc` |
| — | `spawn` expressions inside generic declarations | Generic-body lowering does not yet specialize the thread entry and capture boundary. Both analyzers reject the expression before code generation. | `python/analyzer/expressions.py`, `btrc/analyzer/validation/expressions.btrc` |

## Intentional syntax limits

Multi-dimensional fixed arrays (`int grid[2][3]`, historical gap 9) are not
part of the current language grammar or ASDL: a declaration has one optional
array suffix and `TypeExpr` has one `array_size`. Both parsers now reject a
second dimension explicitly instead of silently producing a partial AST. Adding
multiple dimensions would be a language/specification change, not a missing
implementation of the current grammar.

Grammar keywords are reserved and cannot be used as source identifiers. Code
generators escape schema field names that collide with those keywords, but that
internal escaping does not create quoted identifiers in the language.

Tuple element names such as `_0` and `_1` are ordinary postfix members. A
second tuple access must currently use a parenthesized intermediate—
`(value._1)._0`—because the unparenthesized numeric-looking boundary in
`value._1._0` is intentionally not accepted by the lexer. The equivalent
separate local binding is also supported.

Exceptions carry string messages. A catch may be untyped or bind `string`; a
different catch annotation is rejected explicitly. The stdlib error classes
are ordinary values and do not introduce typed exception payloads.

## Closed gaps

| # | Feature | Resolution | Regression test |
|---|---------|------------|-----------------|
| 1 | `typedef` aliases | Lowered as typed `IRTypedefDef` declarations and emitted before dependent declarations. | `basics/test_typedef_alias_lowering.btrc` |
| 2 | Local storage qualifiers | `static`, `extern`, and `volatile` are preserved as `IRVarDecl` metadata in ordinary declarations and loop initializers. | `basics/test_local_storage_qualifiers.btrc` |
| 3 | Class C-style casts | Class targets lower to pointer C types. Interfaces remain compile-time implementation contracts rather than runtime value types. | `classes/test_class_cast_lowering.btrc` |
| 4 | Wide and unsigned integer string conversion | Dedicated helpers and matching format specifiers cover `long long`, unsigned integer widths, and `long double`. | `basics/test_wide_integer_strings.btrc` |
| 5 | Rich enums in by-value declarations | Rich enums use structured tagged-union IR and are completed before callable declarations or class fields that use them by value. | `enums/test_rich_enum_signatures.btrc` |
| 6 | Class compound assignment | Compound operators call the corresponding overload once and assign its result. | `classes/test_class_compound_assignment.btrc` |
| 7 | Nullable class element in a generic collection (`Vector<Box?>`) | `keep` and keep-parameter retains are null-guarded in both compilers; generic ownership paths use the terminal destructor. | `memory/test_nullable_generic_arc.btrc`, `memory/test_nullable_ownership_ops.btrc` |
| 8 | Valid multi-word C integer spellings | The parsers accept the valid signed/unsigned `short`, `long`, and `long long` spellings; invalid `long long double` is no longer treated as a supported base type. | `basics/test_extended_int_types.btrc` |
| — | Self-host parser diagnostics | Token expectations record one fatal expected/actual diagnostic, unwind to the program boundary, and prevent malformed ASTs from entering analysis or IR generation. | `btrc/test_parser_diagnostics.py` |
| 10 | Capturing IIFEs | The call site creates a typed stack environment, initializes it in an `IRCommaExpr`, and passes its address to the lifted expression- or block-body lambda. Only the inert declaration is hoisted, so branches and loop conditions retain source evaluation semantics. | `functions/test_lambda_capture_iife.btrc` |
| 11 | Capturing lambda conversion to exact `CFunction<Signature>` | `CFunction` is the public spelling of one noncapturing C function-pointer word; result, parameter, pointer, and `const` shapes are checked recursively from the canonical hosted-ABI manifest. A direct inferred local may retain an associated environment only through its dedicated lexical path. Every environment-erasing conversion—explicit storage, aliasing, return, argument, assignment, default/field, or recursively nested collection literal—is rejected once at its source site. Direct `spawn(lambda)` and capturing IIFEs retain their environment-aware lowerings; the self-hosted compiler also fails closed at unsafe IR boundaries. | `btrc/test_cfunction_callback_contract.py`, `python/test_analyzer_lambda_contracts.py`, `functions/test_lambda_capture_local.btrc` |
| 12 | Self-hosted `@gpu` lowering | `btrcc` now registers typed kernel/buffer/uniform IR, emits collision-safe checked WGSL, builds host dispatch/setup/readback/cleanup as structured C IR, prunes unreachable shaders, and provides per-invocation CPU fallbacks for void and array-output kernels. Checked bounds/arithmetic status is read before user data; post-submit transfer failures fail closed, while pre-submit failures use the CPU worker. The native compute context is acquired through an atomic process singleton. | `btrc/test_gpu_boundary.py`, `btrc/fixtures/gpu_checked_semantics.btrc`, `btrc/fixtures/gpu_compound_semantics.btrc` |

Single-dimensional top-level fixed arrays are also represented by typed
`IRGlobalDecl` nodes and covered by `basics/test_global_fixed_array.btrc`.
