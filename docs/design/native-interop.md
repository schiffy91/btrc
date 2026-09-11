# Native interoperability

Objective-C `SEL` arguments/results use the SDK's imported opaque C typedef,
not `id`, `void*` or a fabricated integer token. Both frontends require that
storage and reject incompatible definitions. `GUI.MacOS.ObjectiveCRuntime`
owns its header selection and Foundation linkage, including standalone use.

`MacOSButton` and `MacOSActionQueue` provide ordered momentary activations.
AppKit targets an SDK mutable array; BTRC consumes retained sender identities
after dispatch, preserving repeated clicks without unwinding through AppKit.
Unbinding purges that control's pending actions; controls close before the
queue. The host must drain regularly. This is not value-event snapshots,
arbitrary delegate export, or a bounded-allocation realtime queue.
Both compilers pass actual SDK calls, invalid storage, order, disabled state,
rebinding, teardown and sanitizer tests. Capture native button drawing over an
opaque native background: transparent dark-mode captures lose destination-
dependent title rendering. The native regression checks visible title contrast.

Unqualified `id` in Objective-C method signatures projects as a managed native object, not
`void*` or a presumed `NSObject` subclass. It retains actual object identity and
uses generated ARC retain/release adapters. Typed Objective-C instances may
upcast to `id`; returning from `id` to a concrete class requires a future checked
conversion, not an unchecked cast. No methods are statically available on `id`.
Protocol-qualified objects, generic object projections and `Class` remain
unsupported. This enables actual AppKit APIs such as progress-indicator
start/stop methods without handwritten native wrappers.

Native record inputs use ordinary owning BTRC classes, not managed references
hidden inside C records. Package bindings select `owned-records`, `record-inputs`
and typed `object-fields`; generated adapters materialize call-scoped SDK records.
A checked native descriptor graph is stored in an acyclic metadata catalog.
Mapped objects remain owned by the input; a callee's independently retained
object has a separate lifetime. The real WebGPU/Metal-layer regression verifies
both with weak observation and sanitizers. See the package manifest specification
for the supported mapping and its explicit borrowed-descriptor lifetime promise.

`GUI/MacOS/MacOSGPUSurface` owns an AppKit child view, Metal layer and WebGPU
surface through this path. Real tests compose it with native scrolling/editing
and exercise fractional sizing, backing-pixel rounding, empty/restored bounds,
repeated explicit close and scope teardown, with both compilers and sanitizers.
Layout must call `refreshBackingSize` after attachment or display-scale changes;
automatic resize notifications and cross-display behavior remain unverified.
This is a rendering target, not a production renderer. A real SDK test now
configures a device, clears and presents at three sizes, and reads GPU pixels
back to verify their color. Both compilers pass optimized and ASan/UBSan runs.
Combined native/GPU capture and product integration remain open.

`GUI/MacOS/MacOSViewCapture.captureTiff` now returns owned native-view pixels
without desktop capture. It bounds backing-pixel count and encoded byte length,
and copies SDK data before its owner is released. Real capture was inspected
while the Mac was locked. Both compilers pass optimized/sanitized tests for
changed editor pixels, scrolling beneath a stable header, limits and retained
output after view teardown. This captures AppKit-drawn content only: GPU
readback composition remains open. C ImageIO and AppKit now compose in one
consumer: matching complete C/Objective-C records share the C SDK storage
type, independent of import order. Size, alignment, field types and offsets
must agree; mismatches remain errors. Both compilers pass real capture/decode
and packed nested-record ABI tests, optimized and sanitized. Objective-C-only
records retain their field-wise value projections.

Named opaque handle aliases now preserve slot-level const in `Handle const*`
through import, pointer operations, validation and C lowering. Both compilers
accept reads/copies/submission and reject slot writes, const-dropping and
incompatible callback signatures. This is deliberately narrower than arbitrary
layered native qualifiers. Reuse source-declarator qualifier-depth semantics;
flattened typedef constness cannot distinguish a read-only slot from a read-only
pointee. The pinned wgpu-native has no working WaitAny; the rendering test uses
its verified inline request callbacks, while production request owners still
need explicit asynchronous lifetime and cancellation handling.

