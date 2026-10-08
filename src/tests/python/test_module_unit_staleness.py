"""Module-unit reuse stays exact when a dependency's body or a non-interface fact changes.

Each case builds a small program as module units, edits it once, and builds it
again with the same cache and output directory. The incremental build must
equal a clean build of the edited program in a fresh cache, unit for unit and
diagnostic for diagnostic (docs/design/stage-b-reuse-keys.md, defects SB-D1
to SB-D8). The output directory is the same in every build, because debug
builds name it in their `#line` directives and their keys.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

ROOT = Path(__file__).resolve().parents[3]
# A module-unit build of a small program, through either compiler's CLI.
_BUILD_TIMEOUT = max(TOOL_TIMEOUT, 300.0)


@dataclass(frozen=True)
class _Build:
    """One build's emitted C files, its diagnostics and how many groups it lowered."""

    units: dict[str, str]
    diagnostics: list[str]
    lowered: int


def _command(compiler: str, request) -> list[str]:
    if compiler == "python":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


def _records(cache: Path) -> dict[Path, tuple[int, int]]:
    """The reference compiler's stored unit records, each by the file it was
    last written as: every store replaces the record with a new file."""
    records = {}
    for path in cache.rglob("*.module.json") if cache.exists() else ():
        written = path.stat()
        records[path] = (written.st_ino, written.st_mtime_ns)
    return records


def _build(
    command: list[str],
    source: Path,
    output: Path,
    cache: Path,
    *extra: str,
    environment: dict[str, str] | None = None,
    succeeds: bool = True,
) -> _Build:
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.glob("p*.c"):
        stale.unlink()
    before = _records(cache)
    completed = subprocess.run(
        [
            *command,
            "Main.btrc",
            "-o",
            str(output / "p.c"),
            "--emit-units",
            str(output / "p"),
            "--module-units",
            "--jobs",
            "1",
            *extra,
        ],
        cwd=source,
        env={
            **os.environ,
            "BTRC_HOME": str(ROOT / "src"),
            "PYTHONPATH": str(ROOT),
            "BTRC_CACHE_DIR": str(cache),
            # btrcc reports its module-unit counters in its timing lines.
            **({} if command[0] == sys.executable else {"BTRC_TIMING": "1"}),
            **(environment or {}),
        },
        capture_output=True,
        text=True,
        timeout=_BUILD_TIMEOUT,
    )
    assert (completed.returncode == 0) == succeeds, completed.stderr
    diagnostics = [line for line in completed.stderr.splitlines() if not line.startswith("btrcc ")]
    if "module-units=lowered:" in completed.stderr:
        lowered = int(completed.stderr.split("module-units=lowered:", 1)[1].split(",", 1)[0])
    else:
        # btrcpy stores a record for each group it lowers.
        lowered = sum(1 for path, written in _records(cache).items() if before.get(path) != written)
    units = {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}
    return _Build(units, diagnostics, lowered)


def _incremental_matches_clean(
    compiler: str,
    request,
    tmp_path: Path,
    files: dict[str, str],
    edits: dict[str, tuple[str, str]],
    *extra: str,
    environment: dict[str, str] | None = None,
) -> tuple[_Build, _Build, _Build]:
    """Cold build, edit, incremental build; then a clean build of the edited
    program in a fresh cache, into the same output directory. Returns the
    cold, incremental and clean builds after asserting the last two equal."""
    root = tmp_path.resolve()
    source = root / "program"
    source.mkdir()
    for name, text in files.items():
        (source / name).write_text(text)
    command = _command(compiler, request)
    output = root / "out"
    cold = _build(command, source, output, root / "cache", *extra)
    for name, (old, new) in edits.items():
        path = source / name
        text = path.read_text()
        assert old in text, (name, old)
        path.write_text(text.replace(old, new, 1))
    incremental = _build(command, source, output, root / "cache", *extra, environment=environment)
    clean = _build(command, source, output, root / "fresh-cache", *extra)
    assert incremental.diagnostics == clean.diagnostics
    assert incremental.units.keys() == clean.units.keys()
    for name in clean.units:
        assert incremental.units[name] == clean.units[name], name
    return cold, incremental, clean


