# Windows OS-services providers

Status: CX-P2-01 revision 3, approval pending. Round-2 review: PR #52, comment
5984785229; current-main cross-check: `0214f3d8`. The branch base remains
`72592d36f560517a39e54f4b92b0149d44bef4d6`.
CL-P2-01 must review this design and record approval in PLAN.md before it becomes
an implementation contract. This document does not claim Windows runtime parity.

This specifies the Windows exits of [platform parity P3 and W1](platform-parity.md)
and Windows adaptation rows 1, 1b, 2, 4, 5 and 7 in
[platform adaptations](platform-adaptations.md). Provider selection and SDK
ownership follow [the target contract §§2 and 5](platform-target-contract.md).
It also identifies the seams needed by the later Windows native UI providers.

## Defaults and boundaries

These are the **platform-adaptations** Q4–Q6 assumptions, not the similarly named
workstream scheduling questions. All three await owner sign-off; design proceeds
with these defaults so an unanswered question does not block the foundation.

| Question | Default used here | Consequence if changed |
| --- | --- | --- |
| Q4 | MSIX release packaging; unpackaged developer tools remain supported | Environment-root policy, package identity and background-process restrictions need separate packaged tests. A different package model changes those tests and autostart integration. |
| Q5 | Named pipes for LocalApplicationChannel | No AF_UNIX credentials emulation. Choosing another transport requires a new authenticated peer-identity contract. |
| Q6 | `LockFileEx` behind `AdvisoryFileLock` | The Windows lock is mandatory for conflicting byte-range I/O. Documentation and callers must accept this stronger behavior. |

Windows 11 is the product floor fixed by PLAN decision D21. The SDK declarations
use the pinned MinGW `_WIN32_WINNT` default; do not add a differently spelled
redefinition under `-Werror`. That SDK declaration floor does not qualify Windows
10 as a supported product target. Both `x86_64-windows-gnu` and
`aarch64-windows-gnu` are required.
Windows MSVC is a separate target qualification; a successful GNU reader probe
does not qualify MSVC or native execution. No compiler, runtime, library, manifest,
inventory, availability catalog or PLAN file is changed by this design packet.

## Provider ownership and imports

Keep public facades and portable policy in their existing packages. Select narrow private host
seams at btrc time, preserving existing public facades and Unix bodies; remove Windows refusals only when the entire
operation has a tested Windows provider. Each row below proposes files to be
implemented by the appropriate later packet, not files created here.

| Portable owner and seam | Proposed Windows implementation | Manifest owner |
| --- | --- | --- |
| `FileSystem/FileSystem.btrc`: path conversion and basic file operations | `FileSystem/Windows/FileSystemProvider.btrc` | `FileSystem/btrc.toml` |
| `FileSystem/FileSystemHandles.btrc`: exact file/directory handles, identity, snapshots, private directories and locks | `FileSystem/Windows/FileSystemHandlesProvider.btrc` | `FileSystem/btrc.toml` |
| `FileSystem/FileTree.btrc`: bounded traversal/deletion through the handle seam | Reuses `FileSystemHandlesProvider`; traversal policy stays portable | `FileSystem/btrc.toml` |
| `FileSystem/ApplicationDirectories.btrc`: target path policy and application roots | `FileSystem/Windows/ApplicationDirectoriesProvider.btrc` | `FileSystem/btrc.toml` |
| Root `IO.btrc`: snapshot of an already-open stream | `Windows/IOFileSnapshotProvider.btrc` | Root `btrc.toml` |
| Root `Process.btrc`: process launch, capture and process status | `Windows/ProcessHostProvider.btrc` | Root `btrc.toml` |
| `Terminal/Terminal.btrc`, `TerminalPasswordInput.btrc`: console I/O and password session | `Terminal/Windows/TerminalProvider.btrc`, `TerminalPasswordInputProvider.btrc` | `Terminal/btrc.toml` |
| `Daemon/Daemon.btrc`, `DaemonControl.btrc`, `DaemonControlFiles.btrc`, `DaemonControlProtocol.btrc`: specification, lifecycle, records and supervisor launch | `Daemon/Windows/DaemonProvider.btrc`; sibling `Windows/DaemonSupervisorMain.btrc` entry owned by CX-P2-08 after the build/bundle prerequisite below | `Daemon/btrc.toml` |
| LocalApplicationChannel server/client and `LocalPeerCredentials.btrc`: bounded transport and authenticated identity | `LocalApplicationChannel/Windows/LocalChannelProvider.btrc`, `LocalPeerCredentialsProvider.btrc` | `LocalApplicationChannel/btrc.toml` |
| `BackgroundJobs/BackgroundJobExecutor.btrc`, `NativeWorker.btrc`: locks, conditions and joinable workers | `BackgroundJobs/Windows/BackgroundJobExecutorProvider.btrc`, `NativeWorkerProvider.btrc` | `BackgroundJobs/btrc.toml` |
| `BackgroundJobs/ProcessThreads.btrc`: current-process thread count | `BackgroundJobs/Windows/ProcessThreadsProvider.btrc` | `BackgroundJobs/btrc.toml` |
| `BackgroundJobs/HostWorkerPools.btrc`: compiler process pool | Keep explicit inline-only provider until CL-P2-12 supplies a serialized worker bootstrap | `BackgroundJobs/btrc.toml` |

### Compiler-import impact: reader-free runtime route

Choose route (a): FileSystem, FileSystemHandles, ApplicationDirectories, root
IO/Process and BackgroundJobs ProcessThreads/HostWorkerPools are in btrcc's
closure. **None of their selected providers carries native.bindings.** WindowsMain
has no SDK reader; adding one transitively would break its native bootstrap and
the reader's own launch. These paths call pre-authored `_WIN32` runtime-origin
helpers owned by an explicitly extended CL-P2-02 in `src/runtime/c/windows_os.c`,
compiled separately as specified below, with SDK-free declarations in `btrc_rt.h`.
That request covers stream snapshots, NT relative opens, enumeration, rename,
disposition, locks, wide environment roots, token SID and process/thread observation.
SDK types stay inside runtime C; public btrc boundaries expose checked primitive
values and opaque owners. Raw SDK names are never hosted-ABI escape hatches.

Process launch is always reader-free, even if a future Windows reader exists.
Delete the proposed Win32Process.h launch binding and Daemon's duplicate launch
set. CL-P2-02's runtime seam alone owns process, job and stdio HANDLEs. Daemon
uses its reviewed detached ownership-transfer entry; it never wraps the same
handles through a second btrc SDK owner.

Prefer private `IOFileSnapshotProvider` and `ProcessHostProvider` seams over
configuring all of IO/Process. Root public exports stay where they are. Root
provider selection for these private names must be proved by CL-P1-14 in both
frontends; no hand-rolled resolver. Add a named step to CL-P1-14 covering root
`btrc.toml` private providers in `packages.py` and `Packages.btrc`, including
positive selection, overlap/missing-row diagnostics and cache parity; the current
group-manifest step alone is insufficient. Unix providers are selection-only shells
around the existing bodies, with compile-time C4 selection and no changed
BtrccMain/MacOSMain C. Do not relocate live POSIX implementations just to obtain
a directory layout. CL-P2-27 owns the reviewed WindowsMain changes and native
Windows bootstrap. Its baseline is taken after any approved portable-identity
landing described below; identity changes cannot be hidden in a Windows diff.

Every compiler-import edit satisfies WORKSTREAMS §3.4: own btrcc build,
bootstrap fixed point, zero-warning BtrccMain/WindowsMain (x64 and ARM64)/
MacOSMain transpiles, byte-identical non-Windows host C and the Claude-reviewed
Windows C diff. Root-symbol changes require an approved btrc.symbols owner-line
diff; final derived commits regenerate symbols and btrc.lock. Makefile Windows
transpiles must select --target windows-x86_64/windows-aarch64 explicitly.

### Complete provider coverage before configuration

CL-P1-09/10/14/15 are hard prerequisites: availability, Windows reader target
rows for non-closure bindings, env/mobile filters and cache identity. The matrix
below applies to **every new private seam** in the owner table, not merely IO.
U means an existing desktop implementation retained by its target selector; N
means a new provider or binding that is not implemented by today's manifest; R
means an explicit operation-level refusal provider with the approved diagnostic;
W means Windows GNU runtime-backed closure seam (or checked SDK provider outside
the closure); M means an explicit MSVC refusal preserving facade imports.

| All 11 target rows | IO identity / FileSystem / handles / tree / roots | Process | Terminal | Daemon | Channel | NativeWorker / Executor | ProcessThreads / HostWorkerPools |
|---|---|---|---|---|---|---|---|
| linux-aarch64 | U | U | U | U | U | U | U |
| linux-x86_64 | U | U | U | U | U | U | U |
| macos-aarch64 | U | U | U | U | U | U | U |
| macos-x86_64 | U | U | U | U | U | U | U |
| ios-aarch64 | U + mobile root refusal pending CX-P2-14 | R | U redirected / R console-only | R | R pending mobile channel | N mobile pthread binding (CX-P2-15) | N mobile thread count / R processes (CX-P2-15) |
| ios-aarch64-simulator | U + mobile root refusal pending CX-P2-14 | R | U redirected / R console-only | R | R pending mobile channel | N mobile pthread binding (CX-P2-15) | N mobile thread count / R processes (CX-P2-15) |
| android-aarch64 | U + mobile root refusal pending CX-P2-14 | R (Q8) | U redirected / R console-only | R | R pending mobile channel | N mobile pthread binding (CX-P2-15) | N mobile thread count / R processes (CX-P2-15) |
| android-x86_64 | U + mobile root refusal pending CX-P2-14 | R (Q8) | U redirected / R console-only | R | R pending mobile channel | N mobile pthread binding (CX-P2-15) | N mobile thread count / R processes (CX-P2-15) |
| windows-aarch64 | W | W | W | W | W | W winpthreads | W / explicit inline-only |
| windows-x86_64 | W | W | W | W | W | W winpthreads | W / explicit inline-only |
| windows-aarch64-msvc | M exact/native seams; existing basic IO remains | M | M | M | M | M pending thread ABI | M / explicit inline-only |