Current native-window increment: `GUI/MacOS/MacOSWindow` owns creation, title,
content size and explicit close in BTRC, sharing `AppKitText` with the native
text field. Both parsers preserve SDK keyword names in member position, such as
`NSWindow.new()`; native classes no longer claim nonexistent BTRC allocator
symbols. Real AppKit window/field composition passes with both compilers and
sanitizers, alongside keyword-member AST parity and record rejection. Application
delegate binding, portable recursive layout and product WebGPU composition
remain unfinished.

`GUI/MacOS/MacOSScrollView` now owns a persistent native vertical viewport and
document. AppKit handles clipping, overlay scrollers and wheel behavior; BTRC
validates geometry, preserves/clamps top-relative offsets and detaches on close.
Both compilers pass tests composing nested scroll views beside a pinned native
editor, dispatching a pixel-wheel event and checking retained focus/selection,
including sanitizers and both import orders. This is not collection recycling
or product acceptance.

`GUI/MacOS/MacOSApplication` implements main-thread startup and a bounded,
nonblocking event pump. Read-only Objective-C object globals now project as owned
value reads through generated ARC/exception adapters; they never expose writable
native pointer slots. SDK nullability is preserved, nonnull reads are checked,
and local shadowing retains ordinary local semantics. Mutable object globals
remain rejected. Unsigned SDK constants retain their unsigned literal type,
including the full-width `NSEventMaskAny`.

Both compilers pass actual key dispatch into the native editor, scrolling,
sanitizers and both import orders (8 cases per compiler), plus object-global
reads/storage rejections (9 cases per compiler). The self-hosted checks use fresh
compiler `d6eda046e0dd835f6c2fa479c4650dbe`. This is not completed application
shutdown/delegate handling or product/native-GPU integration.

ImageIO decoding, BackgroundJobs, CoreAudio, LocalApplicationChannel and the macOS directory picker now own their behavior in BTRC using typed header imports. The picker uses managed Objective-C instances and generated message/ARC adapters. General C++ objects and remaining providers are unfinished. Native object identity and layout are preserved; wrappers do not mirror objects into unrelated pointer bags.

`GUI/MacOS/MacOSTextField` owns a real AppKit field through generated Objective-C adapters. It snapshots active editing via `validateEditing`, preserves same-value updates, and explicitly detaches on close. Native modules may select different methods of the same SDK class: both frontends merge compatible selections, preserve every contributing header (including categories), and reject conflicting signatures or lifetime metadata. Both frontends support SDK-proven superclass conversions and attach `NSTextField` through `NSView.addSubview` from BTRC. Implicit downcasts/sibling conversions are rejected; explicit cast semantics are not qualified by these checks. Real AppKit editing/selection/undo/redo/cleanup passes with both compilers and sanitizers. Event binding, native/GPU capture and BTRSmith integration remain unfinished; standalone editor tests are not product acceptance.

Objective-C methods now accept/return complete nested mutable scalar records, enabling native frame geometry. Generated C-compatible value structs cross the adapter boundary; structured field-by-field conversions preserve SDK values without assuming native packing or copying object storage. These are value projections, not a native buffer-layout/borrowing contract. Const/pointer/object/array/union/bitfield members remain explicitly unsupported. `MacOSTextField.setFrame(x, y, width, height)` uses parent-view logical points, rejects nonfinite coordinates and negative dimensions, and positions the actual AppKit control. Both compilers pass fractional-frame, editing and unsupported-record tests on the same frozen source. Recursive layout, collection recycling and native/GPU composition are still to be implemented.

Platform packages expose neutral APIs and isolate concrete SDK providers. Audio contracts live under `Audio`, with the CoreAudio implementation/header under `Audio/MacOS`; native control providers live under `GUI/MacOS`. Nested imports such as `Library.Audio.AudioDevice` resolve exact package paths. macOS is the only platform implementation currently in scope; Windows/Linux are future provider boundaries, not working stubs. BTRSmith's approved `docs/NativePlatformPlan.md` owns the consolidated UI/API delivery plan.

The legacy GUI `Surface` now owns packed pixels through `OwnedBuffer<unsigned int>`, resize rollback, fills and readback in BTRC. The window presenter borrows pixels synchronously; no native surface owner or destructor remains. Remaining text/blending functions import their real header declarations, with explicit read-only string borrows. FreeType, text dispatch and the standalone GLFW/OpenGL presenter still require migration. This is not BTRSmith's GPU UI implementation or visual acceptance.

