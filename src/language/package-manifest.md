# Package manifests and native link plans

This document defines package manifest version 1, lockfile schema 3, and native
link-plan schemas 1 and 2.  The reference and self-hosted compilers implement the same
strict local graph, lock, and plan contracts. The reference compiler also
materializes Git dependencies; the self-hosted compiler currently rejects that
acquisition surface precisely. A build tool consumes the emitted plan; compilers never execute
compiler flags or shell fragments from a manifest.

## Manifest version 1

`btrc.toml` opts into this contract with the integer root field
`manifest-version = 1`.  Versioned manifests are strict: unknown fields,
unknown tables, duplicate package identities, ambiguous dependency sources,
and values of the wrong TOML type are errors.

Every version-1 manifest has exactly one package identity:

```toml
manifest-version = 1

[package]
name = "example"
```

Names and dependency aliases use ASCII identifiers (`[A-Za-z_][A-Za-z0-9_]*`).
A resolved graph may contain only one source for a package name.  Depending on
two different sources with the same package identity is an error.

### Public modules

An optional `package.exports` array defines a package's public source modules:

```toml
[package]
name = "widgets"
exports = ["GUI", "IView", "IButton"]
```

Names resolve to `src/<module>.btrc`, falling back to `<module>.btrc` at the
package root; dotted names select subdirectories. Entries must exist, remain
inside the package after symlink resolution, and be distinct valid module names.
An empty array makes every module private. Omitting `exports` preserves the
existing unrestricted import behavior; it does **not** establish encapsulation.

Code inside the same package can import its private implementations. Imports
from outside can reach only exported files, regardless of dependency alias,
relative/absolute spelling, directory glob, symlink, or BTRC `#include`. Checks
run on every edge before import de-duplication: importing a public factory does
not grant access to a private file that factory already loaded. Canonical paths
and the nearest manifest define ownership, including nested packages and loose
consumers without a manifest. Export-policy caches live for one resolution only.

Exports control source-module access, not symbol re-export or native security.
Ordinary strict per-file visibility still applies. Public factories must return
portable public types; listing a module does not inspect its API for leaked
platform types. Handwritten C and deliberate unsafe access are not sandboxed.

### Target-selected source providers

An ordinary BTRC module can declare one implementation dependency per target:

```toml
[[package.providers]]
module = "GUI"
implementation = "MacOS.Provider"
os = ["macos"]
arch = ["aarch64", "x86_64"]
```

Both names resolve to existing package modules using the same path and symlink
checks as exports. The resolver adds the selected implementation as a normal
import of `GUI` before composing its source. `GUI` contains ordinary BTRC code
using that implementation; no runtime provider registry, virtual source file,
generated import text or caller-side OS branch is introduced. This also applies
when `GUI` is the compilation entrypoint. The compiler's normalized target—not
the build host—selects the dependency.

`os` and `arch` use the existing closed target sets below; omitted or empty
selectors match all values. Declarations for the same canonical module must be
disjoint, even on inactive targets. Self-selection, missing modules, escaping
paths and unknown fields are errors. Importing a configured module without a
matching provider is an error, not a fallback to another OS. Only selected
implementation source is parsed; inactive files must exist but may be unfinished.

Provider imports obey ordinary strict visibility and package privacy. Export the
public module, not its implementation; loading it does not authorize consumers
to import a private implementation directly. Provider selection is scoped to
one resolution and indexed by canonical module identity. The existing manifest
hash locks these declarations; selected implementations enter the ordinary
source dependency graph. They do not create native link-plan records.

Dependencies are local to their declaring package.  An import beginning with
an alias is resolved against the manifest owning the importing source, not the
root application's aliases.  Dependencies use one of these forms:

```toml
[dependencies]
local = { path = "../local" }
remote = { git = "https://example.invalid/remote.git", rev = "<ref>" }
```

`path` and `git` are mutually exclusive.  A Git dependency may specify at most
one of `rev`, `tag`, and `branch`; an omitted ref means `HEAD`.  Paths are
relative to the declaring manifest.  Every dependency directory must contain
a version-1 `btrc.toml` whose package name matches the resolved graph identity.

The native tables contain data, never arbitrary `cflags`, `ldflags`, commands,
or shell text.  Each entry may have `os` and `arch` string arrays.  An omitted
or empty array matches every value.  Supported operating systems are `linux`,
`macos`, and `windows`; supported architectures are `x86_64` and `aarch64`.