def _lowered(build: _Build, groups: int) -> None:
    """The edit relowers exactly `groups` groups: the stale ones, and no more."""
    assert build.lowered == groups, build.lowered


_GPU_PROGRAM = {
    "Kernel.btrc": """@gpu float[] twice(float[] a) {
	int i = gpu_id();
	return a[i] * 2.0;
}
""",
    "Use.btrc": """import ./Kernel.btrc;

float scaled(float value) {
	float[] values = [value, value];
	values = twice(values);
	return values[0];
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{scaled(1.0)}");
	return 0;
}
""",
}


def test_gpu_kernel_body_edit_relowers_its_dispatcher(compiler: str, tmp_path, request):
    """SB-D1: the dispatcher in `Use` embeds the kernel's WGSL, built from its body."""
    _, incremental, _ = _incremental_matches_clean(
        compiler, request, tmp_path, _GPU_PROGRAM, {"Kernel.btrc": ("a[i] * 2.0", "a[i] * 3.0")}
    )
    _lowered(incremental, 2)


_DESTRUCTOR_PROGRAM = {
    "Base.btrc": """int freed = 0;

class Base {
	public int value = 1;

	public Base() {}

	public void __del__() {
		freed = freed + 1;
	}
}
""",
    "Derived.btrc": """import ./Base.btrc;

class Derived extends Base {
	public int extra = 2;

	public Derived() {}
}

int churn() {
	Derived item = Derived();
	return item.extra;
}
""",
    "Main.btrc": """import ./Base.btrc;
import ./Derived.btrc;

int main() {
	print(f"{churn()} {freed}");
	return 0;
}
""",
}


def test_inherited_destructor_body_edit_relowers_the_child(compiler: str, tmp_path, request):
    """SB-D2: `Derived_destroy` carries `Base.__del__`'s body, lowered in Derived's unit."""
    _, incremental, _ = _incremental_matches_clean(
        compiler, request, tmp_path, _DESTRUCTOR_PROGRAM, {"Base.btrc": ("freed + 1", "freed + 2")}
    )
    _lowered(incremental, 2)


def test_debug_lines_above_an_inherited_destructor_relower_the_child(compiler: str, tmp_path, request):
    """SB-D4: in a debug build, the inherited body carries Base's positions."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _DESTRUCTOR_PROGRAM,
        {"Base.btrc": ("int freed = 0;\n", "int freed = 0;\n\n\n// moved\n")},
        "--debug",
    )
    _lowered(incremental, 2)


_DEFAULTS_PROGRAM = {
    "Lib.btrc": """int scale(int x, int factor = 3 + 4) {
	return x * factor;
}

class Meter {
	public int base = 1;

	public Meter() {}

	public int read(int offset = 2 * 5) {
		return self.base + offset;
	}
}
""",
    "Use.btrc": """import ./Lib.btrc;

int measure() {
	Meter meter = Meter();
	return scale(2) + meter.read();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{measure()}");
	return 0;
}
""",
}


def test_debug_lines_above_a_default_argument_relower_its_callers(compiler: str, tmp_path, request):
    """SB-D3: btrcc positions a caller's default helper at the callee's default;
    btrcpy's helper is at `<btrc-generated>`, so its callers do not move."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _DEFAULTS_PROGRAM,
        {"Lib.btrc": ("int scale(", "// one\n// two\nint scale(")},
        "--debug",
    )
    _lowered(incremental, 1 if compiler == "python" else 2)


_PREDEFINED_DEFAULT_PROGRAM = {
    "Lib.btrc": """int where(int line = __LINE__) {
	return line;
}
""",
    "Use.btrc": """import ./Lib.btrc;

int at() {
	return where();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{at()}");
	return 0;
}
""",
}


def test_lines_above_a_line_default_relower_its_callers(compiler: str, tmp_path, request):
    """A `__LINE__` default is frozen at the callee's position, even in a release build."""
    cold, incremental, clean = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _PREDEFINED_DEFAULT_PROGRAM,
        {"Lib.btrc": ("int where(", "// one\n// two\nint where(")},
    )
    assert cold.units != clean.units
    _lowered(incremental, 2)


