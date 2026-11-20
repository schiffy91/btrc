"""Record what the GUI conformance suite proves in the UI catalog.

The suite's cases name the catalog operations they exercise
(src/tests/native/gui/conformance/cases.toml). For the platforms whose
provider is the shim provider (Linux, Windows, Android, iOS) this writes,
into each operation's shard (docs/design/native-ui-catalog/operations), one
cell per platform and frontend: implemented, with the case's tests as its
regression, or an adaptation with its reason. What the runs showed goes
into one evidence shard (evidence/ui3-conformance.toml). The macOS cells,
the ids, owners and links are left exactly as they are.

    python3 -m tools.qualification.ui_conformance record --revision <sha> --recorded-at <ISO time>

The platforms' drivers run on different hosts, and so at different times and
revisions: `--platform` (once for each) records those platforms' runs alone
and leaves every other platform's cells, run and records as they are.

The run it records is a claim: `ui_catalog check --junit <run>=<junit.xml>`
holds it to a JUnit file from that platform's driver, in which every test a
cell names must have passed.
"""

from __future__ import annotations

import argparse
import functools
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


@functools.cache
def needs():
    """What each of the suite's cases needs of a platform, by the case's name."""
    cases = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["case"]
    return {case["name"]: case.get("needs") for case in cases}


def ios_tests(case, frontend):
    """A case's rows on the simulators: both device classes', and the tablet's in a second scene and a compact one."""
    test = f"{TESTS}/test_native_ui_conformance_ios.py"
    classes = ("ipad",) if needs()[case] in PLATFORMS["ios"]["restricted"] else ("iphone", "ipad")
    modes = ("plain", "sanitized")
    return [
        *(
            f"{test}::test_ios_conformance_case[{case}-{device}-{frontend}-{mode}]"
            for device in classes
            for mode in modes
        ),
        *(f"{test}::test_ipad_conformance_case_in_a_second_scene[{case}-{frontend}-{mode}]" for mode in modes),
        *(f"{test}::test_ipad_conformance_case_in_a_compact_scene[{frontend}-{mode}-{case}]" for mode in modes),
    ]


