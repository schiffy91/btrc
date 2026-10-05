# Windows OS-services providers

Status: CX-P2-01 design proposal, based on `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
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

Keep public facades and portable policy in their existing packages. Move host
operations behind provider modules; remove Windows refusals only when the entire
operation has a tested Windows provider. Each row below proposes files to be
implemented by the appropriate later packet, not files created here.

| Portable owner and seam | Proposed Windows implementation | Manifest owner |
| --- | --- | --- |
| `FileSystem/FileSystem.btrc`: path conversion and basic file operations | `FileSystem/Windows/FileSystemProvider.btrc` | `FileSystem/btrc.toml` |
| `FileSystem/FileSystemHandles.btrc`: exact file/directory handles, identity, snapshots, private directories and locks | `FileSystem/Windows/FileSystemHandlesProvider.btrc` | `FileSystem/btrc.toml` |
| `FileSystem/FileTree.btrc`: bounded traversal/deletion through the handle seam | Reuses `FileSystemHandlesProvider`; traversal policy stays portable | `FileSystem/btrc.toml` |
| `FileSystem/ApplicationDirectories.btrc`: target path policy and application roots | `FileSystem/Windows/ApplicationDirectoriesProvider.btrc` | `FileSystem/btrc.toml` |
| Root `IO.btrc`: snapshot of an already-open stream | `Windows/IOFileSnapshotProvider.btrc` | Root `btrc.toml` |
| Root `Process.btrc`: process launch, capture and process status | `Windows/ProcessProvider.btrc` | Root `btrc.toml` |
| `Terminal/Terminal.btrc`, `TerminalPasswordInput.btrc`: console I/O and password session | `Terminal/Windows/TerminalProvider.btrc`, `TerminalPasswordInputProvider.btrc` | `Terminal/btrc.toml` |
| `Daemon/Daemon.btrc`, `DaemonControl.btrc`, `DaemonControlFiles.btrc`, `DaemonControlProtocol.btrc`: specification, lifecycle, records and supervisor launch | `Daemon/Windows/DaemonProvider.btrc`; native supervisor entry owned by the implementation packet | `Daemon/btrc.toml` |
| LocalApplicationChannel server/client and `LocalPeerCredentials.btrc`: bounded transport and authenticated identity | `LocalApplicationChannel/Windows/LocalChannelProvider.btrc`, `LocalPeerCredentialsProvider.btrc` | `LocalApplicationChannel/btrc.toml` |
| `BackgroundJobs/BackgroundJobExecutor.btrc`, `NativeWorker.btrc`: locks, conditions and joinable workers | `BackgroundJobs/Windows/BackgroundJobExecutorProvider.btrc`, `NativeWorkerProvider.btrc` | `BackgroundJobs/btrc.toml` |
| `BackgroundJobs/ProcessThreads.btrc`: current-process thread count | `BackgroundJobs/Windows/ProcessThreadsProvider.btrc` | `BackgroundJobs/btrc.toml` |
| `BackgroundJobs/HostWorkerPools.btrc`: compiler process pool | Keep explicit inline-only provider until CL-P2-12 supplies a serialized worker bootstrap | `BackgroundJobs/btrc.toml` |

Use root `[[package.providers]]` for Process and IO. Do not move `Process.btrc`
into a new package: that would change root exports, import ownership and generated
`btrc.symbols` for existing users. The root package already has a manifest; the
provider mechanism must apply identically there and in a group package. Example:

```toml
[[package.providers]]
module = "Process"
implementation = "Windows.ProcessProvider"
os = ["windows"]
env = ["gnu"]
```

All proposed Windows provider and native-binding entries have exactly
`os = ["windows"]`; the `Windows` path segment is not a substitute for that
filter. Initially use `env = ["gnu"]` as well. Add MSVC only after its separate SDK
and runtime qualification. Unix providers receive explicit disjoint filters;
mobile rows retain their own adaptations rather than inheriting desktop behavior.
Foreign-platform imports must select zero foreign SDK inputs for all Stage 24
targets in both frontends. CL-P2-01 should confirm root-provider selection and
symbol-index regeneration; request a compiler fix if root and group resolution
differ, rather than duplicating import logic in library code.

## SDK binding surface and checked headers

Every header below is a thin SDK include header read by the existing native
header reader. It must not copy SDK declarations, hard-code layouts, define a
second Win32 ABI, or use hand-authored imported record fields. Entries use C11,
the exact module named in the provider table, and the same OS/environment filters.
For example:

```toml
[[native.bindings]]
module = "Windows.FileSystemHandlesProvider"
header = "Windows/Win32FileSystem.h"
language = "c"
standard = "c11"
symbols = ["CreateFileW", "NtCreateFile", "GetFileInformationByHandleEx", "LockFileEx", "UnlockFileEx"]
os = ["windows"]
env = ["gnu"]
```

That abbreviated example illustrates syntax; the following lists are the proposed
full function selection sets. Repeated functions may be selected by multiple
provider entries. Companion SDK types and constants are selected where needed and
must pass the reader's type/record validation, not be recreated in BTRC.

| Header, relative to `src/stdlib/` | SDK includes | Selected function symbols |
| --- | --- | --- |
| `FileSystem/Windows/Win32FileSystem.h` | `windows.h`, `winternl.h`, `shlobj.h` | `CreateFileW`, `NtCreateFile`, `NtSetInformationFile`, `GetFileInformationByHandleEx`, `SetFileInformationByHandle`, `GetFinalPathNameByHandleW`, `ReadFile`, `WriteFile`, `GetFileSizeEx`, `SetFilePointerEx`, `FlushFileBuffers`, `ReplaceFileW`, `MoveFileExW`, `CloseHandle`, `GetLastError`, `LockFileEx`, `UnlockFileEx`, `SHGetKnownFolderPath`, `CoTaskMemFree` |
| `FileSystem/Windows/Win32Security.h` (also included by Daemon and channel binding headers) | `windows.h`, `aclapi.h` | `OpenProcessToken`, `GetTokenInformation`, `GetCurrentProcess`, `EqualSid`, `GetSecurityInfo`, `SetSecurityInfo`, `InitializeAcl`, `AddAccessAllowedAceEx`, `InitializeSecurityDescriptor`, `SetSecurityDescriptorDacl`, `SetSecurityDescriptorOwner`, `SetSecurityDescriptorControl`, `LocalFree` |
| `Windows/Win32Process.h` | `windows.h` | `CreateProcessW`, `InitializeProcThreadAttributeList`, `UpdateProcThreadAttribute`, `DeleteProcThreadAttributeList`, `CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`, `TerminateJobObject`, `CreatePipe`, `SetHandleInformation`, `ReadFile`, `WriteFile`, `WaitForSingleObject`, `WaitForMultipleObjects`, `GetExitCodeProcess`, `ResumeThread`, `CancelIoEx`, `GetOverlappedResult`, `MultiByteToWideChar`, `WideCharToMultiByte`, `GetEnvironmentStringsW`, `FreeEnvironmentStringsW`, `CloseHandle`, `GetLastError` |
| `Windows/Win32IO.h` | `io.h`, `windows.h` | `_get_osfhandle`, `GetFileInformationByHandleEx`, `GetFileSizeEx`, `GetLastError` |
| `Terminal/Windows/Win32Terminal.h` | `windows.h` | `GetStdHandle`, `GetConsoleMode`, `SetConsoleMode`, `ReadConsoleW`, `WriteConsoleW`, `ReadConsoleInputW`, `SetConsoleCtrlHandler`, `CancelSynchronousIo`, `GetFileType`, `MultiByteToWideChar`, `WideCharToMultiByte`, `GetLastError` |
| `Daemon/Windows/Win32Daemon.h` | `windows.h`, `bcrypt.h`, security and process include headers above | `BCryptGenRandom`, plus the listed Process and Security sets |
| `LocalApplicationChannel/Windows/Win32LocalChannel.h` | `windows.h`, security include header above | `CreateNamedPipeW`, `ConnectNamedPipe`, `DisconnectNamedPipe`, `WaitNamedPipeW`, `GetNamedPipeClientProcessId`, `GetNamedPipeServerProcessId`, `OpenProcess`, `OpenThreadToken`, `ImpersonateNamedPipeClient`, `RevertToSelf`, `CreateEventW`, `CreateFileW`, `ReadFile`, `WriteFile`, `CancelIoEx`, `GetOverlappedResult`, `WaitForSingleObject`, `CloseHandle`, `GetLastError`, plus the Security set |
| `BackgroundJobs/Windows/Win32Threads.h` | `windows.h`, `process.h`, `tlhelp32.h` | `_beginthreadex`, `InitializeCriticalSectionEx`, `DeleteCriticalSection`, `EnterCriticalSection`, `TryEnterCriticalSection`, `LeaveCriticalSection`, `InitializeConditionVariable`, `SleepConditionVariableCS`, `WakeConditionVariable`, `WakeAllConditionVariable`, `GetCurrentThreadId`, `WaitForSingleObject`, `CloseHandle`, `CreateToolhelp32Snapshot`, `Thread32First`, `Thread32Next`, `GetCurrentProcessId`, `GetLastError` |

Checked on 2026-10-04 with the pinned Zig **0.16.0** MinGW headers
(`any-windows-any`, target contract's MinGW revision `38c8142f`) and the pinned
native reader (Clang **21.1.8**). An individual batch request was made for each of
90 candidate function symbols for each GNU target. **89 selections succeeded on
each target with no per-request errors.** `NtQueryDirectoryFile` was the one
missing candidate on both targets and is deliberately absent from the lists above.
Use handle-based `GetFileInformationByHandleEx` directory enumeration instead.
`NtCreateFile` and `NtSetInformationFile` were present and readable on both targets.
Reproduce with an aggregate header containing the includes above:

```sh
"$BTRC_NATIVE_HEADER_READER" --batch=Requests.json Windows.c -- \
  -x c -std=c11 --target=x86_64-windows-gnu \
  -isystem "$ZIG_LIB_DIR/libc/include/any-windows-any" \
  -isystem "$ZIG_LIB_DIR/libc/include/x86_64-windows-any"
