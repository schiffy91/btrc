"""Reference/self-host parity for the realtime call-graph contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]


def run_reference(source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            str(source),
            "-o",
            str(output),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


def run_selfhost(compiler: Path, source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(compiler), "--no-stdlib", str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )


def compile_and_run(source: Path, binary: Path) -> subprocess.CompletedProcess[str]:
    compiled = subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run([str(binary)], capture_output=True, text=True, timeout=120)


def test_standalone_realtime_example_compiles_identically(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = REPO / "examples/realtime_gain.btrc"
    reference_output = tmp_path / "reference.c"
    selfhost_output = tmp_path / "selfhost.c"
    reference = run_reference(source, reference_output)
    selfhost = run_selfhost(semantic_btrcc, source)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_output.write_text(selfhost.stdout)
    reference_run = compile_and_run(reference_output, tmp_path / "reference")
    selfhost_run = compile_and_run(selfhost_output, tmp_path / "selfhost")
    assert reference_run.returncode == selfhost_run.returncode == 0
    assert reference_run.stdout == selfhost_run.stdout


def test_manifest_safe_hosted_call_is_accepted_by_both_backstops(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "safe_hosted.btrc"
    source.write_text(
        "@realtime int magnitude(int value) { return abs(value); }\nint main() { return magnitude(-2) == 2 ? 0 : 1; }\n"
    )
    reference_output = tmp_path / "safe_hosted_reference.c"
    selfhost_output = tmp_path / "safe_hosted_selfhost.c"
    reference = run_reference(source, reference_output)
    selfhost = run_selfhost(semantic_btrcc, source)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_output.write_text(selfhost.stdout)
    assert compile_and_run(reference_output, tmp_path / "safe_hosted_reference").returncode == 0
    assert compile_and_run(selfhost_output, tmp_path / "safe_hosted_selfhost").returncode == 0


def test_transitive_failure_has_the_same_effect_and_path(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "unsafe.btrc"
    source.write_text(
        "void writeLog() { print(1); }\nvoid service() { writeLog(); }\n@realtime void audio() { service(); }\n"
    )
    reference = run_reference(source, tmp_path / "unsafe.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = (
        "@realtime callable 'audio' reaches forbidden logging operation "
        "'external call 'print()'' via audio -> service -> writeLog"
    )

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr
    assert ":1:19" in reference.stderr
    assert "at 1:19" in selfhost.stderr


def test_bodyless_external_fails_closed_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "unknown.btrc"
    source.write_text("extern void foreign();\n@realtime void audio() { foreign(); }\n")
    reference = run_reference(source, tmp_path / "unknown.c")
    selfhost = run_selfhost(semantic_btrcc, source)

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert "forbidden unknown operation 'bodyless or abstract callable'" in reference.stderr
    assert "forbidden unknown operation 'bodyless or abstract callable'" in selfhost.stderr
    assert "via audio -> foreign" in reference.stderr
    assert "via audio -> foreign" in selfhost.stderr


def test_unproven_spin_wait_fails_closed_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "spin_wait.btrc"
    source.write_text("@realtime void audio(bool ready) { while (!ready) {} }\n")
    reference = run_reference(source, tmp_path / "spin_wait.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = "forbidden blocking operation 'unproven while loop' via audio"

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


@pytest.mark.parametrize(
    ("name", "source_text", "expected"),
    (
        (
            "string_identifier",
            'string label = "ready"; @realtime void audio() { (void*)label; }',
            "forbidden strings operation 'string identifier 'label'' via audio",
        ),
        (
            "collection_identifier",
            "import std.vector;\nVector<int> values; @realtime void audio() { (void*)values; }",
            "forbidden collections operation 'collection identifier 'values'' via audio",
        ),
        (
            "managed_identifier",
            "class Box {} Box box; @realtime void audio() { (void*)box; }",
            "forbidden ARC operation 'managed identifier 'box'' via audio",
        ),
        (
            "string_field",
            "class Engine { public string label; public @realtime void audio() { (void*)self.label; } }",
            "forbidden strings operation 'string field 'label'' via Engine.audio",
        ),
        (
            "string_cast",
            "@realtime void audio(void* raw) { (string)raw; }",
            "forbidden strings operation 'string cast result' via audio",
        ),
    ),
)
def test_managed_value_admission_has_reference_selfhost_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    name: str,
    source_text: str,
    expected: str,
) -> None:
    source = tmp_path / f"{name}.btrc"
    source.write_text(source_text + "\n")
    reference = run_reference(source, tmp_path / f"{name}.c")
    selfhost = run_selfhost(semantic_btrcc, source)

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


@pytest.mark.parametrize(
    ("name", "declarations"),
    (
        ("string", "enum class Sample { Text(string value), Empty }"),
        ("class", "class Box {} enum class Sample { Object(Box value), Empty }"),
        ("collection", "import std.vector;\nenum class Sample { Values(Vector<int> value), Empty }"),
    ),
)
def test_managed_rich_enum_payload_has_reference_selfhost_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    name: str,
    declarations: str,
) -> None:
    source = tmp_path / f"rich_{name}.btrc"
    source.write_text(f"{declarations}\n@realtime void audio(Sample sample) {{}}\n")
    reference = run_reference(source, tmp_path / f"rich_{name}.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = "forbidden ARC operation 'managed parameter 'sample'' via audio"

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


def test_pod_global_self_field_and_rich_enum_compile_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "pod_values.btrc"
    source.write_text(
        "int globalLevel = 2;\n"
        "enum class Sample { Value(int sample), Empty }\n"
        "class Engine {\n"
        "  public int level;\n"
        "  public Engine(int level) { self.level = level; }\n"
        "  public @realtime int render(Sample sample) { return globalLevel + self.level + sample.tag; }\n"
        "}\n"
        "int main() { Engine engine = new Engine(3); Sample sample = Sample.Value(4); "
        "int result = engine.render(sample); delete engine; return result >= 5 ? 0 : 1; }\n"
    )
    reference_output = tmp_path / "pod_reference.c"
    selfhost_output = tmp_path / "pod_selfhost.c"
    reference = run_reference(source, reference_output)
    selfhost = run_selfhost(semantic_btrcc, source)

    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_output.write_text(selfhost.stdout)
    assert compile_and_run(reference_output, tmp_path / "pod_reference").returncode == 0
    assert compile_and_run(selfhost_output, tmp_path / "pod_selfhost").returncode == 0


def test_recursive_scc_has_the_same_closing_path(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "recursive.btrc"
    source.write_text(
        "int evenStep(int value);\n"
        "int oddStep(int value) { return evenStep(value - 1); }\n"
        "int evenStep(int value) { return oddStep(value - 1); }\n"
        "@realtime int audio(int value) { return evenStep(value); }\n"
    )
    reference = run_reference(source, tmp_path / "recursive.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = "forbidden blocking operation 'recursive call cycle' via audio -> evenStep -> oddStep -> evenStep"

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


@pytest.mark.parametrize(
    "loop",
    (
        "for (;;) {}",
        "for (int index = 0; ready; index++) {}",
        "for (int index = 0; index <= count; index++) {}",
        "for (int index = 0; index < count; index--) {}",
        "for (int index = 0; index < count; index = 0) {}",
        "for (int index = 0; index < count; index++) { index = 0; }",
    ),
)
def test_uncertified_c_for_has_reference_selfhost_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    loop: str,
) -> None:
    source = tmp_path / "uncertified_for.btrc"
    source.write_text(f"@realtime void audio(int count, bool ready) {{ {loop} }}\n")
    reference = run_reference(source, tmp_path / "uncertified_for.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = "forbidden blocking operation 'unproven C-style loop' via audio"

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr


def test_implicit_operator_call_has_the_same_path(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "operator.btrc"
    source.write_text(
        "class Engine {\n"
        "  public int __add__(int value) { print(value); return value; }\n"
        "  public @realtime int render() { return self + 1; }\n"
        "}\n"
    )
    reference = run_reference(source, tmp_path / "operator.c")
    selfhost = run_selfhost(semantic_btrcc, source)
    expected = "via Engine.render -> Engine.__add__"

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    assert expected in reference.stderr
    assert expected in selfhost.stderr
