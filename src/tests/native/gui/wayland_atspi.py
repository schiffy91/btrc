"""Drive the public Wayland sample with the desktop's AT-SPI client library."""

import ast
import ctypes
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

from src.tests.python.test_wayland_public_preview import empty_root_command
from tools.qualification.dependencies import BinaryImports, DependencyAudit


def function(library, name, result, *arguments):
    method = getattr(library, name)
    method.restype = result
    method.argtypes = list(arguments)
    return method


def announced(log, expected):
    for line in Path(log).read_text(errors="replace").splitlines():
        if ":DATA:|<speak>" in line and "</speak>" in line:
            message = line[line.index("<speak>") : line.index("</speak>") + len("</speak>")]
            if expected in " ".join("".join(ET.fromstring(message).itertext()).split()):
                return True
    return False


def exercise_field(library, entry, iterate):
    pointer, integer, string = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p

    class Range(ctypes.Structure):
        _fields_ = [("start", integer), ("end", integer)]

    class Event(ctypes.Structure):
        _fields_ = [("kind", string), ("source", pointer), ("position", integer), ("length", integer)]

    events = []
    callback_type = ctypes.CFUNCTYPE(None, ctypes.POINTER(Event), pointer)

    @callback_type
    def record(event, _):
        value = event.contents
        events.append((value.kind.decode(), value.position, value.length))

    listener = function(library, "atspi_event_listener_new", pointer, callback_type, pointer, pointer)(
        record, None, None
    )
    register = function(library, "atspi_event_listener_register", integer, pointer, string, pointer)
    event_names = [b"object:text-changed", b"object:text-caret-moved", b"object:text-selection-changed"]
    for kind in event_names:
        assert register(listener, kind, None)

    text = function(library, "atspi_accessible_get_text_iface", pointer, pointer)(entry)
    editable = function(library, "atspi_accessible_get_editable_text_iface", pointer, pointer)(entry)
    assert text and editable

    def call(name, result, types, *params):
        target = editable if name.startswith("editable_text_") else text
        return function(library, "atspi_" + name, result, pointer, *types, pointer)(target, *params, None)

    def contents():
        return call("text_get_text", string, [integer, integer], 0, -1).decode()

    try:
        assert contents() == "Aé🌿Z"
        assert call("text_get_character_count", integer, []) == 5
        assert call("text_get_character_at_offset", ctypes.c_uint, [integer], 3) == ord("🌿")
        assert call("text_get_text", string, [integer, integer], 1, 3) == "é".encode()
        assert not call("text_set_caret_offset", integer, [integer], 2)
        assert call("text_set_caret_offset", integer, [integer], 1)
        assert call("text_get_caret_offset", integer, []) == 1
        assert call("text_add_selection", integer, [integer, integer], 1, 3)
        assert call("text_get_n_selections", integer, []) == 1
        selection = call("text_get_selection", ctypes.POINTER(Range), [integer], 0).contents
        assert (selection.start, selection.end) == (1, 3)
        assert call("text_remove_selection", integer, [integer], 0)
        assert not call("editable_text_delete_text", integer, [integer, integer], 2, 3)
        assert contents() == "Aé🌿Z"
        assert call("editable_text_delete_text", integer, [integer, integer], 1, 3)
        assert contents() == "A🌿Z"
        assert call("editable_text_insert_text", integer, [integer, string, integer], 1, "éunused".encode(), 2)
        assert contents() == "Aé🌿Z"
        assert call("editable_text_set_text_contents", integer, [string], "完成".encode())
        assert contents() == "完成"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            while iterate(None, False):
                pass
            if all(any(kind.startswith(name.decode()) for kind, _, _ in events) for name in event_names):
                break
            time.sleep(0.02)
        assert ("object:text-changed:delete", 1, 2) in events, events
        assert ("object:text-changed:insert", 1, 1) in events, events
        assert any(kind.startswith("object:text-caret-moved") for kind, _, _ in events), events
        assert any(kind.startswith("object:text-selection-changed") for kind, _, _ in events), events
    finally:
        unregister = function(library, "atspi_event_listener_deregister", integer, pointer, string, pointer)
        for kind in event_names:
            unregister(listener, kind, None)


