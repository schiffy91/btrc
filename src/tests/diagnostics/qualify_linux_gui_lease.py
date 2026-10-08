"""One bounded hosted qualification of the reviewed Linux pytest session lease."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PINS = json.loads((HERE / "linux_gui_lease_pins.json").read_text())
COORD = "src/tests/python/test_macos_gui_coordination.py"
DIAG = "src/tests/diagnostics/test_native_ui_scroll_focus_diagnostic.py"
SHELL = "src/tests/python/test_native_ui_shell_linux.py"
EVIDENCE = ROOT / "evidence"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", "-c", f"safe.directory={root}", "-C", str(root), *args], text=True)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def tracked(root, revision="HEAD"):
    rows = {}
    for row in git(root, "ls-tree", "-rz", revision).split("\0"):
        if row:
            info, name = row.split("\t", 1)
            mode, kind, oid = info.split()
            assert kind == "blob" and mode in {"100644", "100755"}, (name, mode, kind)
            rows[name] = {"mode": mode, "blob": oid}
    return rows


def snapshot(root, paths):
    values = {}
    for name in sorted(paths):
        path = root / name
        assert path.is_file() and not path.is_symlink(), path
        values[name] = {"sha256": digest(path), "mode": stat.S_IMODE(path.stat().st_mode)}
    for prefix in ("src", "tools"):
        actual = {str(p.relative_to(root)) for p in (root / prefix).rglob("*") if p.is_file() or p.is_symlink()}
        expected = {p for p in paths if p.startswith(prefix + "/")}
        assert actual == expected, (prefix, sorted(actual ^ expected))
    return values


def host():
    baseline = ROOT.parent / "baseline"
    assert os.environ["CANDIDATE_SHA"] == PINS["candidate"]
    assert digest(HERE / "linux_gui_lease_pins.json") == os.environ["PINS_SHA256"]
    base = tracked(baseline)
    assert git(baseline, "rev-parse", "HEAD").strip() == PINS["base"]
    candidate = tracked(ROOT, PINS["candidate"])
    source = tracked(ROOT)
    assert set(candidate) == set(base)
    assert {n for n in base if base[n] != candidate[n]} == set(PINS["production"])
    for name, expected in PINS["production"].items():
        assert digest(ROOT / name) == expected
        assert candidate[name] == source[name] and candidate[name]["mode"] == base[name]["mode"]
    added = set(PINS["installed"]) | {"src/tests/diagnostics/linux_gui_lease_pins.json", ".github/workflows/linux-gui-lease-qualification.yml"}
    assert set(source) - set(base) == added and not set(base) - set(source)
    assert all(source[n] == candidate[n] for n in candidate)
    for name, spec in source.items():
        path = ROOT / name
        assert path.is_file() and not path.is_symlink()
        assert bool(path.stat().st_mode & 0o111) == (spec["mode"] == "100755"), name
        assert git(ROOT, "hash-object", name).strip() == spec["blob"], name
    for name, expected in PINS["installed"].items():
        assert digest(ROOT / name) == expected
    assert not git(ROOT, "diff", "--name-only") and not git(ROOT, "diff", "--cached", "--name-only")
    # Archive the actual original tree; the sole RED overlay is the new test.
    archive = EVIDENCE / "red-source.tar"
    subprocess.run(["git", "-C", str(baseline), "archive", "--format=tar", "-o", str(archive), PINS["base"]], check=True, timeout=60)
    red = ROOT / "red"
    assert not red.exists()
    red.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(red, filter="data")
    shutil.copyfile(ROOT / COORD, red / COORD)
    assert {n for n in base if (red / n).read_bytes() != (baseline / n).read_bytes()} == {COORD}
    write(EVIDENCE / "source-provenance.json", {"base": PINS["base"], "candidate": PINS["candidate"], "head": git(ROOT, "rev-parse", "HEAD").strip(), "base_tree": base, "candidate_tree": candidate, "source_tree": source, "red_archive_sha256": digest(archive), "red_overlay_sha256": digest(red / COORD)})
    (EVIDENCE / "index-before.txt").write_text(git(ROOT, "ls-files", "--stage"))


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def run(name, argv, cwd, env, seconds):
    directory = EVIDENCE / name
    directory.mkdir(parents=True, exist_ok=False)
    record = {"argv": [str(x) for x in argv], "cwd": str(cwd), "timeout_seconds": seconds, "started": time.time(), "environment": {k: env.get(k) for k in ("BTRC_TEST_BTRCC", "BTRC_TEST_RUNNER", "BTRC_TEST_TRANSPILE_TIMEOUT", "BTRC_TEST_RUN_TIMEOUT", "GUI_SESSION")}}
    write(directory / "command.json", record)
    with (directory / "stdout.log").open("wb") as out, (directory / "stderr.log").open("wb") as err:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True)
        try:
            code = child.wait(timeout=seconds)
        except BaseException:
            stop(child)
            record.update(returncode=child.returncode, interrupted=True, finished=time.time())
            write(directory / "result.json", record)
            raise
    record.update(returncode=code, finished=time.time(), stdout_sha256=digest(directory / "stdout.log"), stderr_sha256=digest(directory / "stderr.log"))
    write(directory / "result.json", record)
    print(f"LEASE_STAGE {name} exit={code}", flush=True)
    if code:
        print((directory / "stdout.log").read_text(errors="replace")[-16000:], flush=True)
        print((directory / "stderr.log").read_text(errors="replace")[-6000:], flush=True)
    return code


def junit(path):
    cases = list(ET.parse(path).iter("testcase"))
    keys = [(c.attrib["classname"], c.attrib["name"]) for c in cases]
    assert len(keys) == len(set(keys)), "Duplicate executed case identity"
    return cases


def identities(nodes):
    result = []
    for node in nodes:
        bits = node.split("::")
        result.append((bits[0][:-3].replace("/", ".") + ("." + ".".join(bits[1:-1]) if len(bits) > 2 else ""), bits[-1]))
    return result


def collect(name, root, selectors, env, session=None, *, concurrent=False):
    target = EVIDENCE / (name + "-nodes.json")
    plugin = EVIDENCE / "lease_inventory.py"
    plugin.write_text("""import json, os
