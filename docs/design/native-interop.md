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

`tools/NativeHeaderReader.cpp` implements build-time extraction with pinned Clang LibTooling; build with `nix build .#btrc-native-header`. It preserves scalar/opaque-handle types, per-level qualifiers, constants, exact callbacks and explicit ownership annotations; absent annotations remain unknown. Reachable by-value C structs/unions export target-derived size, alignment, field/bitfield offsets, fixed/flexible arrays and distinct Clang record identities. Recursive pointers reference identities without copying private layouts. Selecting a complete record requests its layout; incomplete typedefs remain opaque and cannot be passed by value. Unsupported field types/C++ adapters and missing declarations fail without partial output.

Both package resolvers now model module-owned [`native.bindings`](../../src/language/package-manifest.md#experimental-native-header-imports): header, language/standard, exact selected names and target predicates. They reject escaping paths, malformed requests and overlapping exports. Loaded-module/target projection selects requests; ordinary headers and linker-plan schema 1 are unchanged. Selecting an active binding currently stops compilation with an explicit unsupported-import error, rather than silently discarding it.

The reader JSON remains experimental, not yet connected to ordinary compilation or a stable binding format. `src/language/native_abi.asdl` now generates a separate native semantic model for both frontends; the ordinary source AST is unchanged. `NativeHeaderCodec` / `FeNativeHeaderCodec` check and decode it without erasing pointer-level qualifiers, declaration identity or explicit ownership. Layout/count values remain exact decimal strings, never JSON floating-point values. Reader/toolchain invocation, source visibility, frontend/IR integration, ownership enforcement, Objective-C/C++ adapters and provider migration remain to implement. BTRC's current flattened `TypeExpr` cannot represent every native pointer qualifier/layout; do not project away those semantics to accelerate integration. Record metadata describes the SDK ABI, not permission to manually clone its objects or manufacture managed ownership.

Run its semantic tests with `BTRC_NATIVE_HEADER_READER=<built-package>/bin/btrc-native-header python3 -m pytest src/tests/python/test_native_header_reader.py`; they explicitly skip when this experimental component has not been built. Qualification requires an enabled run, including actual CoreFoundation on macOS—not a skipped default suite. The native reader is not included in the default tool bundle until integrated.

Record extraction verification: 19 reader tests pass, including native compiled-C layout comparison, actual SDK `CFRange`, recursive/anonymous records, packed structs and 32-bit/64-bit, big-endian and Windows LLP64 target layouts. The same 19 pass with AddressSanitizer/UndefinedBehaviorSanitizer enabled on the reader; 98 existing import/declaration/hosted-ABI/native-package tests also pass. These are reader/regression results, not frontend parity, leak qualification, provider migration or the full compiler matrix.

Binding-selection verification: 116 focused reference tests and 32 native-package tests through a freshly built self-hosted compiler pass. The reader suite now has 20 passing tests, including a package-resolved request against actual CoreFoundation headers. Generated-source, focused lint/format and diff checks pass. The selected-binding error is deliberate unfinished implementation, not evidence of a usable native import; no provider has migrated.

Semantic-model verification: the expanded enabled suite passes 62 checks, including the BTRC decoder compiled through both frontends under strict C11. It checks actual CoreFoundation types, nested qualifiers, ownership annotations, exact layout values beyond double precision, and rejection of malformed/duplicate/overflowing metadata. This is decoder parity, not native-call or managed-lifetime qualification. Next output remains checkpoint 1; do not substitute more manifest-only tests for the SDK-linked BTRC executable.
