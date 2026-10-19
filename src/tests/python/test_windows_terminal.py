"""Library.Terminal on a real Windows console, through both compilers, on x64 and ARM64.

The console provider (src/stdlib/Terminal/Windows) needs a console, which a
hosted runner's redirected standard streams are not, so ConptyHarness.c
makes one: it starts TerminalConsole.btrc in a pseudoconsole, types at its
prompts and checks what it reports. That covers what redirected input
cannot: the password echo hidden and restored, the secrets never on screen,
UTF-16 console input returned as UTF-8, Ctrl-C ending a prompt with the echo
restored before a caller's handler runs (the prompt re-registers its control
handler first), a burst of Ctrl-C, the default handler ending the process
with the echo already back, raw keys as VT bytes, the window size and VT
colours. Redirected input is the corpus program stdlib/Terminal.btrc.

This module builds the harness and the program through both compilers for
windows-x64 and windows-arm64 and publishes them (windows_evidence_fixtures);
windows.yml's win32-native job runs the harness on Windows x64 and ARM64.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import RUN_TIMEOUT
from src.tests.python.windows_evidence_fixtures import WINDOWS_TARGETS, build_c_fixture, build_corpus_program, publish

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "src" / "tests" / "native" / "terminal_windows"
PROGRAM = "native/terminal_windows/src/TerminalConsole.btrc"

# Every line ConptyHarness prints when every check passes, in order.
EXPECTED = "".join(
    f"conpty-terminal {line}\n"
    for line in (
        "ready ok",
        "first prompt ok",
        "password ok: match=1 echo=1",
        "second prompt ok",
        "ctrl-c ok: empty=1 calls=1 saw=1 echo=1",
        "third prompt ok",
        "after ctrl-c ok: match=1 echo=1",
        "burst prompt ok",
        "ctrl-c burst ok: empty=1 echo=1",
        "plain prompt ok",
        "unicode line ok: match=1",
        "raw mode ok: =0 line=0 processed=0",
        "raw ready ok",
        "raw keys ok: 97,98,3,27,91,65 restored=1 echo=1 line=1 processed=1",
        "size ok: 100x30",
        "colors ok: 1",
        "pass ok",
        "exit ok",
        "first secret hidden ok",
        "third secret hidden ok",
        "default prompt ok",
        "default ctrl-c exit ok",
        "restored before exit ok: echo=1 line=1 processed=1",
        "probe exit ok",
        "PASS",
    )
)


@pytest.fixture(scope="module")
def harnesses(tmp_path_factory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("conpty-harness")
    return {
        target: build_c_fixture(
            [FIXTURE / "ConptyHarness.c"], target, directory / f"conpty-terminal-{target}.exe", libraries=("shell32",)
        )
        for target in sorted(WINDOWS_TARGETS)
    }


def test_harness_expects_every_check_the_program_reports():
    """Each line the harness waits for is one the program prints."""
    program = (FIXTURE / "src" / "TerminalConsole.btrc").read_text(encoding="utf-8")
    harness = (FIXTURE / "ConptyHarness.c").read_text(encoding="utf-8")
    for marker in ("first ", "second ", "third ", "burst ", "plain ", "raw echo", "raw keys=", "size ", "colors "):
        assert f'"{marker}' in harness
        assert f'"{marker}' in program or f'printf("{marker}' in program
    for prompt in ("first secret: ", "second secret: ", "third secret: ", "burst secret: ", "plain line: "):
        assert f'"{prompt}"' in program
        assert f'"{prompt.rstrip()}"' in harness


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_redirected_terminal_corpus_builds_for_windows(frontend, target, request, tmp_path):
    """stdlib/Terminal.btrc: the provider on redirected streams, against the corpus goldens."""
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    executable = build_corpus_program("stdlib/Terminal.btrc", frontend, target, btrcc, tmp_path)
    expected = REPO / "src" / "tests" / "stdlib" / "expected"
    publish(
        executable,
        f"corpus-{frontend}-Terminal-{target}",
        (expected / "Terminal.stdout").read_bytes(),
        (expected / "Terminal.stderr").read_bytes(),
    )


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_console_journey_builds_for_windows(harnesses, frontend, target, request, tmp_path):
    btrcc = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    program = build_corpus_program(PROGRAM, frontend, target, btrcc, tmp_path)
    harness = harnesses[target]
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        directory = Path(evidence)
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(program, directory / f"terminal-console-{frontend}-{target}.exe")
        shutil.copy2(harness, directory / harness.name)
        (directory / f"conpty-terminal-{target}.stdout").write_text(EXPECTED, encoding="utf-8")
    if sys.platform == "win32":
        ran = subprocess.run(
            [str(harness), str(program)], capture_output=True, text=True, timeout=RUN_TIMEOUT * 20, check=False
        )
        assert ran.returncode == 0 and ran.stdout.replace("\r", "") == EXPECTED, (ran.stdout, ran.stderr)