Each module becomes configured only in the same commit that covers every row
it resolves on today. U mobile basic IO/regular operations preserve inventory's
equivalent cells; mobile root/process restrictions remain explicit adaptations,
not missing provider-resolution errors. For table entries with mixed behavior,
separate narrow seams select U or R; do not configure a whole facade and lose
its working operations. R/M are real typed refusal implementations, recorded as
restricted/unsupported in platform-inventory, never falsely "implemented" or
"missing provider". Stage-24 intentionally missing public modules remain missing;
this table does not invent a mobile app shell. Exact per-operation mobile
classifications and MSVC restrictions require CL-P2-01 approval and inventory
fragments before landing. Extend test_target_provider_matrix.py for all rows.
ProcessThreads has only Linux/MacOS providers today; NativeWorker/Executor
bindings select only those two desktop OSes. CX-P2-15 must add and qualify each
mobile binding/count provider, not relabel it U. Its inventory fragment changes
Android HostWorkerPools from the current source-only possible fork adaptation to
this proposed Q8 restriction/explicit inline-only implementation; retain the old
cell until CL-P2-01 approves that behavior. No mobile provider is claimed present.

## Runtime SDK inventory and non-closure bindings

The following sets describe the SDK work a runtime/native owner must qualify.
They are not blanket native.bindings entries on compiler-import providers.
Only Terminal, Daemon and LocalApplicationChannel SDK operations outside
btrcc's closure use reader bindings. NativeWorker/Executor use the same reader-free
winpthreads runtime contract, with new per-target bindings where needed. Those headers
include the pinned SDK, never copied Win32 declarations or fabricated layouts.
Windows bindings use os=["windows"], env=["gnu"], C11 and explicit symbols.
Rely on MinGW's _WIN32_WINNT default; do not redefine 0x0A00 against its 0x0a00
under -Werror. D21's Windows 11 floor does not claim Windows 10 support.

| Owner / header or runtime unit | SDK functions to qualify | Libraries |
|---|---|---|
| Runtime filesystem/IO snapshot | CreateFileW, NtCreateFile, NtSetInformationFile, GetFileInformationByHandleEx, SetFileInformationByHandle, GetFinalPathNameByHandleW, GetVolumeInformationByHandleW, ReadFile, WriteFile, GetFileSizeEx, SetFilePointerEx, FlushFileBuffers, ReplaceFileW, MoveFileExW, LockFileEx, UnlockFileEx, _get_osfhandle, RtlNtStatusToDosError | kernel32, ntdll, CRT |
| Sole runtime roots/security owner | GetEnvironmentVariableW, OpenProcessToken, GetTokenInformation, GetCurrentProcess, EqualSid, GetSecurityInfo, SetSecurityInfo, GetAclInformation, GetAce, GetLengthSid, CopySid, InitializeAcl, AddAccessAllowedAceEx, InitializeSecurityDescriptor, SetSecurityDescriptorDacl, SetSecurityDescriptorOwner, SetSecurityDescriptorControl, LocalFree | advapi32, kernel32 |
| Sole runtime launch/image owner | GetModuleFileNameW, QueryFullProcessImageNameW, CreateProcessW, InitializeProcThreadAttributeList, UpdateProcThreadAttribute, DeleteProcThreadAttributeList, CreateJobObjectW, SetInformationJobObject, QueryInformationJobObject, IsProcessInJob, AssignProcessToJobObject, TerminateJobObject, TerminateProcess, CreatePipe, SetHandleInformation, DuplicateHandle, GetStdHandle, ResumeThread, GetExitCodeProcess, GetEnvironmentStringsW, FreeEnvironmentStringsW, WaitForSingleObject, WaitForMultipleObjects, CancelIoEx, GetOverlappedResult | kernel32 |
| Terminal/Windows/Win32Terminal.h | GetStdHandle, GetConsoleMode, SetConsoleMode, ReadConsoleW, WriteConsoleW, ReadConsoleInputW, SetConsoleCtrlHandler, CancelSynchronousIo, GetCurrentThread, DuplicateHandle, GetFileType, SetEvent | kernel32 |
| Daemon/Windows/Win32Daemon.h | BCryptGenRandom; SID/DACL operations call the shared runtime security seam, **no duplicate launch/security binding** | bcrypt, advapi32, kernel32 |
| LocalApplicationChannel/Windows/Win32LocalChannel.h | CreateNamedPipeW, ConnectNamedPipe, DisconnectNamedPipe, WaitNamedPipeW, GetNamedPipeClientProcessId, GetNamedPipeServerProcessId, OpenProcess, OpenThreadToken, ImpersonateNamedPipeClient, RevertToSelf, CreateEventW, SetEvent, CreateFileW, ReadFile, WriteFile, CancelIoEx, GetOverlappedResult, WaitForSingleObject; shared runtime security helpers supply SID/DACL/token checks | kernel32, advapi32 |
| Runtime ProcessThreads; non-closure workers | CreateToolhelp32Snapshot, Thread32First, Thread32Next, GetCurrentProcessId; existing winpthreads start/join/mutex/condition surface | kernel32, existing winpthreads |

Common CloseHandle/GetLastError and strict MultiByteToWideChar/
WideCharToMultiByte use are part of every applicable set. Record qualification
includes OBJECT_ATTRIBUTES, UNICODE_STRING, IO_STATUS_BLOCK, FILE_ID_INFO,
FILE_RENAME_INFO (including flexible array), FILE_DISPOSITION_INFO_EX,
FILE_ID_EXTD_DIR_INFO, FILE_STANDARD_INFO, OVERLAPPED, STARTUPINFOEXW, TOKEN_USER
and JOBOBJECT_EXTENDED_LIMIT_INFORMATION.

The earlier 89/90 declaration-selection observation used an incorrect include
recipe and **is withdrawn as qualification evidence**. The corrected Stage 24
§3.1 recipe is:

```sh
"$BTRC_NATIVE_HEADER_READER" --batch=Requests.json Windows.c -- \
  -x c -std=c11 --target=x86_64-w64-windows-gnu -nostdinc \
  -isystem "$ZIG_LIB_DIR/include" \
  -isystem "$ZIG_LIB_DIR/libc/include/any-windows-any" \
  -isystem "$BTRC_RUNTIME_ROOT/windows"
# Repeat for aarch64-w64-windows-gnu with the same three include roots.
```

The native owner must commit Requests.json in its assigned test fixture and
retain both per-request errors/documents and tool/sysroot hashes. This docs-only
revision adds no fixture and claims no corrected run. NtQueryDirectoryFile is
not assumed available; handle-based directory enumeration remains the selected
route. Compiler-private runtime helpers get runtime-origin hosted_abi rows and
non-Windows unsupported definitions, preserving the target-contract's ported,
not filtered rule. No raw SDK symbol is added to hosted_abi.

Choose a separately compiled `src/runtime/c/windows_os.c` for these Windows
runtime helpers. SDK includes and records stay in that translation unit; the
emitted user C sees only SDK-free `btrc_rt.h` declarations. Do not paste windows.h,
shlobj.h or Win32 macros into user C. Non-Windows unsupported definitions live in
the same asset's target branch and are selected only when a runtime-origin helper
is retained; adding it must not change reachable desktop C. CL-P2-02 owns the
asset, manifest/catalog rows and D14 evidence; CL-P1-11 owns the prerequisite
builder/link-plan extension before Stage 26. CL-P2-19 subsequently preserves the
same mechanism in schema 6, rather than becoming a Stage-28 prerequisite for
Stage 26. Do not claim today's process.c pasted-helper path already supports it.

The **runtime manifest** carries target-filtered external-object sources and
system import libraries for runtime-origin helpers. Package-origin SDK bindings
carry `native.system-libraries` in the package manifest. Both feed one normalized
link-plan set; neither embeds arbitrary linker switches. Link only libraries
required by reachable helpers (`kernel32`, `ntdll`, `advapi32`; Daemon's randomness
also needs `bcrypt`). Environment roots remove the shell32/ole32 dependency from
this compiler closure. Zig already supplies the import libraries: downloading an
SDK does not supply missing link-plan metadata. Both frontends, native_plan,
Makefile, Windows workflow, bootstrap_harness and runner.py must honor the same
object and library set. No pragma comment(lib) escape. Add GNU corpus cases using
`near`, `far`, `IN`, `OUT`, `DELETE`, `min`, `max`, `Rectangle` and `small` as valid
user identifiers, compiled alongside retained runtime helpers, to prove isolation.

## Filesystem, application roots and IO snapshots — row 7

`DirectoryHandle.openExact`, `RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf`,
`AdvisoryFileLock.acquire` and `IO.File.snapshot` currently refuse Windows.
Keep `acquire(path, wait=false)`; a4a9bb79 already corrected the adaptations
method name and suspended-job wording. Do not simply delete these guards:

* `PrivateDirectory.openAbsoluteLeaf` tests for a leading `/` before its Windows
  refusal. `ApplicationDirectoryRoots` and its resolver also normalize Unix
  absolute paths. Introduce target path policy before those validations so drive
  absolute and UNC paths are recognized correctly. Reject drive-relative paths,
  embedded NUL and invalid UTF-8. Preserve native case without promising case
  sensitivity; distinguish paths from canonical object identity.