_LOOKUP = """string? lookup(int key) {
	if (key > 0) { return "found"; }
	return null;
}
"""

_MAIN_USES = """import ./Use.btrc;

int main() {
	print(f"{use(1)}");
	return 0;
}
"""

# Each way a call can never return: a top-level function, a static method, and
# a method `self` dispatches to, each defined in `Lib` and called from `Use`.
_DIVERGENCE_PROGRAMS = {
    "function": {
        "Lib.btrc": """void fail() {
	exit(1);
}
""",
        "Use.btrc": f"""import ./Lib.btrc;

{_LOOKUP}
int use(int key) {{
	string? found = lookup(key);
	if (found == null) {{
		fail();
	}}
	string value = found;
	return value.length();
}}
""",
        "Main.btrc": _MAIN_USES,
    },
    "static": {
        "Lib.btrc": """class Fail {
	class void now() {
		exit(1);
	}
}
""",
        "Use.btrc": f"""import ./Lib.btrc;

{_LOOKUP}
int use(int key) {{
	string? found = lookup(key);
	if (found == null) {{
		Fail.now();
	}}
	string value = found;
	return value.length();
}}
""",
        "Main.btrc": _MAIN_USES,
    },
    "dispatch": {
        "Lib.btrc": """class Guard {
	public Guard() {}

	public void stop() {
		exit(1);
	}
}
""",
        "Use.btrc": f"""import ./Lib.btrc;

{_LOOKUP}
class Checker extends Guard {{
	public Checker() {{}}

	public int check(int key) {{
		string? found = lookup(key);
		if (found == null) {{
			self.stop();
		}}
		string value = found;
		return value.length();
	}}
}}

int use(int key) {{
	Checker checker = Checker();
	return checker.check(key);
}}
""",
        "Main.btrc": _MAIN_USES,
    },
}


@pytest.mark.parametrize("form", sorted(_DIVERGENCE_PROGRAMS))
def test_a_callee_that_starts_returning_replays_no_stale_warning(compiler: str, form: str, tmp_path, request):
    """SB-D5: "never returns" is a body fact; the caller's warnings depend on it."""
    cold, _, clean = _incremental_matches_clean(
        compiler, request, tmp_path, _DIVERGENCE_PROGRAMS[form], {"Lib.btrc": ("exit(1);", "return;")}
    )
    assert not cold.diagnostics
    assert any("Possibly-null value stored" in line for line in clean.diagnostics), clean.diagnostics


_DISPATCH_PROGRAM = {
    "Base.btrc": """string? lookup(int key) {
	if (key > 0) { return "found"; }
	return null;
}

class Base {
	public Base() {}

	public void stop() {
		exit(1);
	}

	public int run(int key) {
		string? found = lookup(key);
		if (found == null) {
			self.stop();
		}
		string value = found;
		return value.length();
	}
}
""",
    "Sub.btrc": """import ./Base.btrc;

class Sub extends Base {
	public Sub() {}

	public void stop() {
		exit(2);
	}
}
""",
    "Main.btrc": """import ./Base.btrc;
import ./Sub.btrc;

int main() {
	Sub sub = Sub();
	print(f"{sub.run(1)}");
	return 0;
}
""",
}


def test_verify_mode_accepts_a_record_whose_answers_moved(compiler: str, tmp_path, request):
    """A record a replay would reject, because a "never returns" answer moved,
    is not a disagreement for BTRC_VERIFY_VALIDATION_RECORDS (btrcc; btrcpy
    keeps no analysis records)."""
    _, _, clean = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _DISPATCH_PROGRAM,
        {"Sub.btrc": ("exit(2);", "return;")},
        environment={"BTRC_VERIFY_VALIDATION_RECORDS": "1"},
    )
    assert any("Possibly-null value stored" in line for line in clean.diagnostics), clean.diagnostics


_IMPORT_ORDER_PROGRAM = {
    "First.btrc": """#define FIRST_LIMIT 4

int first() { return FIRST_LIMIT; }
""",
    "Second.btrc": """#define SECOND_LIMIT 5

int second() { return SECOND_LIMIT; }
""",
    "Main.btrc": """import ./First.btrc;
import ./Second.btrc;

int main() {
	print(f"{first() + second()}");
	return 0;
}
""",
}


