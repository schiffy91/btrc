"""tools/ci-prepared.sh: one CI run's image and compilers, saved once and restored by every Linux job."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="the script and its stand-in tools are POSIX shell")


def _tool(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@pytest.fixture
def runner(tmp_path):
    """A checkout holding the script, and a podman and a make that record what they are asked."""

    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "calls"
    _tool(
        tools,
        "podman",
        f'echo "podman $*" >> "{log}"\n'
        'case "$1" in save) printf "image %s" "$2" ;; load) cat > "$(dirname "$0")/loaded" ;; esac\n',
    )
    _tool(tools, "make", f'echo "make $*" >> "{log}"\n')

    def run(checkout: Path, *arguments: str) -> subprocess.CompletedProcess:
        script = checkout / "tools" / "ci-prepared.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "tools" / "ci-prepared.sh", script)
        environment = {**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}
        environment.pop("BTRC_LINUX_IMAGE", None)
        return subprocess.run(
            ["bash", str(script), *arguments], cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60
        )

    return run, log, tools


def test_a_run_saves_its_image_and_compilers_once_and_each_job_restores_them(tmp_path, runner):
    run, log, tools = runner
    producer, consumer, prepared = tmp_path / "producer", tmp_path / "consumer", tmp_path / "prepared"
    for relative, text in (
        ("test-btrcc/aaaa/btrcc", "compiler"),
        ("test-btrcc/aaaa/btrcc.c", "generated C"),
        ("test-btrcc/drivers/dddd/driver", "driver"),
        ("test-btrcc/aaaa.lock", ""),
    ):
        path = producer / "build" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    saved = run(producer, "save", str(prepared))
    assert saved.returncode == 0, saved.stderr
    assert sorted(path.name for path in prepared.iterdir()) == ["devcontainer.tar.gz", "test-btrcc.tar.gz"]

    restored = run(consumer, "restore", str(prepared))
    assert restored.returncode == 0, restored.stderr
    # The image is loaded, not rebuilt, and it is the image that was saved.
    assert log.read_text().splitlines() == ["podman save btrc-devcontainer:latest", "podman load"]
    assert (tools / "loaded").read_text() == "image btrc-devcontainer:latest"
    built = consumer / "build" / "test-btrcc"
    assert sorted(path.relative_to(built).as_posix() for path in built.rglob("*") if path.is_file()) == [
        "aaaa/btrcc",
        "drivers/dddd/driver",
    ]
    assert (built / "aaaa" / "btrcc").read_text() == "compiler"


def test_a_job_with_nothing_prepared_builds_the_image_itself(tmp_path, runner):
    run, log, _ = runner
    # A local job in a fresh clone: no archive was downloaded.
    restored = run(tmp_path / "clone", "restore", str(tmp_path / "prepared"))
    assert restored.returncode == 0, restored.stderr
    assert log.read_text().splitlines() == ["make devcontainer"]
    assert not (tmp_path / "clone" / "build").exists()


@pytest.mark.parametrize("arguments", [[], ["save"], ["publish", "somewhere"], ["restore", "one", "two"]])
def test_the_script_names_its_two_actions(tmp_path, runner, arguments):
    run, log, _ = runner
    result = run(tmp_path / "checkout", *arguments)
    assert result.returncode == 64 and "usage: tools/ci-prepared.sh save|restore <directory>" in result.stderr
    assert not log.exists()


def test_save_works_in_a_build_directory_the_containers_user_made(tmp_path, runner):
    """On a runner the container creates build/, and the job's user may not add to it.

    The first hosted run failed there: `save` made its directory itself and
    got "mkdir: Permission denied". The prepare job now makes the directory
    before the container runs; `save` then only fills it.
    """

    run, _log, _tools = runner
    checkout = tmp_path / "checkout"
    compiler = checkout / "build" / "test-btrcc" / "aaaa" / "btrcc"
    compiler.parent.mkdir(parents=True)
    compiler.write_text("compiler")
    prepared = checkout / "build" / "ci-prepared"
    prepared.mkdir()
    (checkout / "build").chmod(0o555)  # as the runner's user finds what another user created
    try:
        saved = run(checkout, "save", "build/ci-prepared")
        assert saved.returncode == 0, saved.stderr
        assert sorted(path.name for path in prepared.iterdir()) == ["devcontainer.tar.gz", "test-btrcc.tar.gz"]
        # Without the directory the save cannot make it, which is what the workflow's own step is for.
        # (Root may write anywhere, so there is nothing to refuse it.)
        if os.geteuid() != 0:
            for archive in prepared.iterdir():
                archive.unlink()
            (checkout / "build").chmod(0o755)
            prepared.rmdir()
            (checkout / "build").chmod(0o555)
            refused = run(checkout, "save", "build/ci-prepared")
            assert refused.returncode != 0 and "Permission denied" in refused.stderr
    finally:
        (checkout / "build").chmod(0o755)
