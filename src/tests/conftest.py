"""Shared fixtures + options for the btrc test tree.

The language corpus under src/tests/<category>/ is run through BOTH compilers
by runner.py; the `--compilers` option selects which (default both). The
compiler-specific suites live under src/tests/python/ (Python reference compiler
white-box unit tests) and src/tests/btrc/ (self-hosted compiler tests).

Every session writes a skip report (src/tests/skip_ledger.py): each test's
outcome, each skip's reason and gating environment, and each capability gate,
classified against the runner's expected-skip manifest under
src/tests/fixtures/expected-skips/. `--skip-report` names the file.
"""

import contextlib
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import pytest

from src.tests.c_toolchains import HOST_COMPILER_DIAGNOSTICS
from src.tests.selfhost_cache import SELFHOST, SelfhostCompilerCache
from src.tests.skip_ledger import SkipLedger

REPO = Path(__file__).resolve().parents[2]


def pytest_addoption(parser):
    parser.addoption(
        "--compilers",
        action="store",
        default="python,btrc",
        help="'both', or a comma-separated list containing 'python' (reference) and/or 'btrc' (self-hosted)",
    )
    parser.addoption(
        "--fast",
        action="store_true",
        default=False,
        help="the fast tier: only tests that need neither the self-hosted compiler nor a display (make test-fast)",
    )
    SkipLedger.add_options(parser)


# What keeps a test out of the fast tier (`make test-fast`): it builds or runs
# the self-hosted compiler or a helper driver, it owns a display, or it is a
# sustained qualification load. Everything else is in the tier, so a new test
# joins it without being listed anywhere.
_SELFHOST_FIXTURES = frozenset({"immutable_btrcc", "selfhost_driver"})
_FAST_TIER_EXCLUDED_MARKERS = ("e40_qualification", "nightly", "linux_gui", "macos_gui")


def _in_fast_tier(item) -> bool:
    """Whether collection already shows that a test needs nothing the fast tier leaves out."""

    if _SELFHOST_FIXTURES & set(getattr(item, "fixturenames", ())):
        return False
    return all(item.get_closest_marker(marker) is None for marker in _FAST_TIER_EXCLUDED_MARKERS)


def _skip_selfhost_in_the_fast_tier(config) -> None:
    """A test that asks for the self-hosted compiler while it runs leaves the fast tier here.

    Collection cannot see `request.getfixturevalue`, which the tests that run
    one case per frontend use for their self-hosted half.
    """

    if config.getoption("--fast"):
        pytest.skip("the fast tier never builds the self-hosted compiler; `make test` runs this test")


