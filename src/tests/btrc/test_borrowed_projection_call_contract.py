"""Owned projection receivers remain alive through ordinary calls."""

from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _source(*, generic: bool) -> str:
    invocation = "Harness<int> harness = new Harness<int>(); harness.run(); delete harness;" if generic else "run();"
    harness = (
        "class Harness<T> { public void run() { consume((new Holder()).values); } }"
        if generic
        else "void run() { consume((new Holder()).values); }"
    )
    return (
        "#include <assert.h>\n"
        "int drops = 0; "
        "class Holder { public int values[1]; "
        "public Holder() { self.values[0] = 7; } "
        "public void __del__() { drops += 1; } } "
        "void consume(int[] values) { "
        "assert(drops == 0); assert(values[0] == 7); } "
        f"{harness} int main() {{ {invocation} "
        "assert(drops == 1); return 0; }"
    )


def _borrowed_backing_source(*, generic: bool) -> str:
    harness = "Harness<T>" if generic else "Harness"
    instantiation = "Harness<int>" if generic else "Harness"
    return f"""
        #include <assert.h>
        int drops = 0;

        class Owner {{
            public int values[1];
            public Owner(int value) {{ self.values[0] = value; }}
            public void __del__() {{ drops += 1; }}
        }}

        void consume(int[] values, bool replaced) {{
            assert(replaced);
            assert(drops == 0);
            assert(values[0] == 7);
        }}

        class {harness} {{
            public Owner owner;
            public Harness() {{ self.owner = new Owner(7); }}
            public bool replace() {{
                self.owner = new Owner(99);
                return true;
            }}
            public void run() {{
                consume(self.owner.values, self.replace());
                assert(drops == 1);
                assert(self.owner.values[0] == 99);
            }}
        }}

        int main() {{
            {instantiation} harness = new {instantiation}();
            harness.run();
            delete harness;
            assert(drops == 2);
            return 0;
        }}
    """


def _raw_carrier_source(*, generic: bool, conditional: bool = False) -> str:
    harness = "Harness<T>" if generic else "Harness"
    instantiation = "Harness<int>" if generic else "Harness"
    cases = (
        "inspect(true ? (int*)self.owner.values : (int*)self.owner.values, self.replace(), 7, before);"
        if conditional
        else """
            inspect((int*)self.owner.values, self.replace(), 7, before);
            before = drops;
            inspect(&(self.owner.scalar), self.replace(), 109, before);
            before = drops;
            inspect(&(self.owner.values[0]), self.replace(), 99, before);
            before = drops;
            inspect(self.owner.values + 0, self.replace(), 99, before);
            before = drops;
            inspect((int*)(&(self.owner.values[0])), self.replace(), 99, before);
            before = drops;
            inspect(&(*((int*)self.owner.values)), self.replace(), 99, before);
            before = drops;
            inspect(&(((int*)self.owner.values)[0]), self.replace(), 99, before);
            before = drops;
            inspectSigned((intptr_t)self.owner.values, self.replace(), 99, before);
            before = drops;
            inspectUnsigned(
                (uintptr_t)(((int*)(&(self.owner.values[0]))) + 0),
                self.replace(), 99, before);
        """
    )
    final_assertion = "" if conditional else "assert(drops == before + 1);"
    return f"""
        #include <assert.h>
        #include <stdint.h>
        int drops = 0;

        class Owner {{
            public int values[2];
            public int scalar;
            public Owner(int value) {{
                self.values[0] = value;
                self.values[1] = value + 1;
                self.scalar = value + 10;
            }}
            public void __del__() {{ drops += 1; }}
        }}

        void inspect(int* value, bool replaced, int expected, int before) {{
            assert(replaced);
            assert(drops == before);
            assert(value[0] == expected);
        }}

        void inspectSigned(intptr_t address, bool replaced, int expected,
                int before) {{
            assert(replaced);
            assert(drops == before);
            assert(((int*)address)[0] == expected);
        }}

        void inspectUnsigned(uintptr_t address, bool replaced, int expected,
                int before) {{
            assert(replaced);
            assert(drops == before);
            assert(((int*)address)[0] == expected);
        }}

        class {harness} {{
            public Owner owner;
            public Harness() {{ self.owner = new Owner(7); }}
            public bool replace() {{
                self.owner = new Owner(99);
                return true;
            }}
            public void run() {{
                int before = drops;
                {cases}
                {final_assertion}
            }}
        }}

        int main() {{
            {instantiation} harness = new {instantiation}();
            harness.run();
            delete harness;
            return 0;
        }}
    """


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_borrowed_projection_owner_outlives_ordinary_call(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    source = _source(generic=generic)
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for index, generated in enumerate((selfhost_c, reference_c)):
        _strict_build_and_run(
            generated,
            tmp_path / f"borrowed-projection-call-{index}",
        )


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_borrowed_projection_backing_survives_later_call_operand(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    source = _borrowed_backing_source(generic=generic)
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    toolchain = require_sanitizers(tmp_path)
    for index, generated in enumerate((selfhost_c, reference_c)):
        sanitized_build_and_run(
            generated,
            tmp_path / f"borrowed-projection-backing-{index}-san",
            toolchain,
        )


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_raw_projection_carriers_pin_backing_across_later_operands(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    source = _raw_carrier_source(generic=generic)
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    toolchain = require_sanitizers(tmp_path)
    for index, generated in enumerate((selfhost_c, reference_c)):
        sanitized_build_and_run(
            generated,
            tmp_path / f"raw-projection-carriers-{index}-san",
            toolchain,
        )


def test_readonly_hosted_projection_does_not_overpin(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <string.h>
        bool matchesAt(string text, int offset) {
            return strncmp((char*)text + offset, "x", 1) == 0;
        }
        int main() { return matchesAt("ax", 1) ? 0 : 1; }
    """
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, selfhost_c = _compile_source(semantic_btrcc, self_dir, source)
    reference, reference_c = _compile_reference_source(reference_dir, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for index, generated in enumerate((selfhost_c, reference_c)):
        emitted = generated.read_text()
        start = emitted.rindex("bool matchesAt(")
        end = emitted.index("\n}", start)
        body = emitted[start:end]
        assert 'strncmp((((char*)text) + offset), "x", 1)' in body
        assert "__btrc_kept_operand" not in body
        assert "__btrc_string_release" not in body
        _strict_build_and_run(
            generated,
            tmp_path / f"readonly-hosted-projection-{index}",
        )


@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_conditional_raw_projection_requires_branch_local_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    source = _raw_carrier_source(generic=generic, conditional=True)
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, _ = _compile_source(semantic_btrcc, self_dir, source)
    reference, _ = _compile_reference_source(reference_dir, source)
    message = "Conditional raw projection call arguments require branch-local backing storage"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert message in selfhost.stderr
    assert message in reference.stderr
