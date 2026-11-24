"""Library.DBus, the stdlib's own D-Bus client, through both frontends.

The client links no D-Bus library, so the other end of every exchange here is
another implementation: a private ``dbus-daemon`` (whose message validation is
libdbus), GLib's GDBus in either byte order, and libdbus's ``dbus-send`` and
``dbus-monitor``. The malformed-message program needs no bus; it is built with
AddressSanitizer and UndefinedBehaviorSanitizer.
"""

import contextlib
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder, NativePlanReader
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "dbus"
RUN_TIMEOUT = 120
COMPILE_TIMEOUT = 240
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
SANITIZED = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
BUILDS = [("gcc", False), ("clang", True)]
ECHO = ("org.btrc.test.Echo", "/org/btrc/test/Echo", "org.btrc.test.Echo")


def _require_host() -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux: Library.DBus's transport has a Linux row only")


def assert_links_no_dbus_library(executable: Path) -> None:
    assert DependencyAudit().binary_problems(executable, PackageTarget.parse(None).label) == []


def _build(c_compiler: str, plan: Path, generated: Path, executable: Path, *, sanitized: bool) -> None:
    """Build from the link plan, which asks pkg-config for nothing."""
    if not shutil.which(c_compiler):
        pytest.fail(f"{c_compiler} is unavailable")
    assert NativePlanReader().read(plan).pkg_config == ()
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=STRICT + (SANITIZED if sanitized else []),
        link_flags=SANITIZED if sanitized else [],
    )
    assert_links_no_dbus_library(executable)


