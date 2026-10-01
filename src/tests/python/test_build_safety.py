"""Static regression coverage for destructive and stale build behavior."""

from __future__ import annotations

import fnmatch
import json
import os
import platform
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
FLAKE = REPO_ROOT / "flake.nix"
DEVCONTAINER_CONFIG = REPO_ROOT / "nix"


def _make_dry_run(*args: str) -> str:
    environment = os.environ.copy()
    for inherited_make_state in (
        "PYTEST_WORKERS",
        "PYTEST_ARGS",
        "PYTEST_SERIAL_ARGS",
        "MAKEFLAGS",
        "MFLAGS",
        "MAKEOVERRIDES",
    ):
        environment.pop(inherited_make_state, None)
    result = subprocess.run(
        ["make", "--dry-run", *args],
        cwd=REPO_ROOT,
        env=environment,
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
    assert "test-boundaries" in result.stdout
    assert "test-boundaries-observed" in result.stdout
    assert "btrcc-linux-x64" in result.stdout


def test_all_does_not_install_extension_or_build_devcontainer():
    makefile = MAKEFILE.read_text()
    all_rule = next(line for line in makefile.splitlines() if line.startswith("all:"))

    assert "extension-install" not in all_rule
    assert "devcontainer" not in all_rule


def test_default_pytest_parallelism_is_bounded_and_configurable():
    default = _make_dry_run("test", "NIX=")
    constrained = _make_dry_run("test", "NIX=", "PYTEST_WORKERS=2")

    assert " -n 8" in default
    assert " -n auto" not in default
    assert " -n 2" in constrained


def test_dev_shell_does_not_inject_fortify_into_strict_o0_tests() -> None:
    flake = FLAKE.read_text()
    assert 'hardeningDisable = [ "fortify" "fortify3" ];' in flake


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


def test_main_gate_runs_portable_boundaries_and_keeps_observed_proof_explicit():
    makefile = MAKEFILE.read_text()
    test_rule = next(line for line in makefile.splitlines() if line.startswith("test:"))
    assert "test-boundaries" in test_rule
    assert "test-boundaries-observed" not in test_rule

    portable = _make_dry_run("test-boundaries", "NIX=")
    assert "python3 -m tools.compiler_codegen.main boundary-check" in portable
    assert "--require-observed" not in portable

    observed = _make_dry_run("test-boundaries-observed", "NIX=")
    assert "python3 -m tools.compiler_codegen.main boundary-check --require-observed" in observed

    full = _make_dry_run("test", "NIX=")
    assert "--require-observed" not in full
    assert full.index("python3 -m tools.compiler_codegen.main boundary-check") < full.index(
        "python3 -m pytest src/tests/"
    )


def test_podman_machine_matches_the_documented_host_capacity():
    agents = (REPO_ROOT / "AGENTS.md").read_text()
    row = next(line for line in agents.splitlines() if "`podman-machine-default`" in line)
    memory, cpus, disk = (int(value) for value in re.findall(r"(\d+) (?:GiB|CPUs|GB disk)", row))

    assert f"machine = {{ memory = {memory * 1024}; cpus = {cpus}; disk = {disk}; }};" in FLAKE.read_text()
    assert "test_*.c" not in (REPO_ROOT / ".gitignore").read_text()


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
    assert "files = import ./nix" in (REPO_ROOT / "flake.nix").read_text()
    assert "nix/ /tmp/flake/nix/" in (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()
    ignored = (REPO_ROOT / ".gitignore").read_text().splitlines()
    assert "/build/" not in ignored
    assert "/build/generated/" in ignored
    assert "/build/out/" in ignored


def test_devcontainer_context_excludes_repo_state_and_stages_lsp_runtime():
    ignored = (REPO_ROOT / ".dockerignore").read_text()
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()

    assert ignored.startswith("*\n")
    assert "!.git" not in ignored
    # The deny-all rule keeps build/ (generated C, test compilers, bundles)
    # out of the context; no rule may admit it back.
    assert "!build" not in ignored
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


def test_devcontainer_installs_the_null_alsa_pcm():
    """CI's Linux shards run the ALSA session tests against this PCM; without it they would fail there."""
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()
    admitted = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    config = (DEVCONTAINER_CONFIG / "asound.conf").read_text()

    assert "COPY nix/asound.conf /etc/asound.conf" in containerfile
    assert "!nix/asound.conf" in admitted
    assert "pcm.!default {" in config
    assert "type null" in config


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

    assert makefile.count(" -E ") >= 1
    assert "$$CC" not in makefile
    assert makefile.count("$(CC)") >= 3
    assert '|| echo "GPU runtime skipped' not in makefile
    assert '|| echo "GUI window backend skipped' not in makefile
    assert '|| echo "GUI font backend skipped' not in makefile
    # Fonts resolve through pkg-config's freetype2 module (src/stdlib/GUI/btrc.toml),
    # not through shell variables nothing reads.
    assert " freetype" in flake
    assert "FONT_CFLAGS" not in flake and "FONT_LDFLAGS" not in flake


def test_macos_shell_supplies_the_native_provider_and_proof_sdks():
    """The reader implements a compiler provider only on Apple hosts (tools/NativeHeaderReader.cpp)."""
    flake = FLAKE.read_text()
    shell = flake.split("devShells = ", 1)[1].split("packages = eachSystem", 1)[0]
    darwin_packages = flake.split("pkgs.lib.optionals pkgs.stdenv.hostPlatform.isDarwin [", 1)[1].split("]", 1)[0]
    darwin_environment = shell.split("lib.optionalAttrs isDarwin {", 1)[1].split("} //", 1)[0]

    assert "pugixml sqlite.dev" in darwin_packages
    assert 'BTRC_NATIVE_PROVIDER_CC = "${pkgs.llvmPackages_21.stdenv.cc}/bin/clang";' in darwin_environment
    assert 'BTRC_NATIVE_PROVIDER_CXX = "${pkgs.llvmPackages_21.stdenv.cc}/bin/clang++";' in darwin_environment
    # The reader is built against the same drivers it accepts as a provider.
    assert "-DBTRC_NATIVE_CLANG_DRIVER='\"${pkgs.llvmPackages_21.stdenv.cc}/bin/clang\"'" in flake
    assert flake.count("BTRC_NATIVE_PROVIDER_CC") == 1


def test_dev_shell_links_the_patched_webgpu_library_once():
    flake = FLAKE.read_text()
    shell = flake.split("devShells = ", 1)[1].split("packages = eachSystem", 1)[0]

    assert "nixd wgpu-native" not in flake
    assert "self.packages.${system}.wgpu-native" in shell
    assert 'GPU_LDFLAGS = "-L${self.packages.${system}.wgpu-native}/lib' in shell
    assert "${pkgs.wgpu-native}/lib" not in shell


def test_flake_exports_no_alias_outputs_or_unused_ports():
    flake = FLAKE.read_text()
    devcontainer = (DEVCONTAINER_CONFIG / "devcontainer.nix").read_text()

    assert "btrcpy = self.apps" not in flake
    assert "inherit btrcpy btrcc btrc-format btrc-lsp;" in flake
    assert "btrc-vscode-extension = btrc-vscode;" in flake
    assert "ports = [" not in flake and "forwardPorts" not in devcontainer


def test_ci_devcontainer_omits_claude_code():
    flake = FLAKE.read_text()
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()

    assert "claudeCode = cfg.claudeCode // { enable = false; };" in flake
    assert "share = cfg.share // { claude = false; };" in flake
    assert 'devcontainer-ci = devcontainerFiles "${cfg.name}-devcontainer-ci" ciFiles;' in flake
    assert "lib.optionalString cfg.claudeCode.enable" in containerfile
    assert "nix build .#devcontainer-ci" in _make_dry_run("devcontainer", "CI=true")
    assert "nix build .#devcontainer " in _make_dry_run("devcontainer", "CI=")


def test_devcontainer_stages_the_packaged_formatter_source():
    """The shell's btrc-format is built from the staged flake, not the bind-mounted checkout."""
    containerfile = (DEVCONTAINER_CONFIG / "containerfile.nix").read_text()
    admitted = (REPO_ROOT / ".dockerignore").read_text().splitlines()

    assert "COPY --chown=${uid}:${uid} src/devex/formatter/ /tmp/flake/src/devex/formatter/" in containerfile
    assert "!src/devex/formatter/**" in admitted


def test_btrcc_c_rebuilds_for_every_input_category():
    representative_inputs = [
        "src/compiler/python/ir/lowering/lowerer.py",
        "src/compiler/btrc/ir/lowering/Lowerer.btrc",
        "src/stdlib/Vector.btrc",
        "src/language/grammar.ebnf",
        "src/language/ast.asdl",
        "src/compiler/python/syntax/ast/generated.py",
        "src/compiler/btrc/generated/ast/Node.btrc",
    ]

    for source in representative_inputs:
        output = _make_dry_run("--what-if", source, "dist/btrcc.c")
        assert "python3 -m src.compiler.python.main" in output, source


def test_native_btrcc_rebuilds_from_changed_selfhost_source():
    output = _make_dry_run(
        "--what-if",
        "src/compiler/btrc/frontend/Packages.btrc",
        "bin/btrcc",
        "NIX=",
    )

    assert "python3 -m src.compiler.python.main" in output
    generated = "dist/btrcc-macos-native.c" if platform.system() == "Darwin" else "dist/btrcc.c"
    assert f"{generated} -o bin/btrcc" in output


def test_windows_btrcc_builds_the_host_entrypoint_without_unix_reader():
    output = _make_dry_run("--what-if", "src/compiler/btrc/frontend/Models.btrc", "btrcc-windows-x64", "NIX=")
    assert "src/compiler/btrc/cli/WindowsMain.btrc" in output
    assert "src/compiler/btrc/BtrccMain.btrc" not in output
    assert "dist/btrcc-windows.c -o build/btrcc/windows-x64/btrcc.exe" in output


def test_btrcc_checks_ast_dependencies_before_transpiling():
    output = _make_dry_run("--what-if", "src/language/ast.asdl", "dist/btrcc.c")

    generated_check = "python3 -m tools.compiler_codegen.main check"
    transpile = "python3 -m src.compiler.python.main"
    assert generated_check in output
    assert output.index(generated_check) < output.index(transpile)


def test_btrcc_release_targets_publish_bundles_not_raw_dist_binaries():
    linux = _make_dry_run("btrcc-linux-x64", "NIX=")
    windows = _make_dry_run("btrcc-windows-x64", "NIX=")

    assert "-o build/btrcc/linux-x64/btrcc" in linux
    assert "--binary build/btrcc/linux-x64/btrcc --target linux-x64" in linux
    assert "-o build/btrcc/windows-x64/btrcc.exe" in windows
    assert "--target windows-x64 --output-dir dist" in windows
    assert "tools.compiler_codegen.main check" in linux + windows


def test_explicit_generation_target_forces_regeneration_without_aliases():
    output = _make_dry_run("compiler-codegen-generate", "NIX=")

    assert "python3 -m tools.compiler_codegen.main generate" in output
    # One target regenerates every catalog; the per-AST aliases were removed.
    assert "\nast-generate" not in MAKEFILE.read_text()


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
        "build/devex/vscode/",
        "build/stdlib/",
    ]:
        assert path in output
    assert "-name '*.dSYM'" in output
    assert "-name '*.o'" in output
    assert "make -C tray clean" in output
    assert "find . -type" not in output
    assert "find src examples tools -type" in output
    # A find root that does not exist exits nonzero and stops make before the
    # examples clean; every root must name a tracked directory.
    for line in output.splitlines():
        if line.startswith("find "):
            roots = line.split(" -type", 1)[0].split()[1:]
            assert all((REPO_ROOT / root).is_dir() for root in roots), line
    assert "-C bench" not in output
    assert "test_*.c" not in output


def test_linux_ci_script_defaults_to_the_makefile_targets_as_separate_words():
    script = (REPO_ROOT / "tools" / "linux-ci.sh").read_text()
    default = next(line for line in MAKEFILE.read_text().splitlines() if line.startswith("LINUX_CI_TARGETS ?="))
    targets = default.split("?=", 1)[1].split()

    # "${@:-a b}" expands to the single word "a b", which make takes as one
    # target name.
    assert '"${@:-' not in script
    assert f"  set -- {' '.join(targets)}\n" in script
    assert script.rstrip().endswith('"$@"')
    assert "Three things differ" in script


def test_ast_generation_is_validated_before_atomic_replacement():
    makefile = MAKEFILE.read_text()
    verification = (REPO_ROOT / "tools" / "compiler_codegen" / "verification.py").read_text()

    assert "tempfile.mkstemp" in verification
    assert "os.replace(temporary, target)" in verification
    assert "> src/compiler/python/syntax/ast/generated.py" not in makefile
    assert "> src/compiler/btrc/generated/ast/Node.btrc" not in makefile


def test_extension_build_uses_locked_dependencies():
    makefile = MAKEFILE.read_text()
    manifest_text = (REPO_ROOT / "src" / "devex" / "vscode" / "package.json").read_text()
    manifest = json.loads(manifest_text)

    assert "node src/devex/vscode/packaging/prepare.js" in makefile
    assert "cd build/devex/vscode && npm ci && npm test && npm run package" in makefile
    assert manifest["scripts"]["typecheck"] == "tsc --noEmit"
    assert manifest["scripts"]["test"] == (
        "npm run typecheck && npm run compile && npm run esbuild-test-modules "
        "&& node --test ../../../src/tests/vscode/*.test.js"
    )
    assert manifest["engines"]["vscode"] == "^1.85.0"
    assert manifest["devDependencies"]["@types/vscode"] == "1.85.0"
    assert manifest["devDependencies"]["@types/node"].startswith("^18.")
    assert (REPO_ROOT / "src" / "devex" / "vscode" / "package-lock.json").exists()
    output = _make_dry_run("extension")
    assert output.index("tools.compiler_codegen.main check") < output.index("npm ci")
    assert "python3 -m tools.compiler_codegen.main check" in output


def test_python_wheel_preserves_import_namespace_and_runtime_sources():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    setuptools = config["tool"]["setuptools"]
    discovery = setuptools["packages"]["find"]
    package_data = setuptools["package-data"]["*"]

    assert config["project"]["readme"] == "README.md"
    assert discovery["where"] == ["."]
    assert "src*" in discovery["include"]
    assert "src.tests*" in discovery["exclude"]
    assert "src.devex.vscode*" in discovery["exclude"]
    assert {"*.asdl", "*.btrc", "*.ebnf", "btrc.lock", "btrc.symbols"} <= set(package_data)
    assert "exclude-package-data" not in setuptools
    # Every tracked runtime input under a packaged directory reaches the wheel.
    tracked = subprocess.run(
        ["git", "ls-files", "src"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.split()
    unpackaged = [
        path
        for path in tracked
        if not path.startswith(("src/tests/", "src/devex/vscode/"))
        and not path.endswith(".py")
        and not any(fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern) for pattern in package_data)
    ]
    assert unpackaged == []
    for target in ("wheel", "package"):
        output = _make_dry_run(target, "NIX=")
        check = next(line for line in output.splitlines() if "zipfile.ZipFile" in line)
        assert "src/stdlib/btrc.symbols src/stdlib/LocalApplicationChannel/btrc.lock" in check.replace("\\", "")
    hosted_tables = REPO_ROOT / "src/compiler/btrc/generated/hosted_abi/Tables.btrc"
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
    assert '"src/devex/lsp/tests/"' not in flake


def test_wheel_target_removes_stale_setuptools_outputs_before_building():
    output = _make_dry_run("wheel")

    assert "rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/" in output
    assert "rm -f dist/btrc-*.whl dist/btrc-*.tar.gz" in output
    assert "tools.compiler_codegen.main check" in output
    assert "python3 -m build --wheel --no-isolation" in output


def test_package_target_builds_wheel_from_sdist():
    output = _make_dry_run("package")

    assert "rm -rf build/lib/ build/bdist.*/ btrc.egg-info/ src/btrc.egg-info/" in output
    assert "tools.compiler_codegen.main check" in output
    assert "rm -f dist/btrc-*.whl dist/btrc-*.tar.gz" in output
    # With no --wheel/--sdist selector, `build` creates the sdist first and
    # builds the wheel from that clean source artifact.
    assert "python3 -m build --no-isolation" in output


def test_strict_c11_target_treats_extensions_as_errors():
    flags = "-std=c11 -pedantic-errors -Wall -Wextra -Werror -$(C11_OPT)"
    assert flags in MAKEFILE.read_text()


def test_c11_gate_runs_each_ci_configuration_through_the_shard_target():
    """make test-c11 is the eight CI c11 shards in order, not a second copy of their recipe."""
    output = _make_dry_run("test-c11", "NIX=")

    assert "make --no-print-directory test-c11-one C11_CC=$cc C11_OPT=$opt" in output
    reports = re.findall(r"--skip-report=build/skip-report-c11-([a-z]+)-(O[0-3])\.json", output)
    assert reports == [(cc, opt) for cc in ("gcc", "clang") for opt in ("O0", "O1", "O2", "O3")]
    assert MAKEFILE.read_text().count("-std=c11 -pedantic-errors -Wall -Wextra -Werror") == 1


def test_plain_pytest_includes_debug_adapter_tests():
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    assert "src/tests" in config["tool"]["pytest"]["ini_options"]["testpaths"]
    # No test module is named *_test.py; the glob only widened collection.
    assert config["tool"]["pytest"]["ini_options"]["python_files"] == ["test_*.py", "runner.py"]
    assert "src/devex/debug/tests" not in config["tool"]["pytest"]["ini_options"]["testpaths"]


def test_ci_builds_installable_artifacts_and_pins_external_actions():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    windows = (REPO_ROOT / ".github" / "workflows" / "windows.yml").read_text()

    assert "make NIX= package extension" in ci
    assert (
        "nix build .#btrc .#btrc-lsp .#btrc-vscode-extension .#checks.x86_64-linux.gpu-runtime-package "
        ".#checks.x86_64-linux.native-package-plan --no-link"
    ) in ci
    # After the release builds, the generator's own check and a clean tree
    # stand in for a hand-kept list of generated paths that went stale.
    verify = ci.split("Verify release builds did not mutate", 1)[1].split("\n\n", 1)[0]
    assert "nix develop --command make NIX= generated-check" in verify
    assert 'test -z "$(git status --porcelain --untracked-files=all)"' in verify
    assert "paths=(" not in verify
    assert "@main" not in ci + windows
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in ci
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in windows
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in windows
    assert "DeterminateSystems/determinate-nix-action@c70cb8ae92d68c66953db28a26a63db1665bc837" in ci
    assert "DeterminateSystems/magic-nix-cache-action@908b263ff629f4cc17666315b7fd3ec127c6244d" in ci
    assert '$ver = "0.16.0"' in windows
    assert "68659eb5f1e4eb1437a722f1dd889c5a322c9954607f5edcf337bc3684a75a7e" in windows
    assert "Get-FileHash -Algorithm SHA256 zig.zip" in windows