* Convert strictly between UTF-8 and UTF-16, with dynamic storage for long paths.
  Normalize extended drive/UNC prefixes once, without accidentally reinterpreting
  a device namespace as an ordinary file. Test Unicode, UNC and paths beyond
  MAX_PATH with explicit `\\?\` drive/UNC forms, without depending on
  machine-wide longPathAware policy. CL-P2-14 owns the wide fopen/getenv/environ
  and argv consumer migration; until it lands, ANSI CRT consumers remain
  restricted. Non-ASCII filesystem cases here qualify the new provider only;
  the full non-ASCII compiler-host exit belongs to Stage 27, not Stage 26.
* An exact handle owns its native HANDLE and closes it once. Every exact open
  shares FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE. Use reparse-point
  opens and inspect the opened object's attributes and identity. For traversal,
  private-leaf creation and deletion, open each component relative to the held
  parent handle with `NtCreateFile`/`OBJECT_ATTRIBUTES.RootDirectory`; validate
  every opened component. Refuse IsReparseTagNameSurrogate tags, including
  mount-point tags: Windows volume mount points are explicitly refused along
  with junctions (an adaptation from POSIX traversal, requiring approval).
  For non-surrogate cloud/WOF tags, reopen relative to the retained parent
  without FILE_OPEN_REPARSE_POINT and compare full FILE_ID_INFO identity;
  unsupported tags fail closed with their tag in a typed diagnostic. Never
  silently refuse every reparse tag or treat hydration as a symlink. A final-component flag or a
  path recheck after opening does not close an ancestor-junction race.
* Enumerate through the held directory handle with
  `GetFileInformationByHandleEx` and directory restart/continuation information
  classes. Bounds and stable traversal order remain FileTree policy. Reopen each
  child relative to that directory and compare the opened object's identity;
  enumeration names are not authority. Delete/rename relative to held handles
  using FileDispositionInfoEx/FileRenameInfoEx with POSIX_SEMANTICS only when
  GetVolumeInformationByHandleW advertises FILE_SUPPORTS_POSIX_UNLINK_RENAME;
  otherwise refuse rather than leave incompatible delete-pending semantics. Never fall back to recursive
  string-path deletion when an exact operation is unavailable.
* Identity uses a 64-bit volume serial plus the full 128-bit FILE_ID_128; snapshots preserve size, timestamps and
  checked revisions for files larger than 4 GiB. Existing FileTree revision hashes
  remain cache/change indicators, not authentication. The IO bridge borrows
  `_get_osfhandle` only while its FILE/descriptor remains alive; it must not close
  the borrowed handle or inspect a recycled descriptor after stream close.
* Private-directory creation supplies a protected current-user DACL at creation,
  sets owner explicitly to TokenUser (not an elevated Administrators default),
  requires NumberOfLinks==1 for private files, checks owner and DACL through the opened handle, and rejects conflicting or
  inherited broad access. Obtain the real token SID, not the compatibility
  shim's `getuid()==0`. ACL changes use held handles and preserve required system
  access only through an explicitly reviewed policy.
* Atomic replacement writes a same-directory temporary file with the required
  DACL, flushes it, then performs the documented replacement/rename operation.
  `ReplaceFileW`/`MoveFileExW` alone are suitable only where the namespace is
  trusted; an exact-handle API must use handle-relative operations or refuse.
  Preserve the old file on precommit failure and report ambiguous postcommit
  failures explicitly. Do not promise POSIX directory-fsync durability where
  Windows/filesystem semantics cannot establish it.
* `LockFileEx` locks the agreed whole-file range through the owned handle,
  nonblocking by default and blocking only when `wait=true`. Unlock/close releases
  it. Document mandatory contention with ordinary reads/writes and cancellation
  policy; never silently downgrade to a process-local mutex. Bound crash-release
  observations and report failure if the lock remains held after the deadline.
* Resolve roots from the wide process environment, not Known Folder APIs.
  Require nonempty, valid absolute `LOCALAPPDATA`; no cwd/home/Known Folder
  fallback. `stateRoot = LOCALAPPDATA`, `cacheRoot = LOCALAPPDATA/Cache`,
  `configRoot = LOCALAPPDATA/Config`. These are purpose roots; application code
  appends its validated application namespace. Thus btrcc and btrcpy both use
  `LOCALAPPDATA/btrc/generations`, or their existing explicit absolute
  `BTRC_STATE_DIR` override. Missing/empty/relative/invalid-Unicode values fail
  with a precise root error in both frontends. No roaming-config claim is made.
  Changing the unsigned row-7 Known Folder proposal requires CL-P2-01 approval.
  Packaged execution uses its actual wide environment and separately qualifies
  virtualization and permissions; it must not silently select another authority.
  Packaged and unpackaged roots, ACLs and migration need independent evidence.
  GUI folder selection belongs to UI7's future `IFileOpenDialog/FOS_PICKFOLDERS`
  owner; a scoped grant must not be converted to a fabricated unrestricted path.

### Component grammar and snapshot identity

Every caller component rejects `:`, both separators, NUL/control characters,
`<>"|?*`, trailing dot/space, `.`/`..`, and reserved device names (CON, PRN, AUX,
NUL, COM1–9, LPT1–9, CONIN$, CONOUT$, including extension variants). Reject
alternate streams such as `data:x` and `lock::$DATA`. Lock-name comparison is
case-insensitive. Enumerated names violating the grammar are reported and never
reopened through a normalized Win32 path. Validation alone never grants authority.

FileSnapshot's present two 64-bit fields cannot hold the 192-bit identity.
Choose an additive portable identity carrier and cacheToken version 2, landing
atomically with Linux/macOS providers through a Claude D27 contract packet
**before** Windows exact handles. POSIX fills the carrier from dev/ino without
changing identity meaning. Existing constructor/legacy token decoding needs an
explicit compatibility adapter; no truncation or hash-as-security-identity is
permitted. On Windows, `fromStatus` and the legacy nine-argument constructor
produce an explicit **unidentified** identity; `sameObject` and `sameVersion`
return false if either identity is unidentified. UCRT's zero st_ino cannot become
an object identity. POSIX constructor behavior is retained. Exact Windows
snapshots come only from the new live-handle seam; callers needing identity must
migrate before losing the old refusals. ReFS and Dev Drive remain unavailable until this carrier and their
native fixtures are qualified. That portable change intentionally changes all
host C and needs its own reviewed diffs/bootstrap gate; CL-P2-27 then uses the
new baseline and preserves desktop C while adding Windows providers.

The Windows snapshot uses LastWriteTime and ChangeTime from FILE_BASIC_INFO;
FILETIME ticks are 100 ns since 1601. Subtract 116444736000000000 ticks using
checked signed arithmetic, floor-divide by 10,000,000 for seconds and retain a
nonnegative remainder times 100 as nanoseconds. Pre-1970 seconds remain signed
in the new carrier/token; the old unsigned surface requires an explicit reviewed
adapter, never wraparound. Proposed `_mode` retains only FileKind in its high
field and `FILE_ATTRIBUTE_READONLY` in its low field. Archive, offline, pinned,
unpinned, recall and reparse/storage attributes do not participate in version
comparison. Record raw attributes and ChangeTime as diagnostics; Windows
`sameVersion` compares full identity, kind, size, stable `_mode` and LastWriteTime,
not ChangeTime. Hydration/pinning alone must not invalidate unchanged content.
A hydrate-during-read case compares identity and content before/after; a real
content or LastWriteTime change must fail the snapshot/revision check. This is
cache/version detection, not authentication against an actor restoring metadata;
compiler content digests retain their existing role. Security always uses live
handle/token/DACL checks. The portable identity packet owns this explicit
Windows comparison policy and its cacheToken-v2 encoding atomically.

Win32/NTSTATUS failures need a native-code domain alongside FileSystemError's
existing channel, with an additive atomically landed contract; convert NTSTATUS
with RtlNtStatusToDosError for common categorization while preserving raw code
and domain. Runtime HANDLE owners are private to Claude. Non-closure reader
bindings outside this shared runtime seam need approved R1 support for opaque void* HANDLE values, NULL or
INVALID_HANDLE_VALUE failure sentinel and BOOL-returning CloseHandle, or a
recorded descriptor-owner exception; do not force them into an incompatible
unique-resource declaration.

If the runtime SDK lacks qualified NT layouts or exact semantics, fail closed
with existing unsupported outcomes. No copied structs or pathname retry. Until
the provider ships, preserve the adaptation strings in FileSystemError.message:

```text
PrivateDirectory.openAbsoluteLeaf is unavailable on Windows: owner-only directories need the DACL-backed handle provider; use ApplicationDirectories
RegularFileSnapshot.open is unavailable on Windows: owner-only directories need the DACL-backed handle provider; use ApplicationDirectories
AdvisoryFileLock.acquire is unavailable on Windows: owner-only directories need the DACL-backed handle provider; use ApplicationDirectories
```

## Process and shell — rows 1 and 1b

Keep `ChildProcess.run` validation, argument-vector API, output modes and result
policy portable. Windows construction uses strict UTF conversion, a sorted
case-insensitive environment block, explicit environment removals and a canonical
CommandLineToArgvW-compatible quoting algorithm (including empty strings and
trailing backslashes). ShellWords' POSIX rendering is display-only on this target.
No `cmd.exe` substitution for UnixShell is permitted.

