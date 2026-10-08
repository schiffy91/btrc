# Generated pointer temporaries in single try regions

Packet: `codex/gcc-single-try-pointer-temps-3974`; base `3974d47b`.
Owner: execution_review; integrator authorized the paired compiler repair.

Owned paths:

- `src/compiler/python/ir/lowering/exceptions.py`
- `src/compiler/btrc/ir/optimization/setjmp/Safety.btrc`
- `src/tests/python/test_exception_codegen_contracts.py`
- `src/tests/control_flow/SingleTryPointerOperands.btrc`
- `src/tests/control_flow/expected/SingleTryPointerOperands.stdout`
- `docs/workstreams/gcc-single-try-pointer-temporaries.md`

The existing setjmp safety planners own this GCC coalescing correction. No emitter,
grammar, runtime, generated-source, flags or product workaround changes are claimed.
Original Linux failure and local paired GCC compile-only baseline are retained.
Reference repair qualification is recorded in the final packet report; selfhost,
combined gates and real hosted product continuation remain pending.
