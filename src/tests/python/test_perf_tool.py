"""`python3 -m tools.perf` measures a program through the reference compiler and the C compiler."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from tools import perf

ROOT = Path(__file__).resolve().parents[3]


def test_phase_times_reads_both_compilers_marks():
    stderr = "noise\nbtrcpy timing: lex=1500us parse=500us analyze=2000000us\nbtrcc timing: lex=1000us emit=250us\n"
    assert perf.phase_times(stderr) == {"lex": 0.0025, "parse": 0.0005, "analyze": 2.0, "emit": 0.00025}


def test_c_stats_counts_definitions(tmp_path):
    source = tmp_path / "unit.c"
    source.write_text(
        '#line 3 "x.btrc"\ntypedef struct btrc_Vector_int btrc_Vector_int;\nstruct A {\n};\nint f(void) {\n}\nstatic int g(int a) {\n}\n'
    )
    stats = perf.c_stats(source)
    assert (stats.lines, stats.functions, stats.structs, stats.vector_instances, stats.line_directives) == (
        8,
        2,
        1,
        1,
        1,
    )


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_reference_compiler_measurement(tmp_path):
    report = tmp_path / "report.json"
    code = perf.main(
        [
            str(ROOT / "src/tests/basics/Hello.btrc")
            if (ROOT / "src/tests/basics/Hello.btrc").exists()
            else str(next((ROOT / "src/tests/basics").glob("*.btrc"))),
            "--frontends",
            "btrcpy",
            "--opt",
            "O0",
            "--cc",
            "cc",
            "--out",
            str(tmp_path / "work"),
            "--json",
            str(report),
        ]
    )
    assert code == 0
    data = json.loads(report.read_text())
    assert data["compilers"][0]["frontend"] == "btrcpy"
    assert data["compilers"][0]["phases_s"]["lower"] >= 0.0
    assert data["c_compiles"][0]["optimisation"] == "O0" and data["c_compiles"][0]["object_bytes"] > 0
    assert sys.executable
