# Platform parity: iOS, Android and Windows

Status: proposed milestones for review, 2026-09-20. This extends
[PLAN.md](../../PLAN.md); it does not claim these platforms are qualified.
The code audit used btrc `4e5c98239868e805586524b4ee06424bf4556130` and
BTRSmith remote `5549c261`. No mobile/device or Windows execution was performed
for this document. Numeric budgets below are acceptance goals, not measurements.

The [native UI inventory and roadmap](native-ui-parity.md) adds the detailed
control, input, focus, layout, accessibility, OS-service and GPU requirements
across macOS and Linux as well as these three new platform families. Its UI0–UI11
milestones are part of the same plan. W2/I1/A1 consume the early native shell
and interaction slices; final P5–P7 qualification includes UI10. UI shell proofs
depend on host/binding prerequisites, not complete product milestones, so this
does not create a circular dependency. Extended UI11 capabilities used by an
existing product journey must be promoted into its release prerequisites.

## 1. Destination and definition of parity

Existing portable BTRC programs should preserve language semantics and public
stdlib contracts on these targets. BTRSmith must be installable and complete
its existing Library, Settings, import, playback, practice, rendering, input
and persistence journeys with the same domain/application code. A linked
sample, a rendered window, or a passing portable subset is an intermediate
milestone, not platform parity.

Inventory all existing public features, not only BTRSmith's immediate imports.
Classify each operation as:

- **Equivalent:** same public contract and behavior on the target.
- **Adapted:** a documented platform interaction achieves the same user goal,
  with tests for its different lifetime/permissions. Example: acquiring a
  document capability through a picker rather than opening an arbitrary path.
- **OS-restricted:** the platform cannot provide the original desktop
  operation under the supported application model. Record the exact restriction,
  diagnostic and product replacement. This does not count as equivalent.
- **Missing:** feasible but not implemented or verified. Keep it visible until
  fixed; do not reclassify it as a platform restriction to finish a milestone.

Report equivalent/adapted/restricted/missing totals separately, with immutable
inventory denominators for each release. No silent success stubs or broad
platform skips. OS-specific AppKit/ALSA entry points remain explicitly specific;
portable interfaces must resolve to the appropriate provider. Preserve current
macOS/Linux behavior while adding providers.

### Proposed support matrix

The OS floors below are recommendations to validate against retained hardware
and upstream dependencies in P0, not statements of current support. Pin exact
SDK/toolchain releases and minimum/latest test OS builds before implementation.
Reassess distribution requirements at release time from official guidance.

| Target product | Required architecture/environment | Proposed initial floor | Build host and compiler role |
| --- | --- | --- | --- |
| Windows desktop | x86_64 first; native aarch64 before final Windows parity | Windows 11; older Windows versions are a separately qualified extension | Native Windows reference and self-host compilers; macOS/Linux cross-build subset with a pinned Windows toolchain |
| iOS/iPadOS app | arm64 physical iPhone and iPad; arm64 simulator; simulator x86_64 only if the pinned Xcode/host matrix supports it | iOS/iPadOS 17 | macOS + Xcode SDK; both BTRC frontends run on the Mac and generate target code |
| Android app | arm64-v8a physical devices; x86_64 emulator and arm64 emulator where available | API 29 | Linux/macOS first, Windows host before final Android toolchain parity; pinned NDK/JDK/Gradle/Android SDK |

Separate host OS/architecture, target OS/architecture, ABI/environment,
deployment minimum and selected SDK. iOS device and simulator are distinct
artifacts even on arm64. Android is not a Linux GNU target. Windows GNU and
MSVC-compatible toolchains must have distinct identities and compatible native
dependencies. A target parser accepting a string establishes none of this.

Mobile application support does not require installing the compiler or Python
on a phone. Bootstrap runs on supported desktop compiler hosts; mobile output
runs in a signed application/test host. Windows must eventually bootstrap
natively, not only execute a compiler produced on another OS.

## 2. Evidence from the current tree