```toml
[[native.sources]]
path = "native/example.cpp"
language = "c++"
standard = "c++17"
modules = ["AudioDevice"]
os = ["linux", "macos", "windows"]
arch = ["x86_64", "aarch64"]

[[native.headers]]
path = "native/example.h"

[[native.include-directories]]
path = "native"

[[native.defines]]
name = "EXAMPLE_ABI"
value = "1"

[[native.frameworks]]
name = "Cocoa"
os = ["macos"]

[[native.pkg-config]]
name = "dbus-1"
os = ["linux"]
```

Every native declaration may have a non-empty `modules` array of dotted module
names relative to its declaring package. `AudioDevice` resolves as
`src/AudioDevice.btrc` and `GUI.Window` as `src/GUI/Window.btrc`, with the
package root as the fallback module directory. Missing, malformed, duplicate,
or escaping module names are errors. A scoped declaration is emitted when any
named module is loaded. An entry without `modules` is package-wide and is
emitted when any module from that package is loaded; `modules = []` is invalid.

Source languages and standards are closed sets:

- `c`: `c11`
- `c++`: `c++17`, `c++20`
- `objective-c`: `c11`
- `objective-c++`: `c++17`, `c++20`

Declared sources and headers must be regular files inside their package root.
Declared include directories must be directories inside that root.  Symlinks
that escape the root are rejected.  Define names are C identifiers.  Framework
and pkg-config names use only letters, digits, `_`, `.`, `+`, and `-`.

Selected `native.pkg-config` dependencies supply `--cflags` to typed header
imports as well as the native build plan. The shared header reader invokes
`pkg-config` without a shell, preserving quoted include paths and definitions;
missing dependencies fail before emitting C. Link flags remain build-plan-owned.
The environment must resolve metadata for the explicitly selected target, not an
unrelated host installation. Nix pins the dependency; do not copy store paths into
headers. Target and module selection apply before dependency resolution.

## Experimental native header imports

`native.bindings` describes a typed header request owned by one existing BTRC
module. Both frontends validate, select and experimentally consume C requests.
Unloaded modules and inactive targets do not
activate their bindings. Existing `native.headers` and `#include` retain their
untyped behavior.

### Call-scoped native callbacks

An explicit callback mapping projects a native function-pointer/context pair
into an ordinary BTRC interface parameter. The header remains the signature
authority; the manifest supplies only the context relationship, lifetime,
failure policy and imported interface name:

```toml
[[native.bindings]]
module = "Visits"
header = "Visits.h"
language = "c"
standard = "c11"
symbols = ["VisitNow"]

[native.bindings.callbacks."VisitNow.callback"]
context = "context"
context-index = 1
interface = "IVisitor"
lifetime = "call"
failure = "abort"
executor = "caller"
```

For `int VisitNow(int value, int (*callback)(int, void*), void* context)`, this
imports `IVisitor` with `int invoke(int argument0)` and exposes
`VisitNow(int value, IVisitor callback)`. `context` names the enclosing native
function's parameter; `context-index` is the zero-based context slot in the
callback prototype, whose parameter names are not part of a C function type.

```btrc
class Visitor implements IVisitor {
	public int invoke(int value) { return value * 2; }
}
var result = VisitNow(21, Visitor());
```

Generated strict-C11 adapters retain the ordinary managed receiver across the
whole native call, pass a stack-scoped typed context, dispatch synchronously,
and release the receiver afterward. Nested/reentrant calls use independent call frames.
The stack context records caller-thread identity using the existing thread-local
runtime state; a wrong-thread delivery terminates before entering the receiver.
Receiver leases and owned native results use BTRC's normal exception-cleanup
slots, including when a receiver destructor throws after the native call.
No userdata, manual retain, trampoline, or second owner is exposed to provider
code. An indirect function value uses the same checked adapter.

`call` asserts that native code neither retains the context nor delivers a
callback after the enclosing call returns. This is a trusted foreign lifetime
fact, not a claim that arbitrary C behavior can be statically verified. Context
slots must be distinct, unshared `void*` parameters. Callback arguments/results
currently support scalar values (and void results); pointer/managed payloads
require future borrow/ownership mappings and are rejected. The same interface
name may be reused by mappings with identical native result/payload types,
including across binding modules and different context positions. Context slots
are omitted from interface identity; public arguments are numbered consecutively.
Conflicting signatures or names colliding with other imported declarations fail
compilation. SDK signature changes are checked when compiling.

