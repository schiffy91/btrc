"""Self-host contracts for setjmp continuation and loop-backedge storage."""

import re
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_selfhost_qualifies_try_finally_loop_continuations(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int main() {
            int finallyCount = 0;
            for (int i = 0; i < 4; i++) {
                try {
                    if (i % 2 == 0) { continue; }
                } finally {
                    finallyCount++;
                }
            }
            assert(finallyCount == 2);
            return 0;
        }
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "volatile int finallyCount = 0;" in emitted
    assert "volatile int i = 0;" in emitted
    _strict_build_and_run(
        generated,
        tmp_path / "setjmp-continuation",
        optimization="-O1",
    )


def test_selfhost_preserves_aggregate_mutations_across_longjmp(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        struct Probe { int value; };
        int main() {
            int values[1] = {0};
            struct Probe probe = {0};
            try {
                values[0] = 3;
                values[0] += 4;
                probe.value = 4;
                probe.value += 5;
                throw "done";
            } catch (string message) {}
            return values[0] == 7 && probe.value == 9 ? 0 : 1;
        }
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "volatile int values[1]" in emitted
    assert "volatile struct Probe probe" in emitted
    assert "int volatile* __btrc_lvalue" in emitted
    _strict_build_and_run(
        generated,
        tmp_path / "setjmp-aggregate",
        optimization="-O3",
    )


@pytest.mark.parametrize(
    "source",
    (
        """
        volatile int globalValue = 0;
        int* globalAlias = &globalValue;
        int main() { return *globalAlias; }
        """,
        """
        volatile int globalValues[1] = {0};
        void take(int* values) {}
        int main() { take(globalValues); return 0; }
        """,
        """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; } catch (string error) {}
            return value;
        }
        """,
        """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0; int* alias = &value;
            try { mutate(alias); throw "done"; } catch (string error) {}
            return value;
        }
        """,
        """
        void mutate(int* values) { values[0] = 1; }
        int main() {
            int values[1] = {0};
            try { mutate(values); throw "done"; } catch (string error) {}
            return values[0];
        }
        """,
        """
        int main() {
            int value = 0; int* alias = &value;
            try { value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        """,
        """
        void take(int* values) {}
        struct Probe { int values[2]; };
        int main() {
            struct Probe probe = {{0, 0}};
            try { probe.values[0] = 1; throw "done"; }
            catch (string error) {}
            take(probe.values);
            return 0;
        }
        """,
        """
        int main() {
            int values[1] = {0}; int* alias = values;
            try { values[0] = 1; throw "done"; } catch (string error) {}
            return alias[0];
        }
        """,
        """
        struct Probe { int value; };
        int main() {
            struct Probe probe = {0}; int* alias = &probe.value;
            try { probe.value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        """,
        """
        int run(int value) {
            int* alias = &value;
            try { value = 1; throw "done"; } catch (string error) {}
            return *alias;
        }
        int main() { return run(0); }
        """,
        """
        int main() {
            volatile int value = 0;
            volatile int* alias = &value;
            return alias[0];
        }
        """,
        """
        class Box<T> {
            public Box() {}
            public int run(int value) {
                int* alias = &value;
                try { value = 1; throw "done"; } catch (string error) {}
                return *alias;
            }
        }
        int main() { Box<int> box = new Box<int>(); return box.run(0); }
        """,
    ),
)
def test_selfhost_rejects_volatile_storage_aliases(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 1
    assert "unsupported layered pointer qualifiers" in result.stderr


def test_selfhost_emits_outer_volatile_pointer_global(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int value = 7;
        volatile int* pointer = &value;
        int main() { return *pointer == 7 ? 0 : 1; }
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    assert "int* volatile pointer = (&value);" in generated.read_text()
    _strict_build_and_run(
        generated,
        tmp_path / "volatile-pointer-global",
        optimization="-O3",
    )


def test_selfhost_accepts_shadowed_nonvolatile_alias(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            int value = 0;
            try { value = 1; throw "done"; } catch (string error) {}
            int size = sizeof(&value);
            {
                int value = 2;
                int* alias = &value;
                size = size + *alias;
            }
            return value == 1 && size > 2 ? 0 : 1;
        }
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    _strict_build_and_run(
        generated,
        tmp_path / "setjmp-shadowed-alias",
        optimization="-O3",
    )


def test_selfhost_static_shadow_blocks_outer_qualification(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int main() {
            int value = 0;
            {
                static int value = 0;
                try { value = 1; throw "done"; } catch (string error) {}
            }
            return value;
        }
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, source)

    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "volatile int value = 0;" not in emitted
    assert re.search(r"static int value(?:_\d+)? = 0;", emitted)
    _strict_build_and_run(
        generated,
        tmp_path / "setjmp-static-shadow",
        optimization="-O3",
    )
