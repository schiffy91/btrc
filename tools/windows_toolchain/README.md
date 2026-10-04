# Windows ARM64 compiler and ABI evidence

These CX-P1-03 tools separate the GNU compiler route from the MSVC GPU ABI.
Linux can cross-build an ARM64 PE image and inspect it. Native bootstrap,
MSVC CRT execution and wgpu callback evidence require a Windows ARM64 runner.

## Pinned inputs

`pins.json` records Zig 0.16.0 archive URLs, sizes and SHA-256 values from
`https://ziglang.org/download/index.json`. The Windows ARM64 ZIP digest is
`aee38316ee4111717900f45dd3130145c39289e105541d737eb8c5ed653c78ef`.
The wgpu-native 27.0.4.0 Windows ARM64 MSVC digest comes from
`nix/wgpu-native-prebuilt.nix` (CL-P1-02). Verify each downloaded archive before
extracting it. The installer must verify the Zig archive digest before adding
it to PATH; the helper validates its reported version. The PowerShell probe
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

Native commands require the canonical `WindowsJob` launch gate from
CX-P1-06/PR #43 to be integrated at `tools.target_hosts.windows.executor`.
They fail with that prerequisite if it is absent. This packet reuses that
owner instead of supplying another Windows process implementation. Python
captures partial output on timeout and owns Linux process groups; Windows
commands run inside the canonical kill-on-close Job, including descendants.
The PowerShell probe calls this same owner and never drains unbounded pipes.

Use ARM64 Python 3.13 and native ARM64 PowerShell 7. Install the pinned ARM64
Windows Zig archive on PATH. Download the Linux cross-built compiler artifact
into a separate directory; the native command rejects an output path that
would overwrite it.

```powershell
python -m tools.windows_toolchain.arm64 native --cross cross/btrcc.exe --cross-summary cross/summary.json --out build/windows-arm64-native
pwsh -NoProfile -File tools/windows_toolchain/msvc_probe.ps1 -WgpuArchive downloads/wgpu-windows-aarch64-msvc-release.zip
```

The native command first validates the Linux cross summary's host, mode, source revision, binary size/machine/hash, and ARM64 Python process architecture. It then builds its own compiler, compares its sample C bytes with
the Linux cross-built compiler's output, runs the compiled sample against its
golden, and invokes the repository's existing three-stage bootstrap test.
A skipped bootstrap cannot produce passing evidence. Each bootstrap stage
keeps the repository's 3,600-second Windows limit. No compiler/runtime edits
or alternative bootstrap implementation are supplied here.

The ABI probe discovers Visual Studio with `vswhere`, enters its ARM64
native developer environment, requires MSVC >= 19.40, records the SDK and
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
All Python helper commands have explicit subprocess deadlines.

## Integrator runner request

The workflow is integrator-owned under the current user instruction. This
packet contains no workflow or proposed-workflow file and no contract-test
row for a nonexistent job. The PR's REQUEST asks for:

1. An Ubuntu cross-build job in the pinned Nix shell, uploading
   `build/windows-arm64-cross/btrcc.exe` and its `summary.json`.
2. A `windows-11-arm` job with ARM64 Python 3.13, pinned action SHAs, the
   verified ARM64 Zig archive, and the verified wgpu archive. Download the
   cross artifact, run the native and ABI commands above, and always upload
   both output directories, including failure diagnostics.
3. Push/PR-to-main path filters covering the workflow itself,
   `tools/windows_toolchain/**`, compiler/runtime/stdlib inputs; manual
   dispatch; appropriate timeouts; CI policy/skip-contract rows added by the
   integrator if any pytest job is introduced.

Matrix/device updates remain PR-body proposals until native evidence exists.
GNU btrcc execution does not establish the MSVC GPU ABI route, and linking
wgpu does not establish a usable GPU adapter or platform GUI implementation.