`build/GuiOwnerIntegration.xml` verifies that ownership through both compilers,
sanitizers, allocation failures, existing GUI examples, actual FreeType rendering
and a real window presenter (74 checks). `build/GuiSurfaceMigration.md` records
artifact identity and the remaining migration boundaries.

## Compiler boundary

- C enum imports use SDK-owned tags/typedefs with target-derived underlying types; const enum pointers and record fields retain their declared C storage type. Anonymous typedefs are not fabricated enum tags. Both compiler consumers execute real C tests, including negative values, unsigned storage, anonymous typedefs and rejected const mutations. Direct enum-tag selection and Objective-C enum-record value adapters are not established by this increment.
- Extend ordinary package imports with package-owned native bindings. Keep existing `#include` behavior compatible; it is not a typed import. Bindings identify headers, language, selected declarations and semantic overrides—not hand-copied function signatures or arbitrary build commands.
- Read headers through Clang with the actual target, SDK, language standard and package defines/includes. Import declaration identity, qualified types, layout, enums, overloads, availability and ownership attributes. Cache by those inputs and transitive header contents, never by pathname alone.
- Prefer a pinned Clang LibTooling reader for complete C-family semantics. Any build-time C++ reader exposes semantic data only; it does not become a product runtime or independent BTRC compiler. Both frontends consume the same versioned typed schema. Clang's debug AST dump is not the persistent schema.
- Integrate foreign declarations into source visibility, analysis and structured IR. Lower ownership and native calls in IR generation; emitters only render. Generated BTRC translation units stay strict C11. Necessary C++/Objective-C adapters become typed native-plan units, compiled for the selected architecture with the declared foreign toolchain.
- Unknown layout, ambiguous ownership, unsupported conversions or unavailable target APIs produce source-mapped errors. Never silently erase a type to `void*`, guess an integer return, trust a function as realtime, or fall back to another SDK.

The header reader now recognizes Objective-C selectors in standard
`+[Class selector:]` / `-[Class selector:]` spelling, including implicit property
accessors. Its typed data preserves interface identity, protocols, generic
arguments, instance versus class objects, qualified block signatures,
non-escaping parameters, Clang method families, consumed receivers and borrowed
interior results such as `NSString.UTF8String`. Both codecs validate these
fields. Package selectors feed source-level methods. Managed object storage is
being qualified; block copy/disposal and borrowed strings remain unfinished and
must be implemented before App's Objective-C can be removed.

Reference extraction/import verification passes 206 checks, including actual
Foundation methods and malformed lifetime/selector metadata
(`build/NativeObjCReferenceIntegration.xml`); structure/naming/ABI checks pass
59 (`build/NativeObjCHygiene.xml`). Fresh self-hosted reader/import/channel
verification passes 188 checks (`build/NativeObjCSelfhostIntegration.xml`,
compiler `08566d6f8e2b5ac17baf3fb689c32d4e`).

The C-family IR now represents message sends, autorelease pools and catch-all
exception boundaries explicitly. Only an `objective-c` translation unit may
emit them; ordinary generated programs remain C11, and realtime functions reject
these operations. Adapter bodies must nest the exception handler **inside** the
autorelease pool: letting an exception escape a pool leaked a marker in the
actual Foundation regression. Compile adapters with ARC, Objective-C exceptions
and ARC exception cleanup enabled; translate failure before leaving that scope.
Both emitters produce identical adapter code. The fresh reference/self-hosted
emitter/IR suite passes 121 checks (`build/ObjectiveCAdapterEmission.xml`, compiler
`e99a955de023a18ca4af88cbaa47eb49`), including real Foundation execution at O0,
O2 and with ASan/UBSan: 64-bit values, multiple selector arguments, and 1,000
normal/throwing calls per run with strong and autoreleased object cleanup.
Optimizer/realtime regressions pass 128 checks, CLI regressions 65, and
structure/naming/ABI checks 59. Formatting, Ruff and generated-code checks pass.
Mixed BTRC cleanup inside native scopes still requires implementation and
qualification; no additional App bridge is claimed removed.