`abort` is currently the only supported failure policy: a BTRC exception runs
its local cleanup and terminates at the callback boundary, without unwinding
through native frames. `caller` is the only supported executor. This adapter is
not realtime-safe. Stored registrations, one-shot completion, UI-executor
ownership/destruction, Objective-C delegates/blocks and direct
capturing-lambda conversion remain unfinished. Use table form as above for
both compilers; self-hosted inline-table parsing remains limited.

### Header selection

```toml
[[native.bindings]]
module = "CoreFoundation"
header = "native/CoreFoundation.h"
language = "c"
standard = "c11"
symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease"]
read-only-borrows = ["CFStringCreateWithCString.cStr"]
os = ["macos"]
```

`module` uses existing package-relative dotted module lookup; `header` must be a
file inside the package, including after symlink resolution. An umbrella header
may include SDK headers; do not copy SDK signatures into the manifest. `symbols`
is a non-empty, duplicate-free array of exact names (`name` or `namespace::name`).
Objective-C/Objective-C++ bindings also accept exact `+[Class selector:]` and
`-[Class selector:]` spellings, with one or more named selector components.
`Class` is the requested receiver, not necessarily the declaring class: selecting
`-[NSOpenPanel setTitle:]` uses Clang's inherited/category lookup and retains
`NSSavePanel` as the declaring owner. Overrides keep their actual SDK identity.
The source consumer exposes Objective-C class and instance methods as ordinary
method calls and rejects ambiguous method-name projections. Native object
handles retain SDK identity and use generated ARC lifetime operations;
`instancetype` results use the receiver type. Scalar-pointer parameters preserve
const/nullability qualifiers and require caller-owned storage. Enum constants
are imported as typed values. Scalar globals use generated address accessors that
preserve SDK storage identity and const protection; initialize references to them
at runtime, not in static storage. Required arguments and non-null object results
are checked at the BTRC boundary.
It generates a separate ARC unit in the link plan, translates exceptions back
to BTRC after native cleanup, and never includes Objective-C headers in the
main C11 unit. Blocks, consumed receivers/arguments, protocol/generic/dynamic
objects, native subclass conversions and borrowed interior results remain unsupported. This is scoped
interop support, not completed App/C++ provider migration.
Language/standard and `os`/`arch` use the existing closed sets. There is no
package-wide binding. Duplicate exports into the same module are rejected when
their target predicates overlap, including inactive targets; disjoint providers
are allowed. Bindings participate in manifest locking but are compiler inputs,
not schema-1 linker records or native source units.

Both compiler consumers require explicit `BTRC_NATIVE_HEADER_READER` (built with
`nix build .#btrc-native-header`), `BTRC_NATIVE_SYSROOT` (an available macOS SDK
or Linux GNU sysroot with `usr/include`), and `BTRC_NATIVE_TARGET` (a matching
triple, e.g. `arm64-apple-macosx14.0.0` or `aarch64-unknown-linux-gnu`).
The Nix development shell and packaged compilers supply these from
their pinned reader, SDK and host platform; explicit caller values override
the package defaults. A raw standalone compiler still requires configuration.
`btrcc` also requires `--target OS-ARCH` when a reached stdlib module imports
native headers, even without a project manifest. Omitting it is an error, not
permission to drop target-scoped bindings and use approximate hosted declarations.
They import C scalar/typedef/opaque-pointer signatures, supported C structs,
exact function-pointer signatures, constants, native globals and SDK parameter names into
ordinary visibility and type checking. Struct declarations retain the SDK's
tag or anonymous typedef spelling; the compiler does not reproduce SDK layouts.
Link the emitted C with the
same target/SDK and required frameworks. There is no automatic SDK fallback.
Types or explicit ownership annotations that cannot yet be lowered faithfully
fail; unannotated pointers remain raw, not managed resources. Native compilations
bypass artifact caching until its key includes transitive headers and toolchain
identity. This is not a completed cross-platform import or lifetime feature.

Outer `_Nullable` and `_Nonnull` pointer annotations on function parameters and
results are preserved. Nullable values keep their original pointer depth;
non-null contracts use typed IR-generated call adapters, including calls through
stored function values. A null non-null argument or result prints a diagnostic
and aborts at the boundary; this is not recoverable exception translation.
Nested `_Nullable` output slots and callback values use BTRC's null-admitting raw
pointer representation without adding indirection. The SDK declaration remains
authoritative. Nested `_Nonnull` promises still fail: they require directional
output/callback enforcement, not just an outer call guard.
These checks do not establish ownership, callback lifetime or realtime safety.