def pytest_configure(config):
    """Record every skip and capability gate in this session's skip report."""
    SkipLedger.install(config)
    config.addinivalue_line("markers", "macos_gui: requires exclusive AppKit application execution on macOS")
    config.addinivalue_line("markers", "linux_gui: owns shared Linux GUI focus or clipboard state")
    config.addinivalue_line(
        "markers", "e40_qualification: sustained native workload; requires a serial qualification stage"
    )
    config.addinivalue_line("markers", "nightly: required, but run by `make test-nightly` instead of `make test`")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if call.excinfo is not None:
        evidence = HOST_COMPILER_DIAGNOSTICS.failure(call.excinfo.value)
        if evidence is not None:
            report.sections.append(("host compiler launch evidence", json.dumps(evidence, sort_keys=True)))
    return report


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Select the fast tier; schedule one AppKit/Linux GUI owner per worker pool (the kernel lease spans pools)."""
    if config.getoption("--fast"):
        left_out = [item for item in items if not _in_fast_tier(item)]
        if left_out:
            items[:] = [item for item in items if _in_fast_tier(item)]
            config.hook.pytest_deselected(items=left_out)
    if not (config.getoption("dist", default=None) == "loadgroup" or config.getoption("loadgroup", default=False)):
        return
    if sys.platform == "darwin":
        for item in items:
            if item.get_closest_marker("macos_gui") is None:
                continue
            groups = {
                str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                for mark in item.iter_markers("xdist_group")
            }
            # xdist combines all names into a new group. Adding our name to a
            # different group would silently restore concurrent AppKit workers.
            if groups - {"macos_gui"}:
                raise pytest.UsageError(f"{item.nodeid}: macos_gui cannot combine with another xdist_group")
            if not groups:
                item.add_marker(pytest.mark.xdist_group(name="macos_gui"))
    elif sys.platform == "linux":
        for item in items:
            if item.get_closest_marker("linux_gui") is None:
                continue
            groups = {
                str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                for mark in item.iter_markers("xdist_group")
            }
            if not groups:
                item.add_marker(pytest.mark.xdist_group(name="linux_gui"))


def _parse_compilers(raw: str) -> list[str]:
    """Parse --compilers without silently weakening the requested matrix."""

    value = raw.strip()
    if value == "both":
        return ["python", "btrc"]
    if not value:
        raise pytest.UsageError("--compilers requires 'both', 'python', 'btrc', or a comma-separated list")
    names = [part.strip() for part in raw.split(",")]
    invalid = [name or "<empty>" for name in names if name not in {"python", "btrc"}]
    if invalid:
        raise pytest.UsageError(
            f"unknown --compilers selection(s): {', '.join(invalid)}; expected 'both', 'python', or 'btrc'"
        )
    return list(dict.fromkeys(names))


def _configured_test_btrcc() -> Path | None:
    """Resolve the explicit, test-only self-host compiler override."""

    raw = os.environ.get("BTRC_TEST_BTRCC")
    if raw is None:
        return None
    if not raw.strip():
        raise pytest.UsageError("BTRC_TEST_BTRCC must name an absolute compiler path")
    configured = Path(raw)
    if not configured.is_absolute():
        raise pytest.UsageError("BTRC_TEST_BTRCC must be an absolute path")
    try:
        binary = configured.resolve(strict=True)
    except OSError as error:
        raise pytest.UsageError(f"BTRC_TEST_BTRCC does not resolve to a compiler: {configured}") from error
    if not binary.is_file():
        raise pytest.UsageError(f"BTRC_TEST_BTRCC is not a regular file: {configured}")
    if os.name != "nt" and not os.access(binary, os.X_OK):
        raise pytest.UsageError(f"BTRC_TEST_BTRCC is not executable: {configured}")
    return binary


def pytest_generate_tests(metafunc):
    """Parametrize any test taking a `compiler` arg from --compilers."""
    if "compiler" in metafunc.fixturenames:
        metafunc.parametrize("compiler", _parse_compilers(metafunc.config.getoption("--compilers")))


@pytest.fixture(scope="session", autouse=True)
def _isolated_btrc_cache(tmp_path_factory):
    """Point every btrc cache at a session-temp dir.

    The cache directory resolves to $BTRC_CACHE_DIR > btrc.toml project root >
    the user cache dir; without this fixture the suite would write stdlib JSON
    AST artifacts and generated C into the developer's real user cache. One
    shared dir per session keeps the stdlib AST cache warm across tests while staying
    hermetic. Tests that exercise the resolution order itself monkeypatch the
    variable away.
    """
    cache = tmp_path_factory.mktemp("btrc-cache")
    old = os.environ.get("BTRC_CACHE_DIR")
    os.environ["BTRC_CACHE_DIR"] = str(cache)
    yield
    if old is None:
        os.environ.pop("BTRC_CACHE_DIR", None)
    else:
        os.environ["BTRC_CACHE_DIR"] = old


@pytest.fixture(scope="session", autouse=True)
def _isolated_compiler_generation_state(tmp_path_factory):
    """Keep durable output ownership out of the developer's real state root."""
    state = tmp_path_factory.mktemp("btrc-generations")
    state.chmod(0o700)
    old = os.environ.get("BTRC_STATE_DIR")
    os.environ["BTRC_STATE_DIR"] = str(state)
    yield
    if old is None:
        os.environ.pop("BTRC_STATE_DIR", None)
    else:
        os.environ["BTRC_STATE_DIR"] = old