# Repeat with aarch64-windows-gnu and aarch64-windows-any.
```

`Windows.c` defines `_WIN32_WINNT` and `WINVER` as `0x0A00` before the includes.
`Requests.json` uses schema `btrc.native-requests.v1` and requests of the form
`{"id":"NtCreateFile","symbols":["NtCreateFile"]}`. Inspect every result's
`errors` and `document`: process exit zero alone does not prove every selection.
This verifies declaration selection, not link libraries, recursive record support,
runtime semantics, packaging, or native ARM64 execution. Implementation must
add selected-record tests for `OBJECT_ATTRIBUTES`, `UNICODE_STRING`,
`IO_STATUS_BLOCK`, `FILE_ID_INFO`, directory information, `OVERLAPPED`,
`STARTUPINFOEXW`, security and job structures on both targets. The native reader's
input report must include the selected target/sysroot in cache identity.

No **native product API name** above belongs in `hosted_abi.toml`. Bind through the
SDK reader and link the actual Windows import libraries (`kernel32`, `advapi32`,
`shell32`, `ole32`, `bcrypt`, `ntdll` and the selected CRT as required by each
provider). Compiler-private launch helpers below are a distinct runtime seam.

## Filesystem, application roots and IO snapshots — row 7

`RegularFileSnapshot.open`, `PrivateDirectory.openAbsoluteLeaf`,
`AdvisoryFileLock.acquire` and `IO.File.snapshot` currently refuse Windows.
The adaptations table calls the lock operation `open`; the current public method
is `acquire(path, wait=false)`. Keep that public name and propose the correction
to the adaptations owner. Do not simply delete these guards:

* `PrivateDirectory.openAbsoluteLeaf` tests for a leading `/` before its Windows
  refusal. `ApplicationDirectoryRoots` and its resolver also normalize Unix
  absolute paths. Introduce target path policy before those validations so drive
  absolute and UNC paths are recognized correctly. Reject drive-relative paths,
  embedded NUL and invalid UTF-8. Preserve native case without promising case
  sensitivity; distinguish paths from canonical object identity.
* Convert strictly between UTF-8 and UTF-16, with dynamic storage for long paths.
  Normalize extended drive/UNC prefixes once, without accidentally reinterpreting
  a device namespace as an ordinary file. Test Unicode, UNC and paths beyond
  MAX_PATH; package manifests must enable the intended long-path behavior.
* An exact handle owns its native HANDLE and closes it once. Use reparse-point
  opens and inspect the opened object's attributes and identity. For traversal,
  private-leaf creation and deletion, open each component relative to the held
  parent handle with `NtCreateFile`/`OBJECT_ATTRIBUTES.RootDirectory`; validate
  every opened component and refuse reparse points. A final-component flag or a
  path recheck after opening does not close an ancestor-junction race.
* Enumerate through the held directory handle with
  `GetFileInformationByHandleEx` and directory restart/continuation information
  classes. Bounds and stable traversal order remain FileTree policy. Reopen each
  child relative to that directory and compare the opened object's identity;
  enumeration names are not authority. Delete/rename relative to held handles
  using the appropriate SDK information structures. Never fall back to recursive
  string-path deletion when an exact operation is unavailable.
* Identity uses volume plus file ID; snapshots preserve size, timestamps and
  checked revisions for files larger than 4 GiB. Existing FileTree revision hashes
  remain cache/change indicators, not authentication. The IO bridge borrows
  `_get_osfhandle` only while its FILE/descriptor remains alive; it must not close
  the borrowed handle or inspect a recycled descriptor after stream close.
* Private-directory creation supplies a protected current-user DACL at creation,
  checks owner and DACL through the opened handle, and rejects conflicting or
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
  policy; never silently downgrade to a process-local mutex.
* Resolve application roots with `SHGetKnownFolderPath`, free returned storage
  with `CoTaskMemFree`, then apply the target path policy. Separate configuration,
  cache and durable data purposes; honor explicit overrides only after validation.
  Packaged and unpackaged roots, ACLs and migration need independent evidence.
  GUI folder selection belongs to UI7's future `IFileOpenDialog/FOS_PICKFOLDERS`
  owner; a scoped grant must not be converted to a fabricated unrestricted path.

If an SDK lacks readable NT declarations, record layouts or supported enumeration
classes, **fail closed for exact traversal/private roots** with the existing
unsupported capability outcome. Basic non-exact I/O may still work. The fallback
is not copied NT structs, pathname retries or a C shim hiding an unverified ABI.
Request reader/SDK qualification from Claude and retain refusals until it lands.

## Process and shell — rows 1 and 1b

Keep `ChildProcess.run` validation, argument-vector API, output modes and result
policy portable. Windows construction uses strict UTF conversion, a sorted
case-insensitive environment block, explicit environment removals and a canonical
CommandLineToArgvW-compatible quoting algorithm (including empty strings and
trailing backslashes). ShellWords' POSIX rendering is display-only on this target.
No `cmd.exe` substitution for UnixShell is permitted.

Launch suspended with `STARTUPINFOEXW` and an explicit inherited-handle list
containing only the three selected stdio handles. Duplicate inherited caller
stdio into launch-owned handles and never mutate the caller's inheritance flags.
Assign the child to a kill-on-close job **before** `ResumeThread`. This is the
CL-P2-02 baseline even if `PROC_THREAD_ATTRIBUTE_JOB_LIST` is available; request
the corresponding wording change to adaptation row 1. Job assignment failure
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
The two adaptation diagnostics remain exact:

```text
ChildProcess.run is unavailable on Windows: a console has no controlling-terminal foreground handoff; use a background child
UnixShell.run is unavailable on Windows: there is no POSIX /bin/sh; use ChildProcess.run with an argument vector
```

## Terminal — row 2

`readLine` and `prompt` retain bounded redirected-stream behavior. Console handles
use `ReadConsoleW`/`WriteConsoleW` and strict Unicode conversion. Password input is
a serialized console session: save the original mode, clear `ENABLE_ECHO_INPUT`,
retain `ENABLE_LINE_INPUT`, and restore the mode on success, overflow, error and
control-event cancellation. Preserve the existing 4096-byte password limit and
never log input. A process-global control handler signals cancellation through a
minimal native trampoline; it must not allocate BTRC objects, throw or run user
callbacks. Restore mode and handler registration before propagating interruption.

Redirected stdin is valid for ordinary input but not this secure prompt operation:

```text
Terminal.promptPassword is unavailable on Windows: standard input is not a console handle; use a console or supply the secret on standard input
```

“Supply the secret” means an explicit separate input journey, not having
`promptPassword` silently read an unprotected pipe. TerminalPasswordInput shares
the refusal. Pseudoconsole support is a future owner; these methods do not promise
POSIX raw-terminal job control or foreground handoff.

## Daemon supervisor — row 4

Keep DaemonSpec's validation and declared Command data; replace the rendered
shell supervisor with a native entry. Resolve owner-controlled records/logs through
ApplicationDirectories. Generate 128-bit instance/control tokens with
`BCryptGenRandom`; records, logs and channel endpoints require current-user DACLs.
PID alone is never a capability. Match instance token and authenticated peer before
status/stop or stale-record cleanup; do not terminate a process from an old PID.

Start the supervisor with the adaptation's detached/new-process-group/breakaway
flags only where the parent/package policy permits them. It owns a job for its
managed child tree and applies the declared restart policy. Stop requests graceful
shutdown over the authenticated channel, then terminates that job after the
bounded deadline. Preserve controller result distinctions (success, not running,
deadline, unsafe start) and bound startup handshake, log retention and crash
recovery. A denied breakaway or job assignment is a failed start, not success with
weaker containment. Ensure the launching process closing its own launch handle
does not kill the accepted independent supervisor; detached launch requires a
separately reviewed ownership transfer, not the ordinary ChildProcess close rule.

Per-user autostart is an explicit opt-in integration using an allowed Run/logon-task
or packaged startup mechanism. MSIX does not imply permission to install a per-user
service or evade package process restrictions. Packaging policy and native evidence
must qualify the chosen path; no automatic service installation is proposed here.
The unsupported rendering diagnostic remains:

```text
DaemonSpec.renderStartCommand is unavailable on Windows: the supervisor is a POSIX /bin/sh script; use DaemonController.start
```

## LocalApplicationChannel — row 5

Use local named pipes with a protected current-user DACL and
`PIPE_REJECT_REMOTE_CLIENTS`. `FILE_FLAG_FIRST_PIPE_INSTANCE` claims the initial
server endpoint; subsequent listening instances owned by that server must not
repeat the first-instance flag. Keep an instance generation/token so a stale
client cannot mistake a restarted server for the old one. There is no Unix socket
path to unlink and no device/inode cleanup simulation.

Maintain the existing four-byte big-endian length frame, empty-payload support,
one-response-per-peer behavior, byte budgets and idle deadlines. Overlapped I/O
lets server `poll` stay nonblocking. The client uses one monotonic deadline across
connect, send and receive. Cancellation cancels and completes outstanding I/O
before freeing its OVERLAPPED storage, closing events and pipe handles.

`GetNamedPipeClientProcessId` and `GetNamedPipeServerProcessId` provide process
metadata, not sufficient authorization by themselves. Verify the connection's
token SID through named-pipe impersonation, `OpenThreadToken` and `EqualSid`, and
always `RevertToSelf` before any user callback or failure return. Bound the initial
framing/authentication exchange and reject an unverified peer before accepting a
product command. Client verification likewise checks the server token and instance
handshake, guarding PID reuse; do not authorize solely by an opened numeric PID.
CL-P2-01 must review this identity protocol before implementation.

Replace the current Unix `peerUser(fd, uid_t*)` seam with a portable authenticated
identity result containing platform kind and opaque identity bytes. A Windows SID
must not be truncated or hashed into a uid_t, and `getuid()==0` grants no trust.
No AF_UNIX provider is selected; the adaptation's AF_UNIX peer-credentials refusal
remains the diagnostic if that unsupported route is requested.

## BackgroundJobs and worker pools — P3 jobs exit

Use `_beginthreadex` for joinable CRT-aware native workers, critical sections and
condition variables behind portable executor policy. Preserve the existing bounds
(1–16 workers, 1–4096 outstanding slots, including completed-but-unpolled work),
acceptance ownership, cancellation token rules and owner-thread completion polling.
Rejected submissions retain nothing. A completed job is transferred exactly once
on the owner thread. Synchronize predicate checks and wakeups to avoid lost wakes.

Every worker enters through the runtime's checked foreign-thread boundary, catches
worker failures and retains its body until a successful join. Failed joins keep
ownership for a same-mode retry. Current executor `close(DRAIN/CANCEL_PENDING)`
blocks while joining; UI providers must arrange that off their event loop or use a
future explicitly approved asynchronous close API. This design does not pretend
the existing close is nonblocking. ProcessThreads uses a Toolhelp snapshot filtered
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
CL-P2-02. Names/signatures need its review, but no API design question is left as
an implicit implementation guess. SDK records stay inside the runtime source;
this boundary exposes only fixed-width values, buffers and an opaque owner.

```c
typedef struct BTRCWindowsLaunch BTRCWindowsLaunch;
typedef struct {
    const char *executable_utf8;
    const char *const *argv_utf8; size_t argc;
    const char *cwd_utf8;
    const char *const *environment_utf8; size_t environment_count;
    const unsigned char *stdin_bytes; size_t stdin_size;
    intptr_t inherited_stdin, inherited_stdout, inherited_stderr;
    uint32_t stdin_mode, stdout_mode, stderr_mode;
    size_t stdout_limit, stderr_limit;
} BTRCWindowsLaunchOptions;
typedef struct { uint32_t stage, win32_error; } BTRCWindowsLaunchError;
typedef struct {
    uint32_t state, native_exit_code, has_exit_code;
    uint64_t stdout_bytes_seen, stderr_bytes_seen;
    size_t stdout_bytes_retained, stderr_bytes_retained;
} BTRCWindowsLaunchResult;
int __btrc_windows_launch(const BTRCWindowsLaunchOptions *options,
    BTRCWindowsLaunch **out, BTRCWindowsLaunchError *error);
