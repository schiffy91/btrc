"""Compiler-selection contracts for the ownership sanitizer harness."""

from src.tests.btrc import runtime_ownership_harness as harness


def test_sanitizer_selection_falls_back_after_a_broken_runtime(
    monkeypatch,
    tmp_path,
):
    broken = harness.SanitizerToolchain(("broken-cc",))
    working = harness.SanitizerToolchain(("working-cc",))
    probes = []

    monkeypatch.setattr(
        harness,
        "_sanitizer_candidates",
        lambda: (broken, working),
    )

    def probe(candidate, _tmp_path, index):
        probes.append((candidate.command, index))
        return "runtime crashed" if candidate is broken else None

    monkeypatch.setattr(harness, "_probe_sanitizer_candidate", probe)

    selected = harness._select_sanitizer_toolchain(tmp_path)

    assert selected is working
    assert probes == [(broken.command, 0), (working.command, 1)]


def test_explicit_compiler_override_remains_first_candidate(monkeypatch):
    monkeypatch.setenv("BTRC_CC", "custom-cc")
    monkeypatch.setattr(harness, "CC", ["custom-cc", "--driver-flag"])
    monkeypatch.setattr(harness.shutil, "which", lambda name, path=None: name)
    monkeypatch.setattr(harness.os, "access", lambda path, mode: True)
    monkeypatch.setattr(harness.sys, "platform", "darwin")

    candidates = harness._sanitizer_candidates()

    assert candidates[0].command == ("custom-cc", "--driver-flag")
    assert candidates[1].command == ("/usr/bin/clang",)
