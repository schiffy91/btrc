"""Extended strict-C raw-carrier and hosted-alias contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _hosted_alias_source(*, generic: bool) -> str:
    harness = "Harness<T>" if generic else "Harness"
    instantiation = "Harness<int>" if generic else "Harness"
    return f"""
        #include <assert.h>
        #include <stdlib.h>
        #include <string.h>

        void inspect(char* value, bool replaced) {{
            assert(replaced);
            assert(value[0] == 'b');
        }}
        void inspectVoid(void* value, bool replaced) {{
            assert(replaced);
            assert(((char*)value)[0] == 'b');
        }}

        class Buffer {{
            public char data[3];
            public int length;
            public Buffer(char middle) {{
                self.data[0] = 'a';
                self.data[1] = middle;
                self.data[2] = 'c';
                self.length = 3;
            }}
        }}

        class {harness} {{
            public string value;
            public Buffer buffer;
            public Harness() {{
                self.value = strdup("abc");
                self.buffer = new Buffer('b');
            }}
            public bool replace() {{
                self.value = strdup("xyz");
                return true;
            }}
            public bool replaceBuffer() {{
                self.buffer = new Buffer('x');
                return true;
            }}
            public void run() {{
                inspect(strchr(strchr(self.value, 'a'), 'b'), self.replace());
                inspectVoid(memchr(self.buffer.data, 'b',
                    (size_t)self.buffer.length),
                    self.replaceBuffer());
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
def test_hosted_return_alias_pins_managed_backing(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    source = _hosted_alias_source(generic=generic)
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
            tmp_path / f"hosted-return-alias-{index}-san",
            toolchain,
        )


def _nonportable_cast_source(
    integer_type: str,
    *,
    reverse: bool,
    generic: bool,
) -> str:
    cast = (
        f"{integer_type} bits = ({integer_type})values;"
        if not reverse
        else f"{integer_type} bits = 0; int* pointer = (int*)bits;"
    )
    use = "(void)bits;" if not reverse else "(void)pointer;"
    harness = "Harness<T>" if generic else "Harness"
    instantiation = "Harness<int>" if generic else "Harness"
    return f"""
        class {harness} {{
            public void run() {{
                int values[1];
                {cast}
                {use}
            }}
        }}
        int main() {{
            {instantiation} harness = new {instantiation}();
            harness.run();
            delete harness;
            return 0;
        }}
    """


@pytest.mark.parametrize("integer_type", ["int", "uint", "long"])
@pytest.mark.parametrize("reverse", [False, True], ids=["from-pointer", "to-pointer"])
@pytest.mark.parametrize("generic", [False, True], ids=["normal", "generic"])
def test_nonportable_pointer_integer_casts_are_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
    integer_type: str,
    reverse: bool,
    generic: bool,
) -> None:
    source = _nonportable_cast_source(
        integer_type,
        reverse=reverse,
        generic=generic,
    )
    self_dir = tmp_path / "selfhost"
    reference_dir = tmp_path / "reference"
    self_dir.mkdir()
    reference_dir.mkdir()
    selfhost, _ = _compile_source(semantic_btrcc, self_dir, source)
    reference, _ = _compile_reference_source(reference_dir, source)
    message = "Pointer/integer casts require intptr_t or uintptr_t"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert message in selfhost.stderr
    assert message in reference.stderr
