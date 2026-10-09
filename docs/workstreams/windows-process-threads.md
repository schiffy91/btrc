# Windows process thread count

Source draft against `3e02deba`; no provider projection or native test has run.
The existing Toolhelp importer prerequisite is independently qualified: 155 paired
macro/codec cases and four genuine x64/ARM64 SDK projections passed, with result
`a32d159f2e60807cfed9d36073630fac1f0cd8ef41dff29742e684152eae503a` and
independent audit `09b252f0e23e39c1115cbea02fe6e1810d3cc891aa35692b099d71dd9fd47948`. This draft does not
change Windows worker-pool behavior or the count()/−1 public API.

The provider owns one real Toolhelp snapshot, resets the input record size before
every enumeration call, checks the SDK-derived owner-field extent before reading
that field, and filters GetCurrentProcessId(). It rejects counter overflow and
unknown/empty results. It captures GetLastError before a single CloseHandle
attempt; only ERROR_NO_MORE_FILES plus successful close is a completed result.
The header provides SDK includes and one SDK-derived extent constant, no wrapper
implementation or fabricated ABI. The final provider/binding manifest fragment is committed at `25b5b572`; its
provider projection and Windows native acceptance remain pending.

Required native behavior: held real threads increase and restore the measured
count, a foreign process's held threads are excluded, and successful enumeration
uses real SDK operations. Targeted test-only interception must prove failed
snapshot opens do not close, short records are rejected before field reads,
dwSize is reset, both enumeration failures reject, and CloseHandle is attempted
once even when it fails or overwrites last error. All child threads/processes
need bounded release/join/handle cleanup on test exits. Overflow has a structural boundary proof: the int counter starts at zero, its
only update is +1 after an equality check against the actual imported INT_MAX,
and no other write can put it outside [0, INT_MAX]. The equality path fails
before arithmetic. This is not a runtime overflow-branch claim; no reduced
constant or test-only production helper is introduced. Both frontends
must emit then run strict C11 on Windows x64 and ARM64; WindowsMain SDK-reader
process support is not included.

The native fixture and explicit two-stage driver now live in the existing
background-jobs test owner. `WindowsProcessThreadsFixture.project` requires an
explicit real SDK reader and immutable selected frontend, emits for x64 or ARM64,
and seals the original C/plan plus native fixture and copied header hashes.
`run_native` requires actual matching-architecture Windows and a supplied pinned
Clang-compatible C command. It uses a VFS overlay for only the two authenticated
project headers; emitted C is not rewritten and native SDK headers remain real.
The allocated qualifier must pin that projection receipt. No new default pytest
rows or platform skip claims are introduced; the explicit native stage has not run.

The real-thread trial checks +3 then restoration; the foreign child contributes
at least four actual snapshot records while leaving the parent's count unchanged.
The child waits on release or the exact parent-process handle and has its own
bounded deadline. Test-only interception covers open/first/next/close failure,
short foreign records, valid shortened records requiring size reset, empty and
foreign-only results, and close overwriting last error. A close-failure injection
still performs the real close to avoid leaking the fixture handle. No SDK layouts
or production return values are replaced on the successful real-operations path.


## Native process-owner adapter

The follow-up changes only the existing Python test driver, this report and its
claim. It delegates compilation to `tools.windows_toolchain.process_runner`,
retaining the original 180-second compilation deadlines and raw command output.
The Windows owner assigns its launch gate to a kill-on-close Job before creating
the target, and closes/reaps descendants after successful or failed commands.
No new process wrapper, provider logic or native fixture is introduced.

After linking, the driver writes the existing one-program Windows host bundle
manifest with the executable's actual SHA and PE machine. It uses
`WindowsNativeExecutor.prepare()` to require matching native hardware through
IsWow64Process2, then the same executor runs the complete fixture under its
90-second bound and Job cleanup. Its isolated working directory is compatible
with the fixture: the foreign child starts from GetModuleFileNameW and uses no
working-directory file. Raw output, status/NTSTATUS, hardware provenance and
cleanup outcomes are retained. The success-text comparison preserves the former
text-mode universal-newline behavior; stored evidence bytes are not normalized.

The caller must supply the allocated projection receipt SHA, selected compiler
argv and authenticated toolchain facts. The native qualification must pin the
source adapter and supplied facts, record the actual runner image, compiler and
SDK identities, and use the intended GNU target rather than silently switching
to MSVC ABI. The driver verifies the receipt before reading it, verifies every
original C/plan/header/probe hash before compilation and after successful native
execution, and rechecks the receipt. The shared qualifier still owns all-exit
input/tool/artifact closure; a failing invocation is never accepted merely
because its partial outputs exist.

The immutable 25b5 projection packet remains the local gate input. Its later
successful C/plan/header output may be reused with this driver only after the
native qualifier authenticates that result and the unchanged compiler, provider,
manifest, BTRC/C/header fixture and shared process-owner bytes. This adapter does
not regenerate or alter projected C, plans or SDK declarations. Native Windows
VFS resolution, strict builds and all real/fault runtime cases are still unrun.
Source formatting/review alone is not native acceptance. No build, test,
generation, publication or dispatch was performed for this adapter checkpoint.