def test_swapping_two_imports_matches_a_clean_build(compiler: str, tmp_path, request):
    """SB-D6: the import order decides every unit's directive and prototype order."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _IMPORT_ORDER_PROGRAM,
        {"Main.btrc": ("import ./First.btrc;\nimport ./Second.btrc;", "import ./Second.btrc;\nimport ./First.btrc;")},
    )
    _lowered(incremental, 3)


_TUPLE_PROGRAM = {
    "Lib.btrc": """int pick(int value) {
	(int, string) pair = (value, "lib");
	return pair._0;
}
""",
    "Use.btrc": """import ./Lib.btrc;

int combine(int value) {
	(double, int) left = (1.5, value);
	(int, string) right = (value, "use");
	return left._1 + right._0 + pick(value);
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{combine(2)}");
	return 0;
}
""",
}


def test_a_new_tuple_shape_in_one_body_keeps_other_units_exact(compiler: str, tmp_path, request):
    """SB-D7: tuple structs were ordered by discovery across every body."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _TUPLE_PROGRAM,
        {
            "Lib.btrc": (
                '(int, string) pair = (value, "lib");',
                '(double, int) flag = (0.5, value);\n\t(int, string) pair = (value, "lib");',
            )
        },
    )
    _lowered(incremental, 3)


_SPAN_PROGRAM = {
    "Lib.btrc": """int pick(int value) {
	int storage[2] = {value, value};
	Span<int> view = Span(storage);
	double other[1] = {0.5};
	Span<double> flag = Span(other);
	return view.isEmpty() || flag.isEmpty() ? 0 : value;
}
""",
    "Use.btrc": """import ./Lib.btrc;

int combine(int value) {
	double left[2] = {1.5, 2.5};
	Span<double> dv = Span(left);
	int right[2] = {value, value};
	Span<int> iv = Span(right);
	return (dv.isEmpty() ? 0 : 1) + (iv.isEmpty() ? 0 : 1) + pick(value);
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{combine(2)}");
	return 0;
}
""",
}


def test_reordered_span_shapes_keep_other_units_exact(compiler: str, tmp_path, request):
    """btrcpy declares span shapes once, in body-discovery order, and every unit
    takes them in that order; btrcc declares them in each unit's own session."""
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        _SPAN_PROGRAM,
        {
            "Lib.btrc": (
                "\tint storage[2] = {value, value};\n\tSpan<int> view = Span(storage);\n"
                "\tdouble other[1] = {0.5};\n\tSpan<double> flag = Span(other);\n",
                "\tdouble other[1] = {0.5};\n\tSpan<double> flag = Span(other);\n"
                "\tint storage[2] = {value, value};\n\tSpan<int> view = Span(storage);\n",
            )
        },
    )
    _lowered(incremental, 3 if compiler == "python" else 1)


_INSTANCE_ORDER_PROGRAM = {
    "Lib.btrc": """class Box<T> {
	public T value;

	public Box(T value) { self.value = value; }

	public T get() { return self.value; }
}
""",
    "Use.btrc": """import ./Lib.btrc;

float total() {
	Box<int> whole = new Box<int>(2);
	Box<float> part = new Box<float>(0.5);
	return whole.get() + part.get();
}
""",
    "Main.btrc": """import ./Use.btrc;

int main() {
	print(f"{total()}");
	return 0;
}
""",
}


_METHOD_INSTANCE_ORDER_PROGRAM = {
    "Lib.btrc": """class Converter {
    public Converter() {}
    public T identity<T>(T value) { return value; }
}
""",
    "Use.btrc": """import ./Lib.btrc;

float total() {
    Converter converter = new Converter();
    int whole = converter.identity<int>(2);
    float part = converter.identity<float>(0.5);
    return whole + part;
}
""",
    "Main.btrc": _INSTANCE_ORDER_PROGRAM["Main.btrc"],
}


