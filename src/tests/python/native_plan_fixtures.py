"""Publish a native-plan generation the way the compilers do, for the plan builder's consumers."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.compiler.python.artifacts.cache import CompilerGenerationPublisher, CompilerOutput
from src.compiler.python.artifacts.publication import PublicationLock
from src.compiler.python.frontend.packages import NativeLinkPlan, PackageTarget


def publish_native_generation(root, value, secondary_name="secondary", *, boundary="", ready=None, done=None):
    root = Path(root)
    state = root / "state"
    state.mkdir(mode=0o700, exist_ok=True)
    primary = root / "primary" / "main.c"
    secondary = root / secondary_name / "part.c"
    plan = root / "plan" / "plan.json"
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = [str(secondary)]
    outputs = []
    for destination, role, content in (
        (primary, "primary", f"int answer(void); int main(void) {{ return answer() == {value} ? 0 : 1; }}\n"),
        (secondary, "secondary", f"int answer(void) {{ return {value}; }}\n"),
        (plan, "link-plan", json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"),
    ):
        destination.parent.mkdir(exist_ok=True)
        staged = destination.with_name(f"candidate-{value}")
        staged.write_text(content)
        outputs.append(CompilerOutput(staged, destination, role))
    publisher = CompilerGenerationPublisher(state)
    replace = os.replace
    lock = PublicationLock._lock_descriptor

    def replacing(source, destination):
        replace(source, destination)
        destination = Path(destination)
        if (
            (boundary == "primary" and destination == primary)
            or (boundary == "secondary" and destination == secondary)
            or (boundary == "plan" and destination == plan)
            or (
                boundary == "commit"
                and destination.name.endswith(".publish.journal")
                and json.loads(destination.read_text())["state"] == "committed"
            )
        ):
            os._exit(91)

    def locking(owner):
        if ready is not None and owner._name is None:
            ready.set()
        return lock(owner)

    os.replace = replacing
    PublicationLock._lock_descriptor = locking
    try:
        publisher.publish(outputs)
    finally:
        os.replace = replace
        PublicationLock._lock_descriptor = lock
    if done is not None:
        done.set()
