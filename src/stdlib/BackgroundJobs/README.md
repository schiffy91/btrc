# `Library.BackgroundJobs`

`BackgroundJobExecutor` is the bounded worker-pool boundary for serialized
applications. It complements `spawn()`/`Thread.join()` when the owner loop must
remain responsive and poll completed work instead of blocking.

The executor owns 1–16 workers and 1–4096 fixed outstanding slots. Capacity
includes queued, running, and terminal-but-unpolled jobs. `poll()` is
owner-thread-only and strictly nonblocking: it returns `READY`, `EMPTY`, or
`BUSY` without waiting on a condition or worker.

Owners that schedule dependent work, such as a compiler waiting for the next
finished module, use `awaitCompletion()` instead. It is also owner-only. It
blocks on a condition until a completion is claimable and returns `READY`;
it returns `EMPTY` immediately when nothing is outstanding, so it cannot wait
forever on an idle executor, and `CLOSED` when a worker has failed or
synchronization fails. Each completion is handed over exactly once, whether
it is claimed by `poll()` or `awaitCompletion()`.

Each submission carries:

- a nonzero `BackgroundJobGeneration` and generated `BackgroundJobTicket`;
- a managed `BackgroundJobWork` subtype;
- an exact noncapturing `BackgroundJobAction` receiving that work and a typed
  `BackgroundJobCancellation` view.

The stdlib alone creates and destroys the native context envelope. Acceptance
retains the work for the executor; rejection retains nothing. The action runs
on a worker and checks cooperative cancellation with `cancellation.requested()`.
`poll()` moves the work into a typed `BackgroundJobCompletion`; product code
never handles a raw context or disposer. `close(DRAIN)` finishes admitted work;
`close(CANCEL_PENDING)` requests cancellation first. Both join every worker and
reclaim every unclaimed work item before returning. An action exception is
normalized to `BACKGROUND_JOB_FAILED` before it can cross the C ABI; actions
must eventually return after cancellation.

Queueing, cancellation and completion publication live in
`BackgroundJobExecutor.btrc`; `BackgroundJobs.btrc` is the group facade, which
also re-exports the worker-pool contracts. The package imports pthread
declarations through `BackgroundJobs/NativeThreads.h`; it does not link a
separate background-jobs C runtime.

`close()` currently blocks while joining workers. It is not a nonblocking UI
shutdown primitive: moving an uninterruptible native call onto a worker does
not make joining that worker safe on the UI executor. A failed join or
synchronization teardown retains the executor for an explicit same-mode retry;
do not drop its owner or report completion on failure. A worker-disposal error
is reported separately after resources have been reclaimed. Application owners
must preserve that error rather than treating a later `ALREADY_CLOSED` result
as successful shutdown.

## Native worker threads: `Library.BackgroundJobs.NativeWorker`

`NativeWorker` is the one owner of a joinable native thread that runs managed
code, shared by `BackgroundJobExecutor` (one per worker) and the Linux ALSA
stream. `start(body)` runs `body.workLoop()` (an `INativeWorkerBody`) on a new
pthread and returns a `NativeWorkerStartKind`: `STARTED`, `START_INVALID` for
a null body or a second start, `START_OUT_OF_MEMORY` or
`START_THREAD_FAILED`; only `STARTED` retains anything. While the thread lives, a calloc'd context retains the
worker and through it the body, so no thread outlives what it runs.
`join()` joins once, releases that context and drops the body; it returns
false only when the join itself failed, leaving everything live for a retry,
and an unstarted or joined worker joins trivially. `running()` is true between
a successful start and join, and `workerFailed()` reports a nonzero
`workLoop()` result or an exception. The thread enters BTRC only through the
runtime's foreign-thread boundary, so an exception or cleanup failure becomes
a failed worker instead of crossing the C ABI. That boundary has not yet
migrated to the checked callback-binding contract. A worker starts at most
once; its owner thread alone calls `start`, `join`, `running` and
`workerFailed` (a caller rule, not checked), and `runBody` is the thread
entry's internal hook, never called directly. One that is dropped unjoined
leaks its thread rather than freeing what the thread runs.

## Worker pools: `Library.BackgroundJobs.WorkerPools` and `HostWorkerPools`