@pytest.mark.parametrize("debug", [False, True], ids=["release", "debug"])
@pytest.mark.parametrize(
    "files,first,second",
    [
        pytest.param(
            _INSTANCE_ORDER_PROGRAM,
            "Box<int> whole = new Box<int>(2);",
            "Box<float> part = new Box<float>(0.5);",
            id="class",
        ),
        pytest.param(
            _METHOD_INSTANCE_ORDER_PROGRAM,
            "int whole = converter.identity<int>(2);",
            "float part = converter.identity<float>(0.5);",
            id="method",
        ),
    ],
)
def test_swapping_instance_uses_keeps_the_template_unit_exact(compiler: str, debug, files, first, second, tmp_path, request):
    """G12/SB-29: discovery order changes only Use, never the template unit."""
    # Preserve line count and indentation so debug output in Lib cannot move.
    original = files["Use.btrc"]
    between = original[original.index(first) + len(first) : original.index(second)]
    cold, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        files,
        {"Use.btrc": (first + between + second, second + between + first)},
        *(["--debug"] if debug else []),
    )
    changed = {name for name, text in incremental.units.items() if text != cold.units[name]}
    assert len(changed) == 1 and next(iter(changed)).startswith("p.unit-Use-"), changed
    _lowered(incremental, 1)


@pytest.mark.parametrize("debug", [False, True], ids=["release", "debug"])
def test_an_unrelated_line_shift_reuses_every_other_unit(compiler: str, debug: bool, tmp_path, request):
    """The fixes stay narrow: lines added above a plain function relower only its group."""
    files = dict(_DEFAULTS_PROGRAM)
    files["Other.btrc"] = "int other() { return 3; }\n"
    files["Main.btrc"] = files["Main.btrc"].replace("import ./Use.btrc;", "import ./Use.btrc;\nimport ./Other.btrc;")
    _, incremental, _ = _incremental_matches_clean(
        compiler,
        request,
        tmp_path,
        files,
        {"Other.btrc": ("int other()", "// moved\nint other()")},
        *(["--debug"] if debug else []),
    )
    _lowered(incremental, 1)


# r13: a generic's type parameter may not hide a struct with a flexible array
# member that its file can see. `Lib` is unchanged when `Mid` starts importing
# that struct, so its class validation may replay from its record; the refusal
# must not replay away with it.
_SHADOW_FORMS = {
    "class": (
        "class Holder<Packet> {\n\tpublic Holder() {}\n\n\tpublic int size() { return 1; }\n}\n",
        "\tHolder<int> holder = new Holder<int>();\n\treturn holder.size() - 1;\n",
        "Type parameter 'Packet' of 'Holder' is named like struct 'Packet'",
    ),
    "method": (
        "class Holder {\n\tpublic Holder() {}\n\n\tpublic int pick<Packet>(Packet* value) { return 0; }\n}\n",
        "\tHolder holder = new Holder();\n\tint value = 0;\n\treturn holder.pick(&value);\n",
        "Type parameter 'Packet' of 'Holder.pick' is named like struct 'Packet'",
    ),
}


@pytest.mark.parametrize("form", sorted(_SHADOW_FORMS))
def test_a_newly_visible_flexible_struct_refuses_an_unchanged_generic(compiler: str, form: str, tmp_path, request):
    declaration, body, refusal = _SHADOW_FORMS[form]
    root = tmp_path.resolve()
    source = root / "program"
    source.mkdir()
    (source / "Packet.btrc").write_text("struct Packet { int length; int items[]; };\n")
    (source / "Mid.btrc").write_text("int midValue() { return 0; }\n")
    (source / "Lib.btrc").write_text("import ./Mid.btrc;\n\n" + declaration)
    (source / "Main.btrc").write_text("import ./Lib.btrc;\n\nint main() {\n" + body + "}\n")
    command = _command(compiler, request)
    output = root / "out"
    cold = _build(command, source, output, root / "cache")
    assert not cold.diagnostics
    (source / "Mid.btrc").write_text("import ./Packet.btrc;\n\nint midValue() { return 0; }\n")
    incremental = _build(command, source, output, root / "cache", succeeds=False)
    clean = _build(command, source, output, root / "fresh-cache", succeeds=False)
    assert incremental.diagnostics == clean.diagnostics
    assert any(refusal in line for line in clean.diagnostics), clean.diagnostics