from pathlib import Path

def pytest_collection_finish(session):
    nodes = []
    for item in session.items:
        node = item.nodeid
        if os.environ.get("LEASE_GROUPED") == "1":
            # xdist's loadgroup worker appends the sorted marker identities.
            groups = {str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                      for mark in item.iter_markers("xdist_group")}
            if groups:
                node += "@" + "_".join(sorted(groups))
        nodes.append(node)
    Path(os.environ["LEASE_COLLECTION"]).write_text(json.dumps(nodes))
""")
    environment = env | {"PYTHONPATH": os.pathsep.join([str(EVIDENCE), str(root)]), "LEASE_COLLECTION": str(target), "LEASE_GROUPED": "1" if concurrent else "0"}
    argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "lease_inventory", "-o", f"cache_dir={EVIDENCE / (name + '-cache')}", *selectors]
    if session:
        argv = [str(root / "tools/ui/headless-session.sh"), "--" + session, "--", *argv]
    assert run(name + "-collect", argv, root, environment, 180) == 0
    nodes = json.loads(target.read_text())
    assert nodes and len(nodes) == len(set(nodes))
    return nodes


def pytest_stage(name, root, selectors, env, count, *, red=False, session=None, concurrent=False):
    nodes = collect(name, root, selectors, env, session, concurrent=concurrent)
    assert len(nodes) == count, (name, len(nodes), count)
    directory = EVIDENCE / name
    argv = [sys.executable, "-m", "pytest", "-q", "-vv", "-ra", f"--basetemp={directory / 'pytest'}", f"--junitxml={directory / 'junit.xml'}", "-o", f"cache_dir={root / '.pytest_cache'}", *selectors]
    if concurrent:
        argv += ["-n4", "--dist=loadgroup"]
    if session:
        argv = [str(root / "tools/ui/headless-session.sh"), "--" + session, "--", *argv]
    status = run(name, argv, root, env, 2400)
    cases = junit(directory / "junit.xml")
    assert set(identities(nodes)) == {(c.attrib["classname"], c.attrib["name"]) for c in cases}
    assert not any(c.find("error") is not None or c.find("skipped") is not None for c in cases)
    failures = [c for c in cases if c.find("failure") is not None]
    if red:
        required = {
            "test_native_gui_lease_excludes_other_gui_workers_but_not_ordinary_work[linux]": "AssertionError: Native GUI workers overlapped",
            "test_all_known_linux_display_tests_claim_the_gui_session": "AssertionError: uncoordinated Linux display execution:",
        }
        assert status == 1 and len(failures) == 2
        assert {c.attrib["name"] for c in failures} == set(required)
        for case in failures:
            assert case.find("failure").attrib["message"].startswith(required[case.attrib["name"]]), case.find("failure").attrib
    else:
        assert status == 0 and not failures, (name, status, [c.attrib for c in failures])
    write(directory / "classification.json", {"expected_red": red, "cases": [c.attrib for c in cases], "failures": [c.attrib for c in failures], "native_window_overlap": "not-claimed; cooperating tests now hold a shared lease" if concurrent else "not-applicable"})


def selectors(root, session, label, env):
    query = EVIDENCE / "inventory.mk"
    query.write_text(".PHONY: lease-inventory\nlease-inventory:\n\t@printf '%s\\n' $(GUI_SHARD_TESTS)\n")
    assert run(label, ["make", "-s", "-f", "Makefile", "-f", str(query), "NIX=", f"GUI_SESSION={session}", "lease-inventory"], root, env, 60) == 0
    result = (EVIDENCE / label / "stdout.log").read_text().splitlines()
    assert result and all(x.startswith("src/tests/python/") for x in result)
    assert all("diagnostic" not in x for x in result)
    return result


def inside(session):
    assert session in {"x11", "wayland"} and sys.platform == "linux"
    assert os.uname().machine == "x86_64"
    environment = dict(os.environ)
    for key in ("MAKEFLAGS", "PYTEST_ADDOPTS", "BTRC_TEST_BTRCC", "BTRC_TIMING", "PYTEST_WORKERS", "PYTEST_ARGS"):
        environment.pop(key, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", BTRC_TEST_RUNNER="linux-devcontainer", ALSA_CONFIG_PATH=str(ROOT / "nix/asound.conf"))
    provenance = json.loads((EVIDENCE / "source-provenance.json").read_text())
    paths = provenance["source_tree"]
    initial = snapshot(ROOT, paths)
    write(EVIDENCE / "inputs-before.json", initial)
    red = ROOT / "red"
    red_initial = snapshot(red, provenance["base_tree"])
    write(EVIDENCE / "red-inputs-before.json", red_initial)
    donor = ROOT / "donor/B/bin/btrcc"
    tools = {}
    failed = None
    try:
        assert digest(donor) == PINS["donor_binary"]
        assert digest(ROOT / "donor/B/dist/btrcc.c") == PINS["donor_c"]
        tools = {name: {"path": shutil.which(name), "sha256": digest(Path(shutil.which(name)))} for name in ("cc", "c++", "python3", "make", "pkg-config")}
        # The image exports its full pinned shell through BASH_ENV; enter Bash
        # before this Python process exactly as original Make/shell jobs do.
        shell = Path(os.environ["BASH_ENV"])
        assert shell.is_file() and not shell.is_symlink()
        native_environment = {name: os.environ[name] for name in ("BTRC_NATIVE_HEADER_READER", "BTRC_NATIVE_TARGET", "BTRC_NATIVE_SYSROOT")}
        assert native_environment["BTRC_NATIVE_TARGET"] == "x86_64-unknown-linux-gnu"
        assert Path(native_environment["BTRC_NATIVE_SYSROOT"]).is_dir()
        assert all(value.startswith("/nix/store/") for name, value in native_environment.items() if name != "BTRC_NATIVE_TARGET")
        tools["image_shell"] = {"path": str(shell), "sha256": digest(shell)}
        write(EVIDENCE / "native-shell-environment.json", native_environment | {"shell_path": str(shell), "shell_sha256": digest(shell), "entry": "image Bash loads original BASH_ENV then execs unchanged Python qualifier"})
        reader = Path(native_environment["BTRC_NATIVE_HEADER_READER"])
        assert reader.is_file() and os.access(reader, os.X_OK)
        tools["native_reader"] = {"path": str(reader), "sha256": digest(reader)}
        assert tools["cc"]["sha256"] == (ROOT / "donor/evidence/cc-sha256.txt").read_text().split()[0]
        write(EVIDENCE / "tools-before.json", tools)
        assert run("cc-version", [tools["cc"]["path"], "--version"], ROOT, environment, 30) == 0
        assert run("python-version", [sys.executable, "--version"], ROOT, environment, 30) == 0
        if session == "x11":
            pytest_stage("lease-red", red, [COORD + "::test_native_gui_lease_excludes_other_gui_workers_but_not_ordinary_work[linux]", COORD + "::test_all_known_linux_display_tests_claim_the_gui_session"], environment, 2, red=True)
            pytest_stage("lease-green", ROOT, [COORD], environment, 16)
            focused = environment | {"BTRC_TEST_BTRCC": str(donor)}
            pytest_stage("controlled", ROOT, [DIAG + "::test_scroll_focus_diagnostic[focus-loss-plain-python]"], focused, 1, session="x11")
            positive = [DIAG + f"::test_scroll_focus_diagnostic[{mode}-{sanitizer}-{frontend}]" for mode in ("original", "trace") for sanitizer in ("plain", "sanitized") for frontend in ("python", "selfhost")]
            pytest_stage("isolated", ROOT, positive, focused, 8, session="x11")
            pytest_stage("concurrent", ROOT, [*positive, SHELL + "::test_linux_native_shell"], focused, 12, session="x11", concurrent=True)
        # Original Make computes the complete GUI inventory, unchanged by the
        # nine-file lease repair. This query adds no prerequisite/replacement.
        original = selectors(red, session, "original-selectors", environment)
        current = selectors(ROOT, session, "candidate-selectors", environment)
        assert original == current
        nodes = collect("full-gui", ROOT, current, environment, session)
        command = ["make", "NIX=", "PYTEST_WORKERS=4", "BTRC_TEST_TRANSPILE_TIMEOUT=600", "BTRC_TEST_RUN_TIMEOUT=60", f"GUI_SESSION={session}", "test-shard-gui"]
        status = run("full-gui", command, ROOT, environment, 5400)
        results = ROOT / f"build/linux-gui/{session}/junit.xml"
        cases = junit(results)
        assert set(identities(nodes)) == {(c.attrib["classname"], c.attrib["name"]) for c in cases}, "Original GUI case inventory changed"
        assert status == 0 and not any(c.find("failure") is not None or c.find("error") is not None for c in cases), "Original GUI Make/skip gate failed"
        report = ROOT / f"build/skip-report-gui-{session}.json"
        assert report.is_file()
        write(EVIDENCE / "full-gui/accepted.json", {"session": session, "cases": len(cases), "skipped": sum(c.find("skipped") is not None for c in cases), "junit_sha256": digest(results), "skip_report_sha256": digest(report), "original_make_including_skip_gate": "passed", "built_compiler": digest(ROOT / "bin/btrcc")})
    except BaseException as error:
        failed = repr(error)
        raise
    finally:
        try:
            after = snapshot(ROOT, paths)
            write(EVIDENCE / "inputs-after.json", after)
            assert after == initial
            red_after = snapshot(red, provenance["base_tree"])
            write(EVIDENCE / "red-inputs-after.json", red_after)
            assert red_after == red_initial
            index_after = git(ROOT, "ls-files", "--stage")
            (EVIDENCE / "index-after.txt").write_text(index_after)
            assert index_after == (EVIDENCE / "index-before.txt").read_text()
            assert not git(ROOT, "diff", "--name-only") and not git(ROOT, "diff", "--cached", "--name-only")
            assert digest(donor) == PINS["donor_binary"]
            assert all(digest(Path(t["path"])) == t["sha256"] for t in tools.values())
        except BaseException as audit_error:
            write(EVIDENCE / "postchecks.json", {"state": "failed", "error": repr(audit_error)})
            write(EVIDENCE / "terminal.json", {"state": "failed", "stage_error": failed, "audit_error": repr(audit_error), "session": session})
            raise
        write(EVIDENCE / "postchecks.json", {"state": "passed", "input_inventory": digest(EVIDENCE / "inputs-after.json"), "index_unchanged": True, "tools_unchanged": True, "donor_unchanged": True})
        write(EVIDENCE / "terminal.json", {"state": "failed" if failed else "passed", "error": failed, "session": session})



def terminated(signum, frame):
    raise KeyboardInterrupt("qualification received SIGTERM")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, terminated)
    if sys.argv[1:] == ["host"]:
        host()
    elif len(sys.argv) == 3 and sys.argv[1] == "inside":
        inside(sys.argv[2])
    else:
        raise SystemExit("host | inside x11|wayland")