# Each platform's driver: its run, what its provider is, what it has of what
# a case may need, and the tests that are one case through one compiler.
# `restricted` is what only some of a platform's devices have, with the reason.
PLATFORMS = {
    "linux": {
        "run": "ui-conformance-linux",
        "runner": "linux",
        "configuration": "GTK4 through the shim provider, in a private X11 or Wayland session; WebKitGTK for the web view",
        "has": {"web", "freetype", "modal", "wheel"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance.py::test_linux_conformance_case[{case}-{frontend}-{mode}]"
            for mode in ("plain", "sanitized")
        ],
    },
    "windows": {
        "run": "ui-conformance-windows",
        "runner": "windows",
        "configuration": "Win32 and Common Controls 6 through the shim provider, on windows-x64; WebView2 for the web view",
        "has": {"web", "modal", "wheel"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance_windows.py::test_windows_conformance_case[{case}-{frontend}-windows-x64-{mode}]"
            for mode in ("plain", "ubsan")
        ],
    },
    "android": {
        "run": "ui-conformance-android",
        "runner": "android",
        "configuration": "Android's own views through the shim provider, on the x86_64 emulator; android.webkit.WebView for the web view",
        "has": {"web", "modal", "wheel"},
        "tests": lambda case, frontend: [
            f"{TESTS}/test_native_ui_conformance_android.py::test_android_conformance_case[{case}-{frontend}]"
        ],
    },
    "ios": {
        "run": "ui-conformance-ios",
        "runner": "ios",
        "configuration": "UIKit through the shim provider, on an iPhone and an iPad simulator; WKWebView for the web view",
        "has": {"web", "modal", "wheel"},
        "restricted": {"wheel": "A phone has no pointer and no wheel: the tablet's rows alone exercise it."},
        "tests": ios_tests,
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
    "ios": {
        "IWindow.setContentSize": "The scene gives every window its whole safe area: a size the program asks for is the window's only until it is first shown.",
        "IWindow.setMinimumContentSize": "The scene gives every window its whole safe area, so a least size has nothing to hold.",
        "GUI.createWindow": "The scene gives every window its whole safe area: the size asked for is the window's only until it is first shown.",
        "IApplication.createWindow": "The scene gives every window its whole safe area: the size asked for is the window's only until it is first shown.",
        "GUI.chooseDirectory": "iOS has no folder to choose by path: the chooser reports that it is unavailable.",
        "IDirectoryPicker.chooseDirectory": "iOS has no folder to choose by path: the chooser reports that it is unavailable.",
    },
}

# What a platform does not have, by what a case needs: whether its provider
# implements the operations all the same, and why no run shows them.
WITHOUT = {
    "wheel": {"implementation": "implemented", "note": "The device has no pointer and no wheel."},
    "freetype": {
        "implementation": "missing",
        "note": "A font face from a file is FreeType's, and this platform's SDK does not carry FreeType: text here is the system's own, and Library.GUI.FreeType has no provider.",
    },
}


def quoted(text):
    return json.dumps(text, ensure_ascii=False)


class Recorder:
    def __init__(self, revision, recorded_at, platforms=tuple(PLATFORMS)):
        self.revision, self.recorded_at = revision, recorded_at
        # The platforms this record is of, in the catalog's order.
        self.platforms = [platform for platform in PLATFORMS if platform in platforms]
        suite = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))
        self.cases, self.uncovered = suite["case"], suite["uncovered"]
        self.covering = {operation: case for case in self.cases for operation in case["operations"]}

    def run(self, platform):
        facts = PLATFORMS[platform]
        return [
            f"[runs.{facts['run']}]",
            'source = "junit"',
            f"recorded_at = {quoted(self.recorded_at)}",
            f"runner = {quoted(facts['runner'])}",
            f"btrc_revision = {quoted(self.revision)}",
        ]

    def facts(self, operation, platform, frontend):
        """One slot: its classification, and its evidence."""
        facts = PLATFORMS[platform]
        case = self.covering.get(operation)
        needs = case.get("needs") if case else None
        classification = {"configuration": facts["configuration"]}
        if case is not None and needs and needs not in facts["has"]:
            without = WITHOUT[needs]
            classification |= {"parity": "os-restricted", **without}
            return classification, {"status": "unavailable", "covered_by": [], "reason": without["note"]}
        if case is None:
            reason = self.uncovered[operation]
            classification |= {
                "implementation": "implemented",
                "parity": "equivalent",
                "note": f"No case exercises this operation: {reason}.",
            }
            return classification, {"status": "implemented-unverified", "reason": reason}
        adapted = ADAPTED.get(platform, {}).get(operation)
        restricted = facts.get("restricted", {}).get(needs)
        note = (
            f"The conformance suite's case {case['name']} exercises this operation (src/tests/native/gui/conformance)."
        )
        classification |= {
            "implementation": "implemented",
            "parity": "os-restricted" if restricted else "adapted" if adapted else "equivalent",
            "note": " ".join(text for text in (note, adapted, restricted) if text),
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

    def record(self, operation, platform, name, frontend):
        """One slot's record in the evidence shard, carrying its platform's run."""
        facts = PLATFORMS[platform]
        provenance = (
            f'{{ source = "junit", recorded_at = {quoted(self.recorded_at)}, runner = {quoted(facts["runner"])}, '
            f"btrc_revision = {quoted(self.revision)} }}"
        )
        _, evidence = self.facts(operation, platform, frontend)
        fields = ", ".join(
            f"{key} = {quoted(value) if isinstance(value, str) else '[]'}" for key, value in evidence.items()
        )
        return [
            "[[records]]",
            f'subject = {{ kind = "ui-operation", id = {quoted(operation)}, platform = "{platform}", frontend = "{name}" }}',
            f"evidence = {{ {fields} }}",
            f"provenance = {provenance}",
            "",
        ]

    def evidence(self, operations, existing=""):
        """The evidence shard: one record a slot. A platform this record is not of keeps the records it has."""
        kept = {}
        for block in existing.split("[[records]]\n")[1:]:
            subject = re.match(
                r'subject = \{ kind = "ui-operation", id = "([^"]+)", platform = "(\w+)", frontend = "(\w+)" \}', block
            )
            kept[subject.groups()] = ["[[records]]", *block.rstrip("\n").split("\n"), ""]
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
            for platform in PLATFORMS:
                for name, frontend in FRONTENDS.items():
                    if platform in self.platforms:
                        lines += self.record(operation, platform, name, frontend)
                    else:
                        lines += kept.get((operation, platform, name), [])
        return "\n".join(lines)

    def cells(self, operation, platform):
        lines = []
        for name, frontend in FRONTENDS.items():
            lines += self.cell(operation, platform, name, frontend)
        return lines

    def rewrite(self, path):
        """Replace this record's platforms' cells and runs in one shard, where they stand; everything else stays."""
        lines = path.read_text(encoding="utf-8").splitlines()
        runs = {PLATFORMS[platform]["run"]: platform for platform in self.platforms}
        output, operation, skipping = [], None, False
        # The runs and, of the operation being read, the cells that are not written yet.
        unwritten, cells = list(self.platforms), []

        def close():
            nonlocal operation
            if operation is not None:
                while output and not output[-1].strip():
                    output.pop()
                for platform in cells:
                    output.extend(self.cells(operation, platform))
                output.append("")
                operation = None

        for line in lines:
            header = re.fullmatch(r"\[+([^\]]+)\]+", line.strip())
            if header:
                name = header[1]
                cell = re.fullmatch(r"operations\.(\w+)(\.\w+)?", name)
                skipping = False
                if name.startswith("runs.") and name[5:] in runs:
                    skipping = True
                    if runs[name[5:]] in unwritten:
                        unwritten.remove(runs[name[5:]])
                        output.extend(self.run(runs[name[5:]]))
                elif cell and cell[1] in self.platforms:
                    skipping = True
                    if cell[1] in cells:
                        cells.remove(cell[1])
                        output.extend(self.cells(operation, cell[1]))
                elif name == "operations" and line.strip().startswith("[["):
                    close()
                    for platform in unwritten:
                        output.extend([*self.run(platform), ""])
                    unwritten, cells = [], list(self.platforms)
            if skipping and line.strip():
                # What stood there goes; the lines between tables stay where they are.
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
    record.add_argument(
        "--platform",
        action="append",
        choices=sorted(PLATFORMS),
        help="a platform whose driver ran; every platform's when none is named",
    )
    arguments = parser.parse_args(argv)
    recorder = Recorder(arguments.revision, arguments.recorded_at, arguments.platform or tuple(PLATFORMS))
    operations = []
    for shard in sorted((CATALOG / "operations").glob("*.toml")):
        recorder.rewrite(shard)
        operations += [row["id"] for row in tomllib.loads(shard.read_text(encoding="utf-8")).get("operations", [])]
    shard = CATALOG / "evidence" / EVIDENCE
    shard.write_text(recorder.evidence(operations, shard.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