int __btrc_windows_launch_wait(BTRCWindowsLaunch *launch,
    uint32_t timeout_ms, BTRCWindowsLaunchResult *result,
    BTRCWindowsLaunchError *error);
int __btrc_windows_launch_copy_output(BTRCWindowsLaunch *launch,
    uint32_t stream, unsigned char *buffer, size_t capacity, size_t *written);
int __btrc_windows_launch_terminate(BTRCWindowsLaunch *launch,
    uint32_t exit_code, BTRCWindowsLaunchError *error);
void __btrc_windows_launch_close(BTRCWindowsLaunch *launch);
int __btrc_windows_quote_argv_utf8(const char *const *argv, size_t argc,
    uint16_t *buffer, size_t capacity_units, size_t *required_units,
    BTRCWindowsLaunchError *error);
```

Use `<stddef.h>`/`<stdint.h>`. Launch returns 0 on success, nonzero on failure,
sets `*out=NULL` before work, and copies all input storage before returning. A null
cwd inherits; a null environment pointer inherits while a nonnull zero-count
environment is empty. Entries are validated `NAME=value` strings; argv includes
argv[0]. Embedded NUL is rejected by the BTRC conversion before this C boundary.
Invalid UTF-8 fails conversion. Supplied standard handles are borrowed and duplicated.

Proposed mode values: stdin 0=null, 1=bytes, 2=inherit; stdout/stderr
0=collect, 1=stream, 2=suppress, 3=combine (stderr only, into stdout).
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
close accepts NULL, terminates any still-owned tree, joins all internal I/O workers,
and releases all resources. The quote helper counts the terminating UTF-16 NUL in
`required_units`; NULL/zero capacity queries size and insufficient space makes no
partial output. It never invokes a shell.

Error stages must distinguish validation, UTF conversion, allocation, stdio setup,
attribute list, job setup, CreateProcessW, job assignment, resume, pipe I/O, wait
and termination; preserve GetLastError where meaningful. The runtime owns enum
constants and generated declarations alongside these types, not separate library
copies of their numbers. A detached supervisor needs an additional reviewed
ownership-transfer API; ordinary launch/close must retain its kill-on-close safety.

| Request / owner | Required result and acceptance dependency |
| --- | --- |
| CL-P2-01 | Review provider ownership, exact path/identity model, status representation, named-pipe authentication and Q4–Q6 assumptions; resolve blocking findings and record approval in PLAN.md. Correct adaptation lock method and suspended-job wording in its owned file. |
| CL-P2-02 | Ship the reviewed helper signatures above in `src/runtime/c/process.c` and `btrcrt.h`, with manifest/generated catalog updates. Use explicit STARTUPINFOEXW handle list, suspended creation, assignment to kill-on-close job before resume, bounded concurrent pipe capture, canonical quoting and distinct errors. Include D14 boundary and native launch fixtures. |
| CL-P2-02 / Stage 24 | Confirm root provider selection in both frontends and both GNU targets. Runtime-origin helpers remain selected runtime declarations; do not put native SDK names into hosted ABI availability. Any genuinely required hosted fallback row must be justified separately, not added as a shortcut for Win32 APIs. |
| CL-P2-02 / flake owner | Make the same pinned Zig sysroot/native reader effective in both frontend environments; expose needed import libraries and target include paths. No new SDK download or flake input is currently required by the header probe. Qualify linking and selected record shapes before provider implementation. |
| Filesystem implementation owner | Qualify NT relative opens, handle enumeration/rename/disposition, DACL policy and durable replacement. Preserve unsupported outcomes where the exact contract cannot be met; no pathname security fallback. |
| Daemon implementation owner | Define detached-supervisor launch ownership and packaged startup permission separately from ordinary child containment; test launcher exit, supervisor crash and failed breakaway. |
| BackgroundJobs runtime owner / CL-P2-12 | Provide checked foreign-thread entry for Windows workers and a separate serialized compiler-process bootstrap. Keep inline-only process pool behavior until the latter is qualified. |
| CL-P2-14 | Retire compatibility shims only after every surviving consumer migrates and both frontend audits are green. See migration list below; do not delete the whole overlay because one provider ships. |

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
| Provider and reader selection: `test_windows_os_service_imports.py` | `os_services_windows/` | Both GNU targets, both frontends, SDK function and record selection, zero foreign SDK reads for unrelated targets, root Process/IO imports, absent NT declaration gives an explicit refusal. Cross-target checks run on Linux; linking/runtime evidence is separate. |
| Exact filesystem: `test_windows_filesystem_handles.py` | `filesystem_windows/` | Repeated ancestor-junction swap during walk/delete, final symlink/reparse refusal, DACL denial and inherited broad ACL rejection, stale/reused handles, >4-GiB snapshots, long/UNC/non-ASCII paths, deterministic bounded traversal, concurrent mutation. Native-host rule only; UNC share provisioning is an explicit capability requirement, never silently omitted. |
| Replacement/locks: `test_windows_filesystem_atomic.py` | `filesystem_atomic_windows/` | Kill writer before/after replace, old-or-new content, flush failure, permission failure, file identity preservation expectations; two-process LockFileEx contention, wait/nonwait, ordinary I/O conflict, crash release and cleanup. Report filesystem type and durability limits. |
| Roots and stream snapshot: `test_windows_application_directories.py` | `application_directories_windows/` | Drive/UNC validation occurs before portable facade construction, actual Known Folder root, packaged/unpackaged identity, override validation, owner DACL, borrowed-handle lifetime. MSIX cases require a separately declared packaged runner capability. |
| Launch: `test_windows_launch_seam.py` (CL-P2-02 owner), `test_windows_process.py` | `windows_launch/` (existing packet name), `process_windows/` | Empty/space/quote/backslash/trailing-backslash/non-BMP argv, environment case/removal, cwd, missing executable vs child exit 127, high-bit exit, explicit stdio inheritance and no leaked handles, concurrent stdout/stderr, stdin backpressure, bounds, timeout killing a three-level tree, descendant-held pipe, suspended assignment failure. Unsupported foreground, exact descriptor launch and UnixShell diagnostics. |
| Terminal: `test_windows_terminal.py` | `terminal_windows/` | Real console Unicode and password echo/mode restoration on success, overflow, Ctrl-C, read failure; redirected ordinary input succeeds while password prompt emits the exact refusal; no secret in logs. Console cases need an explicit interactive-console host, not a headless runner skip disguised as green. |
| Daemon: `test_windows_daemon.py` | `daemon_windows/` | Start/status/stop/restart, duplicate start, stale PID/token, protected record/log, launcher exit, supervisor crash, denied breakaway, tree cleanup on deadline, opt-in autostart and packaged restrictions. Separate package capability rule; core native lifecycle never skipped on a qualified Windows host. |
| Channel: `test_windows_local_application_channel.py` | `local_application_channel_windows/` | First-instance exclusivity plus multiple owned listening instances, remote rejection, same-user success, other-user SID rejection, impersonation restoration on every error, server authentication/PID reuse, old generation, exact wire bytes, empty/malformed/oversize/partial frames, slow peers, cancellation and one deadline, bounded nonblocking poll. Cross-user identity requires a provisioned second account and an explicit runner capability. |
| Jobs: `test_windows_background_jobs.py` | `background_jobs_windows/` | Worker/pending bounds, rejected ownership, one completion, owner-thread delivery, cancellation, lost-wakeup stress, DRAIN/CANCEL_PENDING, failed-join retry, foreign-thread exceptions and teardown leaks, thread count accuracy. Native Windows x64 and ARM64 required. |
| Process pools: `test_windows_worker_pools.py` | `worker_pools_windows/` | Inline-only refusal before CL-P2-12; after it lands, serialized startup, framing, crash isolation, resource accounting and cancellation. Do not mark multiprocess parity complete from thread tests. |

Every native exit reports target, OS, architecture, packaging, compiler/frontend,
SDK identity, pass/fail/skip counts and job/run ID. Both GNU targets must also
compile/link with strict C11 diagnostics; Windows x64 bootstrap plus actual ARM64
execution satisfy different W1 requirements. Leak/handle-count and adversarial
race tests need repeated runs under bounded deadlines, not timing-only sleeps.

## Review and deferred work

The binding function selections are checked; provider code, record qualification,
linking, native execution, package permissions and performance are deferred to
implementation packets. CL-P2-01 review/PLAN approval remains pending. Open review
decisions are the unsigned process-status accessor, exact NT
operation coverage, peer-authentication details and detached ownership transfer;
the concrete defaults above allow implementation planning without owner polling.
UI folder-picker grants, Windows UI event-loop integration, process-pool bootstrap
and MSVC qualification belong to their named later owners. No adaptation approval,
inventory promotion or parity claim follows merely from this document's CI pass.
