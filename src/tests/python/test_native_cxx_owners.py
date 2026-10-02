"""C++ SDK owners project as opaque unique documents, owner-bound views and copied strings.

Every SDK call crosses one generated extern "C" adapter that catches C++
exceptions; the strict C module never sees a C++ object. The real pugixml
SDK proves the contract, so the module skips when pkg-config cannot find it.
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.pugixml_fixtures import PROGRAM
from src.tests.python.pugixml_fixtures import pugixml_project as pugixml_project
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder


def build_native_program(native_compile, source, sanitize, *, object_cache=None):
    root = source.parent.parent
    plan = root / "Main.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    assert "__btrc_cxx_PugiDocument_load_buffer" in result.c_source
    # Only adapter names and diagnostics mention the SDK; no C++ type reaches C.
    assert "pugi::xml_document*" not in result.c_source and "pugi::xml_node " not in result.c_source
    generated = root / "Main.c"
    generated.write_text(result.c_source, encoding="utf-8")
    environment = apple_environment()
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []

    def run_command(command, **kwargs):
        # Sanitizer flags belong to the compiler and linker steps, not pkg-config.
        extra = flags if command[0].endswith(("clang", "clang++")) else []
        return subprocess.run(
            [command[0], *extra, *command[1:]],
            env=apple_environment(kwargs.pop("env", environment)),
            timeout=BTRC_TRANSPILE_TIMEOUT,
            **kwargs,
        )

    executable = root / "Main"
    builder = NativePlanBuilder(runner=run_command)
    options = dict(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        pkg_config="pkg-config",
        optimization=1 if sanitize else 2,
        object_cache=object_cache,
    )
    cold = builder.build(**options)
    if object_cache is not None:
        assert cold.adapter_units > 0 and cold.adapter_source_status == "retained"
        assert cold.link_cache_status == "stored" and cold.links == 2
        warm = builder.build(**options)
        assert warm.as_dict()["compiled_units"] == 0
        assert warm.link_cache_status == "hit" and warm.links == 0
        assert warm.as_dict()["reused_units"] == len(warm.units)
    return executable, environment


@pytest.mark.parametrize("sanitize", [False, True])
def test_cxx_owner_views_and_copied_strings(pugixml_project, native_compile, sanitize):
    source, _sdk, _triple = pugixml_project
    executable, environment = build_native_program(native_compile, source, sanitize)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)


def test_cxx_generated_adapter_object_cache(pugixml_project, native_compile):
    source, _sdk, _triple = pugixml_project
    executable, environment = build_native_program(
        native_compile, source, False, object_cache=source.parent.parent / "objects"
    )
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)


@pytest.mark.parametrize(
    "use",
    [
        "PugiNode root = document.document_element(); document.close(); root.name();",
        "PugiNode root = document.document_element(); PugiAttribute version = root.first_attribute(); document.close(); version.value();",
    ],
)
def test_cxx_view_use_after_owner_close_aborts(pugixml_project, native_compile, use):
    source, _sdk, _triple = pugixml_project
    source.write_text(
        PROGRAM
        + f"""
int main() {{
    PugiParseOutcome outcome = parse("<song version=\\"7\\"/>");
    assert(outcome.called && outcome.value != null);
    PugiDocument document = outcome.value;
    {use}
    return 0;
}}
""",
        encoding="utf-8",
    )
    executable, environment = build_native_program(native_compile, source, False)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode < 0, (ran.returncode, ran.stdout, ran.stderr)
    assert "Native resource pugi::xml_document: use after close" in ran.stderr


@pytest.mark.parametrize(
    "before, after, message",
    [
        ('read-only-borrows = ["pugi::xml_document::load_buffer.contents"]\n', "", "explicit read-only byte borrows"),
        (
            '[native.bindings.copied-results."pugi::xml_node::name"]\nkind = "string"\nowner = "self"\n',
            "",
            "receiver-owned string copying",
        ),
        ('success = "pugi::status_ok"', 'success = "pugi::node_element"', "exactly the SDK status field enum"),
        (
            '"first_child", "next_sibling()", "first_attribute"]',
            '"first_child", "next_sibling()", "first_attribute", "remove_attributes"]',
            "only const traversal methods",
        ),
        (
            'methods = ["document_element", "first_child"]\n',
            'methods = ["document_element", "first_child"]\n\n[native.bindings.resources."pugi::xml_parse_result"]\nname = "PugiParseResult"\nownership = "unique"\nconstructor = "default"\nrelease = "delete"\nmethods = ["description"]\n',
            "one checked initialization factory",
        ),
    ],
)
def test_cxx_projection_rejects_incomplete_facts(pugixml_project, native_compile, before, after, message):
    source, _sdk, _triple = pugixml_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text(encoding="utf-8")
    assert before in text
    manifest.write_text(text.replace(before, after), encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + "".join(item.message for item in result.diagnostics)


def test_cxx_artifact_cache_restores_generated_adapters(pugixml_project, monkeypatch):
    from src.compiler.python import Compiler, CompilerOptions
    from src.compiler.python.artifacts.cache import CompilerCache

    source, _sdk, _triple = pugixml_project
    monkeypatch.setenv("BTRC_CACHE_DIR", str(source.parent.parent / "compiler-cache"))
    compiler = Compiler(cache=CompilerCache())
    options = CompilerOptions(include_stdlib=False)

    def compile_cached(source, *, plan_path):
        first = compiler.compile(source.read_text(), str(source), options)
        assert first.successful and not first.cache_hit, first.failure
        assert first.native_plan.generated_units
        warm = compiler.compile(source.read_text(), str(source), options)
        assert warm.successful and warm.cache_hit, warm.failure
        assert warm.c_source == first.c_source
        assert warm.native_plan == first.native_plan
        plan_path.write_text(warm.native_plan.canonical_json())
        return warm

    executable, environment = build_native_program(compile_cached, source, False)
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