Thread workers share the process-wide ARC lock, so ARC-heavy work does not
scale on them. Measured on macOS arm64, each thread building the same managed
object graphs took 0.73 s alone, 3.37 s as one of two, 17.2 s as one of four
and 69.0 s as one of eight. Work of that kind runs on worker processes.

`WorkerPools` holds the portable contracts. An `IWorkerRequestHandler`
answers one string request with one string reply; an `IWorkerPool` delivers
requests to idle workers, returns each reply exactly once through
`awaitReply()` (`READY`, `RAISED` with exactly what the handler threw, `EMPTY`
when nothing is outstanding, `FAILED` once any worker has failed, `TIMEOUT`
when a nonnegative timeout passes with no reply) and owns the workers'
lifetimes (`close()` lets them finish and reaps them, `terminate()` kills and
reaps them). After a `RAISED` reply the worker is idle again and the pool stays
open; the owner decides whether to raise it. `usage(worker)` is a reaped
worker's own `WorkerUsage`: user and system CPU time in microseconds and peak
resident memory in KiB on every host, or null before reaping, for the owner
itself and where the host reports none. `InlineWorkerPool` is a pool whose
single worker is the owner itself; it runs the same schedule, a handler that
throws reaches `awaitReply()` as `RAISED` exactly as a forked worker's does,
and it reports no usage.

`ProcessThreads.count()` is the process's live thread count, or -1 where the
host cannot tell: one `/proc/self/task` entry per thread on linux
(`Linux/ProcessThreadsProvider`), `proc_pidinfo` task info on macOS
(`MacOS/ProcessThreadsProvider`). A thread that will block in a join holding
no lock until the thread it joins finishes calls `ProcessThreads.park()`
before creating that thread and `unpark()` after the join; the forked worker
pool counts `unparkedCount()`, so a process whose only other thread is parked
still forks. One thread parks at a time: the count is not atomic. The self-hosted compiler's Unix entries park their main thread
while the compile runs on a large-stack thread (`BtrccCompilerStack`). A
forked child calls `forgetParked()`, since it runs only the forking thread.

`HostWorkerPools` is the factory a host entry point hands to its owners. The
`[[package.providers]]` entries in `btrc.toml` select its `WorkerPoolProvider`
for the target: `Unix/WorkerPoolProvider` forks workers on linux and macOS,
and the root `WorkerPoolProvider` opens a single `InlineWorkerPool` on
windows. Consumers never name a provider.

One documented exception: the self-hosted compiler's `cli/WindowsMain.btrc`
passes no factory. Its C (`dist/btrcc-windows.c`) used to be transpiled for
the build host, where provider selection would have chosen the host's fork
provider, whose POSIX calls the Windows cross build cannot link. Since Stage
24 commit 1c it is transpiled with `--target windows-x86_64`, so selection
would choose the windows provider; the entry still passes no factory, and
`ModuleUnitCompiler` uses `InlineWorkerPool` directly, which is what the
windows provider would open. The Unix entries (`BtrccMain`, `MacOSMain`) pass
`HostWorkerPools`.

The Unix provider starts each worker as a copy of the owner at `open()`, so
it shares everything the owner had built copy-on-write and keeps what it
builds itself between requests. Owner and worker share one `AF_UNIX` socket
pair; frames are 16 lowercase hex digits of payload length and the payload,
and a reply's payload starts with one kind byte, `=` before an answer and `!`
before what the handler threw. A pool does not start while another thread
runs, since a lock that thread held at the fork would stay held forever in the
worker: `open()` returns null and the owner can answer inline. The owner reaps
each worker with `wait4`, which reports that worker's own usage.
The owner sends only to idle workers and reads every reply whole, so neither
side blocks the other on a full socket. A worker that exits, is killed or
writes a malformed frame fails the pool: every worker is terminated and
reaped, and no further request is accepted. Frames are written with
`send(MSG_NOSIGNAL)`, so a dead peer surfaces as a failed write or end of
input on either side; the pool never changes the process's `SIGPIPE`
disposition, and concurrent pools cannot undo each other's. Workers leave
through `_exit`, never running the owner's exit path or flushing its stdio
buffers twice. `suggestedWorkers()` is one per online CPU, at most four.