| Existing owner | Finding | Work this requires |
| --- | --- | --- |
| `src/compiler/python/frontend/packages.py::PackageTarget`, `src/compiler/btrc/frontend/Packages.btrc::FePackageTarget` | OS set is Linux/macOS/Windows and the model has only OS + architecture. | Add environment, ABI, deployment and SDK identity consistently; preserve existing spellings. |
| `src/compiler/python/frontend/native_imports.py` and self-host native reader | Python native imports accept explicit macOS or Linux GNU triples; Windows is rejected there. `WindowsMain.btrc` has no SDK-reader process provider. | Windows native bindings require both target support and a real host process implementation. Mobile native extraction needs matching SDK semantics. |
| `tools/native_plan.py` | Target validation admits three OSes; frameworks require macOS. Build argv is oriented around desktop cc/c++, pkg-config and executables, without a complete target-toolchain descriptor. | Carry target/sysroot/deployment/link/artifact kind explicitly; never compile for the host by accident. |
| `src/runtime/windows/README.md`, `btrc_win_compat.h` | A real supported compiler/portable subset exists. Process, raw terminal, sockets, Regex/glob and exact filesystem capabilities remain incomplete; Unicode coverage is partial. | Preserve working adapters, implement remaining OS providers, retire shims only after their consumers migrate. |
| `.github/workflows/windows.yml`, `Makefile` | Native Windows CI exercises bundling, selected programs, path/junction and compatibility seams. Distribution is Windows x64 with Zig/MinGW. | Extend the denominator, native bootstrap, SDK imports, provider execution and arm64 coverage. Wine is supplemental. |
| `src/runtime/c/threads.c`, `mutex.c`, `process.c` | Thread/mutex paths use pthreads; process implementation has POSIX contracts. Windows can use the already-established winpthreads ABI subset. | Qualify pthread behavior on each supported toolchain; provide real process/cancellation semantics where supported. Don't label existing threads absent. |
| `src/stdlib/{GUI,Audio,Image,Tray}/btrc.toml` | Provider selection currently names macOS and Linux implementations. | Add iOS, Android and Windows providers and target filtering; verify no foreign SDK imports leak into other targets. |
| `src/stdlib/GPU/btrc_gpu.c`, `btrc_gpu_async.c` | Windows synchronization/time branches already exist in the compute runtime. | Reuse them, but prove native dependencies, surfaces, rendering, async cancellation and device loss; these branches alone do not qualify Windows GPU support. |
| `src/stdlib/Platform.btrc` | Windows detection infers drive/UNC shape from the current working directory. | Use compilation-target identity/capabilities for provider selection; don't infer sandbox/OS support from cwd or compiler host. |
| `src/stdlib/FileSystem/FileSystemHandles.btrc` | Exact snapshots/private-directory capabilities explicitly reject Windows. | Define handle/ACL/reparse semantics and tests; this is load-bearing for product persistence, not an optional cleanup. |
| `src/stdlib/HTTP/HTTPClient.btrc` | HTTPS requests invoke a `curl` child process. | Preserve the public HTTP contract through a native transport on mobile and a dependable Windows deployment, without assuming a shell/curl binary is installed. |
| BTRSmith `flake.nix`, `make/Config.mk`, packages | Product packaging currently targets Apple Silicon macOS and x86_64 Linux; manifests/build rules cover SQLite, YAML, zlib, miniz, pugixml, vgmstream, PSARC and Sloppak. | Cross-build the full dependency closure and package the actual app. Audit process-owned audio, local control/MCP, filesystem and browser-launch assumptions. |

This is a source audit. Existing tests indicate intended coverage; their current
pass status on the new platforms must be established by execution.

## 3. Shared milestones

### P0 — Freeze the parity inventory and supported matrix

Dependencies: none. Exit: **100% of public exported stdlib operations and
existing BTRSmith feature journeys classified for all three platform families**,
with an owner, regression and current evidence status for every row.

1. Derive the public module inventory from every group `btrc.toml`, then include
   its public types/methods, runtime helpers, examples, corpus tests and native
   package contracts. Use the existing tests and a compact checked inventory;
   do not create a second language spec or generate thousands of empty tests.
2. Cover language/types/generics, ARC/cycles/exceptions, threads/atomics,
   collections/graphs/strings/math/date/random, file/stream I/O, Regex/glob, filesystem,
   process/terminal, HTTP client/server, digest/archive/database/media, jobs,
   IPC/daemon, application lifecycle, GUI/input/text, image/font, GPU/compute,
   audio/realtime, tray and diagnostics/tooling. Source absence from BTRSmith
   is not a reason to omit a public library feature.
3. Record compatibility/adaptation decisions for desktop process launching,
   terminal control, tray icons, daemonization, global shortcuts, arbitrary
   directories, dynamic code/plugins and local automation on mobile. Supply a
   supported product journey or an explicit unavailable contract for each;
   do not pretend a notification is an identical tray API.
4. Choose exact OS builds, SDKs, CRT/C++ runtimes, GPU backend versions and
   test devices. Proposed floors above remain editable until this checkpoint.
   Carry over existing stricter BTRSmith runtime budgets instead of relaxing
   them to meet this document.

### P1 — Target identity, ABI and native build artifacts

Dependencies: P0. Exit: both frontends build and run an ABI/callback fixture
on **Windows x64, iOS arm64 simulator/device, Android arm64/device + x86_64
emulator**; Windows arm64 joins no later than W2. No provider alias to a host OS.

