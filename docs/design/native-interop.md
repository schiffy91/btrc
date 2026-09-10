# Native interoperability

Implementation direction, not an implemented language feature. BTRC should call real C, Objective-C and C++ APIs through typed imports, with provider policy and lifetime management written in BTRC. Native object identity and layout are preserved; wrappers do not mirror objects into unrelated pointer bags.

## Compiler boundary

- Extend ordinary package imports with package-owned native bindings. Keep existing `#include` behavior compatible; it is not a typed import. Bindings identify headers, language, selected declarations and semantic overrides—not hand-copied function signatures or arbitrary build commands.
- Read headers through Clang with the actual target, SDK, language standard and package defines/includes. Import declaration identity, qualified types, layout, enums, overloads, availability and ownership attributes. Cache by those inputs and transitive header contents, never by pathname alone.
- Prefer a pinned Clang LibTooling reader for complete C-family semantics. Any build-time C++ reader exposes semantic data only; it does not become a product runtime or independent BTRC compiler. Both frontends consume the same versioned typed schema. Clang's debug AST dump is not the persistent schema.
- Integrate foreign declarations into source visibility, analysis and structured IR. Lower ownership and native calls in IR generation; emitters only render. Generated BTRC translation units stay strict C11. Necessary C++/Objective-C adapters become typed native-plan units, compiled for the selected architecture with the declared foreign toolchain.
- Unknown layout, ambiguous ownership, unsupported conversions or unavailable target APIs produce source-mapped errors. Never silently erase a type to `void*`, guess an integer return, trust a function as realtime, or fall back to another SDK.

Clang recommends [LibTooling for full AST access](https://clang.llvm.org/docs/Tooling.html); its stable [C interface intentionally omits AST information](https://clang.llvm.org/docs/LibClang.html). Preserve the SDK's [ownership attributes](https://clang.llvm.org/docs/AttributeReference.html), supplementing only missing semantics.

## Lifetime and ABI

| Boundary | Required behavior |
|---|---|
| C values | Preserve typedef identity, pointer qualifiers, enum representation, record layout and exact callback signatures. Native headers remain the layout authority. |
| C resources | Distinguish owned results, borrowed views, consumed parameters and fallible creation. Associate the correct release operation with an owner; borrowing cannot outlive it. Not every native pointer is reference-counted. |
| Objective-C | Preserve class/protocol identity, selector signatures, nullability, method-family ownership, retain/release, autorelease pools and block copy/disposal. Keep exceptions inside the adapter boundary and make their policy explicit. |
| C++ | Resolve overloads and explicitly requested template instantiations with Clang. Preserve constructor/destructor, move/copy and borrowed-reference semantics. Catch exceptions in adapters and translate to a declared BTRC error; no foreign unwinding through generated C. |
| Callbacks | Reuse exact `CFunction`, owned closures and registration/drain barriers. Distinguish call-only versus retained callbacks and thread affinity. Foreign declarations cannot manufacture `RealtimeFunction` proof. |

Raw ABI access remains an explicitly unsafe boundary, not the normal application API. Generated adapters may perform ABI/lifetime operations; filesystem, decoder, window and audio policy belongs in BTRC owners.

## Output checkpoints

1. **Typed C import:** real CoreFoundation string creation/query/release with inferred types and constants, plus record/callback coverage. Both frontends reject wrong argument types, ownership escape and double consumption. Run the actual SDK-linked executable, not a mock API.
2. **First migrated provider:** move ImageIO decode orchestration and cleanup into `MacOsEncodedImageDecoder`. Verify real PNG/JPEG/TIFF, invalid input, limits and every partial-failure cleanup path. Remove the superseded C implementation only after provider parity.
3. **Foreign objects:** actual Foundation object/block and an existing package's C++ RAII API. Verify shared identity, borrowed returns, destruction exactly once, exceptions and callbacks through generated adapters.
4. **Audio:** migrate CoreAudio lifecycle/state into BTRC using the proven ownership/callback primitives. Verify permissions, hot-plug, partial initialization, stop/drain and physical input/output; retain bounded allocation-free processing.

Each checkpoint includes focused reference/self-host parity, native execution and sanitizers where supported. Compiler completion still requires the full AGENTS.md matrix, bootstrap and synchronized pinned builds. Do not migrate the entire stdlib ahead of these working consumers.

## Starting evidence

At `3c7844f`, the checkout was clean and 98 reference import/declaration/hosted-ABI/native-package tests passed. A real CoreFoundation create/query/release program compiles and runs under Apple Clang's strict C11 mode. Equivalent BTRC with only the SDK include fails: the reference frontend cannot infer the result or resolve `kCFStringEncodingUTF8`; the existing immutable self-host bundle also rejects that constant. This is the missing semantic import, not a missing framework or permission. No importer implementation or provider migration is claimed yet.
