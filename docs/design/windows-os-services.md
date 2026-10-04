# Windows OS-services providers

Status: CX-P2-01 revision 2, approval pending, based on `72592d36f560517a39e54f4b92b0149d44bef4d6`.
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
| Q4 | MSIX release packaging; unpackaged developer tools remain supported | Known Folder roots, package identity and background-process restrictions need separate packaged tests. A different package model changes those tests and autostart integration. |
| Q5 | Named pipes for LocalApplicationChannel | No AF_UNIX credentials emulation. Choosing another transport requires a new authenticated peer-identity contract. |
| Q6 | `LockFileEx` behind `AdvisoryFileLock` | The Windows lock is mandatory for conflicting byte-range I/O. Documentation and callers must accept this stronger behavior. |

Windows 11 is the product floor fixed by PLAN decision D21. The SDK declarations
use `_WIN32_WINNT=0x0A00` (also used for Windows 11); this does not qualify Windows
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
| `Daemon/Daemon.btrc`, `DaemonControl.btrc`, `DaemonControlFiles.btrc`, `DaemonControlProtocol.btrc`: specification, lifecycle, records and supervisor launch | `Daemon/Windows/DaemonProvider.btrc`; native supervisor entry owned by the implementation packet | `Daemon/btrc.toml` |
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
helpers owned by CL-P2-02 (or a named extension packet) in src/runtime/c.
That request covers stream snapshots, NT relative opens, enumeration, rename,
disposition, locks, Known Folder lookup, token SID and process/thread observation.
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
frontends; no hand-rolled resolver. Unix providers are selection-only shells
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
U means its non-platform Unix/ selector retaining today's implementation; R
means an explicit operation-level refusal provider with the approved diagnostic;
W means Windows GNU runtime-backed closure seam (or checked SDK provider outside
the closure); M means an explicit MSVC refusal preserving facade imports.

| All 11 target rows | IO identity / FileSystem / handles / tree / roots | Process | Terminal | Daemon | Channel | NativeWorker / Executor | ProcessThreads / HostWorkerPools |
|---|---|---|---|---|---|---|---|
| linux-aarch64 | U | U | U | U | U | U | U |
| linux-x86_64 | U | U | U | U | U | U | U |
| macos-aarch64 | U | U | U | U | U | U | U |
| macos-x86_64 | U | U | U | U | U | U | U |
| ios-aarch64 | U + mobile root refusal pending CX-P2-14 | R | U redirected / R console-only | R | R pending mobile channel | U | U thread count / R processes |
| ios-aarch64-simulator | U + mobile root refusal pending CX-P2-14 | R | U redirected / R console-only | R | R pending mobile channel | U | U thread count / R processes |
| android-aarch64 | U + mobile root refusal pending CX-P2-14 | R (Q8) | U redirected / R console-only | R | R pending mobile channel | U | U thread count / R processes |
| android-x86_64 | U + mobile root refusal pending CX-P2-14 | R (Q8) | U redirected / R console-only | R | R pending mobile channel | U | U thread count / R processes |
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

## Runtime SDK inventory and non-closure bindings

