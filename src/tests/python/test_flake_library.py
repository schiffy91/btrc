"""The flake's `lib`: the package builder, the sources helper, the VM test and the testkit package.

The two flake checks build and run them (`build-package` in ci.yml's release
job, `vm-test` in its own job, which needs KVM). What can be read without Nix
is checked here: the package holds what it exports, a scenario reaches it by
one name, and the VM check is a job a machine of the owner's reproduces.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from tools.qualification.local import LocalJobs
from tools.qualification.tiers import TierManifest

REPO = Path(__file__).resolve().parents[3]
LIBRARY = REPO / "nix" / "lib"
TESTKIT = LIBRARY / "testkit"
FLAKE = (REPO / "flake.nix").read_text(encoding="utf-8")
IMPORT = re.compile(r"^import\s+([^;\s]+)\s*;?\s*$", re.MULTILINE)


def _imports(source: Path) -> list[str]:
    return IMPORT.findall(source.read_text(encoding="utf-8"))


def test_the_testkit_exports_every_module_it_holds() -> None:
    manifest = tomllib.loads((TESTKIT / "btrc.toml").read_text(encoding="utf-8"))
    modules = sorted(source.stem for source in TESTKIT.glob("*.btrc"))

    assert manifest["package"]["exports"] == modules
    assert {"Check", "TestDirectory", "CommandLog", "OwnedProcess", "Lab", "Guest", "Framebuffer"} <= set(modules)
    # The one native header belongs to the module that reads the screen.
    assert [(binding["module"], binding["header"]) for binding in manifest["native"]["bindings"]] == [
        ("Framebuffer", "vnc.h")
    ]
    assert (TESTKIT / "vnc.h").is_file()


def test_the_testkit_is_one_package_that_reaches_only_itself_and_the_stdlib() -> None:
    for source in sorted(TESTKIT.glob("*.btrc")):
        for name in _imports(source):
            if name.startswith("Library."):
                continue
            assert re.fullmatch(r"\./[A-Z][A-Za-z0-9]*\.btrc", name), f"{source.name} imports {name}"
            assert (TESTKIT / name).is_file(), f"{source.name} imports {name}"


def test_a_scenario_imports_the_testkit_by_its_package_name() -> None:
    scenario = REPO / "src/tests/native/vm_test/Reboot.btrc"
    helper = (LIBRARY / "with-testkit.nix").read_text(encoding="utf-8")

    assert "testkit.Lab" in _imports(scenario)
    assert not [name for name in _imports(scenario) if name.startswith(".")]
    # The name a scenario writes is the dependency the placed manifest declares.
    assert 'testkit = { path = "${at}" }' in helper
    assert 'at ? "testkit"' in helper
    assert "cp -r ${./testkit}" in helper


def test_the_flake_offers_the_builder_the_sources_and_the_vm_test() -> None:
    library = FLAKE.split("\n      lib = {\n", 1)[1].split("\n      };\n", 1)[0]

    for function, file in (
        ("buildPackageWith", "build-package.nix"),
        ("sources", "sources.nix"),
        ("withTestkit", "with-testkit.nix"),
        ("vmTest", "vm-test.nix"),
    ):
        assert re.search(rf"\b{function} = ", library), function
        assert f"./nix/lib/{file}" in library, file
        assert (LIBRARY / file).is_file()
    assert "buildPackage = pkgs: self.lib.buildPackageWith { inherit pkgs; };" in library
    assert "testkit = ./nix/lib/testkit;" in library
    # The compiler and the plan builder are this flake's own, for the system that builds.
    assert library.count("self.packages.${pkgs.stdenv.buildPlatform.system}.") == 2


def test_the_builder_takes_the_arguments_its_callers_pass() -> None:
    builder = (LIBRARY / "build-package.nix").read_text(encoding="utf-8")
    arguments = builder.split("{ pkgs, btrcpy, btrc-native-plan ? null }:\n", 1)[1].split("}:", 1)[0]

    assert arguments.startswith("{ name, src, programs, buildInputs ? []")
    for optional in (
        "buildInputs",
        "runtimeInputs",
        "linkFlags",
        "linkPlan",
        "nativeBuildInputs",
        "env",
        "wrapperArgs",
        "postInstall",
    ):
        assert f"{optional} ? " in arguments, optional
    assert "linkPlan ? (btrc-native-plan != null && linkFlags == [])" in arguments


def test_both_checks_are_built_and_the_vm_check_is_a_local_job() -> None:
    checks = FLAKE.split("\n      checks = eachSystem", 1)[1]
    linux_only = checks.split("lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux", 1)[1]

    assert "build-package = let" in checks.split("lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux", 1)[0]
    assert "vm-test = self.lib.vmTest pkgs {" in linux_only

    entries = {entry.job: entry for entry in LocalJobs(TierManifest.load()).entries() if entry.workflow == "ci.yml"}
    job = entries["vm-test"]
    assert job.platform == "linux-x86_64" and job.name == "CI / vm-test"
    # The hosted runner's KVM permission step is provisioning; the job is the build.
    assert job.steps == ("nix build .#checks.x86_64-linux.vm-test --no-link --print-build-logs",)
