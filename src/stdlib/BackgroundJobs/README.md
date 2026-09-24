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

Queueing, cancellation, completion publication and worker ownership live in
`BackgroundJobs.btrc`. The package imports pthread declarations through
`BackgroundJobs/NativeThreads.h`; it does not link a separate background-jobs C
runtime. The worker entrypoint still uses an explicit native context and the
runtime's foreign-thread boundary. That boundary has not yet migrated to the
checked callback-binding contract.

`close()` currently blocks while joining workers. It is not a nonblocking UI
shutdown primitive: moving an uninterruptible native call onto a worker does
not make joining that worker safe on the UI executor. A failed join or
synchronization teardown retains the executor for an explicit same-mode retry;
do not drop its owner or report completion on failure. A worker-disposal error
is reported separately after resources have been reclaimed. Application owners
must preserve that error rather than treating a later `ALREADY_CLOSED` result
as successful shutdown.

## Worker pools: `Library.BackgroundJobs.WorkerPools` and `ProcessWorkers`

Thread workers share the process-wide ARC lock, so ARC-heavy work does not
scale on them. Measured on macOS arm64, each thread building the same managed
object graphs took 0.73 s alone, 3.37 s as one of two, 17.2 s as one of four
and 69.0 s as one of eight. Work of that kind runs on worker processes.

`WorkerPools` holds the portable contracts. An `IWorkerRequestHandler`
answers one string request with one string reply; an `IWorkerPool` delivers
requests to idle workers, returns each reply exactly once through
`awaitReply()` (`READY`, `EMPTY` when nothing is outstanding, `FAILED` once any
worker has failed) and owns the workers' lifetimes (`close()` lets them finish
and reaps them, `terminate()` kills and reaps them). `InlineWorkerPool` is a
pool whose single worker is the owner itself, for hosts that cannot fork; it
runs the same schedule.

`ProcessWorkers` implements the contracts with `fork` (POSIX only; import it
only from a host entry point that can fork, as the self-hosted compiler's Unix
entries do). A worker starts as a copy of the owner at `open()`, so it shares
everything the owner had built copy-on-write and keeps what it builds itself
between requests. Frames are 16 lowercase hex digits of payload length and
the payload. The owner sends only to idle workers and reads every reply whole,
so neither side blocks the other on a full pipe. A worker that exits, is
killed or writes a malformed frame fails the pool: every worker is terminated
and reaped, and no further request is accepted. While a pool is open the owner
ignores `SIGPIPE`, so a dead worker surfaces as a failed write or end of input.
Workers leave through `_exit`, never running the owner's exit path or flushing
its stdio buffers twice. `suggestedWorkers()` is one per online CPU, at most
four.
