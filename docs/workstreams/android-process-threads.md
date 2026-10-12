# Android process-thread count: prerequisite finding

Packet CX-P2-Android-ProcessThreads, private base `36b647f079ed7338e51b119a11046eb222dd4877`.
No dependency on unaccepted PR70 is needed to reproduce this blocker. The Linux
provider and reference package owner are identical between this base and `5be08004`;
the ProcessThreads contract file differs only in Windows documentation.

The live-thread count API promises the calling process count, including its caller,
or -1 when the host cannot determine it. Android has no selected provider. The
existing Linux implementation enumerates `/proc/self/task`; its behavior on
Android has not been qualified and is not inferred from Linux.

## Actual metadata evidence

A fresh exact Git archive of 101 reference compiler and BackgroundJobs files was
read with the real `PackageImportPolicy`, `PackageTarget`, and manifest validator.
Linux x86_64 and macOS aarch64 controls resolved their existing providers. Android
x86_64 and aarch64 both raised `has no provider for target android-...`. Adding
`android` to an in-memory copy of the existing selector then raised
`package.providers.os contains unsupported value 'android'`. Source bytes and
modes remained identical. This is reference metadata evidence, not compilation,
SDK header projection, selfhost parity or Android execution.

Retained private packet: `/private/tmp/btrc-audit-repair/android-process-threads-36b647f0`.
`metadata-baseline.py`, `metadata-baseline.json` and `metadata-source.json` retain
the actual command, diagnostics and archive inventory. Command:

```sh
/nix/store/35r726j0hx21698i9p7ry53l1afprc84-python3-3.14.6-env/bin/python3 -B /private/tmp/btrc-audit-repair/android-process-threads-36b647f0/metadata-baseline.py
```

## Required paired prerequisite

```text
REQUEST(CL-P1-14): Complete approved mobile provider-filter support before adding an Android ProcessThreads provider.
Repro: PackageImportPolicy(PackageTarget.parse("android-x86_64")).provider_for(<stdlib>/BackgroundJobs/ProcessThreads.btrc) rejects the current module; PackageManifestValidator.providers rejects a copied selector containing android. The aarch64 row has the same actual result. Selfhost Packages.btrc:732 still restricts providers to linux/macos/windows; no selfhost execution is claimed.
Expected / actual: Approved platform-target-contract.md §5 admits OS values from all target rows and enforces platform-directory ownership. Current reference packages.py:59,1266 uses compiler-host rows only; the selfhost parser likewise excludes Android.
Blocks: A valid Android provider/native binding fragment, paired target projection and actual SDK/API29+36 count qualification.
Workaround in this branch: none. Do not omit OS restrictions, classify Android as Linux, modify generated data, or use a host stub.
```

The approved directory rule requires a Linux/ implementation to select Linux
only. After the paired prerequisite lands, the provider owner must choose the
approved platform-neutral shared owner or an Android owner; simply widening the
Linux/ selector is not an approved final design. Any compiler-import change must
retain WORKSTREAMS §3.4 own-binary/bootstrap/host-entry warning and C-parity gates.
No root API, worker pool or generated symbol change is proposed.

A separate source-inspected prerequisite remains for genuine NDK header bindings.
Both current native importers admit macOS, Linux GNU and Windows MinGW triples
only (`native_imports.py:797-814`, `NativeImports.btrc:2560-2573,3190`). An Android
triple is not accepted. This was identified by source review, not an executed SDK
probe; it must not be reported as a reproduced header failure.

```text
REQUEST(CL-P1-10): Complete the approved target-row-driven native importer for Android SDK bindings.
Repro: Read the current paired native target admission above and platform-target-contract.md §3; Android targets are absent from the accepted reader triples. No SDK execution was attempted because no local NDK is installed.
Expected / actual: The actual selected Android target and genuine NDK sysroot must reach the native reader; current admission supports only the three desktop host families.
Blocks: Typed SDK bindings for the native ProcessThreads test fixture and future Android providers.
Workaround in this branch: none; do not pass a Linux/MinGW triple or handwritten ABI to simulate Android.
```

## Existing SDK host and pending native gate

No Android SDK/NDK is installed at the inspected local SDK paths or retained Nix
store, and the existing AndroidHostBuilder selects Linux x86_64 NDK tools. No
SDK installation, emulator action or guest launch was attempted. A later allocated
Linux SDK host must first run the existing version check:

```sh
python3 -B -m tools.target_hosts.android.sdk verify --sdk "$ANDROID_SDK_ROOT"
```

Use the exact versions in `nix/platforms.nix` (currently NDK 29.0.14206865), not a
new toolchain. Existing host qualification commands are:

```sh
python3 -B -m tools.target_hosts.android.build --ndk "$ANDROID_NDK_HOME" --output build/android-host-x64 --app
python3 -B -m tools.target_hosts.android.check --boot --state build/android-avds --api 29 --bundle build/android-host-x64 --output build/android-api29.json
python3 -B -m tools.target_hosts.android.check --boot --state build/android-avds --api 36 --bundle build/android-host-x64 --output build/android-api36.json
```

These commands build the host's handwritten probe and run its original 28 cases;
they do **not** compile or qualify ProcessThreads. A future provider fixture must
emit real BTRC C through both current frontends, compile it against the actual NDK
for x86_64 and aarch64 with strict C11 flags, and exercise API29/API36 through the
existing AndroidEmulatorExecutor shell-bundle interface. Keep its real supervisor,
`prepare`/`run(ExecutionRequest)`/`close` lifecycle and original bounds. Do not edit
that host builder's fixed probe, invent an executor wrapper, or claim arm64 or
16 KiB runtime from x86_64 results.

The smallest provider oracle needs a known single-thread count, several held
pthread workers counted before release, return to the original count after join,
an unrelated child not added to this process count, and failure-path -1/descriptor
closure. Those tests have not been written or run because manifest admission is
blocked. Any workflow scheduling belongs to the integrator through a separate
REQUEST(CL-UIA-02); no workflow or expected-skip rows changed here.

No CI, native provider acceptance or full mobile GUI capability is claimed.
