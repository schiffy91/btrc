# `Library.BackgroundJobs`

`BackgroundJobExecutor` is the bounded worker-pool boundary for serialized
applications. It complements `spawn()`/`Thread.join()` when the owner loop must
remain responsive and poll completed work instead of blocking.

The executor owns 1–16 workers and 1–4096 fixed outstanding slots. Capacity
includes queued, running, and terminal-but-unpolled jobs. `poll()` is
owner-thread-only and strictly nonblocking: it returns `READY`, `EMPTY`, or
`BUSY` without waiting on a condition or worker.

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