def wait_for_speech(log, expected, iterate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if announced(log, expected):
            return
        while iterate(None, False):
            pass
        time.sleep(0.05)
    raise AssertionError(f"Orca did not send {expected!r} to Speech Dispatcher")


def drive_modal_alerts(app, root, children, identity, state, click, iterate, read_text, set_text):
    def eventually(read):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            while iterate(None, False):
                pass
            value = read()
            if value:
                return value
            time.sleep(0.05)
        raise AssertionError("accessible modal state did not arrive")

    def frames():
        return {identity(window): window for application in children(root) for window in children(application)}

    def button(parent, title):
        return next((node for node in children(parent) if identity(node) == (43, title)), None)

    for title, detail in (
        ("Keyboard alert", "Press Escape to dismiss this message."),
        ("Pointer alert", "Click the Close button."),
        ("Long alert", "Final line of the alert"),
    ):
        dialog = eventually(lambda title=title: frames().get((16, title)))
        assert state(dialog, 16)  # ATSPI_STATE_MODAL
        parent = frames()[(23, "btrc input and pixels")]
        owner_button = eventually(lambda parent=parent: button(parent, "Parent action"))
        assert not state(owner_button, 24) and not click(owner_button)
        entry = next(node for node in children(parent) if identity(node) == (79, "Owner field"))
        assert not state(entry, 7) and not set_text(entry, b"Blocked") and read_text(entry) == b"Existing"
        labels = [name for role, name in map(identity, children(dialog)) if role == 29]
        assert title in labels and any(detail in name for name in labels)
        close = eventually(lambda dialog=dialog: button(dialog, "Close"))
        assert state(close, 24) and click(close)

    def enabled_parent_button():
        parent = frames().get((23, "btrc input and pixels"))
        control = button(parent, "Parent action") if parent else None
        return control if control and state(control, 24) else None

    owner_button = eventually(enabled_parent_button)
    owner = frames()[(23, "btrc input and pixels")]
    entry = next(node for node in children(owner) if identity(node) == (79, "Owner field"))
    assert state(entry, 7) and set_text(entry, b"Released") and read_text(entry) == b"Released"
    assert click(owner_button)
    output, _ = app.communicate(timeout=8)
    assert app.returncode == 0 and output.splitlines() == [
        "keyboard dismissed",
        "pointer dismissed",
        "close requested",
        "parent click",
    ]
    print("AT-SPI dismissed three native modal dialogs and restored the owner action", flush=True)


def main(executable, directory, option=None, orca_trace=None):
    field_test = option == "--field"
    if not field_test:
        orca_trace = option
    library = ctypes.CDLL("libatspi.so.0")
    pointer, integer, string = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
    init = function(library, "atspi_init", integer)
    desktop = function(library, "atspi_get_desktop", pointer, integer)
    count = function(library, "atspi_accessible_get_child_count", integer, pointer, pointer)
    child = function(library, "atspi_accessible_get_child_at_index", pointer, pointer, integer, pointer)
    name = function(library, "atspi_accessible_get_name", string, pointer, pointer)
    role = function(library, "atspi_accessible_get_role", integer, pointer, pointer)
    states = function(library, "atspi_accessible_get_state_set", pointer, pointer)
    has_state = function(library, "atspi_state_set_contains", integer, pointer, integer)
    component = function(library, "atspi_accessible_get_component_iface", pointer, pointer)
    focus = function(library, "atspi_component_grab_focus", integer, pointer, pointer)
    action = function(library, "atspi_accessible_get_action_iface", pointer, pointer)
    action_name = function(library, "atspi_action_get_action_name", string, pointer, integer, pointer)
    perform = function(library, "atspi_action_do_action", integer, pointer, integer, pointer)
    iterate = function(ctypes.CDLL("libglib-2.0.so.0"), "g_main_context_iteration", integer, pointer, integer)

    assert not DependencyAudit().binary_problems(Path(executable), f"linux-{platform.machine()}")
    assert not any("atspi" in item or "dbus" in item for item in BinaryImports.read(Path(executable)))
    # The accessibility bus is itself an OS service outside the app namespace.
    address = subprocess.check_output(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.a11y.Bus",
            "--object-path",
            "/org/a11y/bus",
            "--method",
            "org.a11y.Bus.GetAddress",
        ],
        text=True,
    )
    value = ast.literal_eval(address)[0]
    socket = unquote(value.split("unix:path=", 1)[1].split(",", 1)[0])
    options = ["--ro-bind", socket, "/run/gui/a11y", "--setenv", "AT_SPI_BUS_ADDRESS", "unix:path=/run/gui/a11y"]
    command = empty_root_command(executable, directory, options)
    assert init() == 0
    root = desktop(0)
    assert root
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as app:
        try:
            if orca_trace == "--alerts":
                text_iface = function(library, "atspi_accessible_get_text_iface", pointer, pointer)
                edit_iface = function(library, "atspi_accessible_get_editable_text_iface", pointer, pointer)
                get_text = function(library, "atspi_text_get_text", string, pointer, integer, integer, pointer)
                set_contents = function(
                    library, "atspi_editable_text_set_text_contents", integer, pointer, string, pointer
                )
                drive_modal_alerts(
                    app,
                    root,
                    lambda obj: [child(obj, i, None) for i in range(count(obj, None))],
                    lambda obj: (role(obj, None), (name(obj, None) or b"").decode()),
                    lambda obj, flag: has_state(states(obj), flag),
                    lambda obj: perform(action(obj), 0, None),
                    iterate,
                    lambda node: get_text(text_iface(node), 0, -1, None),
                    lambda node, value: set_contents(edit_iface(node), value, None),
                )
                return
            end = time.monotonic() + 15
            button = None
            while time.monotonic() < end:
                assert app.poll() is None
                while iterate(None, False):
                    pass
                for i in range(count(root, None)):
                    application = child(root, i, None)
                    if not application or role(application, None) != 75:
                        continue
                    for j in range(count(application, None)):
                        window = child(application, j, None)
                        if not window or role(window, None) != 23:
                            continue
                        controls = [child(window, k, None) for k in range(count(window, None))]
                        entries = {(role(c, None), name(c, None)): c for c in controls if c}
                        if (29, b"Native Wayland") in entries and (43, b"Quit") in entries:
                            if orca_trace and not has_state(states(window), 1):
                                continue
                            assert name(window, None)
                            if field_test:
                                field = entries.get((79, b"Message"))
                                if not field:
                                    continue
                                assert all(has_state(states(field), state) for state in (7, 8, 11, 26))
                                assert focus(component(field), None)
                                if orca_trace:
                                    wait_for_speech(orca_trace, "Message entry Aé🌿Z.", iterate)
                                exercise_field(library, field, iterate)
                            button = entries[(43, b"Quit")]
                            break
                if button:
                    break
                time.sleep(0.05)
            assert button, "AT-SPI registry did not expose the Wayland window, label and Quit button"
            available = states(button)
            assert all(has_state(available, state) for state in (8, 11, 24, 25, 30))
            assert focus(component(button), None)
            deadline = time.monotonic() + 4
            while not has_state(states(button), 12) and time.monotonic() < deadline:
                while iterate(None, False):
                    pass
                time.sleep(0.02)
            assert has_state(states(button), 12), "Quit did not receive AT-SPI focus"
            if orca_trace:
                wait_for_speech(orca_trace, "Quit button.", iterate)
            actions = action(button)
            assert actions and action_name(actions, 0, None) == b"click"
            assert perform(actions, 0, None)
            output, _ = app.communicate(timeout=5)
            expected = ["Clicked Quit"]
            if field_test:
                expected = ["Draft A🌿Z", "Draft Aé🌿Z", "Draft 完成", "Final 完成", *expected]
            assert (app.returncode, output.splitlines()) == (0, expected), output
            if field_test:
                print(
                    "AT-SPI Unicode content, caret, selection, edits, events and public draft callbacks verified",
                    flush=True,
                )
            print("AT-SPI window, label, button, states and Quit verified", flush=True)
        finally:
            if app.poll() is None:
                app.kill()


if __name__ == "__main__":
    main(*sys.argv[1:])
