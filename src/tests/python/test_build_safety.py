"""Static regression coverage for destructive and stale build behavior."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
DEVCONTAINER_CONFIG = REPO_ROOT / "build"


def _make_dry_run(*args: str) -> str:
    result = subprocess.run(
        ["make", "--dry-run", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_help_lists_targets_whose_names_contain_digits():
    result = subprocess.run(
        ["make", "help"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "test-c11" in result.stdout
    assert "btrcc-linux-x64" in result.stdout


def test_all_does_not_install_extension_or_build_devcontainer():
    makefile = MAKEFILE.read_text()
    all_rule = next(line for line in makefile.splitlines() if line.startswith("all:"))

    assert "extension-install" not in all_rule
    assert "devcontainer" not in all_rule


def test_default_pytest_parallelism_is_bounded_and_configurable():
    default = _make_dry_run("test", "NIX=")
    constrained = _make_dry_run("test", "NIX=", "PYTEST_WORKERS=2")

    assert " -n 4" in default
    assert " -n auto" not in default
    assert " -n 2" in constrained


def test_memory_intensive_bootstrap_runs_after_the_parallel_suite():
    output = _make_dry_run("test", "NIX=").replace("\\\n", " ")
    commands = [line for line in output.splitlines() if "python3 -m pytest" in line]

    assert len(commands) == 2
    assert "--ignore=src/tests/btrc/test_bootstrap.py" in commands[0]
    assert "src/tests/btrc/test_bootstrap.py" in commands[1]
    assert " -n " in commands[0]
    assert " -n " not in commands[1]

    bootstrap = _make_dry_run("bootstrap", "NIX=")
    bootstrap_command = next(line for line in bootstrap.splitlines() if "python3 -m pytest" in line)
    assert "src/tests/btrc/test_bootstrap.py" in bootstrap_command
    assert " -n " not in bootstrap_command


def test_container_builds_never_prune_global_podman_state():
    build_sources = MAKEFILE.read_text() + (DEVCONTAINER_CONFIG / "host.nix").read_text()

    assert "image prune" not in build_sources
    assert "volume prune" not in build_sources


def test_devcontainer_policy_and_generated_output_are_unambiguously_filtered():
    assert {path.name for path in DEVCONTAINER_CONFIG.glob("*.nix")} == {
        "containerfile.nix",
        "default.nix",
        "devcontainer.nix",
        "host.nix",
    }
    assert "files = import ./build" in (REPO_ROOT / "flake.nix").read_text()
    assert "build/ /tmp/flake/build/" in (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert "/build/" not in ignored
    assert "/build/generated/" in ignored
    assert "/build/out/" in ignored


def test_devcontainer_context_excludes_repo_state_and_stages_lsp_runtime():
    ignored = (REPO_ROOT / ".dockerignore").read_text()
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()

    assert ignored.startswith("*\n")
    assert "!.git" not in ignored
    assert "build/generated/" in ignored
    assert "build/out/" in ignored
    for local_state in (
        "**/.venv/",
        "**/.pytest_cache/",
        "**/.ruff_cache/",
        "**/.btrc-cache/",
        "**/.DS_Store",
    ):
        assert local_state in ignored
    for source in ("src/compiler/python/", "src/devex/lsp/", "src/language/", "src/stdlib/"):
        assert f"COPY --chown=${{uid}}:${{uid}} {source}" in containerfile
    assert "!src/compiler/**" not in ignored


def test_devcontainer_external_tools_are_version_and_digest_pinned():
    flake = (REPO_ROOT / "flake.nix").read_text()
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()

    assert (
        'baseImage = "alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b";'
    ) in flake
    assert 'nixInstallerVersion = "v3.21.5";' in flake
    assert ('nixInstallerSha256 = "c9368f4bbfbc78ace32bf018cb15534344b33c0161468deddbfcc8a04f7c9a01";') in flake
    assert 'claudeCode = { enable = true; version = "2.1.207"; };' in flake
    assert "FROM alpine:latest" not in containerfile
    assert "https://install.determinate.systems/nix |" not in containerfile
    assert "https://install.determinate.systems/nix/tag/${cfg.nixInstallerVersion}" in containerfile
    assert "${cfg.nixInstallerSha256}  /tmp/determinate-nix-installer.sh" in containerfile
    assert "sha256sum -c -" in containerfile


def test_optional_native_backends_only_skip_missing_dependencies():
    makefile = MAKEFILE.read_text()
    flake = (REPO_ROOT / "flake.nix").read_text()

    assert makefile.count(" -E ") >= 3
    assert "$$CC" not in makefile
    assert makefile.count("$(CC)") >= 7
    assert '|| echo "GPU runtime skipped' not in makefile
    assert '|| echo "GUI window backend skipped' not in makefile
    assert '|| echo "GUI font backend skipped' not in makefile
    assert "-I${pkgs.glfw.dev}/include" in flake


def test_btrcc_c_rebuilds_for_every_input_category():
    representative_inputs = [
        "src/compiler/python/ir/gen/lowerer.py",
        "src/compiler/btrc/irgen.btrc",
        "src/stdlib/vector.btrc",
        "src/language/grammar.ebnf",
        "src/language/ast.asdl",
        "src/compiler/python/ast_nodes.py",
        "src/compiler/btrc/ast/node.btrc",
    ]

    for source in representative_inputs:
        output = _make_dry_run("--what-if", source, "dist/btrcc.c")
        assert "python3 -m src.compiler.python.main" in output, source


def test_btrcc_regenerates_ast_dependencies_before_transpiling():
    output = _make_dry_run("--what-if", "src/language/ast.asdl", "dist/btrcc.c")

    python_ast = "python3 src/compiler/python/ast/asdl_python.py"
    btrc_ast = "python3 src/compiler/python/ast/gen_btrc_ast.py"
    transpile = "python3 -m src.compiler.python.main"
    assert python_ast in output
    assert btrc_ast in output
    assert output.index(python_ast) < output.index(transpile)
    assert output.index(btrc_ast) < output.index(transpile)


def test_btrcc_release_targets_publish_bundles_not_raw_dist_binaries():
    linux = _make_dry_run("btrcc-linux-x64", "NIX=")
    windows = _make_dry_run("btrcc-windows-x64", "NIX=")

    assert "-o build/btrcc/linux-x64/btrcc" in linux
    assert "--binary build/btrcc/linux-x64/btrcc --target linux-x64" in linux
    assert "-o build/btrcc/windows-x64/btrcc.exe" in windows
    assert "--target windows-x64 --output-dir dist" in windows
    assert "src.compiler.python.check_generated" in linux + windows


def test_explicit_ast_generation_targets_force_regeneration():
    python_output = _make_dry_run("ast-generate", "NIX=")
    btrc_output = _make_dry_run("ast-generate-btrc", "NIX=")

    assert "python3 src/compiler/python/ast/asdl_python.py" in python_output
    assert "python3 src/compiler/python/ast/gen_btrc_ast.py" in btrc_output


def test_clean_covers_generated_and_runtime_build_directories():
    output = _make_dry_run("clean")

    for path in [
        "dist/",
        "build/generated/",
        "build/out/",
        "build/btrcc/",
        "build/temp.*/",
        ".coverage.*",
        "coverage.json",
        "src/devex/ext/server/",
        "src/devex/ext/debug/",
        "src/stdlib/gpu/build/",
        "src/stdlib/gui/build/",
    ]:
        assert path in output
    assert "-name '*.dSYM'" in output
    assert "-name '*.o'" in output
    assert "make -C tray clean" in output
    assert "find . -type" not in output
    assert "find src examples bench -type" in output


def test_ast_generation_is_validated_before_atomic_replacement():
    makefile = MAKEFILE.read_text()

    assert makefile.count("mktemp") >= 2
    assert makefile.count("test -s") >= 2
    assert makefile.count('mv -f "$$tmp" "$$target"') >= 2
    assert "> src/compiler/python/ast_nodes.py" not in makefile
    assert "> src/compiler/btrc/ast/node.btrc" not in makefile


def test_extension_build_uses_locked_dependencies():
    makefile = MAKEFILE.read_text()
    manifest_text = (REPO_ROOT / "src" / "devex" / "ext" / "package.json").read_text()
    manifest = json.loads(manifest_text)

    assert "npm ci && npm test && npm run package" in makefile
    assert manifest["scripts"]["typecheck"] == "tsc --noEmit"
    assert manifest["scripts"]["test"] == "npm run typecheck && npm run compile && node --test test/*.test.js"
    assert manifest["engines"]["vscode"] == "^1.85.0"
    assert manifest["devDependencies"]["@types/vscode"] == "1.85.0"
    assert manifest["devDependencies"]["@types/node"].startswith("^18.")
    assert (REPO_ROOT / "src" / "devex" / "ext" / "package-lock.json").exists()
    output = _make_dry_run("extension")
    assert output.index("src.compiler.python.check_generated") < output.index("npm ci")
    assert "python3 src/compiler/python/ast/gen_builtins.py" not in output


def test_python_wheel_preserves_import_namespace_and_runtime_sources():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    setuptools = config["tool"]["setuptools"]
    discovery = setuptools["packages"]["find"]
    package_data = setuptools["package-data"]["*"]

    assert config["project"]["readme"] == "README.md"
    assert discovery["where"] == ["."]
    assert "src*" in discovery["include"]
    assert "src.tests*" in discovery["exclude"]
    assert "src.devex.ext*" in discovery["exclude"]
    assert {"*.asdl", "*.btrc", "*.ebnf"} <= set(package_data)
    assert setuptools["exclude-package-data"]["src.compiler.btrc"] == ["fe_debug*.btrc"]
    hosted_tables = REPO_ROOT / "src/compiler/btrc/generated/hosted_abi/tables.btrc"
    assert hosted_tables.is_file()
    hosted_source = hosted_tables.read_text()
    assert "class GeneratedHostedAbi" in hosted_source
    assert '#include "' not in hosted_source


def test_nix_runtime_packages_use_the_filtered_runtime_source():
    flake = (REPO_ROOT / "flake.nix").read_text()

    assert 'export PYTHONPATH="${runtimeSource}' in flake
    assert "runtimeInputs = [ pkgs.python314 pkgs.git ];" in flake
    assert "runtimeInputs = [ lspPython pkgs.git ];" in flake
    assert '"src/compiler/python/"' in flake
    assert '"src/devex/lsp/"' in flake
    assert '"src/compiler/python/tests/"' not in flake
    assert '"src/devex/lsp/tests/"' in flake


def test_wheel_target_removes_stale_setuptools_outputs_before_building():
    output = _make_dry_run("wheel")

    assert "rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/" in output
    assert "rm -f dist/btrc-*.whl dist/btrc-*.tar.gz" in output
    assert "src.compiler.python.check_generated" in output
    assert "python3 -m build --wheel --no-isolation" in output


def test_package_target_builds_wheel_from_sdist():
    output = _make_dry_run("package")

    assert "rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/" in output
    assert "src.compiler.python.check_generated" in output
    assert "rm -f dist/btrc-*.whl dist/btrc-*.tar.gz" in output
    # With no --wheel/--sdist selector, `build` creates the sdist first and
    # builds the wheel from that clean source artifact.
    assert "python3 -m build --no-isolation" in output


def test_strict_c11_target_treats_extensions_as_errors():
    flags = "-std=c11 -pedantic-errors -Wall -Wextra -Werror -$$opt"
    assert flags in MAKEFILE.read_text()


def test_plain_pytest_includes_debug_adapter_tests():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert "src/devex/debug/tests" in config["tool"]["pytest"]["ini_options"]["testpaths"]


def test_ci_builds_installable_artifacts_and_pins_external_actions():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    windows = (REPO_ROOT / ".github" / "workflows" / "windows.yml").read_text()

    assert "make NIX= package extension" in ci
    assert "nix build .#btrc .#btrc-lsp .#btrc-vscode-extension --no-link" in ci
    assert "@main" not in ci + windows
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in ci
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in windows
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in windows
    assert "DeterminateSystems/determinate-nix-action@c70cb8ae92d68c66953db28a26a63db1665bc837" in ci
    assert "DeterminateSystems/magic-nix-cache-action@908b263ff629f4cc17666315b7fd3ec127c6244d" in ci
    assert '$ver = "0.16.0"' in windows
    assert "68659eb5f1e4eb1437a722f1dd889c5a322c9954607f5edcf337bc3684a75a7e" in windows
    assert "Get-FileHash -Algorithm SHA256 zig.zip" in windows