def _program(
    name: str, compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> Path:
    generated = tmp_path / f"{name}-{compiler}.c"
    executable = tmp_path / f"{name}-{compiler}"
    plan = _transpile(compiler, FIXTURE / f"{name}.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized)
    return executable


@contextlib.contextmanager
def private_bus(config: Path | None = None, prefix: tuple[str, ...] = (), listen: str | None = None) -> Iterator[str]:
    """A session bus of the test's own; yields its address."""
    daemon_program = shutil.which("dbus-daemon")
    if daemon_program is None:
        pytest.fail("dbus-daemon is not installed: the dev shell carries it for these tests")
    # Nix's dbus looks for its configuration under /etc, which a container lacks, so the one installed beside
    # the daemon is named, as tools/ui/headless-session.sh does.
    shipped = Path(os.path.realpath(daemon_program)).parent.parent / "share/dbus-1/session.conf"
    configuration = f"--config-file={shipped}" if shipped.is_file() else "--session"
    if config is not None:
        configuration = f"--config-file={config}"
    daemon = subprocess.Popen(
        [
            *prefix,
            daemon_program,
            configuration,
            *([f"--address={listen}"] if listen else []),
            "--nofork",
            "--nopidfile",
            "--print-address=1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        address = daemon.stdout.readline().strip()
        assert address, "dbus-daemon printed no address"
        yield address
    finally:
        daemon.terminate()
        daemon.wait(timeout=10)


def _environment(address: str) -> dict[str, str]:
    return {**os.environ, "DBUS_SESSION_BUS_ADDRESS": address}


@pytest.mark.parametrize("c_compiler,sanitized", BUILDS)
def test_dbus_client_against_a_private_bus(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Hello, names, calls, errors, match rules and signals with the daemon; every type between two connections."""
    _require_host()
    executable = _program("DBusConformance", compiler, c_compiler, sanitized, tmp_path, request)
    with private_bus() as address:
        ran = subprocess.run(
            [str(executable)], env=_environment(address), capture_output=True, text=True, timeout=RUN_TIMEOUT
        )
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: D-Bus addresses, codec, bus calls, signals and a peer round trip\n"
    assert ran.stderr == ""


def test_dbus_address_discovery_and_authentication(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Exercise DNS, nonce files, cookie and anonymous authentication, and GUID pinning against the daemon."""
    _require_host()
    import pwd
    from xml.sax.saxutils import escape

    executable = _program("DBusEcho", compiler, "gcc", False, tmp_path, request)
    # libdbus stores the private cookie in the password database's home. Give
    # the daemon and client an empty temporary home, keeping the user's bus untouched.
    account_home = pwd.getpwuid(os.geteuid()).pw_dir
    home = tmp_path / "account"
    home.mkdir(mode=0o700)
    prefix = (
        "bwrap",
        "--die-with-parent",
        "--bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--bind",
        str(home),
        account_home,
        "--bind",
        str(tmp_path),
        str(tmp_path),
    )
    # AF_UNIX socket names have a small fixed bound; CI checkout paths can be long.
    with (
        tempfile.TemporaryDirectory(prefix="btrc-dbus-") as directory,
        private_bus(listen=f"unix:path={directory}/bus"),
    ):
        runtime = Path(directory)
        unaddressed = {**os.environ, "XDG_RUNTIME_DIR": str(runtime), "DISPLAY": ""}
        unaddressed.pop("DBUS_SESSION_BUS_ADDRESS", None)
        with _echo_service(executable, unaddressed):
            pass

        # The stdio relay is the caller-selected unixexec program. Its argv
        # includes an escaped argument with punctuation and a custom argv0.
        relay = tmp_path / "relay.py"
        relay.write_text(
            "import os, select, socket, sys\n"
            "assert sys.argv[1] == 'comma, semi; percent%'\n"
            "remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "remote.connect(sys.argv[2])\n"
            "local = socket.socket(fileno=0)\n"
            "while True:\n"
            "    for source in select.select([local, remote], [], [])[0]:\n"
            "        chunk = source.recv(65536)\n"
            "        if not chunk: sys.exit(0)\n"
            "        (remote if source is local else local).sendall(chunk)\n"
        )
        helper = (
            f"unixexec:path={quote(sys.executable)},argv0=btrc-relay,"
            f"argv1={quote(str(relay))},argv2={quote('comma, semi; percent%')},"
            f"argv3={quote(str(runtime / 'bus'))}"
        )
        with _echo_service(executable, _environment(helper)):
            pass
    config = tmp_path / "bus.conf"
    for transport, auth in (("tcp", "DBUS_COOKIE_SHA1"), ("nonce-tcp", "ANONYMOUS")):
        listen = f"{transport}:host=localhost,family=ipv4,port=0"
        config.write_text(
            "<busconfig><type>session</type><allow_anonymous/><listen>"
            + escape(listen)
            + f'</listen><auth>{auth}</auth><policy context="default"><allow user="*"/>'
            + '<allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>'
        )
        with private_bus(config, prefix) as address:
            bad = address.split("guid=")[0] + "guid=" + "0" * 32
            refused = subprocess.run([*prefix, str(executable)], env=_environment(bad), capture_output=True, timeout=30)
            assert refused.returncode == 2, refused.stderr
            with subprocess.Popen(
                [*prefix, str(executable)],
                env=_environment(address),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as client:
                try:
                    assert select.select([client.stdout], [], [], 30)[0]
                    line = client.stdout.readline()
                    assert line.startswith("READY :1."), (line, client.poll())
                finally:
                    client.terminate()
                    client.communicate(timeout=10)


@pytest.mark.parametrize("c_compiler,sanitized", BUILDS)
def test_dbus_refuses_malformed_messages(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Truncated, corrupted and hand-broken frames are refused without a read past their end."""
    _require_host()
    executable = _program("DBusMalformed", compiler, c_compiler, sanitized, tmp_path, request)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: D-Bus refuses malformed messages\n"
    assert ran.stderr == ""


@contextlib.contextmanager
def _echo_service(executable: Path, environment: dict[str, str]) -> Iterator[subprocess.Popen[str]]:
    service = subprocess.Popen(
        [str(executable)], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert select.select([service.stdout], [], [], 30)[0], "D-Bus service did not become ready"
        ready = service.stdout.readline()
        assert ready.startswith("READY :1."), (ready, service.poll())
        yield service
    finally:
        if service.poll() is None:
            service.terminate()
        service.communicate(timeout=10)


def test_dbus_client_serves_gdbus_in_both_byte_orders(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """GDBus calls an object this client serves, little- and big-endian; including a multi-megabyte payload."""
    _require_host()
    from gi.repository import Gio, GLib

    executable = _program("DBusEcho", compiler, "clang", True, tmp_path, request)
    values = (
        255,
        True,
        -2,
        65535,
        -(2**31),
        2**32 - 1,
        -9_000_000_000,
        2**64 - 1,
        -0.5,
        "héllo, wörld ✓",
        "/org/btrc/Test",
        "a{sv}(ii)",
        ["a", "bc", ""],
        {
            "name": GLib.Variant("s", "value"),
            "number": GLib.Variant("i", -7),
            "nested": GLib.Variant("a(ysv)", [(1, "row", GLib.Variant("ad", [1.5, 2.25]))]),
        },
        ("icon", [(1, 2, b"\x00\x01\x02")], "title", "description"),
        [(1, {"label": GLib.Variant("s", "Open"), "enabled": GLib.Variant("b", True)}), (2, {})],
        GLib.Variant("v", GLib.Variant("u", 5)),
        [],
    )
    body = GLib.Variant("(ybnqiuxtdsogasa{sv}(sa(iiay)ss)a(ia{sv})vax)", values)
    with private_bus() as address, _echo_service(executable, _environment(address)) as service:
        bus = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        # The writer end sees EPIPE after the message and its reader die.
        # The stand-in sends a real close-on-exec file descriptor, which the
        # native process reads through the public DBusReader API.
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"Q")
            descriptors = Gio.UnixFDList.new()
            index = descriptors.append(read_fd)
            os.close(read_fd)
            read_fd = -1
            result, _ = bus.call_with_unix_fd_list_sync(
                *ECHO,
                "ReadDescriptor",
                GLib.Variant("(h)", (index,)),
                GLib.VariantType("(y)"),
                Gio.DBusCallFlags.NONE,
                5000,
                descriptors,
                None,
            )
            assert result.unpack() == (ord("Q"),)
            for fd in descriptors.steal_fds():
                os.close(fd)
            # A second call advances the event loop past the descriptor-bearing message.
            bus.call_sync(*ECHO, "Order", None, None, Gio.DBusCallFlags.NONE, 5000, None)
            with pytest.raises(BrokenPipeError):
                os.write(write_fd, b"X")
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            os.close(write_fd)
        for order in (Gio.DBusMessageByteOrder.LITTLE_ENDIAN, Gio.DBusMessageByteOrder.BIG_ENDIAN):
            call = Gio.DBusMessage.new_method_call(*ECHO, "Echo")
            call.set_byte_order(order)
            call.set_body(body)
            reply, _serial = bus.send_message_with_reply_sync(call, Gio.DBusSendMessageFlags.NONE, 5000, None)
            assert reply.get_message_type() == Gio.DBusMessageType.METHOD_RETURN, reply.print_(0)
            assert reply.get_byte_order() == Gio.DBusMessageByteOrder.LITTLE_ENDIAN
            assert reply.get_body().print_(True) == body.print_(True)
            asked = Gio.DBusMessage.new_method_call(*ECHO, "Order")
            asked.set_byte_order(order)
            arrived, _serial = bus.send_message_with_reply_sync(asked, Gio.DBusSendMessageFlags.NONE, 5000, None)
            big = order == Gio.DBusMessageByteOrder.BIG_ENDIAN
            assert arrived.get_body().unpack() == ("big" if big else "little",)

        # No arguments at all, and an error reply.
        empty = bus.call_sync(*ECHO, "Echo", None, None, Gio.DBusCallFlags.NONE, 5000, None)
        assert empty.unpack() == ()
        with pytest.raises(GLib.Error, match=r"org\.btrc\.test\.Error\.Failed: asked to fail"):
            bus.call_sync(*ECHO, "Fail", None, None, Gio.DBusCallFlags.NONE, 5000, None)
        with pytest.raises(GLib.Error, match=r"org\.freedesktop\.DBus\.Error\.UnknownMethod"):
            bus.call_sync(*ECHO, "Missing", None, None, Gio.DBusCallFlags.NONE, 5000, None)
        with pytest.raises(GLib.Error, match=r"org\.freedesktop\.DBus\.Error\.UnknownObject"):
            bus.call_sync(ECHO[0], "/elsewhere", ECHO[2], "Echo", None, None, Gio.DBusCallFlags.NONE, 5000, None)

        # A signal this client emits, as GDBus hears it.
        heard = []
        bus.signal_subscribe(
            ECHO[0],
            ECHO[2],
            "Echoed",
            ECHO[1],
            None,
            Gio.DBusSignalFlags.NONE,
            lambda *signal: heard.append(signal[5].print_(True)),
        )
        told = GLib.Variant("(sua{sv})", ("told", 3, {"k": GLib.Variant("ay", b"\x01\x02")}))
        bus.call_sync(*ECHO, "Emit", told, None, Gio.DBusCallFlags.NONE, 5000, None)
        deadline = time.monotonic() + 10
        while not heard and time.monotonic() < deadline:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.01)
        assert heard == [told.print_(True)]

        large = GLib.Variant("(s)", ("x" * (2 * 1024 * 1024),))
        reply = bus.call_sync(*ECHO, "Echo", large, None, Gio.DBusCallFlags.NONE, 30000, None)
        assert reply.equal(large)


def test_dbus_client_serves_libdbus_tools(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """libdbus's dbus-send calls the object and reads its replies; dbus-monitor reads a signal it emits."""
    _require_host()
    dbus_send, dbus_monitor = shutil.which("dbus-send"), shutil.which("dbus-monitor")
    if dbus_send is None or dbus_monitor is None:
        pytest.skip("requires dbus-send and dbus-monitor: libdbus's tools are the other implementation here")
    executable = _program("DBusEcho", compiler, "gcc", False, tmp_path, request)
    with private_bus() as address, _echo_service(executable, _environment(address)):
        environment = _environment(address)

        def send(member: str, *arguments: str) -> subprocess.CompletedProcess[str]:
            command = [dbus_send, "--session", "--print-reply", f"--dest={ECHO[0]}", ECHO[1], f"{ECHO[2]}.{member}"]
            return subprocess.run([*command, *arguments], env=environment, capture_output=True, text=True, timeout=30)

        echoed = send(
            "Echo",
            "string:hello",
            "int32:-5",
            "uint16:3",
            "int64:-9000000000",
            "byte:9",
            "boolean:true",
            "double:1.5",
            "objpath:/org/btrc/Test",
            "array:string:a,bc",
            "dict:string:int32:one,1,two,2",
            "variant:uint32:7",
        )
        assert echoed.returncode == 0, echoed.stderr
        text = " ".join(echoed.stdout.split())
        for expected in (
            'string "hello"',
            "int32 -5",
            "uint16 3",
            "int64 -9000000000",
            "byte 9",
            "boolean true",
            "double 1.5",
            'object path "/org/btrc/Test"',
            'array [ string "a" string "bc" ]',
            'array [ dict entry( string "one" int32 1 ) dict entry( string "two" int32 2 ) ]',
            "variant uint32 7",
        ):
            assert expected in text, (expected, echoed.stdout)

        failed = send("Fail")
        assert failed.returncode != 0
        assert "org.btrc.test.Error.Failed: asked to fail" in failed.stderr

        log = tmp_path / "monitor.log"
        with log.open("w") as output:
            monitor = subprocess.Popen(
                [dbus_monitor, "--session", f"type='signal',interface='{ECHO[2]}'"],
                env=environment,
                stdout=output,
                stderr=subprocess.PIPE,
                text=True,
            )
        try:
            # The monitor prints the signals of its own registration first; then it is listening.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and "NameAcquired" not in log.read_text():
                assert monitor.poll() is None, monitor.communicate()
                time.sleep(0.02)
            assert send("Emit", "uint32:3", "string:told").returncode == 0
            while time.monotonic() < deadline and 'string "told"' not in log.read_text():
                time.sleep(0.02)
            seen = log.read_text()
            assert "member=Echoed" in seen and f"interface={ECHO[2]}" in seen and f"path={ECHO[1]}" in seen, seen
            assert "uint32 3" in seen and 'string "told"' in seen, seen
        finally:
            monitor.terminate()
            monitor.communicate(timeout=10)


def test_windows_has_no_dbus_transport(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Messages and addresses are plain BTRC everywhere; a connection needs a transport provider."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}

    def transpile(source: Path) -> subprocess.CompletedProcess[str]:
        if compiler == "python":
            command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
            command += ["--target", "windows-x86_64", "--no-cache", "-o", str(source.with_suffix(".c"))]
        else:
            btrcc = request.getfixturevalue("immutable_btrcc")
            command = [str(btrcc), "--strict-imports", "--target", "windows-x86_64", str(source)]
        return subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )

    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.DBus.DBusAddress;\nimport Library.DBus.DBusMessage;\n\n"
        'int main() { return DBusAddress.parse("unix:path=/x").len == 1 '
        '&& DBusMessage.signal("/a", "a.b", "C").signature().isEmpty() ? 0 : 1; }\n'
    )
    portable = transpile(values)
    assert portable.returncode == 0, portable.stderr
    for module in ("DBusConnection", "DBus"):
        source = tmp_path / f"{module}.btrc"
        source.write_text(f"import Library.DBus.{module};\n\nint main() {{ return 0; }}\n")
        refused = transpile(source)
        assert refused.returncode != 0
        assert "provider" in refused.stderr