Generated adapters now have a separate native-plan representation: schema 2
embeds emitted source with a unique name, language/standard and explicit
memory-management policy. The production builder compiles these units in private
temporary storage, keeps handwritten MRC units unchanged, chooses the C++ linker
when needed, and publishes only a successfully linked executable. Existing plans
without adapters remain schema 1; source-package containment is not relaxed.
Reference/self-hosted plan, builder, adapter and package integration passes 147
checks (`build/GeneratedNativePlanIntegration.xml`, fresh compiler
`3e7399829db7aa959b9e7c4e193f262c`); structure/naming/ABI/build-safety checks pass
86. Real Foundation and C++ exception tests execute the resulting binaries;
failure tests preserve existing output and remove temporary units.

Source imports now populate structured adapter units during lowering. For
example, selecting `+[NSThread isMainThread]` from a package's Foundation header
exposes `NSThread.isMainThread()` through its ordinary BTRC module import. Scalar
class methods call generated ARC thunks; SDK headers never enter the main C11
unit. Each thunk catches native exceptions inside its autorelease pool, returns
failure to C, and only then raises a BTRC exception. Method exceptions are
contained, and BTRC longjmp never crosses the native scope. Throwing foreign
destructors during pool drainage remain unqualified. The scalar checkpoint below
predates managed instance support. Protocol/generic objects and class objects, consumed
arguments/receivers, interior pointers and aggregate values remain unsupported.
Selector-to-method name collisions are rejected, not guessed.

Reference and fresh self-hosted verification execute the real Foundation entrypoint plus
64-bit/multi-argument, floating-point and void calls through the production
builder. The source-level failure probe runs 1,000 normal/throwing calls at O2
and under ASan/UBSan, with actual autoreleased-object counts returning to zero.
The final native/package/adapter suite passes 436 tests
(`build/ObjectiveCSourceFinalIntegration.xml`, compiler
`6bb876283350b7f9f5145110ce785222`); strengthened exception-message checks pass
four more (`build/ObjectiveCSourceFinalMessages.xml`). Optimizer, realtime, IR,
ABI and repository checks pass 247 (`build/ObjectiveCSourceFinalHygiene.xml`).
Ruff, formatting and generated-source checks pass. This is scoped qualification,
not the full compiler/platform matrix or completed provider migration.

Managed instances use distinct opaque C handle types for the actual native
objects. Generated ARC bridges borrow call arguments, retain returned objects,
and release BTRC-owned references on scope exit or exception cleanup. Native
objects never receive BTRC object headers or cycle descriptors. A BTRC owner
may hold a native object field, but native object graphs are not traversed by
BTRC's cycle collector. Generated ownership operations are non-throwing at the
C boundary and abort on a caught native ownership exception.

The reference compiler passes the real Foundation object probe at O2 and with
ASan/UBSan (`build/ObjectiveCManagedFieldsReference.xml`): 1,000 iterations of
nullable construction, instance calls, native argument/return aliasing, BTRC
function returns, field replacement, explicit release and exception cleanup,
with native live-object counts returning to zero. The matching self-hosted
implementation also passes the source suite: 16 reference/self-hosted checks
(`build/ObjectiveCManagedSource.xml`, compiler `1805067ff0d31bfc5b960bf3ade0631b`).
Final-tree source/emitter verification passed 54 checks
(`build/ObjectiveCManagedFinal.xml`, compiler `3f6ad1dbae0175b182cc065ec52b722d`);
the broader reference native-import suite passed 155, optimizer/realtime 69 and
repository/ABI/IR checks 92. These checks predate the buffer support below and do not
qualify collections, indirect calls, arbitrary ownership annotations or remove
an App provider.

The next increment imports `instancetype` as the selected native receiver type,
scalar-pointer parameters with their const/nullability qualifiers, and enum
constants as typed values without including Objective-C headers in C11. Required
arguments and native non-null results are checked at the BTRC boundary. Raw
pointer storage remains caller-owned; borrowed interior results remain unsupported.

