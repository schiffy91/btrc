"""tools/target_hosts/libsodium.py: what the recipe refuses, and the flags it takes from a target row.

The build itself needs a cross compiler and an SDK, so it runs where a target's
own rows run (src/tests/python/ios_simulator_fixtures.py builds the
simulator's). These rows hold what every host can check.
"""

from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from tools.target_hosts.libsodium import HOSTS, LibsodiumBuild, main


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A directory with the two files the recipe knows a libsodium source tree by."""
    tree = tmp_path / "libsodium"
    (tree / "src/libsodium/include").mkdir(parents=True)
    (tree / "src/libsodium/include/sodium.h").write_text("")
    (tree / "configure").write_text("#!/bin/sh\nexit 1\n")
    return tree


def test_flags_are_the_rows_target_and_its_sysroot(source: Path, tmp_path: Path) -> None:
    simulator = LibsodiumBuild(source, "ios-aarch64-simulator", ["clang"], Path("/sdk"), tmp_path / "out")
    assert simulator.host == "aarch64-apple-darwin"
    assert simulator.flags() == ["--target=arm64-apple-ios17.0.0-simulator", "-isysroot", "/sdk"]
    android = LibsodiumBuild(source, "android-aarch64", ["clang"], Path("/ndk/sysroot"), tmp_path / "out")
    assert android.host == "aarch64-linux-android"
    assert android.flags()[-2:] == ["--sysroot", "/ndk/sysroot"]
    assert android.flags()[:-2] == list(android.row.target_arguments)
    assert LibsodiumBuild(source, "ios-aarch64", ["clang"], None, tmp_path / "out").flags() == [
        "--target=arm64-apple-ios17.0.0"
    ]


def test_every_recipe_names_a_target_row() -> None:
    for system, architecture in HOSTS:
        assert PackageTarget(system, architecture).row.target_arguments


def test_a_target_that_takes_libsodium_from_pkg_config_has_no_recipe(source: Path, tmp_path: Path) -> None:
    for target in ("linux-x86_64", "macos-aarch64"):
        with pytest.raises(ValueError, match="no libsodium recipe"):
            LibsodiumBuild(source, target, ["cc"], None, tmp_path / "out")


def test_refuses_a_directory_that_is_no_source_tree_and_an_empty_compiler(source: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a libsodium source tree"):
        LibsodiumBuild(tmp_path, "ios-aarch64-simulator", ["clang"], None, tmp_path / "out")
    with pytest.raises(ValueError, match="compiler command is empty"):
        LibsodiumBuild(source, "ios-aarch64-simulator", [], None, tmp_path / "out")


def test_a_failed_configure_is_reported_and_leaves_no_library(source: Path, tmp_path: Path, capsys) -> None:
    (source / "configure").chmod(0o755)
    output = tmp_path / "out"
    status = main(
        ["--source", str(source), "--target", "ios-aarch64-simulator", "--cc", "clang", "--output", str(output)]
    )
    assert status == 1
    # A host that cannot run a shell script reports that instead of the script's status.
    assert capsys.readouterr().err.startswith("libsodium: ")
    assert not (output / "lib/libsodium.a").exists()
