"""Android activity completion and failure diagnostics across asynchronous launches."""

from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from tools.target_hosts.android import gui


def test_gui_waits_for_the_program_to_publish_its_status(monkeypatch):
    runner = gui.GUIAppRunner("/sdk", "emulator-5554", "dev.btrc.testhost")
    runner.within = Mock()
    runner.front = Mock(return_value="")
    runner.settle = Mock(return_value=True)
    runner.adb = Mock()
    # A process can briefly appear in pidof while the launcher is still in front.
    # The program then creates an empty exit file before writing the status.
    pids = iter([b"17", b""])
    runner.adb.side_effect = lambda *args, **opts: Mock(stdout=next(pids, b"")) if "pidof" in args else Mock(stdout=b"")
    statuses = iter([None, None, None, b"", b"0\n"])
    runner.file = lambda name: next(statuses) if name == "exit.txt" else b""
    monkeypatch.setattr(gui.time, "sleep", lambda _: None)
    assert runner.run(timeout=3) == (0, "", "")


def test_gui_reads_exit_history_before_stopping_a_timed_out_app():
    runner = gui.GUIAppRunner("/sdk", "emulator-5554", "dev.btrc.testhost")
    runner.within = Mock()
    runner.front = Mock(return_value="current window")
    runner.settle = Mock(return_value=True)
    runner.file = Mock(return_value=None)
    runner.adb = Mock(return_value=Mock(stdout=b""))
    status, _, stderr = runner.run(timeout=0)
    assert status is None and "current window" in stderr and "no exit status" in stderr
    calls = [call.args for call in runner.adb.call_args_list]
    assert calls.index(("shell", "dumpsys", "activity", "exit-info", runner.package)) < len(calls) - 1
    assert calls[-1] == ("shell", "am", "force-stop", runner.package)


@pytest.mark.parametrize("message", [b"", b"error: closed\n"])
@pytest.mark.parametrize("second", [0, 42, 1])
def test_closed_adb_read_is_retried_once(second, message):
    runner = gui.GUIAppRunner("/sdk", "emulator-5554", "dev.btrc.testhost")
    value = b"0" if second == 0 else b""
    runner.within = Mock(side_effect=[CompletedProcess([], 1, b"", message), CompletedProcess([], second, value, b"")])
    if second == 1:
        with pytest.raises(RuntimeError, match="adb exit 1"):
            runner.file("exit.txt")
    else:
        assert runner.file("exit.txt") == (None if second == 42 else value)
    assert runner.within.call_count == 2
