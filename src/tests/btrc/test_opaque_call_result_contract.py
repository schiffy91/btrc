"""Native C result typing across ordered call boundaries."""

from __future__ import annotations

import re
from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_success_pair(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_c, reference_c


def test_fchmod_exact_abi_types_ordered_nonvolatile_result_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <sys/stat.h>
        #include <unistd.h>

        int trace = 0;
        int descriptorValue(int expected) {
            assert(trace == expected);
            trace++;
            return -1;
        }
        int modeValue(int expected, int mode) {
            assert(trace == expected);
            trace++;
            return mode;
        }

        int main() {
            bool rejected = fchmod(
                descriptorValue(0), modeValue(1, 384)) == -1;
            assert(trace == 2);
            assert(rejected);
            return 0;
        }
    """
    result = re.compile(r"\bint __btrc_(?:call|boundary)_result_\d+;")
    volatile_result = re.compile(r"\bvolatile int __btrc_(?:call|boundary)_result_\d+;")
    for index, generated in enumerate(_compile_success_pair(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert result.search(emitted)
        assert not volatile_result.search(emitted)
        _strict_build_and_run(generated, tmp_path / f"exact-fchmod-{index}")


def test_fchmod_result_is_volatile_across_exception_cleanup_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <sys/stat.h>
        #include <unistd.h>

        int trace = 0;
        int descriptorValue(int expected) {
            assert(trace == expected);
            trace++;
            return -1;
        }
        int modeValue(int expected, int mode) {
            assert(trace == expected);
            trace++;
            return mode;
        }

        int main() {
            try {
                bool rejected = fchmod(
                    descriptorValue(0), modeValue(1, 384)) == -1;
                assert(trace == 2);
                assert(rejected);
            } catch (string error) {
                assert(false);
            }
            return 0;
        }
    """
    result = re.compile(r"\bvolatile int __btrc_(?:call|boundary)_result_\d+;")
    for index, generated in enumerate(_compile_success_pair(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert result.search(emitted)
        _strict_build_and_run(generated, tmp_path / f"protected-fchmod-{index}")


def test_opaque_wide_result_keeps_native_c_type_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <time.h>

        int trace = 0;
        time_t timestamp(int expected, int value) {
            assert(trace == expected);
            trace++;
            return (time_t)value;
        }

        int main() {
            double elapsed = difftime(timestamp(0, 9), timestamp(1, 2));
            assert(trace == 2);
            assert(elapsed == 7.0);
            return 0;
        }
    """
    invented_result = re.compile(r"\b__btrc_(?:call|boundary)_result_\d+\b")
    for index, generated in enumerate(_compile_success_pair(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "double elapsed =" in emitted
        assert "difftime(" in emitted
        assert not invented_result.search(emitted)
        _strict_build_and_run(generated, tmp_path / f"opaque-wide-result-{index}")


def test_builtin_print_owned_argument_has_typed_void_result_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        string ownedText() {
            return "owned" + " value";
        }

        int main() {
            print(ownedText());
            return 0;
        }
    """
    for index, generated in enumerate(_compile_success_pair(semantic_btrcc, tmp_path, source)):
        _strict_build_and_run(generated, tmp_path / f"typed-print-result-{index}")


def test_opaque_result_cleanup_reports_call_site_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    header = tmp_path / "opaque_result_api.h"
    header.write_text(
        "#include <string.h>\nstatic inline int opaque_result(const char *value) {\n    return (int)strlen(value);\n}\n"
    )
    source = f"""#include \"{header.as_posix()}\"

string ownedText() {{
    return "owned" + " value";
}}

int main() {{
    bool result = (int)opaque_result(ownedText()) == 11;
    return result ? 0 : 1;
}}
"""
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    diagnostic = (
        "opaque C call result at 8:24 cannot cross an ownership cleanup boundary; "
        "provide a typed declaration or exact hosted ABI contract"
    )
    for result in (selfhost, reference):
        assert result.returncode == 1
        assert result.stdout == ""
        assert diagnostic in result.stderr
        assert "cast it explicitly" not in result.stderr
