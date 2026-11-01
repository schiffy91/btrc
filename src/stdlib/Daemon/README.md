# `Library.Daemon`

The `btrc_stdlib_daemon` group describes a background service and supervises
its process tree through protected control files. Unix uses a `/bin/sh`
supervisor; Windows uses a companion executable built with the application.
Capability tokens come from `/dev/urandom` on Unix and `BCryptGenRandom` on
Windows.

| Module | Owns |
|--------|------|
| `Library.Daemon` (`Daemon.btrc`) | `DaemonSpec` and `DaemonController`, the API applications use. |
| `Library.Daemon.DaemonControl` | `DaemonControlRecord` and `DaemonControlPaths`. Deadlines use `MonotonicClock` from `Library.Timer`. |
| `Library.Daemon.DaemonControlFiles` | The Unix owner-only filesystem boundary for control files and logs. |
| `Library.Daemon.DaemonControlProtocol` | Random capability tokens and the liveness handshake. |

The three `DaemonControl*` modules are exported for conformance tests and
lower-level callers. Applications use `DaemonController`; its Windows
provider owns the native file, launch and supervision policy.

## Describing a daemon

`DaemonSpec(name, command)` names the service and the `Command` it runs. The
name is limited to letters, digits, `-`, `_` and `.`. By default its control
record is `<name>.control` and its log `<name>.log`. On Unix these live in
`~/.btrc/daemons`, or in `$TMPDIR/btrc-daemons-<euid>` when `HOME` is not
absolute. Windows uses `btrc\daemons` beneath the current user's
`FOLDERID_LocalAppData`, resolved through `ApplicationDirectories`.
`control(path)`,
`log(path)`, `cwd(path)` and `restart(enabled)` override those fields and
return the spec. The fields stay declarative, so a platform service manager can
consume a `DaemonSpec` directly. On Unix,
`renderStartCommand(controlFile, logFile)` renders the local supervisor the
controller launches for the canonical control
and log paths the caller already prepared; it never rewrites the spec, and a
path that is not canonical, a control record that already exists, or an unsafe
log renders `exit 125` instead. On Windows this method throws; use
`DaemonController.start(spec)`.

## Supervising it

`DaemonController` reports every operation as an `ExecResult`: 0 on success,
1 when no daemon is answering or a control record
already exists, 124 when a stop missed its deadline, and 125 for an unsafe
specification or a supervisor that failed to start or answer. On Windows,
`startIndeterminate` is true when startup may have committed but its outcome
could not be confirmed. Reconcile the control state with `status(spec)` before
retrying; a failed acknowledgement does not authorize a replacement daemon.

- `start(spec)` requires protected record and log directories, creates the
  default state hierarchy when needed, and refuses an existing control record.
  On Unix, directories are private (0700), the log is an owner-only (0600)
  regular file, and `UnixShell` launches the supervisor under `nohup`. The
  command runs in its own process group (`setsid` when available, otherwise
  shell job control). On Windows, native handles validate directory and file
  ownership, ACLs and identities. The verified companion starts the command
  suspended, assigns it to a kill-on-close job, then resumes it. The supervisor
  publishes a record holding a fresh 128-bit token, and `start` succeeds only
  after the supervisor answers a liveness probe that echoes that token. With
  `restart(true)` the supervisor relaunches the command whenever it exits.
- `stop(spec, timeoutMilliseconds = 7500)` writes a stop file named and filled
  with the record's token. Unix sends `TERM` to the command's process group
  and escalates to `KILL` after about a second. Windows terminates the managed
  job, including descendants. The supervisor removes its control files after
  the process tree has stopped, then exits. `stop` waits for the record to
  disappear.
- `status(spec)` succeeds when the supervisor answers a fresh probe.

The token, not the PID, is the capability. The record's PID is informational,
and controller code never signals a process. Control files are created and
read inside protected directories. Unix refuses symlink traversal; Windows
holds native directory and file identities and rejects unsafe reparse points
and ACLs.

## Building and distributing on Windows

A retained call to `DaemonController.start` adds the supervisor declaration
to the compiler's native link plan. Build that plan with `tools.native_plan`,
passing the application's frontend argv through `--frontend-command`. The
builder emits
`<application basename>.btrc-supervisor.exe` beside the application, for
example `editor.exe.btrc-supervisor.exe`. Ship both files together and preserve
their names. An unrelated program does not need a companion.

The application embeds the companion's exact digest, target ABI and protocol.
Missing or changed companions fail startup. The builder checks the companion's
System32-only dependency policy and hashes its final bytes after optional
signing. Signing or repacking the companion later requires rebuilding the
application's metadata. The supervisor runs under the launching user's
account and does not register a Windows service.

## Unix process groups

A group member whose parent died first is reparented to init and remains a
zombie until init reaps it. Some container inits reap late or never, and
`kill -0` still reaches a zombie, so the supervisor judges a group finished
once its leader is reaped and `ps` lists no member in a state other than `Z`.
Without a working `ps` it keeps waiting for the group to empty, as before.

`src/tests/stdlib/Daemon.btrc` covers portable lifecycle, arguments, logging,
restart and stale records through both compilers. `DaemonPosix.btrc` covers
Unix shell rendering, permissions, signals and process groups.
`DaemonToken.btrc` checks the platform token provider. Windows policy tests
also inject startup, transfer and cleanup failures, and native tests run the
companion on x64 and ARM64.
