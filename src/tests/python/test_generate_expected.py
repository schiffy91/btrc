"""The golden generator writes goldens only for passing programs and reports failures."""

from __future__ import annotations

from pathlib import Path

from src.tests.c_toolchains import requires_host_c_compiler
from src.tests.generate_expected import GoldenGenerator

PASSING = """
#include <stdio.h>
int main() {
    fprintf(stderr, "diagnostic\\n");
    printf("PASS\\n");
    return 0;
}
"""
QUIET = 'int main() {\n    printf("PASS\\n");\n    return 0;\n}\n'
FAILING = 'int main() {\n    printf("PASS\\n");\n    return 3;\n}\n'
NO_PASS = 'int main() {\n    printf("done\\n");\n    return 0;\n}\n'


@requires_host_c_compiler
def test_goldens_are_written_only_for_passing_programs(tmp_path: Path, capsys) -> None:
    topic = tmp_path / "topic"
    expected = topic / "expected"
    expected.mkdir(parents=True)
    for name, source in {"Passing": PASSING, "Quiet": QUIET, "Failing": FAILING, "NoPass": NO_PASS}.items():
        (topic / f"{name}.btrc").write_text(source)
    (expected / "Quiet.stderr").write_text("stale\n")
    (expected / "Failing.stdout").write_text("kept\n")

    status = GoldenGenerator(str(tmp_path)).generate(
        ["topic/Passing.btrc", "topic/Quiet.btrc", "topic/Failing.btrc", "topic/NoPass.btrc"]
    )

    assert status == 1
    assert (expected / "Passing.stdout").read_text() == "PASS\n"
    assert (expected / "Passing.stderr").read_text() == "diagnostic\n"
    assert (expected / "Quiet.stdout").read_text() == "PASS\n"
    assert not (expected / "Quiet.stderr").exists()
    assert (expected / "Failing.stdout").read_text() == "kept\n"
    assert not (expected / "NoPass.stdout").exists()
    report = capsys.readouterr().out
    assert "FAIL topic/Failing.btrc: program exited with 3" in report
    assert "FAIL topic/NoPass.btrc: program did not print PASS" in report
    assert "(0 skipped, 2 failed)" in report
