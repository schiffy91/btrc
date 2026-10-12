# Compact reachability contract checks

PR70 Linux job114602290437 on exact5be08004 ended with5864 passed,34 skipped and
two failed source-shape tests. They required the obsolete `node.callee`,
`node.cType` and `node.targetType` spellings. The optimizer already performs
exact map membership and typed field scanning through guarded compact payloads.
The job log is SHA-256 `aedb0a46ff189b153681121fc8d877622f7f22c4e401e27ec5188cfd4a055f82`;
artifact11719813029 is SHA-256 `d13cfe2043a20e79784f63b96d9fdb851f818fabb3b81f20f23406372c28fd33`.

The two checks now require the exact guarded payload expressions. Function and
global collectors still require `names.has`, not substring scans. The type
collector requires exactly one scan of each compact type expression and retains
its prohibition on text/callee scanning and keys enumeration. Existing native
semantic tests remain byte-identical. No compiler repair or REQUEST is needed
for these observed failures; no production source changes.

Lightweight validation executed only these actual source-inspection function
bodies: the original two checks failed as observed, both corrected checks pass,
and six malformed-source controls (lost exact membership or missing/duplicated
type scans) are rejected. The remaining native semantic test functions have
identical ASTs. Ruff lint and formatting pass. The subsequent focused qualification of composed source `068ce3ab` passed all
nine cycle/reachability contracts, including both unchanged native semantic
checks, and all 162 Objective-C cases. Collection, JUnit and skip ledgers agree:
171 passed, zero failures, errors or skips. Both emitter frontend fixtures were
freshly built using the authenticated production-equivalent `3694ce58` compiler
and the existing native owners. Generated-source checking passed as well.

Result `479773d0` and independent audit `84fddd9a` are retained in
`compact-ir-test-contracts-068ce3ab-attempt-2`; source/tool/output hashes match and
all 11 command groups closed. Attempt 1's working-directory and SDK/linker
failures remain separately retained, with no test assertion or deadline change
in the corrected recipe. This does not qualify the full `5be08004` shard or
replace full hosted and final-tree gates.
