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
- an exact noncapturing `BackgroundJobRun` callback;
- one heap context envelope and its exact disposer.

Acceptance transfers the context to the executor; rejection leaves ownership
with the caller. The callback runs on a worker, mutates that envelope, and checks
its cooperative token with `BackgroundJobWork.cancellationRequested()`. A
polled completion owns the published envelope until `takeContext()` or
destruction. `close(DRAIN)` finishes admitted work; `close(CANCEL_PENDING)`
requests cancellation first. Both join every worker and dispose every unclaimed
context before returning. Callbacks and disposers must not throw across the C
boundary, and callbacks must eventually return after cancellation.

Native consumers link `build/stdlib/background_jobs/libbtrc_background_jobs.a`
and pthreads. `make background-jobs` builds the archive.
