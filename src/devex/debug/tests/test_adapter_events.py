"""Focused event translation regressions for the DAP adapter."""

import types

import adapter_events

from src.devex.debug.tests.adapter_test_support import FakeSession, request
from src.devex.debug.tests.adapter_test_support import adapter as make_adapter


def test_output_decoder_preserves_utf8_split_across_lldb_chunks():
    instance = make_adapter(request("threads"), FakeSession())

    instance._output("stdout", b"\xe2\x82")
    assert instance.writer.events == []
    instance._output("stdout", b"\xac")
    instance._output("stderr", b"\xe2")
    instance._flush_output_decoders()

    assert instance.writer.events == [
        ("output", {"category": "stdout", "output": "\u20ac"}),
        ("output", {"category": "stderr", "output": "\ufffd"}),
    ]


def test_reasonless_non_restarted_stop_is_reported_as_pause(monkeypatch):
    class SelectedThread:
        def IsValid(self):
            return True

        def GetThreadID(self):
            return 17

    class ReasonlessProcess:
        def __iter__(self):
            return iter(())

        def GetSelectedThread(self):
            return SelectedThread()

    monkeypatch.setattr(
        adapter_events,
        "lldb",
        types.SimpleNamespace(eStopReasonNone=0, eStopReasonInvalid=1),
    )
    session = FakeSession()
    session.process = ReasonlessProcess()
    session.reset_handles = lambda: None
    instance = make_adapter(request("pause"), session)

    instance._on_stop()

    assert instance.writer.events == [
        (
            "stopped",
            {"reason": "pause", "threadId": 17, "allThreadsStopped": True},
        )
    ]
