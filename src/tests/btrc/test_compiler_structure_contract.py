"""Ownership and dependency contracts for the self-hosted compiler shell."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"


def _source(relative: str) -> str:
    return (SELFHOST / relative).read_text()


def test_process_entry_point_is_only_a_driver_adapter() -> None:
    entry = _source("btrcc_main.btrc")

    assert "import ./compiler.btrc;" in entry
    assert "#include" not in entry
    assert "BtrccDriver driver = BtrccDriver(argc, argv);" in entry
    assert "return driver.run();" in entry
    for pipeline_detail in (
        "FeFrontendResolver",
        "Lexer(",
        "Parser(",
        "analyzeProgram",
        "IRGen(",
        "CEmitter(",
    ):
        assert pipeline_detail not in entry


def test_stage_manifests_form_one_directed_dependency_chain() -> None:
    manifests = {
        "lexer": _source("lexer/stage.btrc"),
        "frontend": _source("frontend/stage.btrc"),
        "parser": _source("parser/stage.btrc"),
        "analyzer": _source("analyzer/stage.btrc"),
        "ir": _source("ir/stage.btrc"),
        "pipeline": _source("pipeline/stage.btrc"),
    }

    assert "import ../lexer/stage.btrc;" in manifests["frontend"]
    assert "import ../frontend/stage.btrc;" in manifests["parser"]
    assert "import ../parser/stage.btrc;" in manifests["analyzer"]
    assert "import ../analyzer/stage.btrc;" in manifests["ir"]
    assert "import ../ir/stage.btrc;" in manifests["pipeline"]

    for stage in manifests:
        assert "import std.*;" not in manifests[stage]
    assert "import ../ir/stage.btrc;" not in manifests["analyzer"]
    assert '#include "pipeline.btrc"' in manifests["pipeline"]


def test_selfhost_compiler_never_uses_implicit_stdlib_globs() -> None:
    wildcard_imports = [
        path.relative_to(SELFHOST) for path in SELFHOST.rglob("*.btrc") if "import std.*;" in path.read_text()
    ]

    assert wildcard_imports == []


def test_semantic_policies_do_not_reach_back_into_ir_owners() -> None:
    analyzer_stage = _source("analyzer/stage.btrc")
    raw_projection = _source("raw_projection_carriers.btrc")
    ir_projection = _source("ir_raw_projection_context.btrc")

    for policy in (
        "destructor_symbols.btrc",
        "generic_method_symbols.btrc",
        "string_method_semantics.btrc",
        "ownership_transfer_semantics.btrc",
        "mutex_type_semantics.btrc",
        "cycle_semantics.btrc",
        "gpu_builtin_semantics.btrc",
        "gpu_type_semantics.btrc",
    ):
        assert f'#include "../{policy}"' in analyzer_stage
    assert "IRGen" not in raw_projection
    assert "SemanticValidationState" not in ir_projection
    assert "class RawProjectionCarrierContext {" in raw_projection
    assert "class SemanticRawProjectionContextBuilder {" in raw_projection
    assert "class IRRawProjectionContextBuilder {" in ir_projection


def test_application_and_pipeline_have_real_instance_owners() -> None:
    compiler = _source("compiler.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    options = _source("driver_options.btrc")
    output = _source("driver_output.btrc")

    assert "class Compiler {" in compiler
    assert "private CompilerPipeline pipeline;" in compiler
    assert (
        "self.pipeline = CompilerPipeline(\n            grammar, stdlibDirectory, sourceFiles, resolutionPolicy);"
        in compiler
    )
    assert "class BtrccDriver {" in compiler
    assert "private FeSourceResolutionPolicy resolutionPolicy;" in compiler
    assert "private FeSourceFileReader sourceFiles;" in compiler
    assert "self.resolutionPolicy = FeSourceResolutionPolicy();" in compiler
    assert "self.sourceFiles = FeSourceFileReader(self.resolutionPolicy);" in compiler
    assert "self.sourceFiles.readRequired(dataPaths.grammar)" in compiler
    assert "self.sourceFiles.readRequired(sourcePath)" in compiler
    assert "class CompilerPipeline {" in pipeline
    assert "public BtrccCompilationResult compile(" in pipeline

    assert "class BtrccCommandLine {" in options
    assert "private Vector<string> arguments;" in options
    assert "BtrccDriverOptions" not in options
    assert "class string usage()" not in options
    assert "class BtrccOutput {" in output
    for loose_helper in (
        "bool driverWriteStdoutChunk(",
        "bool driverFlushStdout(",
        "bool printNoNL(",
        "bool printLineChecked(",
    ):
        assert loose_helper not in output


def test_frontend_scanning_and_recursive_resolution_are_instance_owned() -> None:
    frontend = _source("frontend.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    visibility = _source("import_visibility.btrc")
    frontend_main = _source("frontend_main.btrc")

    assert "class FeDirectiveScanner {" in frontend
    assert "private GrammarInfo grammar;" in frontend
    assert "public Vector<FeDirective> scan(string source)" in frontend
    assert "private void inlinePaths(" in frontend
    assert "private void resolveInto(" in frontend
    assert "self.dependencies = FeDependencyGraph();" in frontend

    for loose_behavior in (
        "feGrammarCache",
        "GrammarInfo feGrammar(",
        "feScanDirectives(",
        "feInlinePaths(",
        "feResolveTracedInto",
        "feResolveIncludes(",
        "feResolveFrontendSource(",
    ):
        assert loose_behavior not in frontend

    assert "self.grammar, self.stdlib," in pipeline
    assert "program, resolved, self.stdlibSymbols" in pipeline
    assert "Lexer lexer = Lexer(source, self.grammar);" in visibility
    assert "Parser parser = Parser(tokens, self.grammar);" in visibility
    assert "FeFrontendResolver resolver = FeFrontendResolver(" in frontend_main
    assert "resolver.resolve(src, path)" in frontend_main


def test_frontend_source_text_and_directory_policy_have_real_owners() -> None:
    frontend = _source("frontend.btrc")
    limits = _source("frontend_limits.btrc")
    source_io = _source("frontend_source_io.btrc")

    assert "class FeSourceText {" in frontend
    assert "private string content;" in frontend
    for text_operation in (
        "public Vector<string> lines()",
        "public int lineCount()",
        "public bool startsWithAt(",
        "class string joinLines(",
    ):
        assert text_operation in frontend

    assert "class FeSourceDirectoryScanner {" in frontend
    assert "private FeSourceResolutionPolicy policy;" in frontend
    assert "private void sort(Vector<string> entries)" in frontend
    assert "public Vector<string> sortedEntries(string path)" in frontend
    assert "public Vector<string> sortedEntriesWithinBudget(" in frontend
    assert "private FeSourceDirectoryScanner sourceDirectories;" in frontend
    assert frontend.count("FeSourceDirectoryScanner(resolutionPolicy)") == 2
    assert "stdlib, emptySnapshot, self.sourceDirectories" in frontend
    assert "self.stdlib, currentSnapshot, self.sourceDirectories" in frontend

    for obsolete_loose_behavior in (
        "feSplitLines(",
        "feJoinLines(",
        "feSortedListDir(",
        "feSortedListDirBudget(",
        "feRawStartsWith(",
    ):
        assert obsolete_loose_behavior not in frontend

    assert "class FeUtf8SourceDecoder {" in source_io
    assert "private bool continuation(" in source_io
    assert "private bool validAt(" in source_io
    assert "private int widthAt(" in source_io
    assert "public string decode(Bytes data, string path)" in source_io
    assert "class FeSourceFileReader {" in source_io
    assert "private FeSourceResolutionPolicy policy;" in source_io
    assert "private FeUtf8SourceDecoder decoder;" in source_io
    assert "public string readRequired(string path)" in source_io
    assert "FE_MAX_SOURCE_BYTES" not in source_io
    for obsolete_loose_behavior in (
        "feSourceReadError(",
        "feUtf8Continuation(",
        "feValidUtf8At(",
        "feUtf8Width(",
        "feDecodeSource(",
        "feReadRequiredSource(",
        "feReadRequiredDirectory(",
    ):
        assert obsolete_loose_behavior not in source_io

    assert "class FeSourceResolutionPolicy {" in limits
    for private_limit in (
        "private int maximumSourceBytes;",
        "private int maximumFiles;",
        "private int maximumDirectoryEntries;",
        "private int maximumImportDepth;",
    ):
        assert private_limit in limits
    for owned_operation in (
        "public FeResolutionBudget newResolutionBudget()",
        "public FeDirectoryScanBudget newDirectoryBudget(string root)",
        "public void validateCombinedSource(",
    ):
        assert owned_operation in limits
    assert "private FeSourceResolutionPolicy policy;" in limits
    assert "class FeResolutionBudget {" in limits
    assert "class FeDirectoryScanBudget {" in limits
    for obsolete_global in (
        "FE_MAX_RESOLVED_SOURCE_BYTES",
        "FE_MAX_RESOLVED_FILES",
        "FE_MAX_IMPORT_SCAN_ENTRIES",
        "FE_MAX_IMPORT_DEPTH",
        "feCheckCombinedSourceSize(",
    ):
        assert obsolete_global not in limits


def test_import_resolution_has_one_compilation_local_owner() -> None:
    frontend = _source("frontend.btrc")
    owner = frontend.split("class FeImportResolver {", 1)[1].split("/* ----- top-level entry:", 1)[0]

    assert "private FeStdlibRepository stdlib;" in owner
    assert "private FeStdlibRootSnapshot stdlibSnapshot;" in owner
    assert "private FeSourceDirectoryScanner sourceDirectories;" in owner
    assert "private FeSourceResolutionPolicy resolutionPolicy;" in owner
    for public_operation in (
        "public string resolveIncludePath(",
        "public Vector<string> resolveSpec(",
        "public string renderCInclude(",
    ):
        assert public_operation in owner
    assert owner.count("    public ") == 4  # constructor plus three operations
    for private_operation in (
        "private void collectTree(",
        "private void sortPaths(",
        "private Vector<string> resolveRelative(",
        "private bool validIdentifier(",
        "private bool packageImportSpec(",
        "private Vector<string> stdlibModuleNames(",
        "private void rejectInvalidSpec(",
        "private bool cTrigraphSuffix(",
    ):
        assert private_operation in owner

    for obsolete_loose_behavior in (
        "feResolveIncludePath(",
        "feWalkCollect(",
        "feSortPaths(",
        "feRelativeImportPaths(",
        "feImportIdentifier(",
        "fePackageImportSpec(",
        "feStdModuleNames(",
        "feInvalidImportSpec(",
        "feImportSpecPaths(",
        "feCTrigraphSuffix(",
        "feCIncludeDirective(",
    ):
        assert obsolete_loose_behavior not in frontend

    assert "private FeImportResolver importResolver;" in frontend
    assert "stdlib, emptySnapshot, self.sourceDirectories,\n            self.resolutionPolicy" in frontend
    assert "self.stdlib, currentSnapshot, self.sourceDirectories,\n            self.resolutionPolicy" in frontend
    assert "self.importResolver.resolveIncludePath(" in frontend
    assert "self.importResolver.resolveSpec(" in frontend
    assert "self.importResolver.renderCInclude(" in frontend


def test_stdlib_behavior_has_one_explicit_instance_owner() -> None:
    frontend = _source("frontend.btrc")
    compiler = _source("compiler.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    visibility = _source("import_visibility.btrc")

    assert "class FeStdlibRepository {" in frontend
    assert "class FeStdlibRootSnapshot {" in frontend
    assert "private Vector<string> paths;" in frontend
    assert "private Vector<string> sources;" in frontend
    assert "private string directoryPath;" in frontend
    assert "private FeDirectiveScanner directiveScanner;" in frontend
    assert "private FeSourceFileReader sourceFiles;" in frontend
    assert "private FeSourceResolutionPolicy resolutionPolicy;" in frontend
    assert "self.sourceFiles = sourceFiles;" in frontend
    assert "self.resolutionPolicy = resolutionPolicy;" in frontend
    for owned_behavior in (
        "public FeStdlibRootSnapshot rootSnapshot()",
        "public string findFileForCompilation(",
        "public FeStdlibLookup requiredModuleForCompilation(",
        "public Vector<string> rootPaths(",
        "public string readSourceForCompilation(",
        "public string sourceAtSnapshot(",
    ):
        assert owned_behavior in frontend
    assert "private Vector<string> discoverFiles()" in frontend
    assert "private Map<string, bool> definedTypeNames(" in frontend
    assert "public string findFile(string includePath)" not in frontend
    assert "public string source(string userSource)" not in frontend
    for leaked_index_lifecycle in (
        "beginSymbolIndex(",
        "indexSymbol(",
        "completeSymbolIndex(",
        "mergeSymbolFiles(",
        "hasSymbolIndex(",
    ):
        assert leaked_index_lifecycle not in frontend

    for loose_behavior in (
        "feConfiguredGrammarPath",
        "feConfiguredStdlibDirectory",
        "feConfigureDataPaths(",
        "feGrammarPath(",
        "feStdlibDir(",
        "feDiscoverStdlibFiles(",
        "feFindStdlibFile(",
        "feStdlibModulePath(",
        "feRequiredStdlibModulePath(",
        "feStdlibGlobPaths(",
        "feStdlibFileSource(",
        "feGetStdlibSource(",
        "feDefinedNames(",
    ):
        assert loose_behavior not in frontend

    assert not (SELFHOST / "frontend_data_paths.btrc").exists()
    assert "feConfigureDataPaths" not in compiler
    assert "private FeStdlibRepository stdlib;" in pipeline
    assert "FeStdlibRepository(\n            stdlibDirectory, grammar, sourceFiles, resolutionPolicy)" in pipeline
    assert "private FeStdlibSymbolIndex stdlibSymbols;" in pipeline
    assert "FeStdlibSymbolIndex(grammar)" in pipeline
    assert pipeline.count("FeStdlibSymbolIndex(") == 1
    compile_body = pipeline.split("public BtrccCompilationResult compile(", 1)[1]
    assert "FeStdlibSymbolIndex(" not in compile_body
    assert "program, resolved, self.stdlibSymbols" in pipeline
    assert "class FeStdlibSymbolIndex {" in visibility
    assert "Map<string, Vector<string>> nextSymbolFiles = {};" in visibility
    assert "self.symbolFiles = nextSymbolFiles;" in visibility
    assert "self.indexedSnapshot = snapshot;" in visibility
    assert "self.resolved.stdlibSnapshot" in visibility
    assert "public FeStdlibSymbolIndexResult mergeSnapshotInto(" in visibility
    assert "self.stdlibSymbols.mergeSnapshotInto(" in visibility


def test_strict_imports_are_the_application_default() -> None:
    models = _source("pipeline/models.btrc")
    options = _source("driver_options.btrc")
    frontend_main = _source("frontend_main.btrc")

    assert "self.strictImports = true;" in models
    assert 'option.equals("--relaxed-imports")' in options
    assert "options.strictImports = false;" in options
    assert "bool strictImports = true;" in frontend_main
    assert 'option.equals("--relaxed-imports")' in frontend_main
    assert "strictImports = false;" in frontend_main