Actual `NSString`/`NSURL` round-trips pass reference O2 and ASan/UBSan checks for
ASCII, accented and Japanese paths, byte counts using imported
`NSUTF8StringEncoding`, short-buffer rejection, and null arguments. Filesystem
output is checked against macOS's canonical decomposed UTF-8, not assumed to be
byte-identical to the input. A native method violating its non-null return
annotation also raises a checked BTRC error and releases its owner. These eight
checks (`build/ObjectiveCPathReference.xml`) and the full 161-check reference
suite (`build/ObjectiveCPathFullReference.xml`) pass. Fresh reference/self-hosted
source and emitter qualification passed 68 checks (`build/ObjectiveCPathIntegration.xml`,
compiler `bb574eaee0dd748a51d290e4b4cf367e`). This still does not remove the picker provider.

Scalar globals from Objective-C headers now use generated typed address accessors.
Reads and writes address the SDK-owned storage; `&name` preserves its identity,
including static constants such as `NSNotFound` and `NSModalResponseOK`. No SDK
values are hand-copied into BTRC declarations. Local bindings shadow imported names;
read-only globals remain const. These accessor-backed addresses require runtime
initialization and are rejected in static initializers. Native object/pointer globals
remain unsupported until their ownership semantics can be preserved. Real AppKit
constant and mutable-storage tests pass O2 and ASan/UBSan through both compilers.
Final source/emitter verification passes 82 checks (`build/ObjectiveCGlobalsVerified.xml`,
fresh compiler `2948d65354f227e566a54626f5bb5317`). The reference native/optimizer
run passes 177 checks (`build/ObjectiveCGlobalsFinalReference.xml`); structure,
naming, ABI, optimizer and static-initializer checks pass 93
(`build/ObjectiveCGlobalsFinalHygiene.xml`). Inherited AppKit selectors and the
actual picker replacement remain next; no provider was retired in this increment.

Selected inherited Objective-C methods now use Clang's superclass/category lookup.
The shared model preserves the requested receiver separately from the method's
declaring owner and canonical identity. `instancetype` projects to the receiver,
so an inherited `NSMutableString.stringWithUTF8String` factory creates a mutable
native object that can call its own and inherited methods. This does not yet
implement general BTRC conversions between native superclass/subclass handles.
Actual AppKit extraction and Foundation mutation/byte-copy tests pass O2 and
ASan/UBSan through both compilers, with identical link plans. The reference
reader/import suite passes 235 checks (`build/ObjectiveCInheritedReference.xml`);
fresh self-hosted reader and reference/self-hosted source/emitter integration
passes 135 (`build/ObjectiveCInheritedIntegration.xml`, compiler
`290ab963862937b939418c28f7388271`). Structure, naming, ABI, static-initializer
and optimizer checks pass 93 (`build/ObjectiveCInheritedHygiene.xml`). That
checkpoint qualified inherited imports, not the picker migration described below.

The directory picker now puts `NSString`, `NSOpenPanel` and `NSURL` operations
in `MacOSDirectoryPicker.btrc`, using caller-owned filesystem buffers, inherited
methods and SDK response constants. `ApplicationWindow.chooseDirectory` accepts
the concrete provider and snapshots typed outcomes without holding the native
application lock. BTRSmith supplies the macOS provider explicitly. The old
picker implementation, path storage, ABI entries and build inputs are removed.

Reference tests exercise real panel configuration, main-thread rejection,
native cancellation and programmatic completion of a real modal session with
its actual selected directory. Injected SDK failures cover missing URL, unknown
response, exceptions and insufficient buffers; Unicode filesystem bytes survive
later calls. O2 and ASan/UBSan pass (`build/DirectoryPickerReference.xml`). These
tests do not prove a user clicking the native acceptance button: automated
button actions did not dismiss the remote AppKit panel. That UI check remains
pending. Fresh reference/self-hosted integration passes 61 checks with compiler
`d4ff54f2a286b785e7255b1016239e90` (`build/DirectoryPickerIntegration.xml`);
its three skipped window checks pass when explicitly configured (one native
titlebar test and two real-window GPU tests). Nix App/GPU libraries rebuild
without the old picker symbols. Both reference and self-hosted BTRSmith consumers
build with identical native link plans, load a real PSARC fixture, present 120
frames and tear down cleanly. The self-hosted run reuses the reference catalog
and state. This is local integration with current libraries, not synchronized-pin
package qualification.

