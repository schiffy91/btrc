# Compact IR test consumers

Owned paths: the existing ObjectiveCEmitter native fixture, test_cycle_boundaries.py, WORKSTREAMS claim and this report. Base5be08004.

PR70 Linux unit job114602290441 at run38183975817 completed with7222passed,3096skipped,160errors and1failure. Its tested merge2b88b4f2 has exactly the5be treeba68fb63. All160errors came from the two frontend builds of the shared ObjectiveCEmitter fixture, which still used removed fat-IR fields. The separate failure expected the obsolete node.callee spelling in the self-hosted cycle-boundary implementation.

Construct Objective-C block nodes with their kind so the existing constructor allocates the native payload. Project their existing fields, pool/boundary fields and declaration cleanup metadata through their concrete payload types. Original field values, invalid modes, error expectations, function bodies, shared build owner, strict C flags, test roster and deadlines stay unchanged. The cycle test keeps the same helper, value-before-flush and temporary-order requirements using the current concrete projections. Intentional null invalid-vector modes and unrelated pre-existing GPU placeholder warnings remain unchanged.

No compiler production repair is needed by the observed failures. The focused
qualification of the composed test-only source `068ce3ab` now passes all nine
cycle/reachability contracts and all 162 Objective-C cases, with zero failures,
errors or skips. Both reference and self-host emitter fixtures were freshly
built; the original Apple native lifetime cases ran with their existing flags
and assertions. Generated-source checking also passed. The qualified `3694ce58`
compiler binary was reused after authenticating unchanged production inputs.

Attempt 1 remains retained as an environmental failure: seven contracts passed,
while an incorrect working directory broke a relative source lookup and mixed
Apple SDK/Nix linker settings broke a native build. Objective-C cases were not
reached. Attempt 2 corrected only the recipe's working directory and toolchain
environment, preserving the source, selections, assertions and bounds.

Result `479773d0` and independent audit `84fddd9a` are retained in
`compact-ir-test-contracts-068ce3ab-attempt-2`. The audit matched all collected,
JUnit and skip-ledger identities, 342 file pins, 4,522 Git source files, generated
outputs and 22 raw logs; all 11 owned command groups closed. This is focused
qualification, not a green full gate for `5be08004` or the final integration
tree. Full hosted shards and the repository's final-tree gates remain required.
