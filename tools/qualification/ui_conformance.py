"""Record what the GUI conformance suite proves in the UI catalog.

The suite's cases name the catalog operations they exercise
(src/tests/native/gui/conformance/cases.toml). For the platforms whose
provider is the shim provider (Linux, Windows, Android) this writes, into
each operation's shard (docs/design/native-ui-catalog/operations), one cell
per platform and frontend: implemented, with the case's tests as its
regression, or an adaptation with its reason. What the runs showed goes
into one evidence shard (evidence/ui3-conformance.toml). The macOS and iOS
cells, the ids, owners and links are left exactly as they are.

    python3 -m tools.qualification.ui_conformance record --revision <sha> --recorded-at <ISO time>

The run it records is a claim: `ui_catalog check --junit <run>=<junit.xml>`
holds it to a JUnit file from that platform's driver, in which every test a
cell names must have passed.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CATALOG = REPO / "docs/design/native-ui-catalog"
SUITE = REPO / "src/tests/native/gui/conformance"
FRONTENDS = {"reference": "python", "selfhost": "selfhost"}
# It sorts after the earlier evidence shards, as newer evidence must.
EVIDENCE = "ui3-conformance.toml"
TESTS = "src/tests/python"

# Each platform's driver: its run, what its provider is, what it has of what
# a case may need, and the tests that are one case through one compiler.
PLATFORMS = {
    "linux": {
        "run": "ui-conformance-linux",
        "runner": "linux",
        "configuration": "GTK4 through the shim provider, in a private X11 or Wayland session; WebKitGTK for the web view",
        "has": {"web", "freetype", "modal"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance.py::test_linux_conformance_case[{case}-{frontend}-{mode}]"
            for mode in ("plain", "sanitized")
        ],
    },
    "windows": {
        "run": "ui-conformance-windows",
        "runner": "windows",
        "configuration": "Win32 and Common Controls 6 through the shim provider, on windows-x64; WebView2 for the web view",
        "has": {"web", "modal"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance_windows.py::test_windows_conformance_case[{case}-{frontend}-windows-x64-{mode}]"
            for mode in ("plain", "ubsan")
        ],
    },
    "android": {
        "run": "ui-conformance-android",
        "runner": "android",
        "configuration": "Android's own views through the shim provider, on the x86_64 emulator; android.webkit.WebView for the web view",
        "has": {"web", "modal"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance_android.py::test_android_conformance_case[{case}-{frontend}]"
        ],
    },
}

# What a platform does differently from the contract's words, by operation,
# where the suite's case passes on the adapted behaviour.
ADAPTED = {
    "android": {
        "IWindow.setContentSize": "The session gives every window the whole screen: a size the program asks for is the window's only until it is first shown.",
        "IWindow.setMinimumContentSize": "The session gives every window the whole screen, so a least size has nothing to hold.",
        "GUI.createWindow": "The session gives every window the whole screen: the size asked for is the window's only until it is first shown.",
        "IApplication.createWindow": "The session gives every window the whole screen: the size asked for is the window's only until it is first shown.",
        "GUI.chooseDirectory": "Android has no folder to choose by path: the chooser reports that it is unavailable.",
        "IDirectoryPicker.chooseDirectory": "Android has no folder to choose by path: the chooser reports that it is unavailable.",
    },
}

# What a platform's provider does not have, by what a case needs.
WITHOUT = {
    "freetype": "A font face from a file is FreeType's, and this platform's SDK does not carry FreeType: text here is the system's own, and Library.GUI.FreeType has no provider.",
}


def quoted(text):
    return json.dumps(text, ensure_ascii=False)


class Recorder:
    def __init__(self, revision, recorded_at):
        self.revision, self.recorded_at = revision, recorded_at
        suite = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))
        self.cases, self.uncovered = suite["case"], suite["uncovered"]
        self.covering = {operation: case for case in self.cases for operation in case["operations"]}

    def runs(self):
        lines = []
        for facts in PLATFORMS.values():
            lines += [
                f"[runs.{facts['run']}]",
                'source = "junit"',
                f"recorded_at = {quoted(self.recorded_at)}",
                f"runner = {quoted(facts['runner'])}",
                f"btrc_revision = {quoted(self.revision)}",
                "",
            ]
        return "\n".join(lines)

    def facts(self, operation, platform, frontend):
        """One slot: its classification, and its evidence."""
        facts = PLATFORMS[platform]
        case = self.covering.get(operation)
        needs = case.get("needs") if case else None
        classification = {"configuration": facts["configuration"]}
        if case is not None and needs and needs not in facts["has"]:
            classification |= {"implementation": "missing", "parity": "os-restricted", "note": WITHOUT[needs]}
            return classification, {"status": "unavailable", "covered_by": [], "reason": WITHOUT[needs]}
        if case is None:
            reason = self.uncovered[operation]
            classification |= {
                "implementation": "implemented",
                "parity": "equivalent",
                "note": f"No case exercises this operation: {reason}.",
            }
            return classification, {"status": "implemented-unverified", "reason": reason}
        adapted = ADAPTED.get(platform, {}).get(operation)
        note = (
            f"The conformance suite's case {case['name']} exercises this operation (src/tests/native/gui/conformance)."
        )
        classification |= {
            "implementation": "implemented",
            "parity": "adapted" if adapted else "equivalent",
            "note": note + (" " + adapted if adapted else ""),
            "regression": facts["tests"](case["name"], frontend),
        }
        return classification, {"status": "passed", "observed": "passed"}

    def cell(self, operation, platform, name, frontend):
        classification, _ = self.facts(operation, platform, frontend)
        lines = [f"[operations.{platform}.{name}]"]
        for key in ("implementation", "parity", "configuration", "note"):
            lines.append(f"{key} = {quoted(classification[key])}")
        if "regression" in classification:
            lines.append("regression = [" + ", ".join(quoted(test) for test in classification["regression"]) + "]")
        return lines

    def evidence(self, operations):
        """The evidence shard: one record a slot, each carrying its platform's run."""
        lines = [
            "# What the GUI conformance suite proves of each operation on the shim provider's",
            "# platforms. Written by tools/qualification/ui_conformance.py; `ui_catalog check",
            "# --junit <run>=<junit.xml>` holds each run to its driver's JUnit file.",
            "# The revision is the parent of the commit that records it, for a commit cannot",
            "# name itself: the two trees differ by this catalog's files and the plan's notes.",
            'schema = "btrc.qualification.ledger/1"',
            "",
        ]
        for operation in operations:
            for platform, facts in PLATFORMS.items():
                provenance = (
                    f'{{ source = "junit", recorded_at = {quoted(self.recorded_at)}, runner = {quoted(facts["runner"])}, '
                    f"btrc_revision = {quoted(self.revision)} }}"
                )
                for name, frontend in FRONTENDS.items():
                    _, evidence = self.facts(operation, platform, frontend)
                    fields = ", ".join(
                        f"{key} = {quoted(value) if isinstance(value, str) else '[]'}"
                        for key, value in evidence.items()
                    )
                    lines += [
                        "[[records]]",
                        f'subject = {{ kind = "ui-operation", id = {quoted(operation)}, platform = "{platform}", frontend = "{name}" }}',
                        f"evidence = {{ {fields} }}",
                        f"provenance = {provenance}",
                        "",
                    ]
        return "\n".join(lines)

    def cells(self, operation):
        lines = []
        for platform in PLATFORMS:
            for name, frontend in FRONTENDS.items():
                lines += self.cell(operation, platform, name, frontend)
        return lines

    def rewrite(self, path):
        """Replace the shim platforms' cells and this tool's runs in one shard; everything else stays."""
        lines = path.read_text(encoding="utf-8").splitlines()
        runs = {facts["run"] for facts in PLATFORMS.values()}
        output, operation, skipping, wrote_runs = [], None, False, False

        def close():
            nonlocal operation
            if operation is not None:
                while output and not output[-1].strip():
                    output.pop()
                output.extend(self.cells(operation))
                output.append("")
                operation = None

        for line in lines:
            header = re.fullmatch(r"\[+([^\]]+)\]+", line.strip())
            if header:
                name = header[1]
                mine = name.startswith("runs.") and name[5:] in runs
                cell = re.fullmatch(r"operations\.(\w+)(\.\w+)?", name)
                skipping = mine or bool(cell and cell[1] in PLATFORMS)
                if name == "operations" and line.strip().startswith("[["):
                    close()
                    if not wrote_runs:
                        output.append(self.runs())
                        wrote_runs = True
                if skipping:
                    continue
            elif skipping:
                continue
            if operation is None and (found := re.fullmatch(r'id = "([^"]+)"', line.strip())):
                operation = found[1]
            output.append(line)
        close()
        path.write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="write the shim platforms' cells into every operation shard")
    record.add_argument("--revision", required=True, help="the commit whose tree the drivers ran")
    record.add_argument("--recorded-at", required=True, help="when they ran, as an ISO time with its zone")
    arguments = parser.parse_args(argv)
    recorder = Recorder(arguments.revision, arguments.recorded_at)
    operations = []
    for shard in sorted((CATALOG / "operations").glob("*.toml")):
        recorder.rewrite(shard)
        operations += [row["id"] for row in tomllib.loads(shard.read_text(encoding="utf-8")).get("operations", [])]
    (CATALOG / "evidence" / EVIDENCE).write_text(recorder.evidence(operations), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
