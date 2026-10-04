"""Capture real AT-SPI nodes from the probe window in its private session."""

import json
import sys
import time
from collections import Counter

import pyatspi
from gi.repository import GLib

WINDOW_TITLE = "BTRC GTK4 WebGPU probe"
NODE_BUDGET = 256
CHILD_LIMIT = 16


def tree(node, remaining, deadline):
    if remaining[0] <= 0 or time.monotonic() >= deadline:
        return {"truncated": "node-or-time-budget", "children": []}
    remaining[0] -= 1
    child_count = node.childCount
    result = {
        "name": node.name,
        "role": node.getRoleName(),
        "child_count": child_count,
        "children": [],
    }
    for index in range(min(child_count, CHILD_LIMIT)):
        if remaining[0] <= 0 or time.monotonic() >= deadline:
            break
        child = node.getChildAtIndex(index)
        if child is not None:
            result["children"].append(tree(child, remaining, deadline))
    if len(result["children"]) != child_count:
        result["truncated"] = "children-not-fully-enumerated"
    return result


def flatten(node):
    yield node
    for child in node.get("children", []):
        yield from flatten(child)


def main():
    deadline = time.monotonic() + 10
    observed = set()
    last_error = None
    while time.monotonic() < deadline:
        # Dispatch AT-SPI cache/registration updates on this client as the
        # separately running GTK process services its native main context.
        context = GLib.MainContext.default()
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)
        desktop = pyatspi.Registry.getDesktop(0)
        for application in desktop:
            try:
                observed.add(application.name)
                # GtkApplication registration alone need not set the process's
                # accessible application name: this probe is named "Unnamed".
                # Its exact native window title identifies the target instead.
                for window in application:
                    if window.name != WINDOW_TITLE:
                        continue
                    document = {
                        "name": application.name,
                        "role": application.getRoleName(),
                        "children": [tree(window, [NODE_BUDGET], deadline)],
                    }
                    nodes = list(flatten(document))
                    roles = Counter(node["role"] for node in nodes if "role" in node)
                    entry = any(roles[role] for role in ("entry", "text", "password text"))
                    button = any(node.get("name") == "Overlay" and "button" in node.get("role", "") for node in nodes)
                    collection = any(roles[role] for role in ("list", "list box", "table"))
                    if not (entry and button and collection):
                        continue
                    summary = {
                        "atspi": "captured",
                        "application": application.name,
                        "window": window.name,
                        "nodes": len(nodes),
                        "roles": dict(sorted(roles.items())),
                        "truncated_nodes": sum("truncated" in node for node in nodes),
                        "node_budget": NODE_BUDGET,
                        "children_per_node_limit": CHILD_LIMIT,
                    }
                    document["capture"] = summary
                    with open(sys.argv[1], "w") as output:
                        json.dump(document, output, indent=2)
                    print(json.dumps(summary, sort_keys=True))
                    return 0
            except GLib.Error as error:
                # Registration and teardown can race a remote read. Retry
                # within the same deadline, retaining diagnosis on failure.
                last_error = str(error)
        time.sleep(0.1)
    print(
        json.dumps(
            {
                "atspi": "unavailable",
                "applications": sorted(observed),
                "error": last_error,
                "reason": "probe window did not expose entry, Overlay button and list before deadline",
            }
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