Executable resolution belongs to the same runtime seam: merge overrides/unsets
case-insensitively into GetEnvironmentStringsW, preserving names such as
ProgramFiles(x86), then search the child's effective PATH and resolve explicit
relative paths against the child's cwd. An unset or empty effective PATH gives
zero search directories; an empty semicolon-delimited entry is ignored, never
interpreted as cwd. A bare name searches only nonempty explicit PATH entries,
never implicit parent application/cwd search; relative PATH entries resolve
against child cwd. No POSIX default search path is imported. Do not use PATHEXT
script types: explicit extensions are used exactly; extensionless names probe
`.exe` then `.com`, in that order for each directory. The candidate must pass a
bounded PE validation from an opened file: MZ, checked e_lfanew and PE signature,
complete target-compatible COFF/optional headers, executable-image flag and no
DLL flag. Extension alone never proves PE. Reject DOS COM images and malformed,
truncated or wrong-machine candidates; the Windows loader remains the final
loader check. Test x64/ARM64 policy explicitly rather than silently counting
emulation as native qualification.
Always pass absolute lpApplicationName. Refuse .bat/.cmd and all non-PE targets
with a distinct launch validation failure even if CreateProcessW could run them;
ordinary argument quoting is unsafe when Windows inserts cmd.exe. Reject a
quote in argv[0] and command lines over 32,767 UTF-16 units including NUL.

Launch suspended with `STARTUPINFOEXW` and an explicit inherited-handle list
containing only the three selected stdio handles. Duplicate inherited caller
stdio into launch-owned handles and never mutate the caller's inheritance flags.
Assign the child to a kill-on-close job **before** `ResumeThread`. This is the
CL-P2-02 baseline even if `PROC_THREAD_ATTRIBUTE_JOB_LIST` is available;
adaptation row 1 already matches it. Job assignment failure
terminates the still-suspended child and returns launch failure. Nested-job or
package restrictions must not leave a running, uncontained child.

Drain stdout and stderr concurrently while feeding stdin, under independent byte
bounds and one monotonic deadline. COMBINE shares the intended output endpoint;
STREAM writes to the requested parent stream; SUPPRESS still prevents child
blocking. Match Unix's deadline semantics: with no public deadline, wait for
EOF from descendants retaining output handles even after the direct child exits;
there is no hidden post-exit timer. With a deadline, that same monotonic deadline
covers process completion and both pipe drains; expiry returns timeout/124 and
kills the owned job, including a descendant retaining a pipe. Explicit SUPPRESS
or non-pipe output does not invent an EOF obligation. Memory remains bounded in
all modes. Cancellation, timeout and capture overflow
terminate the whole owned job, finish/cancel I/O, join service threads and close
all handles. No callbacks into BTRC objects from raw runtime I/O threads.

Map timeout to existing code 124 and capture-limit failure to 125. Launch and
capture-I/O failures use 127 with distinct reasons/flags; a child that itself exits
127 is an ordinary child exit, not a launch failure. Preserve the native DWORD
exit bits separately: the portable `ProcessStatus` currently decodes POSIX wait
bits and must receive a target-specific status seam. CL-P2-01 must approve how an
unsigned high-bit exit is exposed through the existing signed `ExecResult.code`;
the proposal is signed bit-preserving code plus an exact unsigned native-status
accessor, never applying WIFEXITED/WTERMSIG to a Windows exit code.

Descriptor-relative executable/cwd launch and arbitrary descriptor mappings have
no exact CreateProcessW equivalent. Return an explicit unsupported result for
those options initially; do not reopen a supposedly exact executable by its path.
Ordinary path-based cwd, stdio inheritance and argument vectors are supported.
The adaptation diagnostics remain exact:

```text
ChildProcess.run is unavailable on Windows: exact executable/cwd descriptors and arbitrary descriptor mappings need a native handle contract; use path-based launch with explicit stdio handles
ChildProcess.run is unavailable on Windows: a console has no controlling-terminal foreground handoff; use a background child
UnixShell.run is unavailable on Windows: there is no POSIX /bin/sh; use ChildProcess.run with an argument vector
```

## Terminal — row 2

`readLine` and `prompt` retain bounded redirected-stream behavior. Console handles
use `ReadConsoleW`/`WriteConsoleW` and strict Unicode conversion. Password input is
a serialized console session: save the original mode, clear `ENABLE_ECHO_INPUT`,
retain `ENABLE_LINE_INPUT` and `ENABLE_PROCESSED_INPUT`, and restore the mode on success, overflow, error and
control-event cancellation. Preserve the existing 4096-byte password limit and
never log input. A process-global control handler signals cancellation through a
minimal native trampoline; it must not allocate BTRC objects, throw or run user
callbacks. Restore mode and handler registration before propagating interruption.

For redirected stdin, match the tested POSIX promptPassword behavior: bounded
reading with the same overflow/error semantics, without pretending a pipe has
console echo to disable. This deliberately replaces unsigned row 2's contradictory
refusal (which tells the caller to supply stdin immediately after refusing it);
CL-P2-01 must record the adaptation decision for both platforms before delivery.
No secret is logged. For a blocking console reader, duplicate its real thread
handle for CancelSynchronousIo, signal cancellation via a native event, and
restore mode/handler registration after drain. Never GenerateConsoleCtrlEvent.
Pseudoconsole/foreground handoff remains separately unqualified.

## Daemon supervisor — row 4

Keep DaemonSpec's validation and declared Command data. Choose **a sibling
supervisor executable**, not self re-exec: the compiler has no pre-main hook.
The fixed sibling name is `btrc-daemon-supervisor.exe`, produced from
`src/stdlib/Daemon/Windows/DaemonSupervisorMain.btrc`. CX-P2-08 owns that thin
entry and its policy through an amended packet, but cannot implement the builder,
manifest, runtime or runner changes; those are explicit prerequisites below.

CL-P1-11 must add a reviewed auxiliary-executable declaration to the package/link
plan and its builder/bundle support before CX-P2-08 starts. The Daemon package
names the source entry, target filter, exact sibling basename and runtime protocol
version; both frontends emit the same declaration only for a reachable Windows
Daemon consumer. The builder compiles it with the same frontend, ABI, runtime
revision and library set as the main executable. The auxiliary dependency graph
must be acyclic: the supervisor is a leaf image, cannot request another Daemon
supervisor, and never embeds its own digest. Build/hash that leaf first, then
emit the primary consumer's expected-digest metadata and link the primary image.
Auxiliary declarations are selected by retained Daemon-start capability, not by
merely importing the package. Both plan writers reject recursive declarations. Each unpackaged corpus program
gets its own sibling in its isolated output directory, not a shared mutable PATH
location. A bundle carries the sibling next to the executable that uses it,
records both hashes and rejects absent/mismatched companions before execution.
An app distributing Daemon must distribute that pair and its declared runtime
libraries in both unpackaged and MSIX layouts; no install-time/runtime download.
No auxiliary executable is added to unrelated or non-Windows programs.

The runtime resolves its own absolute module path with `GetModuleFileNameW`,
forms only that fixed sibling path, and returns a **verified image owner** after
opening and checking the canonical file, expected build-manifest digest, protocol
and target machine. It retains the image with no write/delete sharing and holds
its verified ancestor directories against write/reparse changes and rename; untrusted reparse ancestry or
an unenforceable namespace lock fails closed. The location must satisfy the
same reviewed distribution-owner/ACL policy as the application. User-writable
application installation remains in the application's trust domain; this does
not claim protection against an actor who can replace the application itself.
The launcher passes the resulting absolute path as lpApplicationName and checks
the suspended child's image identity before resume. It never resolves a bare
supervisor name, PATH, PATHEXT, cwd override or caller-supplied arbitrary image.
Hold validation locks through creation/identity check; post-hoc path equality
alone is not an image-race proof. Missing image, mismatched digest/ABI/protocol,
rename/write interference or unsupported verification gives **unsafe start**
before transferring any instance/control token. CL-P2-02 owns this runtime helper.

The launch seam below takes the verified image owner; it cannot use ordinary
executable search for detached transfer. Tokens travel only over the explicitly
inherited private control pipe, not command-line/environment/log text. Transfer
has two additional fixed, audited bootstrap-pipe slots (request and reply)
beyond ordinary launch's three stdio slots; it admits no arbitrary descriptor
mapping. Only the intended child ends inherit; parent/unused ends close at their
handshake boundary. Parent creation remains suspended/contained. The supervisor creates its own managed-tree
job, publishes READY only after ownership is established, and waits for COMMIT.
The launcher clears its temporary job's kill-on-close only after READY, sends
COMMIT, and reports success only after the protected instance record and ACK
match. Before COMMIT, timeout/launcher loss makes the supervisor terminate its
managed job and itself. A failure after COMMIT is **indeterminate start**, never
an automatic second launch: reconcile the authenticated record. This state must
be added to the controller result contract by CL-P2-01. Ordinary ChildProcess
close rules remain unchanged. Nested-job/breakaway restrictions fail closed.

CX-P2-08's amended owned paths explicitly include the new BTRC entry and its
Daemon manifest fragment; runtime, compiler, native_plan, runner and bundle
changes remain Claude's. Its acceptance must run both frontends' unpackaged
`stdlib/Daemon.btrc` with the sibling supplied by the corpus builder within the
existing 15-second corpus limit, then execute the exact same pair through the
CX-P1-07 Linux-built Windows bundle. Add missing/replaced/wrong-ABI sibling,
planted PATH/cwd image, launcher-exit and each READY/COMMIT/ACK failure point.
MSIX/autostart evidence remains separately capability-gated. Until these named
prerequisites land, CX-P2-08 cannot claim an implementable completed supervisor.

Resolve owner-controlled records/logs through
ApplicationDirectories. Generate 128-bit instance/control tokens with
`BCryptGenRandom`; records, logs and control-capability files require current-user DACLs.
PID alone is never a capability. Match the instance token against the protected
instance record and authenticate the file-control capability before status/stop
or stale-record cleanup; do not terminate a process from an old PID.

