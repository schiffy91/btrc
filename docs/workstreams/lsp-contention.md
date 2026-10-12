# LSP feature/validation contention

The frozen PR70 macOS unit run failed the feature contention test's five-second
completion assertion. It retained no worker exception or stack, so the evidence
does not identify a production deadlock or establish a machine-load cause.

The test now uses an isolated server and observes a failed acquisition of the
same real lock held by validation before checking that analysis cannot enter.
Real SAMPLE analysis occurs before the synchronization window; the existing
uncached feature/cache integration test remains unchanged. The actual server
method must publish that result to both caches after release within the original
five seconds. Worker exceptions are captured and the worker is joined before
test dependency restoration, including failed assertion paths.

Only this test, its workstream claim and this report change. Focused behavioral
qualification and lock-bypass negative controls are pending; final-tree CI remains
required. The original macOS failure is preserved under the task's
`pr70-macos-unit-38183975819` audit packet.