Function calls retain the SDK's source name and included declaration, so the
native compiler applies SDK linker aliases. BTRC does not redeclare those
functions using the linker spelling. Top-level parameter `restrict` is excluded
from compatible function-type projection; the original C declaration and its
aliasing obligations still apply. Nested `restrict`, volatile pointers and
restricted return types remain unsupported.

A complete SDK record imported indirectly can own storage (`sizeof`, locals,
or allocation) without exposing its private fields. The SDK header supplies its
size and alignment; BTRC does not emit an empty/mirrored definition. A genuinely
incomplete SDK type still cannot own storage. Field access requires imported
field metadata. Verified native declarations use their SDK signatures, not
approximate hosted-ABI prototypes; handwritten declarations retain the existing
hosted-ABI checks.

Native globals refer to SDK-owned storage; the compiler does not emit another
definition. A read-only pointer slot and a pointer to read-only data are distinct:
`int *const` forbids rebinding but permits pointee writes; `const int *` does the
reverse. Local shadowing is allowed, but handwritten global redeclarations may
not replace the imported declaration. Taking a read-only scalar/record's address
preserves const; taking a read-only pointer slot's address is rejected until
per-pointer qualifiers can be represented faithfully. Thread-local, renamed,
and C++-linkage globals remain unsupported and produce no partial output.

The Unix self-host entry point supplies bounded SDK-reader execution. The
Windows host entry point uses the same compiler pipeline without that capability;
selected SDK imports fail explicitly rather than pulling unsupported Unix
process helpers into the Windows executable.

### Read-only call borrows

The optional `read-only-borrows` array names exact `function.parameter` pairs
from the selected header declarations. This is a **trusted package assertion**:
the call neither writes through the argument nor retains, consumes, returns,
or otherwise exposes any address into its storage after the call, on any path.
It is not inferred from `const`, and the compiler cannot prove a foreign
implementation honors it. Review the upstream API before declaring it.

The initial surface accepts only pointers to const scalar storage, such as
`CFStringCreateWithCString.cStr`. It allows a managed string to be borrowed for
that copying call without a handwritten wrapper or an intermediate copy.
It does not establish ownership of the returned CF object.
Unknown functions/parameters, duplicate entries, mutable pointers, nested
pointers, records and conflicting consumed-parameter annotations fail closed.
Declarations are attached to the imported function, not a global name whitelist;
ordinary BTRC forwarding wrappers use the same borrow-effect proof. Erasing a
function into a type without borrowing metadata does not grant permission to
pass a managed value. Unannotated SDK calls remain conservative.

### Realtime native calls

### Owning native record inputs

A C binding can generate ordinary owning BTRC classes for selected SDK input
records. The SDK structs themselves keep their original ABI and remain available.

```toml
# Inside [[native.bindings]], with these records and function in symbols:
owned-records = ["WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer"]
record-inputs = ["wgpuInstanceCreateSurface.descriptor"]
[native.bindings.object-fields]
"WGPUSurfaceDescriptor.nextInChain" = "WGPUSurfaceSourceMetalLayer?"
"WGPUSurfaceSourceMetalLayer.layer" = "CAMetalLayer"
```

This exposes `WGPUSurfaceDescriptorInput` and `WGPUSurfaceSourceMetalLayerInput`.
Their mapped fields retain ordinary BTRC or selected Objective-C objects. Import
the module owning `CAMetalLayer` in the binding's BTRC module. Other fields retain
their SDK-derived types; no header signatures or byte offsets are duplicated.

`record-inputs` changes only the named const-record-pointer parameters. At each
call, including indirect calls, a generated adapter materializes temporary SDK
records, converts mapped object fields and passes the record addresses. Nullable
parameters/fields accept null; required mapped fields are checked before calling
native code. Unannotated root parameters are required. A nested record pointer
must match the SDK record identity, or its first embedded record at offset zero
(for typed extension chains). Cycles, unknown fields, incompatible pointers,
direct array/const-value fields, and realtime declarations are rejected.