Start the supervisor with the adaptation's detached/new-process-group/breakaway
flags only where the parent/package policy permits them. It owns a job for its
managed child tree and applies the declared restart policy. Use the existing owner-DACL-protected file-capability control protocol, not
an additional named-pipe daemon protocol. A stop record authenticates the instance
and asks the supervisor to stop/reconcile. Windows then uses declared hard tree
termination via TerminateJobObject; it does not claim POSIX graceful signals.
This hard-stop adaptation requires Q4/row-4 approval. The public UnixShell field
remains a compatibility field but is unused on Windows; no shell command is run. Preserve controller result distinctions (success, not running,
deadline, unsafe start) and bound startup handshake, log retention and crash
recovery. A denied breakaway or job assignment is a failed start, not success with
weaker containment. Ensure the launching process closing its own launch handle
does not kill the accepted independent supervisor; detached launch requires a
separately reviewed ownership transfer, not the ordinary ChildProcess close rule.

Per-user autostart defaults only to the explicit opt-in packaged startup task.
Run/logon-task registration belongs to a separately approved unpackaged artifact. MSIX does not imply permission to install a per-user
service or evade package process restrictions. Packaging policy and native evidence
must qualify the chosen path; no automatic service installation is proposed here.
The unsupported rendering diagnostic remains:

```text
DaemonSpec.renderStartCommand is unavailable on Windows: the supervisor is a POSIX /bin/sh script; use DaemonController.start
```

## LocalApplicationChannel — row 5

Validate the supplied path using the Windows component policy and retain its
PrivateDirectory parent after owner/DACL checks. Derive a deterministic name
`\\.\pipe\btrc-lac-<SID>-<digest(volume,parent-file-id,leaf)>`, using the full
identity, canonical case policy and bounded collision-resistant digest. Namespace
hashing is routing, not authorization. Reject insecure parents with
INSECURE_PARENT. First-instance ERROR_ACCESS_DENIED/ERROR_PIPE_BUSY maps to PATH_CONFLICT
until a connection validates the existing pipe object's owner SID and server
process token as the current TokenUser. Only then return ALREADY_RUNNING. This
is same-user endpoint authentication, not proof of a particular product binary;
same-user code is the documented trust boundary. A missing/exiting process,
failed token query or mismatched owner remains PATH_CONFLICT. Never drop
exclusivity or trust an unauthenticated squatting endpoint.

The initial server uses FILE_FLAG_FIRST_PIPE_INSTANCE|PIPE_REJECT_REMOTE_CLIENTS,
explicit TokenUser owner, protected user-only DACL and nMaxInstances=maximumClients.
Later instances owned by that server omit FIRST_PIPE_INSTANCE. Preserve the
four-byte big-endian frame, empty payload, one reply, bounded bytes and one
monotonic connect/send/receive deadline. Overlapped poll is nonblocking; canceled
I/O is completed/drained before releasing OVERLAPPED storage, events or handles.

The client opens with SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION and
READ_CONTROL. **Before its first write**, verify pipe-object owner SID, then the
server process token while holding the process handle. Query the connected
pipe's server PID again and require the retained process to remain live and match;
PID alone is diagnostic. A disappearing/reused process fails closed. **There is
no instance record, generation token or server-first hello for this channel.**
The first wire bytes remain the existing four-byte big-endian length. After
reading that bounded header the server impersonates the client, calls
OpenThreadToken(OpenAsSelf=TRUE), and compares TokenUser with EqualSid.
RevertToSelf before reading any product frame or executing a command; failure to
revert terminates the process immediately. No exception return may leave it
impersonating. Each newly connected pipe authenticates afresh; disconnect or
restart fails an outstanding request rather than replaying it into another
instance. No unauthorized peer reaches product dispatch. Daemon's protected
file-capability protocol is separate and supplies no channel wire extension.

Add an owned authenticated identity result with platform discriminator and copied
opaque SID bytes (R1 native token scoped through extraction; returned immutable
managed data created on its owning executor). Keep Unix peerUser(fd, uid_t*)
unchanged as a compatibility operation. This additive portable identity lands
atomically with both reference providers under D27. Never truncate SID into uid_t.
The unused AF_UNIX route retains the exact diagnostic:

```text
LocalPeerCredentials is unavailable on Windows: AF_UNIX sockets carry no peer credentials; use the named-pipe channel provider
```

## BackgroundJobs and worker pools — P3 jobs exit

Reuse the runtime's existing winpthreads start/join/mutex/condition bindings on
windows-gnu, with one NativeWorker envelope. Do not add a competing
_beginthreadex calling convention and lifetime model. MSVC remains refused
until its thread ABI is separately qualified. The Windows NativeWorker/Executor
runtime binding is new work, not evidence that the current Linux/macOS-only
native.bindings already select Windows. Preserve the existing bounds
(1–16 workers, 1–4096 outstanding slots, including completed-but-unpolled work),
acceptance ownership, cancellation token rules and owner-thread completion polling.
Rejected submissions retain nothing. A completed job is transferred exactly once
on the owner thread. Synchronize predicate checks and wakeups to avoid lost wakes.

Every worker enters through the runtime's checked foreign-thread boundary, catches
worker failures and retains its body until a successful join. Failed joins keep
ownership for a same-mode retry. Current executor `close(DRAIN/CANCEL_PENDING)`
blocks while joining; UI providers must arrange that off their event loop or use a
future explicitly approved asynchronous close API. This design does not pretend
the existing close is nonblocking. Reader-free runtime ProcessThreads uses a Toolhelp snapshot filtered
to the current PID, closes its handle and reports enumeration failure distinctly.

Native threads are separate from HostWorkerPools' process protocol. Unix pools
depend on forked retained state and wait4 usage accounting; CreateProcessW cannot
reproduce that state implicitly. Preserve Windows' current explicit inline-only
behavior until CL-P2-12 defines serialized compiler-worker startup, framed IPC,
crash isolation, resource accounting and cancellation. Request that design rather
than silently running a requested multiprocess pool on threads or claiming parallel
support from the BackgroundJobExecutor implementation.

## Requests to Claude

The following is a concrete proposed compiler-private C11 launch seam for
CL-P2-02. Names/signatures need its review, with explicit decisions and remaining approval dependencies below. SDK records stay inside the runtime source;
this boundary exposes only fixed-width values, buffers and an opaque owner.

```c
typedef struct __btrc_windows_launch_owner __btrc_windows_launch_owner;
typedef struct {
    const char *executable_utf8;
    const char *const *argv_utf8; size_t argc;
    const char *cwd_utf8;
    const char *const *environment_overrides_utf8; size_t override_count;
    const char *const *environment_unsets_utf8; size_t unset_count;
    const unsigned char *stdin_bytes; size_t stdin_size;
    uint32_t stdin_mode, stdout_mode, stderr_mode;
    size_t stdout_limit, stderr_limit;
} __btrc_windows_launch_options;
typedef struct {
    uint32_t stage, domain, native_code, ownership_state;
} __btrc_windows_launch_error;
typedef struct {
    uint32_t state, native_exit_code, has_exit_code, launch_failed;
    uint64_t stdout_bytes_seen, stderr_bytes_seen;
    size_t stdout_bytes_retained, stderr_bytes_retained;
} __btrc_windows_launch_result;
int __btrc_windows_launch(const __btrc_windows_launch_options *options,
    __btrc_windows_launch_owner **out, __btrc_windows_launch_error *error);
int __btrc_windows_launch_wait(__btrc_windows_launch_owner *launch,
    uint32_t wait_mode, uint64_t timeout_ms, __btrc_windows_launch_result *result,
    __btrc_windows_launch_error *error);
int __btrc_windows_launch_copy_output(__btrc_windows_launch_owner *launch,
    uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written);
int __btrc_windows_launch_terminate(__btrc_windows_launch_owner *launch,
    uint32_t exit_code, __btrc_windows_launch_error *error);
int __btrc_windows_launch_close(__btrc_windows_launch_owner **launch,
    uint64_t timeout_ms, __btrc_windows_launch_error *error);
int __btrc_windows_quote_argv_utf8(const char *const *argv, size_t argc,
    uint16_t *buffer, size_t capacity_units, size_t *required_units,
    __btrc_windows_launch_error *error);
```

Use `<stddef.h>`/`<stdint.h>`. Launch returns 0 on success, nonzero on failure,
sets `*out=NULL` before work, and copies all input storage before returning. A null
cwd inherits; overrides/unsets are merged into GetEnvironmentStringsW inside
the runtime. The portable validator must use Windows case/name rules rather than
POSIX env grammar/ANSI environ. argv includes argv[0]; embedded NUL and invalid
UTF-8 are rejected before native calls. Runtime obtains parent std handles itself,
substitutes NUL for absent handles, duplicates owned launch handles and deduplicates
the explicit inheritance list. Parent flags are never mutated.

Mode values match public enums: stdin 0=CHILD_STDIN_NULL,
1=CHILD_STDIN_INHERIT; nonempty stdin bytes are a separate input source and
cannot combine with INHERIT. Output 0=COLLECT, 1=STREAM, 2=COMBINE (stderr only),
3=SUPPRESS. Windows pipes differ from Unix's tmpfile input; concurrent producer
and consumers must preserve bounded memory, early-close and backpressure results.
Validate combinations before launch. Wait returns 0 for a valid result and nonzero
for API failure. Wait mode 0=poll, 1=finite deadline, 2=unbounded; timeout_ms is
used only in mode 1, where it must be positive and fit checked monotonic deadline
arithmetic. All uint32 values, including UINT32_MAX, are valid finite durations;
no duration doubles as an unbounded sentinel. Result state
0=running, 1=exited, 2=timed-out, 3=capture-limit, 4=capture-I/O-failed.
A positive finite wait deadline that expires terminates and reaps the owned tree before
returning state 2; it is not a detachable wait timeout. The portable wrapper's
public timeout 0 maps to mode 2. Poll mode never terminates the tree; the same
finite deadline is retained across polling rather than reset on each call. State is stable after completion;
`has_exit_code` distinguishes no child exit.

