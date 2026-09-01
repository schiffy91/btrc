# `std.background_jobs`

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

When a source graph imports `std.background_jobs`, both compilers add the
compiler-shipped `btrc_background_jobs.c` unit and include directory to the
emitted native link plan. The canonical plan adapter therefore links the
runtime and pthreads without a consumer-specific flag or ambient prebuilt
archive. `make background-jobs` still builds
`build/stdlib/background_jobs/libbtrc_background_jobs.a` for direct native
embedding and runtime conformance tests.