This is a **trusted package lifetime declaration**: native code borrows the
temporary descriptor bytes and chain only during the call; it cannot store or
return those addresses. It may independently retain a mapped Objective-C object
through that object's native ownership API. The owning input and the callee's
retained object have separate lifetimes. This is not `read-only-borrows`, an
output/writeback adapter, a callback registration, or permission for application
code to cast managed objects to raw pointer storage. Verify the actual callee's
lifetime behavior before selecting this mapping.

### Managed reference-counted C resources

Ownership facts belong to the existing binding, not copied C signatures. The
canonical resource syntax is a named TOML subtable:

```toml
[[native.bindings]]
module = "Widgets"
header = "Widgets.h"
language = "c"
standard = "c11"
symbols = ["WidgetRef", "WidgetCreate", "WidgetRead", "WidgetRetain", "WidgetRelease"]
owned-results = ["WidgetCreate"]
borrowed-parameters = ["WidgetRead.widget"]

[native.bindings.resources.WidgetRef]
ownership = "reference-counted"
retain = "WidgetRetain"
release = "WidgetRelease"
```

Both manifests validate selected names, distinct retain/release operations,
closed fields and duplicate-free selections. Multiple resource types may share
the same lifetime functions. Resources must be SDK record-pointer typedefs;
hooks take one compatible pointer. Release returns void; retain returns void or
a compatible pointer. The importer checks the actual header, not names alone.
Contradictory SDK ownership is an error. SDK `cf_retained` results supply the
owned-result fact without an additional manifest entry.

The declared semantics are: each successful owned result supplies one native
ownership claim; a borrowed parameter is valid only for the call and does not
transfer ownership; aliases retain the same native object through its declared
operation. Both native lifetime functions are reserved for generated cleanup,
including when referenced as function values. Managed values preserve native
identity; they never receive a BTRC ARC header. Generated strict-C11 adapters
convert typed carriers and guard null before calling lifetime hooks. Ordinary
BTRC fields, aliases, returns, `release` and exception cleanup use these hooks.
Each borrowed resource argument holds a native retain claim until its call
finishes, even if a reentrant callback clears the last application owner. This
also applies when a callback was registered earlier rather than passed to the
current function. Arguments unwind in reverse order through normal cleanup
slots; a returned owned resource remains protected during that teardown.
This protects object lifetime, not mutable interior storage or concurrent
unsynchronized mutation of the application's owner slot.
Unannotated resource parameters/results are not inferred safe. Nullability
remains SDK-owned; unannotated results are nullable.

**Limits:** raw casts, output slots, native callbacks carrying these resources,
unowned resource globals/results and realtime resource adapters are rejected.
Unique resources, transfers, borrowed results and executor-affine cleanup still
need checked support through this mechanism. Reference counting alone does not
prove a UI object's executor or a registration's cancellation contract; this is
not permission to migrate those providers yet. Inactive bindings remain inactive.
Use named subtables for portable manifests; the self-hosted parser does not yet
support general inline TOML tables outside its existing dependency syntax.

### Realtime native functions

The optional `realtime-safe` array names exact selected functions, for example
`realtime-safe = ["AudioUnitRender"]`. This is a trusted, target-specific package
assertion that the configured foreign implementation is bounded and performs no
allocation, blocking, locking, logging, managed ownership or other forbidden
realtime effects. Review the API and its required setup before declaring it;
headers alone cannot prove an implementation's behavior. It does not certify
every possible audio-unit/plugin implementation reachable through a handle.

Both analyzers attach the assertion to the actual imported declaration. Unknown
names, non-functions, duplicates and malformed arrays fail. Unannotated calls and
ordinary erased function pointers remain unproven. BTRC wrappers still undergo
transitive effect analysis; known forbidden effects cannot be overridden. The structured-IR verifier checks their generated
adapters too. Nullability guards on a certified call trap without logging or
unwinding; non-realtime adapters retain their diagnostic. No callback, allocation
or resource lifetime promise is implied by this setting.

### Native callback fields

Imported record fields may receive BTRC C-compatible callbacks whose raw pointer
parameters accept the SDK's incoming arguments. Non-null input promises are
retained on the field rather than projected into an unchecked callable value.
This supports real `AURenderCallbackStruct` registration without mirroring its
layout or writing a C bridge. The registering owner must keep callback context
alive until the SDK's unregister/drain barrier completes.

