# `Library.Daemon`

The `btrc_stdlib_daemon` group describes a background service declaratively
and supervises it on Unix through owner-only control files. It is written
against POSIX: the supervisor is a `/bin/sh` script, and tokens come from
`/dev/urandom`.

| Module | Owns |
|--------|------|
| `Library.Daemon` (`Daemon.btrc`) | `DaemonSpec` and `DaemonController`, the API applications use. |
| `Library.Daemon.DaemonControl` | `DaemonControlRecord` and `DaemonControlPaths`. Deadlines use `MonotonicClock` from `Library.Timer`. |
| `Library.Daemon.DaemonControlFiles` | The owner-only filesystem boundary for control files and logs. |
| `Library.Daemon.DaemonControlProtocol` | Random capability tokens and the liveness handshake. |

The three `DaemonControl*` modules are exported as the lower layer the
controller is built from, so conformance tests can drive them directly;
applications use `DaemonController`.

## Describing a daemon

`DaemonSpec(name, command)` names the service and the `Command` it runs. The
name is limited to letters, digits, `-`, `_` and `.`. By default its control
record is `<name>.control` and its log `<name>.log` in `~/.btrc/daemons`, or in
`$TMPDIR/btrc-daemons-<euid>` when `HOME` is not absolute. `control(path)`,
`log(path)`, `cwd(path)` and `restart(enabled)` override those fields and
return the spec. The fields stay declarative, so a platform service manager can
consume a `DaemonSpec` directly. `renderStartCommand(controlFile, logFile)`
renders the local supervisor the controller launches for the canonical control
and log paths the caller already prepared; it never rewrites the spec, and a
path that is not canonical, a control record that already exists, or an unsafe
log renders `exit 125` instead.

## Supervising it

`DaemonController` runs through `UnixShell` and reports every operation as an
`ExecResult`: 0 on success, 1 when no daemon is answering or a control record
already exists, 124 when a stop missed its deadline, and 125 for an unsafe
specification or a supervisor that failed to start or answer.

- `start(spec)` requires the record's and log's parents to be private (0700)
  directories, creating the default state directory when the spec uses it,
  refuses an existing control record, opens the log as an owner-only (0600)
  regular file, and launches the supervisor detached under `nohup`; the
  supervisor runs the command in its own process group (`setsid` when
  available, otherwise shell job control). The supervisor
  publishes a record holding a fresh 128-bit token, and `start` succeeds only
  after the supervisor answers a liveness probe that echoes that token. With
  `restart(true)` the supervisor relaunches the command whenever it exits.
- `stop(spec, timeoutMilliseconds = 7500)` writes a stop file named and filled
  with the record's token; the supervisor sends `TERM` to the command's process
  group, escalates to `KILL` after about a second, removes its control files
  and exits. `stop` waits for the record to disappear.
- `status(spec)` succeeds when the supervisor answers a fresh probe.

The token, not the PID, is the capability. The record's PID is informational,
and controller code never signals a process. Control files are created and
read only inside owner-only directories reached without symlinks, so another
local user cannot forge a record or redirect a stop.

The corpus test is `src/tests/stdlib/Daemon.btrc`. It asserts wall-clock bounds
on its stop deadlines, so it can fail on a saturated machine.