Output stream 1=stdout and 2=stderr. Copy is allowed after terminal completion;
it reports required bytes in `written` on insufficient capacity, makes no partial
copy then, and never exceeds the configured retained bound. Byte-seen counters
include discarded bytes and saturate rather than wrap. Terminate is idempotent;
close accepts a null owner and has a bounded join that cancels pending pipe I/O.
It returns 0 and nulls the owner only after release; a failed/timed-out close
returns nonzero with error and retains ownership for safe drain/retry, never frees
live state. An attempted native handle close with uncertain failure retains a
poisoned owner, not a blind retry; the shared ownership_state contract below
distinguishes that from a live owner whose I/O has not drained.
Timeout/cancel/abandoned active operations terminate the owned job. On normal
completion, clear KILL_ON_JOB_CLOSE before closing the job so descendants may
survive as Unix permits; only classify normal completion after the required
output EOFs, under the same finite/unbounded wait policy above. Do not impose a
second drain timeout or kill successfully completed descendants. If the cleared-job policy fails, report cleanup failure
instead of a false successful close. One owner serializes wait/copy/close; only
the explicit atomic/native cancellation entry may race. Resource release waits
for all native I/O workers to quiesce. The quote helper counts the terminating UTF-16 NUL in
`required_units`; NULL/zero capacity queries size and insufficient space makes no
partial output. It never invokes a shell.

Error stages must distinguish validation, UTF conversion, allocation, stdio setup,
attribute list, job setup, CreateProcessW, job assignment, resume, pipe I/O, wait
and termination; preserve GetLastError where meaningful. The runtime owns enum
constants and generated declarations alongside these types, not separate library
copies of their numbers. The separate verified-image/transfer API and handshake
below are prerequisites, not an unassigned extra API. Ordinary active launch
abandonment retains kill-on-close safety, with normal completion's explicit
descendant policy above.

Required creation flags are EXTENDED_STARTUPINFO_PRESENT,
CREATE_UNICODE_ENVIRONMENT, CREATE_SUSPENDED and CREATE_NEW_PROCESS_GROUP;
CREATE_NO_WINDOW applies when there is no console. Detached supervisor transfer
has separate reviewed flags and lifetime, never an accidental ordinary-child
exception. Add runtime-origin rows for every type/function/constant and
non-_WIN32 unsupported definitions. A native-status accessor and launchFailed
flag are additive public contracts; code 127 alone is insufficient.

### Filesystem, roots, token and image C boundary

CL-P2-02's extended scope owns **all** entries in this table in the isolated
`src/runtime/c/windows_os.c` asset. Its generated runtime declarations in
`btrc_rt.h` expose opaque `__btrc_windows_file_owner`, `lock_owner`, `token_owner`,
`image_owner` and `launch_owner` tags, fixed-width values and caller buffers.
These proposed names are runtime-origin, not copied SDK declarations. There is
no second Win32Security.h owner: Daemon and Channel call this security boundary.
The `__btrc_windows_launch_error` record is also the shared filesystem/security/
image error carrier; no narrower Win32-only variant is used. Each `int` operation
returns zero for success and otherwise initializes that error
record `{stage, domain, native_code, ownership_state}` before any cleanup can
overwrite the original error. Domain distinguishes validation, Win32, NTSTATUS
and runtime refusal; a mapped Win32 category never replaces the raw NTSTATUS.

| Entry / inputs and outputs | Ownership, bounds and failure contract |
| --- | --- |
| `file_open_absolute(utf8, byte_count, kind, access, file_owner** out, error*)`; `file_open_relative(file_owner* parent, component_utf8, byte_count, kind, access, file_owner** out, error*)` | Borrow inputs for the call; initialize out to null. Parent remains owned by caller. Return one runtime owner on success; no raw HANDLE escapes. Relative open validates exactly one component and never retries by pathname. Stages distinguish UTF conversion, component validation, open, reparse check and identity check. |
| `file_duplicate(file_owner* source, file_owner** out, error*)`; `file_close(file_owner** owner, error*)` | DuplicateHandle gives an independent native ownership claim and wrapper; it never transfers source. Close null is success; successful close nulls owner exactly once. Pending I/O refuses close while preserving a live owner for drain/retry. If CloseHandle was attempted and fails, retain a poisoned wrapper/error, prohibit use/duplication and do not blindly retry an indeterminate native close. The runtime diagnoses uncertain cleanup rather than falsely reporting release. |
| `file_snapshot(file_owner*, snapshot_v2* out, error*)`; `stream_snapshot(FILE* borrowed, snapshot_v2* out, error*)` | Snapshot copies volume64/file-id128, signed times, size, kind and stable version fields. Stream snapshot borrows FILE and `_get_osfhandle` only under the caller's stream lifetime exclusion; it neither closes nor caches that HANDLE. Snapshot failure returns no partial identified value. |
| `directory_next(file_owner*, restart, char* utf8, size_t capacity, size_t* required_bytes, directory_entry* out, error*)` | Owner retains enumeration cursor/bounded native buffer. Capacity includes UTF-8 NUL; insufficient capacity copies nothing and does not advance the entry. End-of-directory is a distinct successful state. Names are not capabilities; relative reopen compares full identity. |
| `file_rename(file_owner* source, file_owner* destination_parent, component_utf8, byte_count, replace, mutation_result* out, error*)`; `file_dispose(file_owner*, mutation_result* out, error*)` | Borrow owners, retaining both claims on failure. No implicit close/transfer. Results distinguish not-committed, committed and indeterminate; unsupported POSIX semantics returns not-committed and never falls back to path operations. Error stage distinguishes capability refusal from native commit failure. |
| `file_read/file_write(file_owner*, uint64_t offset, buffer, capacity, size_t* transferred, error*)`; `file_flush(file_owner*, error*)` | Synchronous caller-buffer borrow only, checked offsets/counts and explicit partial-transfer count. No background retention of btrc buffers. Flush failure never claims durable commit. |
| `lock_acquire(file_owner*, wait, lock_owner** out, error*)`; `lock_release(lock_owner** owner, error*)` | Lock owner retains its own duplicated file handle; caller may close its original. No lock-owner duplication. Refused acquisition releases its temporary claim. Release first unlocks then closes; partial/failed cleanup retains explicit lock-vs-file state, never repeats a completed unlock. An uncertain native close poisons as above. |
| `token_current(token_owner** out, error*)`; `token_from_process(process_id, token_owner** out, error*)`; `token_from_impersonation(token_owner** out, error*)`; `token_copy_sid(token_owner*, bytes, capacity, required_bytes, error*)`; `token_close(token_owner** owner, error*)` | Own token/process handles until extraction/verification ends; copied SID bytes are immutable caller-owned output. Insufficient capacity copies nothing. Token close uses the same live/poisoned rules. TokenUser identity, not process ID or shim uid, authorizes. The channel still owns paired impersonate/RevertToSelf; token extraction failure must not bypass reversion. |
| `private_create/check(file_owner* parent_or_object, component_utf8, token_owner*, file_owner** out, error*)`; `pipe_check_peer_owner(pipe_native_borrow, token_owner*, error*)` | Runtime owns SDK security descriptors, ACL/SID temporary storage and allocator-matched release. Pipe HANDLE is a call-scoped borrow from the channel's checked owner, never retained or closed. Token/DACL decisions are shared with Daemon; no second SDK security owner. |
| `environment_copy(name_utf8, name_bytes, utf8, capacity, required_bytes, present, error*)`; `roots_resolve(roots_snapshot* out, error*)` | Read/GetEnvironmentVariableW through the runtime once per resolution; distinguish absent and present-empty. Windows name grammar and absolute-root validation are explicit. Roots snapshot is immutable owned data released with `roots_close`; caller copies UTF-8 fields with query/copy semantics. No SHGetKnownFolderPath fallback. |
| `process_thread_count(uint32_t* out, error*)` | Runtime owns and closes its Toolhelp snapshot before return. Enumeration failure is not a successful zero count. |

All UTF-8 inputs carry byte counts and reject embedded NUL/invalid encodings.
Runtime UTF-16 allocations count **code units including terminator**, check
multiplication/maximum bounds before allocating, and use strict conversion.
The quote helper above returns UTF-16 units; UTF-8 output helpers return bytes
including NUL. Null/zero-capacity queries report the required size and never
partially populate a caller buffer. Changing environment during a query/copy
is handled by an owned bounded snapshot, not an unbounded sizing retry.
Native record buffers never escape to btrc. Fixed enums/records and every selected
entry have one runtime manifest/generated declaration; non-Windows unsupported
implementations obey the same initialized-output/lifetime contract.

The supervisor-specific interface is proposed as:

```c
typedef struct __btrc_windows_image_owner __btrc_windows_image_owner;
typedef struct {
    uint32_t state; /* confirmed, failed-before-commit, indeterminate-after-commit */
    uint32_t supervisor_pid; /* diagnostic, never a capability */
} __btrc_windows_transfer_result;
int __btrc_windows_supervisor_image_verify(
    const unsigned char expected_sha256[32], uint32_t protocol_version,
    __btrc_windows_image_owner **out, __btrc_windows_launch_error *error);
int __btrc_windows_supervisor_transfer(
    const __btrc_windows_image_owner *image,
    const __btrc_windows_launch_options *options,
    const unsigned char instance_token[16], const unsigned char control_token[16],
    uint64_t startup_timeout_ms, __btrc_windows_transfer_result *result,
    __btrc_windows_launch_error *error);
int __btrc_windows_supervisor_image_close(
    __btrc_windows_image_owner **image, __btrc_windows_launch_error *error);
```