Reading, invoking, taking the address of, or exporting a field with those
preconditions currently fails: it needs a checked indirect-call adapter. Record
copies retain the restriction. Fields promising non-null callback results also
remain unsupported until assignment can establish that outgoing guarantee.
Nullable callback arguments retain the ordinary raw-pointer value domain and
ABI. No realtime, ownership, or foreign-thread runtime-entry proof is implied.

## Recursive graph and lockfile

Resolution walks dependency manifests recursively with an explicit visiting
stack.  Cycles report their package path.  The graph is deterministic and a
diamond dependency contributes one package and one set of native inputs.

Schema-3 `btrc.lock` records the complete resolved graph, each package's local
alias map, portable path edges, and exact Git commits.  It is canonical UTF-8
JSON with sorted keys and no insignificant whitespace.  Publication is an
atomic same-directory replacement.  A stale graph is rebuilt from manifests;
a malformed or future lockfile fails closed. Package manifest stamps hash the
exact validated UTF-8 manifest bytes, so either compiler detects every source
change without depending on a TOML serializer's formatting choices.

## Native link-plan schemas

The compiler result owns the validated native plan.  `--emit-link-plan PATH`
writes its canonical JSON representation while normal C emission continues.
`--target OS-ARCH` selects platform predicates; accepted aliases are `x64` for
`x86_64` and `arm64` for `aarch64`. The self-hosted `btrcc` requires this
option explicitly for every version-1 manifest and fails closed if it is
missing. The reference `btrcpy` may infer a supported host target.

Plans without compiler-emitted adapters retain the byte-compatible schema 1.
Schema 2 adds a nonempty `generated-units` array, sorted by unique identifier
`name`. Each record contains exactly `name`, `language`, `standard`,
`memory-management` and `source` (the emitted translation-unit text). It has no
package path: generated output must not masquerade as a source-package file.
The plan is the single published artifact, so it cannot refer to a half-published
adapter file. This is compiler output, not a new manifest input table.

Generated C uses `c11`/`manual`, C++ uses `c++17` or `c++20`/`raii`, and
Objective-C or Objective-C++ uses the matching standard with `arc`. The builder
enables C++ exceptions for RAII units, and Objective-C exceptions, ARC and ARC
exception cleanup for ARC units. These policies apply only to generated units;
handwritten Objective-C sources keep their existing memory-management behavior.
No unit accepts arbitrary compiler flags. Both ordinary and generated C++ units
participate in linker-language selection.

The builder validates the whole plan before invoking tools, writes generated
units only inside its private temporary build directory, and removes them after
success or failure. It replaces the requested executable only after a successful
link. Existing package-root/path validation remains unchanged for source units.

The plan contains the target, package roots and dependency aliases, selected
headers, include directories, defines, source compilation units, frameworks,
pkg-config requirements, and final linker language.  Paths in a generated plan
are absolute so a consumer can run from another working directory.  Package
and unit ordering is deterministic.  If any selected C++ or Objective-C++ unit
is present, `linker-language` is `c++`; otherwise it is `c`.

Plan packages and dependency edges are a closed projection of the modules
loaded from the compilation root. Native declarations are then selected from
that projection by module scope and target predicates. Unrelated packages and
native inputs remain validated and locked, but do not appear in the emitted
plan.

Compiler-owned standard-library metadata lives in `src/stdlib/btrc.toml`, using
this same schema and validator. Loaded modules select their native sources,
headers, frameworks and typed bindings before semantic imports run. The reserved
`btrc_stdlib_runtime` package owns all selected stdlib units; the compiler no
longer contains separate provider lists. Importing an unrelated pure module adds
no native package. The manifest travels with installed compiler data, is hashed
as a compiler input, and cannot declare package dependencies. Importing it never
writes a lock into compiler data. Custom pure-source stdlibs may omit it.

This preserves module-owned metadata in installed and relocatable compiler data
without placing an ambient checkout archive in a supposedly reproducible plan. Migrating a
provider replaces its manifest source unit with a module-owned header binding;
it does not require another compiler-specific provider branch.

Make, Nix, CMake, or another build adapter may realize this plan.  Generated
CMake is a projection of the plan and is never an independent metadata source.
The shipped `btrc-native-plan` adapter is the canonical Make/Nix consumer. It
accepts only a plan, generated C input, output path, and exact tool executable
names; it has no free-form flags or shell surface and never scans source
directories. `nix flake check` builds and runs `examples/native-package`
through the packaged compiler and adapter on every qualified flake system.
