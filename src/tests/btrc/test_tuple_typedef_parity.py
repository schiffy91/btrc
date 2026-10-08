"""Tuple typedefs for shapes spelled only in generic code or generic instances.

Both compilers declare one C struct per concrete tuple shape. A shape inside a
generic class, generic method or generic interface is concrete only through an
instance, so neither compiler may record it with an unbound type parameter
(``struct btrc_Tuple_U_char { U _0; ... }`` breaks the C once dead-code
elimination is off), and both must record it under each instance's
substitution. Each program here is compiled through the Python compiler and
``btrcc``, with and without ``--no-dce``; the two C files must be identical and
must build and run under strict C11 on every host C compiler.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

REPO = Path(__file__).resolve().parents[3]

HOLDER_MODULE = """class Holder<T> {
	public T value;

	public int size() {
		(T, char) pair = {self.value, 'z'};
		return (int)sizeof((T, short)) + pair._1;
	}
}
"""

PROGRAMS = {
    "CanonicalInstanceReturnOrder": (
        """class Pair<T> {
    public T value;
    public Pair(T value) { self.value = value; }
    public (T, T) both() { return (self.value, self.value); }
}

int main() {
    Pair<int> numbers = new Pair<int>(7);
    Pair<char> letters = new Pair<char>('k');
    print(f"{numbers.both()._0} {letters.both()._1}");
    return 0;
}
""",
        "7 k\n",
    ),
    "CanonicalNestedDependencies": (
        """int main() {
    (int, (short, char)) outer = (7, ((short)2, 'q'));
    (char, int) earlier = ('a', 4);
    print(f"{outer._0 + outer._1._0 + earlier._1} {outer._1._1}");
    return 0;
}
""",
        "13 q\n",
    ),
    "GenericMethodSizeof": (
        """class Box {
	public int width<U>(U value) {
		return (int)sizeof((U, char));
	}
}

int main() {
	Box box = new Box();
	delete box;
	print("done");
	return 0;
}
""",
        "done\n",
    ),
    "GenericClassSizeof": (
        """class Holder<T> {
	public T value;

	public int size() {
		return (int)sizeof((T, char));
	}
}

int main() {
	Holder<int> holder = new Holder<int>();
	(int, char) pair = {1, 'c'};
	print(f"{holder.size() == (int)sizeof((int, char))} {pair._1}");
	return 0;
}
""",
        "true c\n",
    ),
    "GenericInterfaceSignature": (
        """interface Pairing<T> {
	(T, int) pairUp(T value);
}

int main() {
	print("ok");
	return 0;
}
""",
        "ok\n",
    ),
    "InstanceMethodReturn": (
        """class Box<T> {
	public T value;

	public Box(T v) { self.value = v; }

	public (T, T) both() { return (self.value, self.value); }
}

int main() {
	Box<int> b = new Box<int>(3);
	int x = b.both()._0;
	print(f"{x}");
	return 0;
}
""",
        "3\n",
    ),
    "InstanceMethodLocal": (
        """class Box<T> {
	public T value;

	public Box(T v) { self.value = v; }

	public int second() {
		(T, int) p = {self.value, 5};
		return p._1;
	}
}

int main() {
	Box<char> b = new Box<char>('a');
	print(f"{b.second()}");
	return 0;
}
""",
        "5\n",
    ),
    "InstanceFieldInitializer": (
        """class Box<T> {
	public int width = (int)sizeof((T, char));
}

int main() {
	Box<short> b = new Box<short>();
	print(f"{b.width > 0}");
	return 0;
}
""",
        "true\n",
    ),
    "GenericMethodInstance": (
        """class Wrapper {
	public (U, int) wrap<U>(U a) {
		(U, int) result = {a, 7};
		return result;
	}
}

int main() {
	Wrapper w = new Wrapper();
	short s = 4;
	(short, int) r = w.wrap(s);
	print(f"{r._1}");
	return 0;
}
""",
        "7\n",
    ),
    "InstanceInferredGenericCall": (
        """class Box<T> {
	public T value;

	public Box(T v) { self.value = v; }

	public (T, U) pairWith<U>(U other) { return (self.value, other); }

	public int use() {
		var p = self.pairWith('c');
		return (int)p._1;
	}
}

int main() {
	Box<int> b = new Box<int>(3);
	print(f"{b.use()}");
	return 0;
}
""",
        "99\n",
    ),
    "ImportedInstanceBody": (
        """import "Holder.btrc";

int main() {
	Holder<int> h = new Holder<int>();
	print(f"{h.size() > 0}");
	return 0;
}
""",
        "true\n",
    ),
}


def _transpile(tmp_path: Path, btrcc: Path, name: str, no_dce: bool) -> tuple[str, str]:
    source, _expected = PROGRAMS[name]
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    (directory / "Holder.btrc").write_text(HOLDER_MODULE)
    program = directory / "Main.btrc"
    program.write_text(source)
    flags = ["--no-stdlib", *(["--no-dce"] if no_dce else [])]
    selfhost = subprocess.run(
        [str(btrcc), *flags, str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    reference_c = directory / "reference.c"
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(program), *flags, "--no-cache", "-o", str(reference_c)],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(directory / "cache")},
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert reference.returncode == 0, reference.stderr
    return reference_c.read_text(), selfhost.stdout


@pytest.mark.skipif(not HOST_C_COMPILERS, reason="no host C compiler")
@pytest.mark.parametrize("no_dce", [False, True], ids=["dce", "no-dce"])
@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_both_compilers_declare_every_concrete_tuple_shape(
    immutable_btrcc: Path, tmp_path: Path, name: str, no_dce: bool
) -> None:
    reference_c, selfhost_c = _transpile(tmp_path, immutable_btrcc, name, no_dce)
    assert selfhost_c == reference_c, f"{name}: the compilers' C diverged"
    generated = tmp_path / name / "program.c"
    generated.write_text(selfhost_c)
    expected = PROGRAMS[name][1]
    for compiler in HOST_C_COMPILERS:
        binary = tmp_path / name / f"program-{Path(compiler).name}"
        build = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(generated),
                "-o",
                str(binary),
                "-lm",
                "-lpthread",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=C_COMPILE_TIMEOUT,
        )
        assert build.returncode == 0, f"{compiler}: {build.stderr}"
        run = subprocess.run([str(binary)], cwd=REPO, capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert run.returncode == 0, run.stderr
        assert run.stdout == expected