@pytest.fixture(scope="session", autouse=True)
def _selfhost_runtime_data():
    """Give temp-built self-host compilers an explicit, hermetic data root.

    Relocation/security tests pass a subprocess environment with ``BTRC_HOME``
    removed when they need to exercise executable-relative discovery.  Making
    the ordinary test-session configuration explicit avoids teaching temporary
    binaries to trust the repository working directory.
    """

    old = os.environ.get("BTRC_HOME")
    os.environ["BTRC_HOME"] = str(REPO / "src")
    yield
    if old is None:
        os.environ.pop("BTRC_HOME", None)
    else:
        os.environ["BTRC_HOME"] = old


@pytest.fixture(scope="session")
def gui_provider_root(tmp_path_factory) -> Path:
    """A data root exporting the native GUI providers to their conformance fixtures."""

    from src.tests.gui_provider_root import GUIProviderRoot

    return GUIProviderRoot.create(tmp_path_factory.mktemp("gui-provider") / "data")


@contextlib.contextmanager
def _gui_exclusive(lock_path: Path, *, timeout: float, owner: str):
    """FIFO GUI ownership; a waiter's kernel-held ticket survives only its process.

    The queue guard covers publication and head selection, never GUI work.
    Compiler locks continue to use the ordinary _exclusive owner.
    """
    if os.name == "nt":  # pragma: no cover - GUI leases apply to POSIX hosts
        yield
        return
    import fcntl

    deadline = time.monotonic() + timeout
    queue = lock_path.with_name(lock_path.name + ".queue")
    queue.mkdir(parents=True, exist_ok=True)
    ticket_path = None
    ticket = None

    def wait():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            holder = lock_path.read_text().strip() if lock_path.exists() else ""
            raise TimeoutError(
                f"Timed out after {timeout:g}s waiting for {lock_path}; "
                f"last recorded holder: {holder or 'not yet recorded'}"
            )
        time.sleep(min(0.05, remaining))

    @contextlib.contextmanager
    def guarded():
        with (queue / "guard").open("a+") as guard:
            while True:
                if time.monotonic() >= deadline:
                    wait()
                try:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    wait()
            try:
                yield
            finally:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)

    try:
        with guarded():
            positions = [int(path.stem) for path in queue.glob("*.ticket")]
            planned = queue / f"{max(positions, default=0) + 1:020d}.ticket"
            ticket = planned.open("x+")
            ticket_path = planned
            # Publish a locked ticket under the guard: another waiter cannot
            # mistake an incompletely admitted ticket for a dead process.
            fcntl.flock(ticket.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            json.dump({"pid": os.getpid(), "owner": owner}, ticket)
            ticket.flush()
        with lock_path.open("a+") as execution:
            acquired = False
            while not acquired:
                with guarded():
                    for head in sorted(queue.glob("*.ticket")):
                        if head == ticket_path:
                            try:
                                fcntl.flock(execution.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                                acquired = True
                            except BlockingIOError:
                                pass
                            break
                        try:
                            previous = head.open("r+")
                        except FileNotFoundError:
                            continue  # A timed-out waiter removed its own ticket.
                        with previous:
                            try:
                                fcntl.flock(previous.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                break  # The oldest ticket is still owned.
                            # An unlocked ticket has no live owner. Kernel locks,
                            # rather than PID liveness, also cover PID reuse.
                            head.unlink(missing_ok=True)
                if not acquired:
                    wait()
            try:
                execution.seek(0)
                execution.truncate()
                json.dump({"pid": os.getpid(), "owner": owner}, execution)
                execution.flush()
                yield
            finally:
                fcntl.flock(execution.fileno(), fcntl.LOCK_UN)
    finally:
        # Removing only our ticket needs no queue guard, including on timeout.
        # Readers tolerate its disappearance; the lifetime lock stays held
        # until unlink completes so it can never be reaped as a live waiter.
        try:
            if ticket_path is not None:
                ticket_path.unlink(missing_ok=True)
        finally:
            if ticket is not None:
                ticket.close()


@pytest.fixture(autouse=True)
def _macos_gui_session(request):
    """Only AppKit execution owns focus; ordinary workers remain parallel.

    This checkout lease is distinct from the outer host gui-capture lease.
    Keeping it in pytest's shared cache makes it common to xdist workers and
    concurrent pytest processes, without inheriting or reacquiring host locks.
    """
    if sys.platform != "darwin" or request.node.get_closest_marker("macos_gui") is None:
        yield
        return
    lock_path = request.config.cache.mkdir("macos-gui") / "execution.lock"
    with _gui_exclusive(lock_path, timeout=1800, owner=request.node.nodeid):
        yield


@pytest.fixture(autouse=True)
def _linux_gui_session(request):
    """Serialize display-mutating Linux journeys, including their fixture lifetime.

    Like the AppKit lease, this is shared by workers/processes using this
    checkout's pytest cache, not the outer host gui-capture lock. X11 and
    Wayland can share one desktop focus domain, so protocol is not a bypass.
    Delegating desktop collectors stay unmarked: their child pytest cases
    acquire the lease; the parent must not hold it while waiting for them.
    """
    if sys.platform != "linux" or request.node.get_closest_marker("linux_gui") is None:
        yield
        return
    lock_path = request.config.cache.mkdir("linux-gui") / "execution.lock"
    with _gui_exclusive(lock_path, timeout=1800, owner=request.node.nodeid):
        yield


@pytest.fixture(scope="session")
def immutable_btrcc(request, _selfhost_runtime_data) -> Path:
    """Return one strict immutable self-host compiler for the whole run.

    Building it costs minutes -- a 431k-line single translation unit -- so it is
    content-addressed and built at most once (src/tests/selfhost_cache.py).
    Every xdist worker, every gate and every later run over unchanged sources
    reuses the same binary; any source edit changes the key and forces a
    rebuild.
    """

    _skip_selfhost_in_the_fast_tier(request.config)
    configured = _configured_test_btrcc()
    if configured is not None:
        return configured
    return SelfhostCompilerCache.configured().compiler_binary()


@pytest.fixture(scope="session")
def selfhost_driver(immutable_btrcc: Path):
    """Build one self-hosted driver per source and share it everywhere.

    Modules needing a driver binary built their own in module-scoped fixtures,
    so under xdist every worker touching such a module paid a full transpile and
    link. Seven modules do this with the production compiler or its tool
    drivers, and they were the seven most expensive setups in the suite -- one
    module's fixture alone accounted for 472s.

    The shared cache keys each driver on the compiler's fingerprint plus the
    driver's own bytes and flags, so one build serves every module, every
    worker, and every later run over unchanged sources. The session's
    self-hosted compiler transpiles it; `frontend=REFERENCE` asks for the
    reference compiler instead.
    """

    cache = SelfhostCompilerCache.configured()

    def build(source: Path | str, *, compile_flags: Sequence[str] = (), frontend: str = SELFHOST) -> Path:
        return cache.driver(source, compile_flags=compile_flags, frontend=frontend, selfhost_compiler=immutable_btrcc)

    return build


@pytest.fixture(scope="session")
def semantic_btrcc(immutable_btrcc: Path) -> Path:
    """Compatibility name for semantic and focused self-host tests."""

    return immutable_btrcc


@pytest.fixture(scope="session")
def btrcc_bin(immutable_btrcc: Path) -> str:
    """Compatibility name for the unified language-corpus runner."""

    return str(immutable_btrcc)
