# Windows ARM64 compiler and ABI evidence

These CX-P1-03 tools separate the GNU compiler route from the MSVC GPU ABI.
Linux can cross-build an ARM64 PE image and inspect it. Native bootstrap,
MSVC CRT execution and wgpu callback evidence require a Windows ARM64 runner.

## Current qualification

Native run [37576400208](https://github.com/schiffy91/btrc/actions/runs/37576400208)
stopped at the report regression: detached PowerShell returned success with no
JSON, even with an encoded command. No native compiler or bootstrap was run.
The launch gate now starts targets with `CREATE_NO_WINDOW` while the gate itself
remains detached. Explicit standard handles and Job Object ownership are
unchanged. Microsoft's [process creation flags](https://learn.microsoft.com/windows/win32/procthread/process-creation-flags)
define this as console execution without a visible console window. The native
report regression must pass before attributing the empty report to these flags
or claiming this repair works on Windows. Local process regression coverage is
116 passed, one native-only skip, and eight subtests under Python 3.13.

## Pinned inputs

`pins.json` records the Zig 0.16.0 Windows ARM64 archive URL, size and SHA-256 from
`https://ziglang.org/download/index.json`. The Windows ARM64 ZIP digest is
`aee38316ee4111717900f45dd3130145c39289e105541d737eb8c5ed653c78ef`.
The wgpu-native 27.0.4.0 Windows ARM64 MSVC digest comes from
`nix/wgpu-native-prebuilt.nix` (CL-P1-02). Verify each downloaded archive before
extracting it. The installer must verify the Zig archive digest before adding
it to PATH; the helper validates its reported version against `pins.json`.
Linux uses the flake-pinned Zig, so no unused Linux archive pin is retained. The PowerShell probe
verifies the wgpu archive digest itself.

## Linux cross-build

From the repository root, in the pinned development shell:

```sh
python -m tools.windows_toolchain.arm64 cross --out build/windows-arm64-cross
python -m tools.windows_toolchain.arm64 pe --cross build/windows-arm64-cross/btrcc.exe --out build/windows-arm64-pe
```

The cross-build uses `cli/WindowsMain.btrc`, explicit
`aarch64-windows-gnu`, strict C11 and the existing Windows compatibility
header. `summary.json` records the source revision, Zig version, exact argv,
exit codes, PE machine `0xAA64`, artifact SHA-256 and `native_execution:
not-run`. Command stdout/stderr are retained beside the report. A Linux
cross-build is not bootstrap or Windows execution evidence.

## Native Windows ARM64

Windows commands use the integrated `tools.target_hosts.windows.executor.WindowsJob`
owner and its gated launch: assignment precedes target execution, cleanup kills
and drains the whole job, and file-backed captures survive inherited output
handles. Missing target executables retain the gate's structured launch error.
Linux commands reuse `bundle.run_build_command` and its process-group cleanup.
There is one Windows containment owner and no external-containment opt-in.
The target table, PE parsing and strict C flags also come from the shared host.

Use ARM64 Python 3.13 and native ARM64 PowerShell 7. Install the pinned ARM64
Windows Zig archive on PATH. Download the Linux cross-built compiler artifact
into a separate directory; the native command rejects an output path that
contains either the input executable or its provenance summary.

```powershell
python -m pip install '.[dev]'
python -m tools.windows_toolchain.arm64 native --cross cross/btrcc.exe --cross-summary cross/summary.json --out build/windows-arm64-native
pwsh -NoProfile -File tools/windows_toolchain/msvc_probe.ps1 -WgpuArchive downloads/wgpu-windows-aarch64-msvc-release.zip
```

The native command first validates the Linux cross summary's host, mode, source revision, binary size/machine/hash, and ARM64 Python process architecture. It then builds its own compiler, compares its sample C bytes with
the Linux cross-built compiler's output, runs the compiled sample against its
golden, and invokes the repository's existing three-stage bootstrap test.
A skipped bootstrap cannot produce passing evidence. Each bootstrap stage
keeps the repository's 3,600-second Windows limit. The native sequence has one
12,000-second monotonic deadline; every command is capped by its remaining
budget so failure reporting precedes the hosted step's 210-minute deadline. No compiler/runtime edits
or alternative bootstrap implementation are supplied here.

The ABI probe requires Visual Studio's ARM64 and Clang components through
`vswhere`, records `installationVersion`, and enters its ARM64
native developer environment via a temporary `.cmd` script (no nested command-line
quoting). Developer-command diagnostics go to stderr; paths containing carets,
percent signs, quotes or line breaks fail before invocation. It records the detected MSVC version even if it is rejected, requires MSVC >= 19.40, records the SDK and
clang versions, and runs a strict C11 hello with the pinned
`aarch64-pc-windows-msvc19.40.0` triple. It verifies the wgpu archive digest,
links its MSVC import library, and runs `wgpu_link_smoke.c` beside the DLL.
The smoke requires instance creation and a completed adapter callback.
An unavailable adapter is recorded without claiming rendering support.
The callback loop has a ten-second window; the launcher has a thirty-second
process limit. The JSON preserves partial/failed results and exact errors.

## Portable validation

```sh
python -m unittest tools.windows_toolchain.test_arm64 -v
pwsh -NoProfile -File tools/windows_toolchain/test_probe.ps1
cc -std=c11 -Wall -Wextra -Werror -pedantic-errors -fsyntax-only \
  $(pkg-config --cflags wgpu-native) tools/windows_toolchain/wgpu_link_smoke.c
```

PowerShell parsing/version/hash cases are portable stand-ins, not MSVC runs.
All Python helper commands have explicit subprocess deadlines. Windows-native
containment and Visual Studio execution require the hosted lane described below;
portable mocks do not establish those behaviors.

## Hosted qualification

`.github/workflows/windows-arm64.yml` owns the lane. It runs portable tooling
checks and a Linux cross-build, uploads the compiler and provenance, then uses
`windows-11-arm` with ARM64 Python 3.13 and native PowerShell. The native job
installs checksum-verified Zig/wgpu archives and `.[dev]`, runs the Python and
PowerShell regression suites, qualifies compiler/bootstrap, and separately runs
the MSVC ABI probe even if compiler qualification fails. Both evidence folders
are retained on failure. All actions are pinned; the Nix cache disables FlakeHub.

The native compiler step has a 210-minute outer deadline, the ABI probe 15 minutes,
and the job 240 minutes. The shared Job owner also bounds every command. Successful
portable mocks or a Linux PE inspection do not satisfy the native acceptance rows.
The runner records its actual image/version; the current `windows-11-arm` image
is the Visual Studio 2026 ARM64 image, not an x64 emulation substitute.

Matrix/device updates wait for the actual run artifacts. GNU btrcc execution
does not establish the MSVC GPU ABI route, and linking wgpu does not establish a
usable GPU adapter or platform GUI implementation.

At revision `957126d6`, [hosted run 37560567746](https://github.com/schiffy91/btrc/actions/runs/37560567746)
passed the Linux cross-build and the native ARM64 MSVC/wgpu probe: Visual Studio
18.10.12217.157, MSVC 19.51.36260, SDK 10.0.26100.0, Clang 22.1.8, strict-C11
hello, wgpu instance creation and adapter callback (adapter present). These are
stand-in execution results, not GUI/rendering or physical GPU qualification.

The native Python tooling suite passed 22/23 tests. Its missing-executable
check failed because Windows' error message omitted the executable name; the
capture now explicitly retains that name beside the structured Win32 error.
The failed tooling step prevented native compiler/bootstrap execution, which
remains unqualified until a new complete run passes.

At `bd36d38b`, [run 37564453309](https://github.com/schiffy91/btrc/actions/runs/37564453309)
passed the repaired tooling, Linux cross-build and MSVC/wgpu probe. Native
Python transpilation succeeded, but Zig's native C build exited with
`0xC0000005` and no stderr, before a native btrcc executable or bootstrap was
produced. The Linux and Windows generated C files were byte-identical
(70,724,834 bytes, SHA-256
`c83fe2d954d7791966a589b42fcc51bfcc8167b742d491070f1983c6106654a5`).
The crash cause remains unqualified. Builds now retain verbose compiler
diagnostics and generated-source identity; a failed Windows command also
collects read-only capacity and recent Zig/Clang/linker application crash
events under a separate 20-second bound. Partial diagnostics and diagnostic
failures cannot replace the original error or produce a passing report.

At `347dca91`, [run 37567934632](https://github.com/schiffy91/btrc/actions/runs/37567934632)
again passed the cross-build, native tooling and MSVC/wgpu checks. The native
C build reached its unchanged 3,600-second deadline; no native btrcc execution
or bootstrap occurred. Its generated C has the same hash above. Partial stderr
contains one compiler-runtime archive command and does not identify the stalled
phase. The diagnostic subprocess exited zero with empty stdout/stderr, leaving
the host capacity and crash cause unobserved.

The diagnostic command now uses PowerShell's documented
[UTF-16LE `-EncodedCommand` argument](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_pwsh)
and validates a versioned JSON report before accepting a successful diagnostic
process. This removes multiline command quoting from the diagnostic path;
it does not establish the cause of the empty output or the compiler timeout.
A Windows-only regression executes the actual command through the shared Job
owner and requires real host capacity in its report before the expensive native
compiler step runs. Partial output and the original compiler error remain
preserved if diagnostics fail. Native compiler/bootstrap qualification is still
required.


At revision `9480f89f`, hosted run `37578721489` passed the actual native
Job/CIM report regression and all 28 Python tooling tests. The console launch
repair therefore has native evidence. The later deadline probe and MSVC setup
failed with a sharing violation on a captured stderr file; compiler/bootstrap
did not run. The exact holder was not identified.

Capture disposal now retries only Windows sharing violations for at most five
seconds after Job termination, gate reaping and the empty-Job check. A persistent
lock still fails and retains the command status, partial streams and capture
path instead of replacing them with a directory-cleanup exception. Fault-injected
checks cover transient release, persistent lock and unrelated permission errors;
they do not establish native Windows success. The actual deadline/MSVC and
compiler/bootstrap lane must pass on the new revision.

At `7cb3770b`, [run 37581720184](https://github.com/schiffy91/btrc/actions/runs/37581720184)
passed all 31 native Python tooling tests, the deadline/PowerShell probes, and
the native MSVC/wgpu lane. Capture disposal no longer blocked these checks.
The GNU-route C build again exited with `0xC0000005`, with empty stderr despite
`-v`; native btrcc execution and bootstrap did not run. The generated C hash is
unchanged. The retained host report is now valid: roughly 12.8 GiB physical
memory remained free after the failure, and no matching application crash event
was found. This is a post-failure observation, not a peak-memory measurement or
a proven explanation for the crash.

Native qualification now first requests the C frontend's version and compiles
a small ordinary C program with the same strict flags, Windows overlay, target
and shared Job owner. The resulting ARM64 image must execute and preserve
separate stdout/stderr sentinels before the large compiler build begins. Each
command records its elapsed duration. This distinguishes an early toolchain or
stdio failure from one requiring the generated compiler input; it neither
substitutes for bootstrap nor changes the compiler pin, flags or deadlines.

At `f2476cc2`, [run 37584587972](https://github.com/schiffy91/btrc/actions/runs/37584587972)
passed both version probes, 34 native Python tests and the separate MSVC/wgpu
lane. The tiny C build exited with `0xC0000005` in 0.158 seconds and emitted no
stderr, before compiler transpilation. The large generated input is therefore
not required to reproduce the failure. Native GNU-route compilation and
bootstrap remain unqualified.

At `0423088d`, [run 37589160851](https://github.com/schiffy91/btrc/actions/runs/37589160851)
again failed the tiny build before compiler transpilation. Its six diagnostic
commands passed object generation and Windows-overlay preprocessing, but the
driver-plan, two syntax and link commands crashed without output. These results
do not yet distinguish frontend failure from link setup: the verified
[Zig 0.16.0 source archive](https://ziglang.org/download/0.16.0/zig-0.16.0.tar.xz)
shows `src/main.zig` defaulting `c_out_mode` to `.link`; forwarding `-###` or
`-fsyntax-only` to Clang does not select object mode.

The driver-plan and syntax diagnostics now also specify `-c`. A verbose object
compile separately checks diagnostic output without requesting a linked image.
The ordinary object, link and overlay-preprocessing probes remain. Each of the
seven commands uses the same pinned Zig and Job owner with a 60-second limit
inside the overall native deadline. Their results are diagnostic only; even if
every diagnostic succeeds, the original build failure remains the qualification
result. Native results for the corrected probes are pending.
