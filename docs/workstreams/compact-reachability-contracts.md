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
identical ASTs. Ruff lint and formatting pass. No pytest fixture collection,
compiler or native execution occurred; this is not a rerun of the full shard.
Full hosted shard and final-tree gates remain required; no skips or deadlines
change.