Native `realtime-safe` annotations are explicit reviewed assertions on selected header functions, not inferred from C linkage. Both frontends retain their declaration provenance and the IR verifier checks generated adapters. Known allocation/blocking/I/O effects cannot be overridden; ordinary function pointers do not gain realtime proof. Non-null checks trap without logging on certified paths. This enables the remaining BTRC render migration; it does not certify arbitrary audio plugins or remove callback lifetime requirements.

Native callback slots preserve incoming non-null promises on imported record
fields. BTRC callbacks accept those arguments without a copied SDK struct;
extraction/invocation/address-taking stays rejected until a checked indirect
adapter can preserve the preconditions. Non-null callback results also remain
rejected. Both compilers' real Apple mixer tests register an
`AURenderCallbackStruct`, call BTRC through the SDK and verify the supplied samples
at the mixer output, with and without sanitizers. The combined native consumer,
realtime and CoreAudio run passed **331 tests** (`build/NativeCallbackIntegration.xml`,
fresh compiler `29daa057077fd827916b7ad4f38ad27b`); naming/build/ABI hygiene passed
86 tests. Formatting, Ruff and generated-code consistency checks passed. This
qualifies the callback increment, not physical guitar operation or the full
platform matrix. It predates the CoreAudio replacement described below.

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

Scope: migrate every handwritten native bridge, stdlib first. The initial providers are proofs, not the completion boundary. Audit all native sources, including runtime/tool/test code; retain only code with a concrete ABI, runtime, third-party or verification purpose. Do not merely rename C files or recreate pointer façades in BTRC.

1. **Typed C import:** real CoreFoundation string creation/query/release with inferred types and constants, plus record/callback coverage. Both frontends reject wrong argument types, ownership escape and double consumption. Run the actual SDK-linked executable, not a mock API.
2. **First migrated provider:** move ImageIO decode orchestration and cleanup into `MacOSEncodedImageDecoder`. Verify real PNG/JPEG/TIFF, invalid input, limits and every partial-failure cleanup path. Remove the superseded C implementation only after provider parity.
3. **Foreign objects:** actual Foundation object/block and an existing package's C++ RAII API. Verify shared identity, borrowed returns, destruction exactly once, exceptions and callbacks through generated adapters.
4. **Audio:** migrate CoreAudio lifecycle/state into BTRC using the proven ownership/callback primitives. Verify permissions, hot-plug, partial initialization, stop/drain and physical input/output; retain bounded allocation-free processing.

Each checkpoint includes focused reference/self-host parity, native execution and sanitizers where supported. Compiler completion still requires the full AGENTS.md matrix, bootstrap and synchronized pinned builds. Do not migrate the entire stdlib ahead of these working consumers.

## Migration inventory

Initial tracked-file inventory (2026-09-09), not a completed semantic audit: BTRC has 58 native stdlib sources/headers (about 12.5k lines), ten runtime files, one Clang reader, six native-package example files and 56 test fixtures/probes. Inspect every file within each owner; a directory classification alone does not justify retaining its contents.

| Owner | Native files | BTRC destination / required proof |
|---|---:|---|
| `src/stdlib/MacOSEncodedImageDecoder/` | 1 remaining | `ImageIO.h` includes SDK headers only. Decode policy and cleanup moved to `MacOSEncodedImageDecoder`; old C implementation/header removed. |
| `src/stdlib/Audio/MacOS/` | 1 native header | `Hardware.h` includes SDK headers and read-only aliases for SDK string macros. BTRC owns inventory, configuration/rollback, aggregates, AUHAL setup/render/drain and retryable cleanup. Old session C/header/ABI removed; both-compiler runtime checks pass. |
| `src/stdlib/App/` | 9 | Existing app/window owners; platform objects, pickers, event delivery and shutdown. |
| `src/stdlib/GPU/` | 14 | WebGPU and native UI owners; resource lifetimes, async completion, actual rendering/text/captures. |
| `src/stdlib/GUI/` | 7 | Existing GUI/font/window owners; layout, glyph metrics and real window behavior. |
| `src/stdlib/BackgroundJobs/` | 1 remaining | `NativeThreads.h` includes pthread/errno SDK headers only. `BackgroundJobs` owns queues, cancellation, completion, worker joins and disposal; old C executor/header/ABI/archive target removed. |
| `src/stdlib/LocalApplicationChannel/` | 1 remaining | `Socket.h` supplies SDK declarations and a Darwin/Linux peer-credential ABI helper. Client/server ownership, framing, budgets, deadlines, permissions and conditional endpoint cleanup moved to BTRC; old C/header/hosted ABI/archive target removed. Windows provider selection and Linux self-hosted qualification remain open. |
| `src/stdlib/Tray/` | 3 | Platform tray providers; event callbacks, menus and teardown. |
| `src/stdlib/Windows/` | 17 | Typed Windows providers; audit compatibility headers individually, no success-only POSIX shims. |
| `src/runtime/c/` | 10 | Separate unavoidable runtime machinery from movable stdlib policy; preserve bootstrap, ARC, exceptions and threading semantics. |
| `tools/NativeHeaderReader.cpp` | 1 | Build-time Clang AST access remains justified C++; no product policy here. |
| Native tests/examples | 62 | Keep genuine foreign-ABI oracles; update consumers and remove fixtures for retired bridges, not independent correctness coverage. |