The expected digest/protocol comes from the builder's emitted application
metadata, not a file chosen from PATH. Verification derives the fixed sibling
from the running module and retains its absolute verified path/locks privately.
Transfer rejects options.executable_utf8 and argv attempts to select another
image; only that owner's absolute path is accepted. It borrows the owner until
creation/identity verification and the handshake end, copies bounded startup
storage, scrubs token buffers after use and exposes no token in diagnostics.
Failure before COMMIT cleans the temporary job/tree; failure after COMMIT returns
indeterminate and requires record reconciliation. Closing the image owner frees
verification locks, never terminates an accepted supervisor. This signature and
the isolated-object plumbing must be reviewed/implemented before CX-P2-08.

```text
REQUEST(CL-P2-02): Extend the sole reader-free runtime owner and replace the pasted-helper boundary with the isolated windows_os.c asset.
Repro: WindowsMain has no SDK reader; closure bindings break bootstrap. Pasted SDK includes also leak near/far/IN/OUT/DELETE into emitted user C.
Expected / actual: Own the launch, image/transfer and filesystem/IO/roots/token/thread C seams above, SDK-free btrc_rt.h declarations, runtime manifest/object/library metadata, generated catalogs and non-Windows unsupported definitions. Amend the packet's current process.c-only/_WIN32-only wording explicitly. D14, strict-C11 identifier-collision fixtures and owner cleanup cases are required.
Blocks: CX-P2-04/05/06/08/16 and CL-P2-27. Workaround: retain refusals until this seam and its linker prerequisite land.

REQUEST(CL-P1-11): Add the sibling-image and isolated-runtime-object builder prerequisites before Stage 26; CL-P2-19 preserves them in schema 6.
Repro: Today the package/link plan and runner build one executable; neither can produce or place btrc-daemon-supervisor.exe for an unpackaged Daemon corpus program.
Expected / actual: Paired package/plan writers declare target-filtered auxiliary executable source/basename/protocol, one runtime-manifest external-object/system-library carrier, and package native.system-libraries. Extend native_plan, Makefile, runner.py, bootstrap_harness and bundle metadata/verification; arrange workflow adoption through the integrator. Package the sibling beside every Windows Daemon consumer in isolated corpus output and relocatable/MSIX bundles. Bind its digest/ABI/protocol in generated consumer metadata. No PATH lookup or pre-main compiler hook.
Blocks: CX-P2-08's unpackaged and bundled acceptance, runtime-object linking, CL-P2-27. Workaround: no shell supervisor or unverified loose image.

REQUEST(CL-P2-01): Amend CX-P2-08's dependency, owned paths and acceptance around the selected sibling mechanism.
Expected / actual: Dependencies are the CL-P1-11 auxiliary-image builder/bundle change and CL-P2-02 verified-image/transfer/shared-security seam. Explicitly assign src/stdlib/Daemon/Windows/DaemonSupervisorMain.btrc and the Daemon manifest fragment to CX-P2-08; runtime/compiler/runner remain Claude-owned. Require both-frontends unpackaged corpus under 15 seconds and the CX-P1-07 supplied-image bundle, plus image-planting/missing/replacement/ABI and handshake-failure tests. Repoint CX-P2-08 and CX-P2-16 DACL prerequisites from CX-P2-05 to CL-P2-02.
Blocks: Implementable Daemon/channel packets. Workaround: documentation only until prerequisites land.

REQUEST(CL-P1-14): Add explicit root-manifest private-provider parity, not only group manifests.
Expected / actual: packages.py and Packages.btrc resolve IOFileSnapshotProvider and ProcessHostProvider from the root btrc.toml identically on all 11 rows; positive/overlap/missing-row/cache tests precede their configuration.
Blocks: Root IO/Process provider selection. Workaround: do not configure an uncovered root seam.

REQUEST(CL-P2-27): Land compiler-import provider selection with complete 11-row coverage and native Windows bootstrap.
Expected / actual: Byte-identical BtrccMain/MacOSMain on the post-identity baseline; reviewed WindowsMain changes, explicit Windows targets, LOCALAPPDATA roots identical to btrcpy, owner-line approval and final derived symbols/lock. Name Driver.sync, FePackageFileStore/FeStagedFile (including discard of failed .btrc-package-* stages) and SourceIo identity as migrations required before claiming btrcc -o on Windows; stdout-only bootstrap is not that claim. Keep unmigrated paths fail-closed. CL-P1-09/10/14/15 and the runtime/link dependencies remain prerequisites.
Blocks: Compiler-import provider delivery and later -o support. Workaround: native stdout bootstrap stays distinct from compiler-output-file qualification.

REQUEST(CL-P2-01): Assign and own the D27 portable identity/error/status/environment landing scope before Windows exact handles.
Expected / actual: >=192-bit identity, cacheToken v2, signed timestamps; Windows legacy constructor/fromStatus explicitly unidentified; stable mode mask and Windows ChangeTime-excluding hydration policy above; additive native error domain, peer SID identity, native exit/launchFailed and indeterminate Daemon start; Windows env grammar. Land atomically with Linux/macOS reference providers and all-host C diffs/bootstrap before CL-P2-27's baseline. Assign a numbered implementation packet on approval; no unnamed owner may start these contract edits.
Blocks: Safe identity/launch. Workaround: unidentified cannot compare equal; ReFS/Dev Drive exact support is restricted until qualification.

REQUEST(CL-P2-01): Assign corrected SDK/opaque-HANDLE qualification to the native-interop owner before reader-bound providers.
Expected / actual: Record the R1 NULL/INVALID_HANDLE_VALUE and BOOL-release policy or descriptor-owner exception; amend the receiving packet with Requests.json ownership and both GNU corrected include-recipe runs. Keep the failed earlier 89/90 probe withdrawn. This docs-only packet cannot claim or commit that code fixture outside its ownership.
Blocks: Terminal/Daemon/channel bindings. Workaround: missing qualified SDK semantics fail closed.

REQUEST(CL-P2-01): Record adaptation choices and packet amendments before implementation.
Expected / actual: Q4–Q6, packaged-only autostart/hard-stop/file-capability Daemon, redirected password parity, name-surrogate/mount refusal, exact component grammar, environment-root replacement for row 7, same-user channel authentication with unchanged framing, full target/refusal matrix and mobile N labels. CX-P2-15 owns new mobile ProcessThreads/worker bindings and the reviewed Android HostWorkerPools inventory restriction. Approval remains pending, not inferred from docs CI.
Blocks: Contract approval. Workaround: all choices remain proposals.

REQUEST(CL-P2-14): Own wide fopen/getenv/environ/argv consumers and retire each shim only after migration.
Expected / actual: Driver.sync, package staging/discard and SourceIo use native identified snapshots before their unsafe CRT paths reopen. Re-extract availability tables and obtain zero-warning WindowsMain transpiles; retain shims for unmigrated users. Non-ASCII compiler-host acceptance belongs to Stage 27.
Blocks: Shim retirement and full Unicode-host/output-file claims. Workaround: retain explicit unsupported paths.

REQUEST(CL-P2-11): Distinguish Stage-26 cross-compilation from Stage-27 Windows-host SDK compilation.
Expected / actual: Until the Windows-built reader and btrcpy reader launcher land, CX-P1-07 reader-bound provider suites consume both-frontends Linux-built bundles. Native Windows-host compilation of Terminal/Daemon/Channel is unavailable; do not make missing Windows SDK a test failure for a prebuilt-bundle job.
Blocks: Native Windows-host header imports. Workaround: qualified cross-build then native execution, reported separately.

REQUEST(CL-P2-12): Define serialized compiler-process workers; preserve inline-only Windows pools meanwhile.
Expected / actual: Explicit startup/IPC/crash/resource-accounting design; native threads do not implement forked retained state.
Blocks: Windows multiprocess pools. Workaround: documented inline-only behavior.

REQUEST(CL-P2-01): Assign the capability acceptance plan to CX-P1-07 and the qualification registry changes to CL-P1-19.
Expected / actual: Amend those packets: CX-P1-07 provisions console, UNC, second-account and package cases plus optional ReFS/CfAPI/WOF fixtures; CL-P1-19 adds windows-arm64 RUNNERS/capability and per-runner ledger integration in its owned-scope extension. Integrator owns all workflow installation under the user's prohibition. Approve the explicit support/refusal tiers below, rather than silently dropping unsupported filesystem cells. A numbered follow-up is required if these named owners cannot accept the extension.
Blocks: Native evidence coverage and full ARM64/filesystem qualification. Workaround: no native or optional-filesystem support claim from Linux cross-builds.
```

Compat retirement candidates are the `fchmod`, `fcntl`, `pread`, `O_NOFOLLOW` and
`O_DIRECTORY` unsupported routes after native file/lock/handle migration; uid/euid
sentinels after every identity decision uses token SIDs; and `lstat`/`unlink`,
`mkdir`, `realpath`, `mkdtemp`, environment and time shims only after their actual
remaining consumers migrate. `O_CLOEXEC`'s noninheritance mapping remains necessary
for UCRT descriptor consumers. Empty process/terminal/socket include overlays
remain until reachability audits show they are unused. Inventory every caller;
bootstrap/runtime internals and public product providers need not migrate together.

## Exit tests and evidence

These are proposed test owners and fixtures for implementation packets. This
docs-only packet adds no skip rules and claims no Windows execution. Each driver
must run both Python and self-hosted frontend variants where compilation applies;
the existing skip-ledger format records explicit runner/target/capability reasons.
Linux may skip native Windows execution with an approved platform rule, but must
still exercise provider filtering, reader selection and negative imports. On a
declared native Windows execution host, a missing bundled image/helper/provider
is a failure. Before CL-P2-11, reader-bound suites compile on Linux through both
frontends and execute the verified bundle through CX-P1-07's windows-native
executor; do not require an unavailable SDK reader on that execution host.
Native Windows-host compilation remains unavailable until CL-P2-11. After that
qualification, missing declared SDK/reader is a compile-job failure. ARM64
qualification requires a native ARM64 host; emulation is separate evidence.

