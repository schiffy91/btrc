# Terminal processes

`import Library.Terminal.PTYProcess;` provides `PTYProcess` on Linux and macOS.
It starts an executable with a controlling pseudo-terminal; arguments include
`argv[0]`, and the supplied environment replaces the inherited environment.
`start` returns null if setup fails. An executable that cannot be executed exits
with status 127.

```btrc
import Library.Bytes;
import Library.Terminal.PTYProcess;
import Library.Timer;
import Library.Vector;

var child = PTYProcess.start("/bin/sh", ["sh", "-c", "printf ready; read answer"], []);
if (child == null) { throw "Cannot start child"; }
var deadline = MonotonicClock.deadlineAfter(3000);
var output = child.readUntil(deadline);
child.writeUntil(Bytes.fromString("hello\n"), deadline);
var status = child.waitExitUntil(deadline);
```

`readUntil(deadline, sliceMilliseconds=1000)` returns up to 4096 bytes, empty
`Bytes` on timeout, or null on EOF/error/closed. Each result owns its bytes,
including embedded NULs, independently of the next read or the process lifetime.
`writeUntil` writes all bytes within the deadline or returns false. It permits
arbitrary bytes: line limits, password policy and prompt recognition belong to
the application. `echoDisabled()` checks the terminal's current echo flag.

`waitExitUntil` drains output while waiting and returns the exit code, 128 plus
the terminating signal, or -1 on timeout/error. It closes the process owner.
`close()` kills the process group, reaps the child and closes the master; it is
idempotent. Dropping the last reference, including on exception paths, performs
the same cleanup through the compiler's unique native-resource ownership.
Cleanup waits for reaping after SIGKILL, so it does not promise a hard return
bound for a child stuck in uninterruptible kernel work. Use an instance from
one thread at a time.

The native binding is declared in `btrc.toml`: the handle has unique ownership,
operations borrow it, strings and byte input are read-only borrows, and read
results are copied into managed `Bytes`. `Unix/PTY.h` owns the POSIX boundary;
`PTYProcess.btrc` owns the deadline loops and the public API. Consumers do not
handle descriptors, pids, `poll` flags, native arrays or manual release.
