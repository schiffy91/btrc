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


def test_explicit_apple_clang_keeps_its_isolated_fallback(monkeypatch, tmp_path):
    isolated = {"PATH": "/usr/bin:/bin"}
    monkeypatch.setenv("BTRC_CC", "/usr/bin/clang")
    monkeypatch.setattr(harness, "CC", ["/usr/bin/clang"])
    monkeypatch.setattr(harness, "HOST_CLANG", "/usr/bin/clang")
    monkeypatch.setattr(harness, "HOST_GCC", None)
    monkeypatch.setattr(harness, "_host_clang_environment", lambda: isolated)
    monkeypatch.setattr(harness.shutil, "which", lambda name, path=None: name)
    monkeypatch.setattr(harness.os, "access", lambda path, mode: True)
    monkeypatch.setattr(harness.sys, "platform", "darwin")
    monkeypatch.setattr(
        harness,
        "_probe_sanitizer_candidate",
        lambda candidate, _path, _index: None if candidate.environment == isolated else "incompatible runtime",
    )

    candidates = harness._sanitizer_candidates()
    assert [(candidate.command, candidate.environment) for candidate in candidates] == [
        (("/usr/bin/clang",), None),
        (("/usr/bin/clang",), isolated),
    ]
    assert harness._select_sanitizer_toolchain(tmp_path).environment == isolated
