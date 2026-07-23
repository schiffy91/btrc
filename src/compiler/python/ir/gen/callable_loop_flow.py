"""Callable-ABI dataflow across structured loop exits."""

from __future__ import annotations

from .callable_provenance import BORROWED_RETURN, snapshot_callable_flow


def begin_callable_loop_capture(owner):
    """Capture callable states reaching break/continue in one loop body."""
    capture = (frozenset(owner.context.callable_return_abis), [], [])
    owner._callable_loop_captures.append(capture)
    return capture


def finish_callable_loop_capture(owner, capture):
    """Close ``capture`` and return its break and continue exit states."""
    if not owner._callable_loop_captures or owner._callable_loop_captures[-1] is not capture:
        raise RuntimeError("callable loop captures must be properly nested")
    owner._callable_loop_captures.pop()
    return capture[1], capture[2]


def record_callable_loop_exit(owner, kind: str) -> None:
    """Record a break/continue only when it targets the active loop."""
    if not owner._callable_loop_captures:
        return
    target = _nearest_control_target(owner._control_context, kind)
    if target != "loop":
        return
    names, break_states, continue_states = owner._callable_loop_captures[-1]
    state = snapshot_callable_flow(owner)
    state = {name: state.get(name, BORROWED_RETURN) for name in names}
    states = break_states if kind == "break" else continue_states
    if not states or states[-1] != state:
        states.append(state)


def _nearest_control_target(context: list[str], kind: str) -> str | None:
    targets = {"loop", "switch"} if kind == "break" else {"loop"}
    return next((target for target in reversed(context) if target in targets), None)


def lower_loop_body(
    gen,
    body,
    *,
    lower_block,
    iteration_bindings=(),
    local_bindings=(),
    may_skip: bool = True,
    type_renderer,
):
    """Lower one ordinary loop body and install its reachable exit flow."""
    from ..completion import sequence_may_fall_through
    from .callable_provenance import (
        join_callable_flows,
        lower_isolated_callable_flow,
        restore_callable_flow,
        snapshot_callable_flow,
    )

    incoming = snapshot_callable_flow(gen)
    capture = begin_callable_loop_capture(gen)
    gen.push_loop_scope()
    gen.push_control_context("loop")
    try:
        lowered, body_flow = lower_isolated_callable_flow(
            gen,
            lambda: lower_block(
                gen,
                body,
                iteration_bindings=iteration_bindings,
                local_bindings=local_bindings,
                type_renderer=type_renderer,
            ),
        )
    finally:
        gen.pop_control_context()
        gen.pop_loop_scope()
        break_flows, continue_flows = finish_callable_loop_capture(gen, capture)
    exit_flows = [*break_flows, *continue_flows]
    if sequence_may_fall_through(lowered.stmts):
        exit_flows.append(body_flow)
    if may_skip:
        exit_flows.append(incoming)
    if exit_flows:
        join_callable_flows(gen, *exit_flows)
    else:
        restore_callable_flow(gen, incoming)
    return lowered


__all__ = [
    "begin_callable_loop_capture",
    "finish_callable_loop_capture",
    "lower_loop_body",
    "record_callable_loop_exit",
]
