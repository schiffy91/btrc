# Compact IR test consumers

Owned paths: the existing ObjectiveCEmitter native fixture, test_cycle_boundaries.py, WORKSTREAMS claim and this report. Base5be08004.

PR70 Linux unit job114602290441 at run38183975817 completed with7222passed,3096skipped,160errors and1failure. Its tested merge2b88b4f2 has exactly the5be treeba68fb63. All160errors came from the two frontend builds of the shared ObjectiveCEmitter fixture, which still used removed fat-IR fields. The separate failure expected the obsolete node.callee spelling in the self-hosted cycle-boundary implementation.

Construct Objective-C block nodes with their kind so the existing constructor allocates the native payload. Project their existing fields, pool/boundary fields and declaration cleanup metadata through their concrete payload types. Original field values, invalid modes, error expectations, function bodies, shared build owner, strict C flags, test roster and deadlines stay unchanged. The cycle test keeps the same helper, value-before-flush and temporary-order requirements using the current concrete projections. Intentional null invalid-vector modes and unrelated pre-existing GPU placeholder warnings remain unchanged.

No compiler production repair is needed by the observed failures. Source/format checks only; neither frontend fixture build nor behavioral/native qualification has run for this candidate. The full Objective-C suite must still qualify both frontends; Apple-only native cases require their actual platform.