| Exit / proposed Python driver | Proposed `src/tests/native/` fixture | Required cases and skip boundary |
| --- | --- | --- |
| Provider selection: extend `test_target_provider_matrix.py`; native binding qualification: `test_windows_os_service_imports.py` | `os_services_windows/` | Both GNU targets, both frontends, SDK function and record selection, zero foreign SDK reads for unrelated targets, reader-free root Process/IO imports on all 11 rows, corrected SDK recipe only for non-closure bindings, absent runtime capability gives an explicit refusal. Cross-target checks run on Linux; linking/runtime evidence is separate. |
| Exact filesystem: `test_windows_filesystem_handles.py` | `filesystem_windows/` | Repeated ancestor-junction swap during walk/delete, final symlink/name-surrogate/mount refusal; cloud placeholder (CfAPI provider) hydrate-during-read and WOF reopen identity; ADS/device/trailing-dot/lock-case grammar; ReFS full identity; DACL denial and inherited broad ACL rejection, stale/reused handles, >4-GiB snapshots, long/UNC/non-ASCII paths, deterministic bounded traversal, concurrent mutation. Native-host rule only; UNC share provisioning is an explicit capability requirement, never silently omitted. |
| Replacement/locks: `test_windows_filesystem_atomic.py` | `filesystem_atomic_windows/` | Kill writer before/after replace, old-or-new content, flush failure, permission failure, file identity preservation expectations; two-process LockFileEx contention, wait/nonwait, ordinary I/O conflict, crash release and cleanup. Report filesystem type and durability limits. |
| Roots and stream snapshot: `test_windows_application_directories.py` | `application_directories_windows/` | Drive/UNC validation occurs before portable facade construction, wide LOCALAPPDATA roots, empty/unset/relative refusal and BTRC_STATE_DIR parity between both frontends, packaged/unpackaged identity, override validation, owner DACL, borrowed-handle lifetime. MSIX cases require a separately declared packaged runner capability. |
| Launch: `test_windows_launch_seam.py` (CL-P2-02 owner), `test_windows_process.py` | `windows_launch/` (existing packet name), `process_windows/` | Batch/.cmd/non-PE refusal, planted-cwd executable, child PATH override/empty/unset/empty-component policy and malformed PE validation, argv[0] quote and UTF-16 length bounds; empty/space/quote/backslash/trailing-backslash/non-BMP argv, environment case/removal, cwd, missing executable vs child exit 127, high-bit exit, explicit stdio inheritance and no leaked handles, concurrent stdout/stderr, stdin backpressure, bounds, timeout killing a three-level tree, descendant-held pipe with no deadline (test helper eventually closes) and finite deadline/124, UINT32_MAX as finite wait, suspended assignment failure. Unsupported foreground, exact descriptor launch and UnixShell diagnostics. |
| Terminal: `test_windows_terminal.py` | `terminal_windows/` | Real console Unicode and password echo/mode restoration on success, overflow, Ctrl-C, read failure; redirected ordinary/password input matches Unix bounded behavior after the adaptation decision; no secret in logs. Console cases need an explicit interactive-console host, not a headless runner skip disguised as green. |
| Daemon: `test_windows_daemon.py` | `daemon_windows/` | Supplied sibling in unpackaged corpus and relocated bundle through both frontends; planted PATH/cwd, missing/replaced/hash/ABI/protocol-mismatched image and READY/COMMIT/ACK failures; start/status/stop/restart, duplicate start, stale PID/token, protected record/log, launcher exit, supervisor crash, denied breakaway, tree cleanup on deadline, opt-in autostart and packaged restrictions. Separate package capability rule; core native lifecycle never skipped on a qualified Windows host. |
| Channel: `test_windows_local_application_channel.py` | `local_application_channel_windows/` | First-instance exclusivity plus multiple owned listening instances, remote rejection, same-user success, other-user SID rejection, impersonation restoration on every error, server owner/token authentication/PID reuse, disconnect/restart refusal without replay, unchanged exact wire bytes (no hello), empty/malformed/oversize/partial frames, slow peers, cancellation and one deadline, bounded nonblocking poll. Cross-user identity requires a provisioned second account and an explicit runner capability. |
| Jobs: `test_windows_background_jobs.py` | `background_jobs_windows/` | Worker/pending bounds, rejected ownership, one completion, owner-thread delivery, cancellation, lost-wakeup stress, DRAIN/CANCEL_PENDING, failed-join retry, foreign-thread exceptions and teardown leaks, thread count accuracy. Native Windows x64 and ARM64 required. |
| Process pools: `test_windows_worker_pools.py` | `worker_pools_windows/` | Inline-only refusal before CL-P2-12; after it lands, serialized startup, framing, crash isolation, resource accounting and cancellation. Do not mark multiprocess parity complete from thread tests. |

### Capability tiers and achievable outcomes

Freeze **required supported cases and explicit refusal cases** separately from
optional-filesystem positive qualification before the first run. Baseline Stage
26 support requires native Windows x64 NTFS, ordinary long/UNC operations,
launch/tree-kill, channel authentication and worker tests. UNC traversal/read
must pass on the provisioned share. An exact rename/delete on SMB or FAT/exFAT
without FILE_SUPPORTS_POSIX_UNLINK_RENAME must return the documented unsupported
outcome before mutation; that is a tested operation-level **restricted** inventory
cell, not a skipped positive test or a claim that all UNC operations work. A
filesystem reporting the capability must pass the exact mutation cases or the
qualification fails. Ordinary unsupported operations retain no weaker fallback.

| Capability / named provisioning owner | Qualifying outcome and missing-capability disposition |
| --- | --- |
| Native x64 NTFS, console, temporary UNC share and second account: CX-P1-07 | Required baseline. Provision with deterministic cleanup; missing capability or failed provisioning fails that qualifying job. CLI/stdin cases run independently of actual console cases. |
| Native ARM64: CX-P1-07; `RUNNERS`/ledger registration extension: CL-P1-19 | Same core cases through native ARM64 execution. Until registered/provisioned, ARM64 exit remains awaiting runner; x64 completion is reported separately and never closes both-GNU-target/W1 acceptance. |
| MSIX/startup task: CX-P1-07 packaged capability | Unpackaged core lifecycle may qualify independently. Packaged/autostart acceptance remains awaiting package capability until real permission and lifecycle cases pass; no silent unbounded skip. |
| ReFS/Dev Drive test volume: CX-P1-07 | Before the 192-bit carrier and positive native qualification, a ReFS exact-operation probe must return restricted with no mutation. Positive support cells stay missing/unqualified until the separately declared capability passes full identity/lock/rename cases. This does not block an explicitly NTFS-scoped result and cannot be called full filesystem parity. |
| CfAPI registered test sync root and WOF test volume/file: CX-P1-07 | Initial missing capability means corresponding non-surrogate-tag operations remain explicitly restricted. Qualified support requires provider registration/hydration and WOF identity cases, including unchanged content through hydration. A candidate advertising support must fail, not skip, when provisioning breaks. |
| SMB/FAT/exFAT mutation policy: CX-P1-07 fixture matrix | Assert supported exact semantics only when advertised and proved. Otherwise record per-operation restricted cells and assert no mutation. Volume-kind labels alone never authorize POSIX_SEMANTICS. |

CL-P2-01 must approve these scoped support/refusal inventory cells and amend the
provider packets' unconditional positive-test wording before delivery. Required
baseline cases cannot be moved into the optional tier to obtain green results.
A full-platform claim still waits for both target ABIs and every advertised
capability. Missing optional positive qualifications are named and retained in
the report, not subtracted from a purported full-support denominator.

Freeze denominators before the first qualifying run: 100 junction/rename-race
attempts per frontend/ABI, 100 launch/cleanup cycles (including 10 forced timeout
trees), 100 channel authentication/teardown cycles including 10 second-account
rejections, and 100 job-pool create/close cycles. Every individual semantic case
in the declared support/refusal tier runs at least once per supported
frontend/ABI; missing required cases are listed and fail that tier. Optional
positive qualification has a separate predeclared denominator and an explicit
pending status until provisioned; it cannot be reported as passed. Proposed budgets require CL-P2-01 approval.
Linux-devcontainer and macOS runners get exact Windows-native skip rules while
still running cross-target selector checks; windows has no core-native skip;
windows-arm64 is registered before ARM64 execution is claimed. Console, UNC,
second-account, MSIX, ReFS/Dev Drive, CfAPI and WOF rows get explicit
capability/provisioning records and the table's owners/outcomes; a required
hosted capability provisioning failure fails its qualifying job.

Every native exit reports target, OS, architecture, packaging, compiler/frontend,
SDK identity, pass/fail/skip counts and job/run ID. Both GNU targets must also
compile/link with strict C11 diagnostics; Windows x64 bootstrap plus actual ARM64
execution satisfy different W1 requirements. Leak/handle-count and adversarial
race tests need repeated runs under bounded deadlines, not timing-only sleeps.

## Review and deferred work

The corrected binding recipe and runtime route still require qualification;
provider code, linking, native execution, package permissions and performance are deferred to
implementation packets. CL-P2-01 review/PLAN approval remains pending. Open review
decisions include approval of the native-status accessor, NT operation coverage,
sibling image/build contract, READY/COMMIT transfer state and scoped capability
exits. Concrete choices above replace the earlier unspecified mechanisms; they
still need CL-P2-01 approval and implementation evidence, not owner polling.
UI folder-picker grants, Windows UI event-loop integration, process-pool bootstrap
and MSVC qualification belong to their named later owners. No adaptation approval,
inventory promotion or parity claim follows merely from this document's CI pass.