The following sets describe the SDK work a runtime/native owner must qualify.
They are not blanket native.bindings entries on compiler-import providers.
Only Terminal, Daemon, LocalApplicationChannel and BackgroundJobExecutor/
NativeWorker (outside btrcc's closure) may use reader bindings. Those headers
include the pinned SDK, never copied Win32 declarations or fabricated layouts.
Windows bindings use os=["windows"], env=["gnu"], C11 and explicit symbols.
Rely on MinGW's _WIN32_WINNT default; do not redefine 0x0A00 against its 0x0a00
under -Werror. D21's Windows 11 floor does not claim Windows 10 support.

| Owner / header or runtime unit | SDK functions to qualify | Libraries |
|---|---|---|
| Runtime filesystem/IO snapshot | CreateFileW, NtCreateFile, NtSetInformationFile, GetFileInformationByHandleEx, SetFileInformationByHandle, GetFinalPathNameByHandleW, GetVolumeInformationByHandleW, ReadFile, WriteFile, GetFileSizeEx, SetFilePointerEx, FlushFileBuffers, ReplaceFileW, MoveFileExW, LockFileEx, UnlockFileEx, _get_osfhandle, RtlNtStatusToDosError | kernel32, ntdll, CRT |
| Runtime roots/security; non-closure Win32Security.h | SHGetKnownFolderPath, CoTaskMemFree, OpenProcessToken, GetTokenInformation, GetCurrentProcess, EqualSid, GetSecurityInfo, SetSecurityInfo, GetAclInformation, GetAce, GetLengthSid, CopySid, InitializeAcl, AddAccessAllowedAceEx, InitializeSecurityDescriptor, SetSecurityDescriptorDacl, SetSecurityDescriptorOwner, SetSecurityDescriptorControl, LocalFree | shell32, ole32, advapi32, kernel32 |
| Sole runtime launch owner | CreateProcessW, InitializeProcThreadAttributeList, UpdateProcThreadAttribute, DeleteProcThreadAttributeList, CreateJobObjectW, SetInformationJobObject, QueryInformationJobObject, IsProcessInJob, AssignProcessToJobObject, TerminateJobObject, TerminateProcess, CreatePipe, SetHandleInformation, DuplicateHandle, GetStdHandle, ResumeThread, GetExitCodeProcess, GetEnvironmentStringsW, FreeEnvironmentStringsW, WaitForSingleObject, WaitForMultipleObjects, CancelIoEx, GetOverlappedResult | kernel32 |
| Terminal/Windows/Win32Terminal.h | GetStdHandle, GetConsoleMode, SetConsoleMode, ReadConsoleW, WriteConsoleW, ReadConsoleInputW, SetConsoleCtrlHandler, CancelSynchronousIo, GetCurrentThread, DuplicateHandle, GetFileType, SetEvent | kernel32 |
| Daemon/Windows/Win32Daemon.h | BCryptGenRandom and security functions; **no CreateProcess/job/pipe launch surface** | bcrypt, advapi32, kernel32 |
| LocalApplicationChannel/Windows/Win32LocalChannel.h | CreateNamedPipeW, ConnectNamedPipe, DisconnectNamedPipe, WaitNamedPipeW, GetNamedPipeClientProcessId, GetNamedPipeServerProcessId, OpenProcess, OpenThreadToken, ImpersonateNamedPipeClient, RevertToSelf, CreateEventW, SetEvent, CreateFileW, ReadFile, WriteFile, CancelIoEx, GetOverlappedResult, WaitForSingleObject; security functions above | kernel32, advapi32 |
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

Zig already ships ole32/bcrypt import libraries, but current manifests and link
plans cannot declare them. A Claude system-library mechanism must reach both
frontends, native_plan, Makefile, windows.yml, bootstrap_harness and runner.py.
This is a hard prerequisite for roots/Daemon and CL-P2-27, not a flake download.
No pragma comment(lib) workaround is allowed on MinGW.

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
  machine-wide longPathAware policy. Basic fopen/getenv/environ must also use
  wide runtime helpers assigned to Claude; ANSI code-page paths cannot pass the
  Stage-26 non-ASCII exit.
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
* Resolve application roots with `SHGetKnownFolderPath`, free returned storage
  with `CoTaskMemFree`, then apply the target path policy. Separate configuration,
  cache and durable data purposes: FOLDERID_LocalAppData for generation/cache
  and machine-local state, FOLDERID_RoamingAppData for explicitly roaming config;
  btrcc generation state must match btrcpy's LOCALAPPDATA policy (never roam it); honor explicit overrides only after validation.
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
permitted. ReFS and Dev Drive remain unavailable until this carrier and their
native fixtures are qualified. That portable change intentionally changes all
host C and needs its own reviewed diffs/bootstrap gate; CL-P2-27 then uses the
new baseline and preserves desktop C while adding Windows providers.

The Windows snapshot uses LastWriteTime and ChangeTime from FILE_BASIC_INFO;
FILETIME ticks are 100 ns since 1601. Subtract 116444736000000000 ticks using
checked signed arithmetic, floor-divide by 10,000,000 for seconds and retain a
nonnegative remainder times 100 as nanoseconds. Pre-1970 seconds remain signed
in the new carrier/token; the old unsigned surface requires an explicit reviewed
adapter, never wraparound. Proposed Windows mode encodes FileKind in a dedicated
high field and the raw FILE_ATTRIBUTE_* bits in the low 32 bits; it is version
metadata, not a POSIX permission or DACL summary. Security decisions always use
the live descriptor/token/DACL checks. Freeze this mapping in the identity packet.

Win32/NTSTATUS failures need a native-code domain alongside FileSystemError's
existing channel, with an additive atomically landed contract; convert NTSTATUS
with RtlNtStatusToDosError for common categorization while preserving raw code
and domain. Runtime HANDLE owners are private to Claude. Non-closure reader
bindings need approved R1 support for opaque void* HANDLE values, NULL or
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
relative paths against the child's cwd. A bare name searches only explicit PATH
entries, never implicit parent application/cwd search; relative PATH entries
are resolved against child cwd by the declared policy. Do not use PATHEXT script
types: accept only PE executables with explicit extension or .exe/.com probing.
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
blocking. Bound buffers and drain activity, including a descendant keeping a pipe
open after the direct child exits. Cancellation, timeout and capture overflow
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

Keep DaemonSpec's validation and declared Command data; replace the rendered
shell supervisor with the explicitly packaged `btrc-daemon-supervisor.exe`
entry, owned by CX-P2-08 and launched only through the runtime transfer helper. Resolve owner-controlled records/logs through
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
until an authenticated existing-instance handshake proves ALREADY_RUNNING;
never retry by dropping exclusivity or trusting a squatting endpoint.

The initial server uses FILE_FLAG_FIRST_PIPE_INSTANCE|PIPE_REJECT_REMOTE_CLIENTS,
explicit TokenUser owner, protected user-only DACL and nMaxInstances=maximumClients.
Later instances owned by that server omit FIRST_PIPE_INSTANCE. Preserve the
four-byte big-endian frame, empty payload, one reply, bounded bytes and one
monotonic connect/send/receive deadline. Overlapped poll is nonblocking; canceled
I/O is completed/drained before releasing OVERLAPPED storage, events or handles.

The client opens with SECURITY_SQOS_PRESENT|SECURITY_IDENTIFICATION and
READ_CONTROL. **Before its first write**, verify pipe-object owner SID, then the
server process token while holding the process handle, then read a bounded
server-first hello matching the protected instance record;
PID alone is diagnostic. A process disappearing/reused during verification fails
closed. Before any product frame, the server sends only that fixed-size routing hello,
then reads the bounded four-byte header, impersonates the
client, calls OpenThreadToken(OpenAsSelf=TRUE), and compares TokenUser with EqualSid.
RevertToSelf before reading any product frame or executing a command; failure to
revert terminates the process immediately. No exception return may leave it
impersonating. Generation/token checks bind the authenticated instance across
restart; no unauthorized peer reaches product dispatch.

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
until its thread ABI is separately qualified. Preserve the existing bounds
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
typedef struct { uint32_t stage, win32_error; } __btrc_windows_launch_error;
typedef struct {
    uint32_t state, native_exit_code, has_exit_code, launch_failed;
    uint64_t stdout_bytes_seen, stderr_bytes_seen;
    size_t stdout_bytes_retained, stderr_bytes_retained;
} __btrc_windows_launch_result;
int __btrc_windows_launch(const __btrc_windows_launch_options *options,
    __btrc_windows_launch_owner **out, __btrc_windows_launch_error *error);
int __btrc_windows_launch_wait(__btrc_windows_launch_owner *launch,
    uint32_t timeout_ms, __btrc_windows_launch_result *result,
    __btrc_windows_launch_error *error);
int __btrc_windows_launch_copy_output(__btrc_windows_launch_owner *launch,
    uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written);
int __btrc_windows_launch_terminate(__btrc_windows_launch_owner *launch,
    uint32_t exit_code, __btrc_windows_launch_error *error);
int __btrc_windows_launch_close(__btrc_windows_launch_owner **launch,
    uint32_t timeout_ms, __btrc_windows_launch_error *error);
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
for API failure. Timeout 0 polls; UINT32_MAX waits without a deadline. Result state
0=running, 1=exited, 2=timed-out, 3=capture-limit, 4=capture-I/O-failed.
A positive finite wait deadline that expires terminates and reaps the owned tree before
returning state 2; it is not a detachable wait timeout. The portable wrapper's
public timeout 0 means unbounded and therefore maps to UINT32_MAX, not poll.
Polling with zero never terminates the tree. State is stable after completion;
`has_exit_code` distinguishes no child exit.

Output stream 1=stdout and 2=stderr. Copy is allowed after terminal completion;
it reports required bytes in `written` on insufficient capacity, makes no partial
copy then, and never exceeds the configured retained bound. Byte-seen counters
include discarded bytes and saturate rather than wrap. Terminate is idempotent;
close accepts a null owner and has a bounded join that cancels pending pipe I/O.
It returns 0 and nulls the owner only after release; a failed/timed-out close
returns nonzero with error and retains ownership for retry, never frees live state.
Timeout/cancel/abandoned active operations terminate the owned job. On normal
completion, clear KILL_ON_JOB_CLOSE before closing the job so descendants may
survive as Unix permits; bound inherited-pipe drains without silently killing
successful descendants. If the cleared-job policy fails, report cleanup failure
instead of a false successful close. One owner serializes wait/copy/close; only
the explicit atomic/native cancellation entry may race. Resource release waits
for all native I/O workers to quiesce. The quote helper counts the terminating UTF-16 NUL in
`required_units`; NULL/zero capacity queries size and insufficient space makes no
partial output. It never invokes a shell.

Error stages must distinguish validation, UTF conversion, allocation, stdio setup,
attribute list, job setup, CreateProcessW, job assignment, resume, pipe I/O, wait
and termination; preserve GetLastError where meaningful. The runtime owns enum
constants and generated declarations alongside these types, not separate library
copies of their numbers. A detached supervisor needs an additional reviewed
ownership-transfer API; ordinary active launch abandonment retains kill-on-close safety, with normal
completion's explicit descendant policy above.

Required creation flags are EXTENDED_STARTUPINFO_PRESENT,
CREATE_UNICODE_ENVIRONMENT, CREATE_SUSPENDED and CREATE_NEW_PROCESS_GROUP;
CREATE_NO_WINDOW applies when there is no console. Detached supervisor transfer
has separate reviewed flags and lifetime, never an accidental ordinary-child
exception. Add runtime-origin rows for every type/function/constant and
non-_WIN32 unsupported definitions. A native-status accessor and launchFailed
flag are additive public contracts; code 127 alone is insufficient.

```text
REQUEST(CL-P2-02): Extend the sole reader-free runtime owner to launch and compiler-closure filesystem/IO/roots/token/thread operations.
Repro: WindowsMain composes no SDK reader; native.bindings in its transitive providers fail its bootstrap and make reader launch circular.
Expected / actual: Runtime C owns native handles, NT relative operations, snapshots, Known Folder/token queries and launch; btrc sees checked primitive/opaque boundaries only. Implement reviewed signatures above in src/runtime/c/process.c and btrc_rt.h (plus assigned filesystem unit), runtime manifest/generated catalog and hosted_abi runtime-origin declarations with non-Windows unsupported definitions. Daemon gets a detached transfer entry, not a second launch owner. D14 and native fixtures required.
Blocks: CX-P2-04/05/06 and CL-P2-27. Workaround: retain refusals until the runtime seam lands.

REQUEST(CL-P2-27): Land compiler-import provider selection with complete 11-row coverage and native Windows bootstrap.
Expected / actual: Byte-identical BtrccMain/MacOSMain on the post-identity baseline; reviewed WindowsMain changes, explicit --target Windows transpiles in Makefile, generation-state LOCALAPPDATA parity with btrcpy, owner-line approval and final derived symbols/lock. Root private providers require CL-P1-14 confirmation; CL-P1-09/10/14/15 are hard prerequisites.
Blocks: Windows compiler-import provider delivery. Workaround: no runtime Platform guard to hide unreachable POSIX names.

REQUEST(CL-P2-01): Assign a D27 portable identity/error/status/environment landing before Windows exact handles.
Expected / actual: >=192-bit FileSnapshot identity with cacheToken v2 and signed timestamps; additive native error domain, authenticated peer identity beside Unix peerUser, native process status/launchFailed, and Windows environment-name grammar. Atomic Linux/macOS reference-provider changes, reviewed all-host C diffs and bootstrap proof precede the CL-P2-27 unchanged-desktop-C baseline.
Blocks: Safe Windows identity/launch. Workaround: no truncation; ReFS/Dev Drive remain unavailable until qualified.

REQUEST(CL-P1-11 / CL-P2-19): Add one target-filtered system import-library mechanism and amend v5 or advance v6.
Expected / actual: Closed native.system-libraries grammar with os/arch/env selection parsed identically by both frontends and honored by native_plan, Makefile, windows.yml, bootstrap_harness and runner.py. The SDK already supplies ole32/bcrypt; flake exposure does not fix missing linker arguments. Shared facility with HTTP's ws2_32/winhttp request.
Blocks: ApplicationDirectories, Daemon and CL-P2-27. Workaround: no pragma comment(lib) or custom linker escape.

REQUEST(CL-P2-01 / native-interop owner): Qualify opaque HANDLE unique-resource ownership and corrected reader fixtures outside btrcc's closure.
Expected / actual: NULL/INVALID_HANDLE_VALUE and BOOL-release support or explicit R1 descriptor exception; commit Requests.json and run corrected Stage-24 include recipe on both GNU targets with selected record layouts. Old 89/90 probe is not accepted proof.
Blocks: Terminal/Daemon/channel binding qualification. Workaround: no copied SDK ABI.

REQUEST(CL-P2-01): Record decisions and amend packet scope before implementation.
Expected / actual: Q4 packaged-only autostart and declared hard-stop Windows Daemon/file-capability protocol; redirected password input matches Unix; name-surrogate/mount refusal plus non-surrogate identity re-open; full component grammar; complete target matrix/refusal inventory; wide runtime fopen/environment helpers. The supervisor executable is btrc-daemon-supervisor.exe. Adaptation method/job wording is already corrected and needs no repeated request.
Blocks: Contract approval. Workaround: all choices remain proposals.

REQUEST(CL-P2-14): Retire overlay shims only after per-consumer compile-time unreachability, platform-table re-extraction and zero-warning WindowsMain transpiles.
Expected / actual: Preserve compiler/runtime consumers until migrated; runtime Platform.isWindows guards are not sufficient.
Blocks: Shim removal. Workaround: retain each still-needed shim.

REQUEST(CL-P2-12): Define serialized compiler-process workers; preserve inline-only pools meanwhile.
Expected / actual: Explicit startup/IPC/crash/resource-accounting design; native threads do not implement forked retained state.
Blocks: Windows multiprocess pools. Workaround: documented inline-only behavior.

REQUEST(CL-REQ): Assign hosted capability and evidence integration.
Expected / actual: windows-arm64 runner in qualification plus CX-P1-07 collector; admin windows-latest fixtures provision AllocConsole/reader, a temporary UNC share, a second-account helper and packaged MSIX cases with cleanup. Add capability checks, per-runner expected skips and test_target_provider_matrix coverage; Stage-26 required UNC/channel cases cannot disappear behind missing capabilities.
Blocks: Native platform exit evidence. Workaround: cross-build evidence remains labelled non-native.
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
declared native Windows host, missing SDK/helper/provider is a failure, not a skip.
ARM64 qualification requires a native ARM64 host; emulation is separate evidence.

| Exit / proposed Python driver | Proposed `src/tests/native/` fixture | Required cases and skip boundary |
| --- | --- | --- |
| Provider selection: extend `test_target_provider_matrix.py`; native binding qualification: `test_windows_os_service_imports.py` | `os_services_windows/` | Both GNU targets, both frontends, SDK function and record selection, zero foreign SDK reads for unrelated targets, reader-free root Process/IO imports on all 11 rows, corrected SDK recipe only for non-closure bindings, absent runtime capability gives an explicit refusal. Cross-target checks run on Linux; linking/runtime evidence is separate. |
| Exact filesystem: `test_windows_filesystem_handles.py` | `filesystem_windows/` | Repeated ancestor-junction swap during walk/delete, final symlink/name-surrogate/mount refusal; cloud placeholder (CfAPI provider) and WOF reopen identity; ADS/device/trailing-dot/lock-case grammar; ReFS full identity; DACL denial and inherited broad ACL rejection, stale/reused handles, >4-GiB snapshots, long/UNC/non-ASCII paths, deterministic bounded traversal, concurrent mutation. Native-host rule only; UNC share provisioning is an explicit capability requirement, never silently omitted. |
| Replacement/locks: `test_windows_filesystem_atomic.py` | `filesystem_atomic_windows/` | Kill writer before/after replace, old-or-new content, flush failure, permission failure, file identity preservation expectations; two-process LockFileEx contention, wait/nonwait, ordinary I/O conflict, crash release and cleanup. Report filesystem type and durability limits. |
| Roots and stream snapshot: `test_windows_application_directories.py` | `application_directories_windows/` | Drive/UNC validation occurs before portable facade construction, actual Known Folder root, packaged/unpackaged identity, override validation, owner DACL, borrowed-handle lifetime. MSIX cases require a separately declared packaged runner capability. |
| Launch: `test_windows_launch_seam.py` (CL-P2-02 owner), `test_windows_process.py` | `windows_launch/` (existing packet name), `process_windows/` | Batch/.cmd/non-PE refusal, planted-cwd executable, child PATH override/unset, argv[0] quote and UTF-16 length bounds; empty/space/quote/backslash/trailing-backslash/non-BMP argv, environment case/removal, cwd, missing executable vs child exit 127, high-bit exit, explicit stdio inheritance and no leaked handles, concurrent stdout/stderr, stdin backpressure, bounds, timeout killing a three-level tree, descendant-held pipe, suspended assignment failure. Unsupported foreground, exact descriptor launch and UnixShell diagnostics. |
| Terminal: `test_windows_terminal.py` | `terminal_windows/` | Real console Unicode and password echo/mode restoration on success, overflow, Ctrl-C, read failure; redirected ordinary/password input matches Unix bounded behavior after the adaptation decision; no secret in logs. Console cases need an explicit interactive-console host, not a headless runner skip disguised as green. |
| Daemon: `test_windows_daemon.py` | `daemon_windows/` | Start/status/stop/restart, duplicate start, stale PID/token, protected record/log, launcher exit, supervisor crash, denied breakaway, tree cleanup on deadline, opt-in autostart and packaged restrictions. Separate package capability rule; core native lifecycle never skipped on a qualified Windows host. |
| Channel: `test_windows_local_application_channel.py` | `local_application_channel_windows/` | First-instance exclusivity plus multiple owned listening instances, remote rejection, same-user success, other-user SID rejection, impersonation restoration on every error, server authentication/PID reuse, old generation, exact wire bytes, empty/malformed/oversize/partial frames, slow peers, cancellation and one deadline, bounded nonblocking poll. Cross-user identity requires a provisioned second account and an explicit runner capability. |
| Jobs: `test_windows_background_jobs.py` | `background_jobs_windows/` | Worker/pending bounds, rejected ownership, one completion, owner-thread delivery, cancellation, lost-wakeup stress, DRAIN/CANCEL_PENDING, failed-join retry, foreign-thread exceptions and teardown leaks, thread count accuracy. Native Windows x64 and ARM64 required. |
| Process pools: `test_windows_worker_pools.py` | `worker_pools_windows/` | Inline-only refusal before CL-P2-12; after it lands, serialized startup, framing, crash isolation, resource accounting and cancellation. Do not mark multiprocess parity complete from thread tests. |

Freeze denominators before the first qualifying run: 100 junction/rename-race
attempts per frontend/ABI, 100 launch/cleanup cycles (including 10 forced timeout
trees), 100 channel authentication/teardown cycles including 10 second-account
rejections, and 100 job-pool create/close cycles. Every individual semantic case
above runs at least once per supported frontend/ABI; missing cases are listed,
not subtracted from the denominator. Proposed budgets require CL-P2-01 approval.
Linux-devcontainer and macOS runners get exact Windows-native skip rules while
still running cross-target selector checks; windows has no core-native skip;
windows-arm64 is registered before ARM64 execution is claimed. Console, UNC,
second-account and MSIX rows get explicit capability/provisioning records; a
required hosted capability provisioning failure fails the qualifying job.

Every native exit reports target, OS, architecture, packaging, compiler/frontend,
SDK identity, pass/fail/skip counts and job/run ID. Both GNU targets must also
compile/link with strict C11 diagnostics; Windows x64 bootstrap plus actual ARM64
execution satisfy different W1 requirements. Leak/handle-count and adversarial
race tests need repeated runs under bounded deadlines, not timing-only sleeps.

## Review and deferred work

The corrected binding recipe and runtime route still require qualification;
provider code, linking, native execution, package permissions and performance are deferred to
implementation packets. CL-P2-01 review/PLAN approval remains pending. Open review
decisions are the unsigned process-status accessor, exact NT
operation coverage, peer-authentication details and detached ownership transfer;
the concrete defaults above allow implementation planning without owner polling.
UI folder-picker grants, Windows UI event-loop integration, process-pool bootstrap
and MSVC qualification belong to their named later owners. No adaptation approval,
inventory promotion or parity claim follows merely from this document's CI pass.