- Extend shared target contracts, both package resolvers, provider filters,
  native semantic extraction, link-plan codec/reader and artifact cache keys.
  Specify target triple, environment, deployment/API minimum, sysroot/SDK,
  toolchain/CRT, architecture, build mode and artifact kind. Version schemas
  deliberately. Reject incompatible/missing settings before invoking a compiler.
- Use the same effective target arguments for header extraction and C/C++/
  Objective-C compilation. Verify reported pointer/scalar/enum/layout facts
  against native `sizeof`, alignment, offsets, by-value records, callbacks and
  function returns. Cover LP64/LLP64, `long`, `size_t`, `wchar_t`, variadics,
  nullable pointers, bool/char conversions, packing and atomics.
- Model executable, static library and shared library outputs, PIC, exports,
  symbol visibility, linker/library lookup, Apple frameworks, Android system
  libraries and Windows import libraries. Cache definitions distinguish device/
  simulator, Android API/NDK, GNU/MSVC ABI and debug/release. No host pkg-config
  or headers in a target build by accident.
- Add checked SDK availability/deployment facts where the API needs them;
  minimum-version code must not reference an unavailable symbol unguarded.
  Android API level must accompany the target compiler invocation, following
  the [NDK cross-build contract](https://developer.android.com/ndk/guides/other_build_systems).
- Package and execute the first minimal test apps early. Do not finish all
  Windows providers before discovering an iOS or Android target-model flaw.
  These are small test hosts, not the complete product shells of I1/A1.
  Use local C ABI fixtures first; full Windows SDK extraction is W1.
  Keep generated application C strict C11; native adapters retain their
  existing explicitly declared Objective-C/C++ language boundary.

### P2 — Hosted runtime and language semantics

Dependencies: P1. Exit: **100% of the inventoried portable language/runtime
corpus passes through both frontends on each required target environment**.
Report restricted OS tests separately; no hidden skip-based parity.

- ARC retain/release/adopt, cross-unit runtime state, cycle collection,
  destructor ordering, callback captures, weak/raw/native borrows, exceptions,
  setjmp cleanup, TLS and thread exit need target execution and sanitizer
  coverage where supported. Test objects crossing native callbacks and threads.
- Qualify existing pthread-backed `Thread`, `Mutex`, jobs, SPSC and atomics on
  Android/iOS/Windows toolchains. Implement missing primitives through the
  retained runtime owner; don't substitute a busy loop for blocking waits or
  silently weaken memory ordering. Check which atomic operations are lock-free
  before admitting them in realtime code.
- Audit clocks, sleep precision, locale, Unicode conversion, environment,
  errno/status translation, alignment, page sizes and dynamic loading. Platform
  probes become target-aware contracts with runtime capabilities where needed.
- A mobile test host executes fixtures without pretending every test is a
  shell process; preserve isolation, exit status, stdout/stderr and timeout
  semantics. Include cold-launch and repeated in-process compiler/runtime
  library calls where that API is supported.
- Reuse existing platform-neutral library tests for math, strings, containers,
  streams, dates, random, JSON/TOML and digests. Add fixtures for uncovered
  contracts, not copied platform-specific implementations of pure algorithms.

### P3 — Files, processes, networking and background work

Dependencies: P1–P2; individual providers can prove their slices early.
Exit: each applicable public operation has a real backend, negative/failure
coverage and a tested capability adaptation on restricted mobile operations.

**Filesystem/storage:** preserve UTF-8 public names and native Unicode paths,
large files/offsets, case rules, timestamps, symlinks/reparse points, durable
atomic replacement, locking, snapshots, recursive deletion, application data
and temporary/cache directories. Windows needs a handle-based design for
private-directory/ancestor-reparse guarantees and ACLs; falling back to path
strings or a root UID sentinel is unacceptable. Test untrusted path changes,
permission denial, long/UNC/non-ASCII paths and process interruption. Mobile
user documents are scoped capabilities or streams, not fabricated filesystem
paths. Support revocation, unavailable cloud files, nonseekable sources and a
bounded import into app-owned storage when a decoder requires random access.

**Process/terminal:** on Windows preserve argv, Unicode environment/cwd,
pipe I/O, bounded capture, timeouts, cancellation, exit codes, inherited-handle
control and cleanup of process trees. Use a real
[CreateProcessW provider](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)
with explicit inheritance. Add console/PTY/password/resize handling to match
existing terminal contracts. Mobile apps do not get a fictitious desktop
shell: unsupported subprocess/daemon/terminal calls fail explicitly, and
product uses must move to an allowed in-process or platform-service owner.
Land the minimal bounded Windows launch seam early for the SDK reader; it
belongs in the retained host/runtime owner and can use pre-authored runtime C.
Do not make launching the native reader depend on first importing the SDK
through that same unavailable reader. Expand the public Process contract from
that proven seam; native product adapters still use the generated binding path.

**Networking:** port sockets, HTTP framing/client/server, DNS, address families,
timeouts, cancellation and browser/open-URL actions. Recommend a checked native
HTTP transport (shared libcurl or platform providers selected after the API
audit), preserving size limits, binary bodies and error behavior. Verify TLS
trust/hostname handling, redirects, offline and permission states with local
test endpoints. No runtime dependency on a command-line curl executable.

**Jobs/IPC:** distinguish a thread-pool job from OS background execution.
Preserve cancellation/draining and bounded queues. Windows local channels need
peer identity/access control and single-instance behavior; mobile foreground
local control must respect sandbox and app lifecycle. Desktop daemon/process
owners remain separate from mobile scheduled work/audio services. Reuse the
same product command handlers; never invent a second mobile state machine.

**Remaining libraries:** finish Regex/glob/fnmatch parity with the existing
syntax/error contract, filesystem enumeration and malformed-input tests;
bring forward every P0 item not covered by the major providers above.

### P4 — Native dependencies, media and build integration

Dependencies: P1; ownership-sensitive execution also requires P2/P3.
Exit: all dependencies in the chosen product closure build for every required
ABI and pass their existing package tests via both frontends.

- Cross-build/pin SQLite, libyaml, zlib, miniz, pugixml, vgmstream and its selected
  codecs, PSARC/Sloppak consumers, wgpu-native, image and font dependencies.
  Record actual features, transitive libraries and disabled upstream options;
  do not drop a decoder/format from the parity denominator to get a build.
- Test database schema migrations/locking, archive traversal/limits, invalid
  inputs, exact media metadata, channel layouts, seeking, end-of-stream,
  streaming and resource closure. Include packaged asset access and sandboxed
  import. No assumption that all content lives at a seekable POSIX pathname.
- Inventory bundled and user-loaded plugins separately from data-only song/
  asset packages. Decide ahead-of-time code inclusion and runtime content
  loading per application model; preserve supported plugin behavior and make
  restricted executable extension points explicit instead of dropping them.
- Extend the existing native ABI/ownership mechanism for needed foreign facts;
  retain generated adapters and package-owned SDK selection. No handwritten
  per-product C/Objective-C/JNI bridge competing with the compiler's owner model.
- Build a reusable native artifact set consumed by the platform shell. Shell
  files may own required startup/build boilerplate, but domain, audio and GUI
  policy stay in BTRC owners. Keep package manifests/lockfiles authoritative;
  don't fork dependency versions between Make, Xcode and Gradle.
- Integrate M6a/M11 keys with SDK, target, availability, native headers, package
  settings and resources. Preserve split-unit state identity when units become
  a library, and validate every generated/native adapter in the final link.

## 4. Windows milestones

### W1 — Complete the Windows compiler host and native interop

Dependencies: P1–P3. Exit: native Windows x64 self-host fixed point, portable
corpus, SDK import/callback fixture and a relocatable compiler/tool bundle
that works outside the checkout with Unicode/space-containing paths.

- Supply `WindowsMain.btrc` with a Windows SDK-reader process provider using
  the normal driver/pipeline. Preserve bounded input/output, timeout,
  cancellation, launch errors and native-reader version checks.
- Support selected Win32 and COM metadata through the existing native reader,
  schema, analyzers and structured adapters: handles, HRESULT/status failure,
  GUIDs, calling conventions, COM AddRef/Release, out parameters, callbacks,
  apartment/thread affinity and asynchronous cancellation. Verify actual SDK
  types rather than manually transcribing layouts or vtables.
- Keep the working Zig/MinGW route first. Qualify a Windows SDK/clang-cl or
  equivalent MSVC-ABI route when required by dependencies; state what remains
  unsupported with MSVC itself rather than implying toolchain interchangeability.
  Test CRT/C++ ownership boundaries and allocator pairing.
- Fix UTF-8/UTF-16 across compiler arguments, source/import/cache paths,
  diagnostics, environment, SDK-reader invocation and bundle discovery.
  SDK extraction belongs to the build machine, never the shipped product.
- Extend Windows CI from examples to the inventoried applicable suite, debug
  line mapping, native plan realization and bootstrap. Preserve existing
  junction/path error tests. Test PowerShell/native invocation without requiring
  an MSYS shell in the installed user's environment.

### W2 — Desktop providers and shipped BTRSmith

Entry dependencies: W1 and P4. Exit: the provider suites and an installable
product candidate run on native x64 and arm64 hardware. Complete Windows
parity additionally requires P5–P7; emulated x64 is supplementary on ARM.

1. Recommend Win32-backed window/control providers behind the existing GUI
   interfaces first, avoiding a prerequisite to support arbitrary C++/WinRT
   templates. Cover all widgets, layout, clipping, scrolling, focus, keyboard/
   IME, Unicode editing/selection/undo, DPI changes, dialogs, clipboard, images,
   fonts, menus/tray and GPU child surfaces. Preserve platform controls and
   typed callbacks; don't scatter Win32 handles through product code. A later
   WinUI provider is a separate implementation choice. The
   [Win32 application model](https://learn.microsoft.com/en-us/windows/win32/learnwin32/your-first-windows-program)
   provides the bootstrap/message-loop boundary.
2. Implement audio against checked WASAPI/MMDevice contracts: capture/render,
   endpoint selection/change, format negotiation, event-driven buffer flow,
   clock mapping, shared-mode operation and supported exclusive-mode options.
   Handle device invalidation and permissions; preserve terminal-close behavior
   when the provider cannot prove release. Start with WASAPI; ASIO is an
   additional backend only if the existing product's qualified hardware needs
   it. [WASAPI source](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi).
3. Reuse the GPU runtime's Windows paths; prove the pinned WebGPU backend,
   HWND surfaces, resize/DPI, async readback, device loss, compute and packaged
   shader/assets. Keep image/font decoding and text metrics consistent with
   the portable interfaces; layout must work at 100%, 150% and 200% scale.
4. Ship a relocatable developer bundle and installable product. Recommend a
   normal unpackaged developer executable plus MSIX for qualified release
   delivery; verify deployment model before depending on package identity.
   Test install/update/uninstall, shortcuts/file associations, crash symbols,
   signed binaries and persistence. [Microsoft packaging guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/packaging/).

## 5. iOS/iPadOS milestones

### I1 — Application shell, UIKit and sandboxed storage

Dependencies: P1–P3; P4 provides product native libraries.
Exit: a signed physical-device application from each frontend supports the
real Library/Settings shell, file import and state restoration.

- Add explicit iOS device/simulator provider selection. Reuse Objective-C
  metadata, protocols/delegates, blocks and generated owner adapters with UIKit;
  don't alias `MacOS.GUIProvider` or use AppKit in a mobile package.
- Define application/scene startup, foreground/background, memory pressure,
  termination/relaunch and main-executor delivery. The OS owns the event loop;
  adapt existing `GUI.run/poll` assumptions through the application owner.
  Avoid synthetic desktop busy polling. Use
  [UIKit lifecycle guidance](https://developer.apple.com/documentation/uikit/managing-your-app-s-life-cycle)
  as the native boundary.
- Implement every applicable GUI interface: views/containers/text fields,
  selectors/sliders, scroll/grid, images/progress, dialogs and GPU view hosting.
  Add portable input/lifecycle facts only where needed for touch identity,
  cancellation, safe areas, on-screen keyboard/IME, orientation, scale and
  iPad resizing/multiple scenes. Do not force a desktop titlebar/window model
  onto an app screen or require a mouse to use existing product controls.
- Implement sandbox application directories, picker-based import/export,
  durable library references and user cancellation/revocation. Model acquired
  resource lifetime explicitly. Apple's document picker exposes scoped URLs;
  balance access through the same checked owner mechanism.
  [Document-picker contract](https://developer.apple.com/documentation/uikit/uidocumentpickerviewcontroller).
- Preserve SQLite/settings durability across suspension/termination and
  background-task expiration. File scanning/artwork work must be cancellable
  and restartable; do not assume an exit callback will flush pending data.

### I2 — Audio, GPU, packaging and full product parity

Entry dependencies: I1 and P4. Exit: the provider suites and a packaged product
candidate run on a physical iPhone and iPad, plus simulator CI. Complete iOS
parity additionally requires P5–P7 and minimum/current supported OS coverage.

1. Implement a real iOS audio provider using AVAudioSession and a qualified
   I/O AudioUnit (RemoteIO first). Desktop AUHAL device selection cannot be
   copied unchanged. Handle record permission, activation failure, actual
   negotiated sample rate/buffer size, interruptions, route changes, media
   services reset, external USB input/output and clock discontinuities. Define
   foreground practice and background playback policies independently; do not
   auto-resume input monitoring without the intended product action.
   [AVAudioSession](https://developer.apple.com/documentation/AVFAudio/AVAudioSession),
   [RemoteIO](https://developer.apple.com/documentation/audiotoolbox/kaudiounitsubtype_remoteio).
2. Build the pinned GPU runtime for device and simulator, use an appropriate
   Metal-backed surface and lifecycle, and qualify WGSL compute/rendering,
   readback, drawable unavailability, resize and suspension. A simulator
   screenshot does not prove physical GPU/audio correctness.
3. Package generated BTRC libraries/adapters, native dependencies, assets,
   entitlements, permission descriptions, deployment target and symbols in a
   reproducible Xcode-controlled application build. Version Xcode/SDK metadata;
   never reuse a simulator slice as a device slice. XCFramework/library
   packaging is useful when consumers embed BTRC, but does not replace the app.
4. Produce simulator and development-device builds, then a distribution archive
   with validation reports using configured signing credentials. Verify upgrade,
   uninstall/reinstall policy, document access and crash symbolication. Follow
   [Xcode distribution guidance](https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases).
   Preparing/validating artifacts is part of the milestone; external store
   submission remains a separate user-authorized action.

## 6. Android milestones

### A1 — Native app lifecycle, checked JNI and storage

Dependencies: P1–P3; P4 supplies product libraries.
Exit: an APK from each frontend runs on an emulator and physical arm64 device,
with real Library/Settings, text input, file import and process-death recovery.

- Use a small platform Activity/application shell with generated BTRC native
  code. Choose a standard Activity for native platform widgets plus a GPU
  surface; evaluate GameActivity only if it fits the existing GUI contracts.
  It is a lifecycle/input integration option, not proof that desktop widgets
  have mobile providers. [GameActivity](https://developer.android.com/games/agdk/game-activity).
- The Clang header reader cannot supply arbitrary Java/Kotlin declarations.
  Add a narrowly scoped checked JNI boundary: method/field descriptors from
  SDK/class metadata, reference ownership, nullability, exceptions, callback
  lifetimes, thread attach/detach, local/global reference limits, UTF conversion
  and UI-executor requirements. Generate adapters through the normal shared
  schema/IR owners; avoid handwritten per-product JNI functions and ad hoc
  selector strings. Kotlin/Java startup boilerplate must not own product policy.
  [JNI lifecycle guidance](https://developer.android.com/ndk/guides/jni-tips).
- Implement the GUI interfaces using platform views/controls and bounded
  native callbacks, including IME/keyboard, focus, selection, scrolling,
  touch cancellation, insets, Back navigation, rotation and density changes.
  Surface destruction and Activity recreation must not destroy an unrelated
  live audio owner or retain a stale Activity.
- Support app-private storage and the Storage Access Framework. Persisted
  document/tree grants, content URIs and descriptors need checked owners;
  a content URI is not a POSIX filename. Exercise revoked grants, nonseekable
  streams, provider errors, cancellation and process recreation.
  [Android document access](https://developer.android.com/training/data-storage/shared/documents-files).
- Match network/record permissions, external intents/browser launch,
  background limits and product command routing. Distinguish pending OS
  permission from success or unsupported. A service is not a portable daemon.

### A2 — Realtime audio, GPU and installable distribution

Entry dependencies: A1 and P4. Exit: provider suites and a packaged product
candidate run on at least two physical Android vendors and in both 4 KiB/
16 KiB environments. Complete Android parity additionally requires P5–P7
and minimum/current supported OS coverage.

1. Begin with a checked AAudio C provider at the proposed API floor; evaluate
   Oboe's device handling if direct AAudio misses hardware coverage or latency
   goals. If Oboe is adopted, prove the needed C++ adapter subset rather than
   introducing unchecked ownership. Negotiate actual rates/bursts/channels,
   bound buffers and record xruns, disconnects and clock drift. Keep callbacks
   free of allocations, blocking and JNI/UI work. Qualify audio focus,
   permission, route change, interruption and permitted background playback.
   [Android low-latency guidance](https://developer.android.com/games/sdk/oboe/low-latency-audio).
2. Build the pinned WebGPU backend for the selected Android ABIs and native
   surface, beginning with Vulkan where supported. Define capability failure
   for devices lacking required GPU features; an alternate backend needs the
   same tests. Exercise surface replacement, app pause/resume, orientation,
   memory pressure, driver/device loss, compute and readback.
3. Pin NDK/JDK/Gradle/SDK and package native `.so` files, generated adapters,
   Java shell, permissions, resources, C++ runtime where used and debug
   symbols. Verify ABIs, exported entry points and all transitive libraries.
   Produce a debug APK and a validated release APK/AAB with configured signing.
4. Require 16 KiB-compatible native allocation assumptions, ELF and package
   alignment for **every** native dependency, and execute in both page-size
   environments. Do not postpone this until store submission or assume the
   top-level binary fixes third-party libraries.
   [Android page-size requirements](https://developer.android.com/guide/practices/page-sizes).
   Recheck current target-SDK/distribution requirements when pinning release
   tooling; this document intentionally does not freeze a moving store deadline.

## 7. Product and qualification milestones

### P5 — Existing BTRSmith journeys on each platform

Dependencies: working target shell/providers and P4, completed incrementally.
Exit: **100% of P0's existing product journeys passed or explicitly classified
as OS-restricted with a reviewed replacement; zero unclassified/missing core
Library/Settings/playback/practice journeys**.

Use unchanged domain/application logic wherever its contract is portable.
Fix a wrong stdlib abstraction at its owner; don't fork the application three
ways or reintroduce native wrappers in the product. Mobile layout/navigation
may adapt intentionally while preserving reachable controls and behavior.

Required journeys include:

- Import the currently supported local package/media formats, validate them,
  scan and rescan, cancel, remove a library source, survive unavailable/revoked
  storage, restore settings/catalog and recover from interrupted writes.
- Browse/search/filter/sort the same large library, load artwork progressively,
  preserve navigation history, change settings and resize/reorient with usable
  native text input. Every applicable desktop control has a reachable mobile
  path; no hover-only action on touch devices.
- Open a chart, select arrangement/instrument, play/pause/seek/replay at end,
  change rate/pitch/volume and practice sections according to existing product
  capabilities. Preserve rendering, timing, effects and decoder behavior.
- Use actual instrument input and output, change/disconnect devices, interrupt
  and resume, close/reopen, switch app/scene and handle denied permissions.
  Desktop process-owned audio needs an explicit mobile ownership adaptation;
  sharing the command/state model does not require an unsupported subprocess.
- Preserve local automation/MCP/control commands where the OS permits them;
  expose a supported app-lifecycle-scoped transport or documented restriction.
  Do not open an unrestricted network listener to emulate a private channel.
- Install/update/relaunch the packaged app with real assets, import user data,
  inspect captures and symbols, and verify persistence and clean shutdown.

Run existing integration fixtures with platform adapters and real dependency
libraries. Native UI screenshots, physical audio and package installation are
separate evidence from model/command tests.

### P6 — Numeric build and runtime acceptance

Use the measurement rules in PLAN.md, with frontend/mode/target/SDK and hardware
recorded. At least 5 cold builds and 20 edit/no-op samples per artifact variant;
report medians, p95, maximum, failures and actual rebuild counts. Dependencies,
compiler tools and signing credentials are preinstalled; initial SDK downloads,
emulator startup and credential prompts are timed separately, never hidden.

Final **self-host** product build goals after M6a/M11 integration:

| Scenario | Windows | iOS/iPadOS | Android |
| --- | --- | --- | --- |
| Cold dev package, one architecture | ≤30 s | ≤45 s | ≤60 s |
| One private-body edit to installable dev artifact | ≤10 s; p95 ≤15 s | ≤15 s; p95 ≤20 s | ≤20 s; p95 ≤30 s |
| No-op through actual platform build driver | ≤2 s | ≤3 s | ≤5 s |
| Install/relaunch on already-running local test target, incremental artifact | ≤5 s | ≤15 s | ≤15 s |
| Cold reference-frontend dev package | ≤90 s | ≤120 s | ≤150 s |
| Reference private-body edit to installable artifact | ≤15 s | ≤20 s | ≤30 s |

Cold package includes BTRC analysis/lowering, native compile/link, packaging
and local development signing when required. For mobile, edit/deploy medians
combine to **≤30 s iOS / ≤35 s Android**. Simulator and physical-device results
are separate; simultaneous multi-ABI archives are separate scenarios. Before
M11, publish actual baselines and aim for at least **30% improvement** over
those baselines; do not claim the final latency targets are already achieved.
Compiler memory goals remain ≤1.5 GiB per frontend and ≤6 GiB aggregate build
RSS at the fixed native job count. Explain host/toolchain differences.

Runtime workload: a fixed **10,000-song / 1,000-album** catalog with named artwork
assets and a pinned representative chart/audio fixture. If the current product
acceptance fixture is larger, retain it. Use the same data on all platforms;
import/scanning and a pre-indexed launch are separate measurements.

| User-visible or lifecycle metric | Proposed acceptance |
| --- | --- |
| Pre-indexed cold launch to interactive Library | p95 ≤3 s desktop, ≤4 s mobile over 20 launches |
| Local catalog search/filter to visible result | p95 ≤100 ms after input debounce, with debounce reported separately |
| Visible navigation/button response, excluding explicitly pending I/O | p95 ≤100 ms |
| Library scroll and Player at 60 Hz | p95 frame time ≤16.7 ms, p99 ≤33.3 ms over 10 minutes; report missed presents |
| Steady product working set, same catalog/chart | ≤512 MiB desktop; ≤384 MiB mobile, including GPU/native resources with separate accounting |
| Repeated lifecycle ownership | 100 open/close/route-change/recreate cycles, zero leaked live handles/callback owners; settled memory growth ≤5% after warmup |
| Controlled audio soak | 30 minutes with zero app-induced xruns/dropouts; 2-hour physical release soak separately |
| Realtime callback execution | p99 ≤50% and p99.9 ≤75% of the negotiated buffer period; zero forbidden allocation/blocking paths |
| Wired instrument round-trip latency on qualified hardware | p95 ≤20 ms Windows/iOS, ≤30 ms Android; record sample rate, actual buffers, interface and measurement method |
| Ordinary graceful close/drain | p95 ≤2 s, no late callback use-after-free; terminal provider failure remains explicit |
| Pause/resume/permission/route recovery | 100 scripted cycles without crash, duplicate playback or lost durable state; report recovery duration separately |

These budgets require real measurements on named reference devices, not a
claim that every phone/audio interface can satisfy them. Bluetooth and emulator
audio are separate from wired instrument qualification. Measure physical
round-trip latency with a loopback/input-output setup; callback duration alone
is not latency. Measure retained OS/native resources as well as BTRC counters.
Do not relax an existing stricter product requirement. Budget misses remain
open milestones with evidence and a proposed remedy.

### P7 — Continuous qualification, packaging and release evidence

Dependencies: all applicable shared/platform/product milestones. Exit: the
complete declared matrix passes on the same source revision and package set.

- PR CI: schema/target/manifest/provider filtering, generated-source/structure
  gates, Python and self-host focused parity, cross-build/ABI checks and cache
  invalidation. Preserve current macOS/Linux gates and bootstrap sequencing.
- Extended CI: full applicable corpus through both frontends; Windows native
  x64 + arm64 bootstrap/provider checks; iOS simulator apps; Android emulator
  apps at minimum/current API and 4/16 KiB page sizes. Use the real native
  compiler at O0/O2 on mobile, and additional supported optimization levels
  before release. macOS/Linux retain the existing full strict-C11 matrix.
- Physical release qualification: Windows x64 and ARM hardware, iPhone and
  iPad, at least two Android vendors (one minimum-floor representative and one
  current/16-KiB configuration). Keep recorded GUI/GPU/audio results distinct
  from virtualization. Required device coverage that is unavailable is an
  unfinished gate, not a pass.
- App journey stress covers denied/revoked permissions, low storage, absent
  devices, corrupt media, native initialization failure, OS suspension,
  process death, GPU loss, callback races and upgrade from the previous package.
  Run sanitizer configurations supported by each target/toolchain and identify
  omitted sanitizer coverage rather than silently claiming equivalence.
- Developer tools: source-mapped debug builds, generated/native symbols,
  exception/crash stacks into `.btrc`, profiler attachment and actionable
  diagnostics on each target. Extend existing LSP/DAP owners for target-aware
  imports and device launch/attach where required; no parallel debugger stack.
- Release artifacts: compiler bundle where applicable, app package, symbols,
  dependency/license notices, checksums and a concise support/coverage report.
  Reproduce unsigned code/resources before signing; signatures/timestamps need
  not be byte-identical. Validate install/update/uninstall and native library
  loading from an unrelated cwd/user account.
- Use configured signing credentials; do not embed secrets or bypass signing.
  Creating a store account, accepting agreements and external store submission
  are separate authorized actions. Missing signing/device access does not
  prevent compiling, simulator checks or preparing a reviewable artifact.

## 8. Execution order and completion rule

Platform foundations are **bucket 3**, after compiler performance and
C compatibility, under [PLAN.md's sequential execution order](../../PLAN.md#execution-order-five-buckets).
The UI portions of the platform milestones run in bucket 4; final installed
product qualification runs in bucket 5. Do not start a platform implementation
as a parallel track beside the active compiler-performance milestone. The
sequence below describes platform dependencies within those scheduled buckets.

P0 → P1 with tiny apps on **all three** platforms → P2/P3/P4 shared contracts
→ W1 and the I1/A1 shells → W2/I2/A2 providers → P5/P6/P7 qualification.
These are dependency lanes, not instructions to spawn agents. Work one bounded
contract at a time; keep other platforms' incomplete rows visible.

Recommend Windows host/filesystem/process first where it unlocks reuse and
native SDK testing, while proving the mobile target and JNI/Objective-C paths
early within bucket 3. Do not postpone Android's bridge or iOS lifecycle
discovery until after a full desktop port. M6a/M11 preserve target identity in
their contracts; that design constraint does not start the port ahead of its
scheduled bucket.

A platform is complete only when its inventory, language/runtime behavior,
applicable stdlib APIs, native packages, BTRSmith journeys, numeric budgets and
installable artifacts are qualified. A narrower checkpoint must state its exact
subset and remaining missing/restricted counts. Maintain one ownership model,
one structured compiler pipeline and platform-selected providers throughout.
