"""Application-object and public stage API contracts."""

from src.compiler.python import Compiler, CompilerOptions, CompilerResult
from src.compiler.python.pipeline.models import CompilerOutput
from src.compiler.python.pipeline.pipeline import CompilerPipeline

SOURCE = "int main() { return 0; }\n"


class MemoryCache:
    def __init__(self) -> None:
        self.value = None
        self.loads = 0
        self.stores = 0

    def load(self, source, input_path):
        self.loads += 1
        return self.value

    def store(self, source, input_path, c_source):
        self.stores += 1
        self.value = c_source


def test_public_compiler_defaults_to_strict_imports_and_emits_c(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)

    result = Compiler().compile(
        SOURCE,
        str(source_path),
        CompilerOptions(include_stdlib=False, use_cache=False),
    )

    assert isinstance(result, CompilerResult)
    assert result.options.strict_imports
    assert result.successful
    assert result.program is not None
    assert result.analyzed is not None
    assert result.ir_module is not None
    assert result.c_source is not None
    assert "int main(void)" in result.c_source


def test_pipeline_exposes_each_terminal_representation(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)
    compiler = Compiler(CompilerPipeline())

    tokens = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.TOKENS,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    ast = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.AST,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    ir = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.IR,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    optimized = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.OPTIMIZED_IR,
            include_stdlib=False,
            use_cache=False,
        ),
    )

    assert tokens.tokens and tokens.program is None
    assert ast.program is not None and ast.analyzed is None
    assert ir.ir_module is not None and ir.c_source is None
    assert optimized.ir_module is not None and optimized.c_source is None


def test_compiler_uses_injected_cache_without_reentering_pipeline(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)
    cache = MemoryCache()
    compiler = Compiler(cache=cache)
    options = CompilerOptions(include_stdlib=False)

    first = compiler.compile(SOURCE, str(source_path), options)
    second = compiler.compile(SOURCE, str(source_path), options)

    assert first.successful and not first.cache_hit
    assert second.successful and second.cache_hit
    assert second.program is None
    assert second.c_source == first.c_source
    assert cache.loads == 2
    assert cache.stores == 1


def test_analyzer_failure_stops_before_ir_lowering(tmp_path):
    source = 'int main() { int value = "wrong"; return value; }\n'
    source_path = tmp_path / "bad.btrc"
    source_path.write_text(source)

    result = Compiler().compile(
        source,
        str(source_path),
        CompilerOptions(include_stdlib=False, use_cache=False),
    )

    assert not result.successful
    assert result.analyzed is not None and result.analyzed.errors
    assert result.ir_module is None
    assert result.c_source is None
