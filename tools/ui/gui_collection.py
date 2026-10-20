"""Explicit pytest hooks for GUI partition collection and canonical JUnit identities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ui.gui_shards import NODE_PROPERTY


class GUICollection:
    """Retain collection problems instead of turning them into absent test nodes."""

    def __init__(self, path: Path | None):
        self.path = path
        self.nodes: list[str] = []
        self.problems: list[dict[str, str]] = []

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items):
        # xdist may decorate scheduling IDs. The original identity belongs in
        # JUnit, including skipped/setup-error cases that never enter the test.
        originals = {id(item): item.nodeid for item in items}
        result = yield
        self.nodes = [originals[id(item)] for item in items]
        for item in items:
            item.user_properties.append((NODE_PROPERTY, originals[id(item)]))
        return result

    def pytest_collectreport(self, report):
        if report.failed or report.skipped:
            self.problems.append({"nodeid": report.nodeid, "outcome": report.outcome, "detail": str(report.longrepr)})

    def pytest_sessionfinish(self, session, exitstatus):
        if self.path is not None:
            self.path.write_text(
                json.dumps(
                    {
                        "schema": "btrc.gui-collection/1",
                        "nodes": self.nodes,
                        "problems": self.problems,
                        "exitstatus": int(exitstatus),
                    },
                    indent=2,
                )
                + "\n"
            )


def pytest_addoption(parser):
    parser.addoption("--gui-collection", help="write the complete GUI collection manifest")


def pytest_configure(config):
    path = config.getoption("--gui-collection")
    config.pluginmanager.register(GUICollection(Path(path) if path else None), "btrc-gui-collection")
