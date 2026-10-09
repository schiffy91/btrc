# macOS unit GUI scheduling

The unit job at PR68 head `6f1b81d9` completed with 10,147 passes,
227 expected skips, two known test-contract failures and one setup error.
The tray reference/plain case exhausted the original 1800-second GUI lease
wait. Its recorded sanitized self-hosted shell holder subsequently passed.
The dedicated native-GUI run passed all 353 runnable cases, including that
tray row, using the existing GUI worker group and original three workers.

The unit workflow did not enable that scheduler. It now adds `--dist=loadgroup`
only for the unit shard, preserving `matrix.pytest_addopts` in both branches.
Existing marked GUI cases share one worker; other unit tests can still run
across the three workers. Other shards retain their exact per-row options.
There are no collection, runtime, lease, skip or timeout changes.

The parent includes separately qualified test repair `69e0b5d8` for the two
assertion failures. The original Mac unit evidence and classified skip roster
are retained in `/private/tmp/btrc-audit-repair/pr68-6f-final-mac-oct9`;
independent audit SHA-256 is
`69334cb33bf0a027c9d02281083fbffff67497c68be928263bc041718244ade2`.
No missing GCC-executable error recurred in this run; its prior cause remains
unproven.

Focused qualification on October 9 passes the two original baseline contracts
and all 102 candidate cases (79 workflow, 23 coordination), with no failures,
errors or skips. Collection, JUnit and skip identities agree; every source,
archive, tool and log hash closes, and all eight process groups are reaped and
absent. Independent audit SHA-256 is
`7f81ea57547b81f89eef765d5d4556217956863d6a596c2063346db8a1e31934`.
Evidence is retained under `macos-unit-gui-grouping-dbdc50d2-attempt-1` in the
October 7 consolidation evidence directory. The actual full hosted unit replay
remains required; these focused checks do not establish that acceptance.