BTRSmith's 14 production adapter files under `packages/{miniz,pugixml,sqlite,vgmstream,yaml,zlib}/native/` are also in scope; their nine native release probes/fixtures require individual review. Preserve pinned upstream implementations. Move our resource management, parser/decoder orchestration and error mapping into the package's BTRC objects, then delete superseded adapters after parity and real-content tests. Any remaining native file must have a specific documented purpose; migration is not complete with these bridges merely hidden behind new wrappers.

`MacOSEncodedImageDecoder` owns content recognition, bounds and format checks; its private decode transaction retains input and pixels while SDK handles borrow them. `__del__` releases the native resources before managed fields. `Image.tryCreate` makes pixel-allocation failure recoverable; CoreGraphics draws directly into the final buffer, followed by in-place BTRC alpha conversion. No resource or borrowed SDK value escapes through the public API. This is a verified concrete owner, not general compiler-checked native ownership.

The retired C implementation/header, fake decoder and old C smoke test are removed, together with obsolete hosted-ABI registrations. Retained C test code has two specific purposes: independently encode a multi-frame TIFF with the SDK, and intercept actual SDK calls to inject failures/count resource releases. Neither implements a decoder. Regression coverage includes actual PNG/JPEG/GIF/TIFF, portable DDS, limits/corrupt input, first-frame selection, all 65,536 channel/alpha combinations and 16 partial-failure paths. Actual generated providers execute under strict C11 and Apple ASan/UBSan.

## Implementation and verification

The poll-driven channel server now owns its listener, endpoint identity and
bounded peer collection in BTRC. Each peer owns its partial-frame/response
buffers and idle deadline. Requests retain a separate managed identity token,
not a raw server pointer or the server itself. Nonblocking EINTR yields rather
than monopolizing the application loop. Endpoint cleanup requires the recorded
user/device/inode and a successful bind; a preparation/bind collision cannot
delete an interloper. The remaining 710-line C server, header, old C-only fault
test, hosted ABI and archive target are removed. Their fault scenarios are now
real socket/filesystem tests in BTRC, including server replacement and stale
requests. Post-removal macOS verification passes all 16 channel tests through
both compilers, including ASan/UBSan and native link-plan parity
(`build/LocalChannelServerMigration.xml`, fresh self-hosted compiler
`63948e161d6fe1bc62aa1b286a2c6992`). Independent peers exercise the actual wire
protocol; the build asserts there are no handwritten channel compilation units.
Linux's reference path passes nine channel/ABI checks with GCC, Clang and
sanitizers (`build/LocalChannelServerLinux.xml`). Its `_GNU_SOURCE` definition
comes from the package plan before SDK headers are read. The final naming,
ABI, build-safety and package suite passes 117 tests
(`build/LocalChannelServerFinalHygiene.xml`). SDK structure fields retain their
native spellings after deletion of the C bridge. Linux self-hosted, Windows
provider selection and packaged BTRSmith qualification remain incomplete.

