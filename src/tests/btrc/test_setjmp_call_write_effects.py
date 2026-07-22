"""Mirrored setjmp call-write summaries for both compiler fronts."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_both(
    compiler: Path,
    tmp_path: Path,
    source: str,
):
    selfhost = _compile_source(compiler, tmp_path, source)
    reference = _compile_reference_source(tmp_path, source)
    return selfhost, reference


def test_read_only_source_calls_do_not_qualify_addressed_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        struct Probe { int value; };
        int readValue(int* value) { return *value; }
        int readProbe(struct Probe* probe) {
            return readValue(&probe->value);
        }
        int relayRead(struct Probe* probe) { return readProbe(probe); }
        int run(struct Probe probe) {
            int result = 0;
            int* alias = &probe.value;
            try {
                result = relayRead(&probe) + readValue(alias);
                throw "done";
            } catch (string message) {}
            return result;
        }
        int main() {
            struct Probe probe = {21};
            return run(probe) == 42 ? 0 : 1;
        }
    """

    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        emitted = generated.read_text()
        assert "int run(struct Probe probe)" in emitted
        assert "volatile struct Probe" not in emitted
        _strict_build_and_run(
            generated,
            tmp_path / f"read-only-call-{index}",
            optimization="-O3",
        )


def test_const_pointee_typedef_source_body_is_read_only(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        typedef const int* ReadOnlyBase;
        typedef const ReadOnlyBase ReadOnly;
        int observe(ReadOnly value) { return *value; }
        int run(int value) {
            int result = 0;
            try {
                result = observe(&value);
                throw "done";
            } catch (string message) {}
            return result;
        }
        int main() { return run(0); }
    """

    for result, generated in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 0, result.stderr
        assert "int run(int value)" in generated.read_text()


@pytest.mark.parametrize(
    "source, diagnostic",
    (
        (
            """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "unsupported layered pointer qualifiers",
        ),
        (
            """
        void mutate(int* value) { *value = 1; }
        int main() {
            int value = 0; int* alias = &value;
            try { mutate(alias); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "unsupported layered pointer qualifiers",
        ),
        (
            """
        void mutate(int* values) { values[0] = 1; }
        int main() {
            int values[1] = {0};
            try { mutate(values); throw "done"; }
            catch (string error) {}
            return values[0];
        }
        """,
            "unsupported layered pointer qualifiers",
        ),
        (
            """
        void mutate(int* value) { *value = 1; }
        void relay(int* value) { mutate(value); }
        int main() {
            int value = 0;
            try { relay(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "unsupported layered pointer qualifiers",
        ),
        (
            """
        typedef int* Mutable;
        void mutate(Mutable value) { *value = 1; }
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "unsupported layered pointer qualifiers",
        ),
        (
            """
        typedef int* Mutable;
        extern void mutate(const Mutable value);
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "escapes into unmodelled storage",
        ),
        (
            """
        typedef int* Mutable;
        typedef const Mutable QualifiedMutable;
        extern void mutate(QualifiedMutable value);
        int main() {
            int value = 0;
            try { mutate(&value); throw "done"; }
            catch (string error) {}
            return value;
        }
        """,
            "escapes into unmodelled storage",
        ),
    ),
)
def test_pointer_writes_still_reject_layered_qualification(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert diagnostic in result.stderr


def test_void_pointer_cast_widening_preserves_nested_write(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        void mutate_widened(void* raw) { **(int**)raw = 7; }
        int main() {
            int value = 0; int* pointer = &value;
            try { mutate_widened(&pointer); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert "unmodelled pointer value" in result.stderr


def test_partial_dereference_cast_uses_remaining_depth(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        void mutate_widened(void*** raw) { ***(int***)*raw = 7; }
        int main() {
            int value = 0; int* p1 = &value; int** p2 = &p1;
            void** bridge = (void**)&p2;
            try { mutate_widened(&bridge); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert "unmodelled pointer value" in result.stderr


def test_pointer_to_scalar_representation_loss_fails_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        void mutate(intptr_t bits) {
            int* pointer = (int*)bits;
            *pointer = 7;
        }
        int main() {
            int value = 0;
            try { mutate((intptr_t)(&value)); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert "escapes into unmodelled storage" in result.stderr


@pytest.mark.parametrize(
    "carrier",
    (
        "(intptr_t)(&value)",
        "((((intptr_t)(&value)) ^ (intptr_t)7) ^ (intptr_t)7)",
        "labs((intptr_t)(&value))",
    ),
)
def test_custom_extern_scalar_argument_is_conservative(
    semantic_btrcc: Path,
    tmp_path: Path,
    carrier: str,
) -> None:
    source = f"""
        void sneaky(intptr_t bits);
        int main() {{
            int value = 0;
            try {{ sneaky({carrier}); throw "boom"; }}
            catch (string error) {{}}
            return value;
        }}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert "escapes into unmodelled storage" in result.stderr


def test_scalar_return_chain_cannot_launder_an_address(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        intptr_t encode(int* pointer) { return (intptr_t)pointer; }
        intptr_t forward(intptr_t bits) { return bits; }
        void mutate(intptr_t bits) { int* pointer = (int*)bits; *pointer = 7; }
        int main() {
            int value = 0;
            try { mutate(forward(encode(&value))); throw "boom"; }
            catch (string error) {}
            return value;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 1
        assert "escapes into unmodelled storage" in result.stderr


def test_typedef_void_cast_is_a_non_capturing_discard(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        typedef void Nothing;
        typedef const Nothing QualifiedNothing;
        int main() {
            int value = 0; int* pointer = &value;
            (QualifiedNothing)pointer;
            try { throw "boom"; } catch (string error) {}
            return value;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        _strict_build_and_run(generated, tmp_path / f"void-alias-{index}")
