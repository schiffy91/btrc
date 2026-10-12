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

Only this test, its workstream claim and this report change. The original and candidate hardening files each pass all23 cases with no skips.
The real-analysis and both-cache integration test remains unchanged. Three
in-memory controls independently prove that the repaired test rejects omitted
locking, analysis before lock acquisition, and missing good-cache publication;
all workers retire. A controlled analyzer waiting for validation release shows
the old timed test can accept an omitted lock, without claiming this reproduces
the hosted timeout. Final-tree CI remains required. The original macOS failure is preserved under the task's
`pr70-macos-unit-38183975819` audit packet.


Qualification is retained in the private `lsp-contention-5be` evidence packet.
Its aggregate audit records exact collection, JUnit/ledger identities, unchanged
source/tool inventories and all eight closed process groups. Two earlier control
script classification errors remain failed receipts; the passing23+23 test runs
were not repeated or relabeled. The final corrected controls passed separately.
No native/compiler build, production edit, push or workflow change occurred.