The subsequent BTRSmith consumer build exposed a strict-import regression:
transitive SDK typedefs made hosted `size_t` appear privately owned by the
channel module. Both visibility checkers now keep existing hosted SDK typedefs
globally available without exporting new SDK aliases or source-defined
typedefs. The minimal reference reproduction and visibility suite pass 35
checks; an additional source-typedef boundary test passes with all 34 visibility
tests. Fresh self-hosted qualification is recorded below; the earlier 16-test
report predates this compiler correction.
The BTRSmith retry exposed a second defect: duplicate SDK declarations imported
by multiple providers. Both importers now validate shared declarations' types,
record layouts, constants and call contracts, retaining every importing module
until visibility is checked. Analysis receives one canonical declaration,
preferring complete SDK record fields over an opaque projection. Conflicting
layouts or borrowing/realtime assertions are errors, not first-import-wins
behavior. Private SDK storage layouts preserve qualifiers while being compared;
comparison does not attempt to expose those fields as BTRC types.

The complete reference native-import suite passes 148 tests
(`build/NativeSharedSdkReferenceAll.xml`), including real shared CoreFoundation
calls under ASan/UBSan, both record import orders, incompatible declarations and
sibling visibility. The structure/naming/visibility suite passes 62 checks
(`build/NativeSharedSdkHygiene.xml`). BTRSmith's reference
`BTRSmithAgentOperationChannel` consumer builds and runs successfully against
the sibling sources: actual application requests, malformed-message recovery,
reconnection and borrowed-session lifetime pass. Its synthetic capture fixture
is not visual acceptance. Fresh self-hosted compiler
`0eafff7f6e2dad35bf71c795a26025ec` passes all 154 native-import/channel checks
without skips (`build/NativeSharedSdkSelfhostIntegration.xml`). The BTRSmith
self-hosted consumer also builds and runs successfully, with an identical link
plan to the reference path. These checks precede the Objective-C metadata
extension; its fresh qualification is separate. Sibling overrides do not
qualify the pinned packaged app.

CoreAudio's live provider now uses `CoreAudioUnit` in BTRC, with no handwritten
session/render C implementation or hosted session ABI. It owns the SDK unit,
channel maps, buffers, callback admission counters and the retained program.
Setup precomputes exact slice-clock offsets; the realtime callback performs
bounded copying/slicing and reviewed SDK calls without allocation, ARC or
checked runtime arithmetic. Stop/drain precedes disposal; failed uninitialization
or disposal preserves ownership for retry. The SDK owns record layouts.

Reference verification passed ten SDK fault/sanitizer cases, including partial
setup, delayed configuration, inventory changes, failed teardown and the live
provider's pending-cleanup path. The callback test covers 1–65,536 frames,
16–8,192-frame program limits, input/output channel selection, exact clocks,
partial input failure and buffer guards. Final verification passed **26 tests**
through both compilers, including real output-device callbacks/drain and
ASan/UBSan (`build/CoreAudioUnitMigration.xml`, fresh compiler
`d9265f0e7167e4bf4d5b1ababd08802b`). Naming/ABI/build/package checks passed 117
tests (`build/CoreAudioUnitHygiene.xml`). `UnitFaults.c` supplies SDK-shaped test
responses only. A subsequent reference-analyzer fix handles missing source
metadata on directly parsed ASTs; its regression verification is separate and
passes 65 storage and 18 native-global tests (`build/CoreAudioCopiedStorageFinal.xml`,
`build/NativeGlobalProvenanceFinal.xml`). It requires a fresh compiler before
final-tree qualification.

BackgroundJobs owns queues, cancellation, completion and worker lifetime in
BTRC. Its retained runtime entry handles ARC/exception thread-local state around
an SDK-created worker; that allocating boundary is never used for audio.
ImageIO owns decoding policy and explicit SDK-resource release in BTRC.
Neither migration establishes general compiler-managed native ownership.

The prior typed-callback checkpoint passed 331 native/realtime/CoreAudio tests
on compiler `29daa057077fd827916b7ad4f38ad27b`
(`build/NativeCallbackIntegration.xml`). That report predates the current
CoreAudio replacement. Historical reports are not final-tree qualification.

Next: qualify remaining consumers, migrate the remaining native providers and
implement general owned C resources and
Objective-C/C++ object adapters. A fresh complete compiler/platform matrix and
physical guitar/app acceptance remain required.
