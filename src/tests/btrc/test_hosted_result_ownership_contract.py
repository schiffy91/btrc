"""Hosted pointer results cross managed boundaries without leaks or UAF."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair, run_strict_pair
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_semantic_validation import REPO

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "hosted_result_ownership_runtime.btrc"
GETCWD_FIXTURE = Path(__file__).with_name("fixtures") / "hosted_getcwd_fresh_runtime.btrc"
GETCWD_SHIM = Path(__file__).with_name("fixtures") / "hosted_getcwd_alloc_shim.c"

HOSTED_SHADOW_PROBE = """
    #include <string.h>

    string hostedFreshCopy(string value) {
        return strdup(value);
    }

    class HostedFreshCopyBox<T> {
        public HostedFreshCopyBox() {}

        public string copy(string value) {
            return strdup(value);
        }
    }
"""

HOSTED_SHADOW_USER = """
    import std.hosted_result_probe;

    #include <string.h>

    char* strdup(string value) {
        (void)value;
        return (char*)"source-shadow";
    }

    int main() {
        size_t baseline = __btrc_string_live_count();
        {
            string ordinary = hostedFreshCopy("ordinary");
            HostedFreshCopyBox<int> box = new HostedFreshCopyBox<int>();
            string generic = box.copy("generic");
            char* source = strdup("ignored");
            bool valid = strcmp(ordinary, "ordinary") == 0
                && strcmp(generic, "generic") == 0
                && strcmp(source, "source-shadow") == 0;
            delete box;
            if (!valid) { return 1; }
        }
        return __btrc_string_live_count() == baseline ? 0 : 2;
    }
"""


def _compile_hosted_shadow_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> tuple[tuple[str, Path], tuple[str, Path]]:
    data_root = tmp_path / "hosted-result-data"
    language = data_root / "language"
    stdlib = data_root / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for source in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(source, stdlib / source.name)

    program = tmp_path / "hosted-result-shadow.btrc"
    (stdlib / "hosted_result_probe.btrc").write_text(f"import {json.dumps(str(program))};\n{HOSTED_SHADOW_PROBE}")
    program.write_text(HOSTED_SHADOW_USER)
    environment = {
        **os.environ,
        "BTRC_HOME": str(data_root),
        "BTRC_CACHE_DIR": str(tmp_path / "hosted-result-cache"),
    }
    selfhost_c = tmp_path / "hosted-result-shadow.selfhost.c"
    selfhost = subprocess.run(
        [str(semantic_btrcc), str(program)],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_c.write_text(selfhost.stdout)

    pipeline = CompilationPipeline(
        frontend=FrontendStage(
            StdlibRepository(directory=str(stdlib)),
        )
    )
    options = CompilerOptions(
        include_stdlib=True,
        map_stdlib_positions=True,
        use_ast_cache=False,
    )
    resolved = pipeline.resolve(
        HOSTED_SHADOW_USER,
        str(program),
        options,
    )
    parsed = pipeline.parse(resolved, program.name, options)
    analyzed = pipeline.analyze(parsed.program)
    assert not analyzed.errors, analyzed.errors
    reference_c = tmp_path / "hosted-result-shadow.reference.c"
    # Stage 5 is finalized by the pipeline: optimizing in place and emitting
    # directly would skip runtime materialization and the IR verifier.
    lowered = IRLowerer(
        analyzed,
        debug=False,
        source_file=program.name,
    ).lower()
    reference_c.write_text(pipeline.emit(pipeline.optimize(lowered, options)))
    return ("selfhost", selfhost_c), ("reference", reference_c)


def test_non_free_managed_helper_raw_result_is_rejected_by_both_analyzers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <string.h>
        int main() {
            string value = (char*)__btrc_str_track(strdup("owned"));
            return value == null ? 0 : 0;
        }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "ownership is not proven" in result.stderr


def test_hosted_results_are_converted_inside_operand_lifetime_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURE.read_text(),
        "hosted-result-ownership",
        include_stdlib=False,
    )
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert "__btrc_str_track(strdup" in source
        assert "__btrc_strdup" in source
    run_strict_pair(compiled, tmp_path)
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-hosted-result-san",
            toolchain,
        )


@pytest.mark.skipif(os.name == "nt", reason="getcwd(NULL, 0) is a POSIX ABI")
def test_getcwd_null_result_is_adopted_without_leaking_original_allocation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        GETCWD_FIXTURE.read_text(),
        "hosted-getcwd-fresh",
        include_stdlib=False,
    )
    for artifact in compiled:
        generated = artifact[1].read_text()
        assert "__btrc_str_track(getcwd" in generated
        assert "__btrc_strdup(getcwd" not in generated
        _tracked_strict_matrix(
            artifact,
            tmp_path,
            extra_compile_args=("-Dgetcwd=btrc_test_getcwd",),
            extra_sources=(GETCWD_SHIM,),
        )


def test_hosted_result_identity_precedes_bodyful_source_shadow_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_hosted_shadow_pair(semantic_btrcc, tmp_path)
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert source.count("__btrc_str_track(strdup") >= 2
        assert "__btrc_source_strdup" in source
    run_strict_pair(compiled, tmp_path)
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in compiled:
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-hosted-shadow-san",
            toolchain,
        )
