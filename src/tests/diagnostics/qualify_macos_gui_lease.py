"""One main-based AppKit lease qualification; original native gate owns acceptance."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path.cwd().resolve()
PINS = json.loads(Path(__file__).with_name('macos_gui_lease_pins.json').read_text())
OUT = ROOT / 'build/macos-gui-lease'
BASE = Path(os.environ['RUNNER_TEMP']) / 'macos-gui-lease-baseline'
MODULE = 'src/tests/python/test_macos_gui_coordination.py'
RED = {
    'test_macos_gui_lease_excludes_other_gui_workers_but_not_ordinary_work': 'AppKit workers overlapped',
    'test_all_known_appkit_execution_tests_claim_the_gui_session': 'uncoordinated AppKit execution:',
}
GREEN = set(RED) | {
    'test_macos_gui_lease_releases_after_failed_or_dead_owner[exception]',
    'test_macos_gui_lease_releases_after_failed_or_dead_owner[process-death]',
    'test_macos_gui_marker_does_not_serialize_non_macos_workers',
    'test_macos_gui_lease_covers_fixture_teardown',
    'test_macos_gui_lease_timeout_reports_holder_and_keeps_it_exclusive',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], timeout=60)


def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')


def run(label, argv, cwd=ROOT, timeout=120, addenv=None):
    env = os.environ | {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(cwd), 'PYTEST_ADDOPTS': ''} | (addenv or {})
    start = time.monotonic()
    with (OUT / (label + '.stdout')).open('wb') as stdout, (OUT / (label + '.stderr')).open('wb') as stderr:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            status = child.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=10)
            save(label + '.process.json', {'argv': argv, 'cwd': str(cwd), 'returncode': child.returncode, 'interrupted': True, 'seconds': time.monotonic() - start})
            raise
    save(label + '.process.json', {'argv': argv, 'cwd': str(cwd), 'returncode': status, 'seconds': time.monotonic() - start})
    return status


def cases(path):
    found = ET.parse(path).findall('.//testcase')
    result = {(c.attrib['classname'], c.attrib['name']): c for c in found}
    assert len(result) == len(found) and found, 'duplicate/missing JUnit identities'
    return result


def inputs():
    rows = {}
    for raw in git('ls-tree', '-rz', '--full-tree', PINS['candidate']).split(b'\0'):
        if not raw:
            continue
        metadata, name = raw.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        path = name.decode()
        assert kind == 'blob' and mode in ('100644', '100755'), path
        actual = ROOT / path
        assert actual.is_file() and not actual.is_symlink(), path
        assert git('hash-object', '--', path).decode().strip() == oid, path
        assert bool(actual.stat().st_mode & 0o111) == (mode == '100755'), path
        rows[path] = {'git_blob': oid, 'sha256': sha(actual), 'mode': mode}
    # Only the reviewed diagnostic installation may extend source/tool directories.
    for directory in ('src', 'tools'):
        actual = {str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob('*') if p.is_file() or p.is_symlink()}
        expected = {p for p in rows if p.startswith(directory + '/')} | {p for p in PINS['install_paths'] if p.startswith(directory + '/')}
        assert actual == expected, sorted(actual ^ expected)
    for path, digest in PINS['install'].items():
        assert sha(ROOT / path) == digest, path
    return rows


def selection(cwd):
    query = OUT / 'selection.mk'
    query.write_text('include Makefile\n.PHONY: lease-selection\nlease-selection:\n\t@printf "%s\\n" $(NATIVE_GUI_TESTS)\n')
    return subprocess.check_output(['make', '--no-print-directory', '-f', str(query), 'NIX=', 'lease-selection'], cwd=cwd, timeout=30).decode().splitlines()


def main():
    assert sys.platform == 'darwin' and os.uname().machine == 'arm64'
    assert len(PINS['candidate']) == 40 and PINS['candidate'] != '0' * 40, 'candidate pin unresolved'
    assert not OUT.exists() and not BASE.exists(), 'evidence must be fresh'
    OUT.mkdir(parents=True)
    assert git('status', '--porcelain', '--untracked-files=no') == b''
    assert git('rev-parse', 'HEAD').decode().strip() == os.environ['GITHUB_SHA']
    assert git('rev-parse', 'HEAD^').decode().strip() == PINS['candidate']
    assert git('diff', '--name-only', PINS['candidate'], 'HEAD').decode().splitlines() == sorted(PINS['install_paths'])
    assert git('diff', '--name-only', PINS['base'], PINS['candidate']).decode().splitlines() == sorted(PINS['owned'])
    for path, expected in PINS['owned'].items():
        assert sha(ROOT / path) == expected['sha256'], path
    save('publication.json', {'head': git('rev-parse', 'HEAD').decode().strip(), 'candidate': PINS['candidate'], 'base': PINS['base'], 'pins_sha256': sha(Path(__file__).with_name('macos_gui_lease_pins.json')), 'runner_sha256': sha(Path(__file__)), 'workflow_sha256': sha(ROOT / '.github/workflows/macos-gui-lease-qualification.yml')})
    before = inputs()
    index = git('ls-files', '--stage')
    save('inputs-before.json', before)
    (OUT / 'index-before.txt').write_bytes(index)
    archive = OUT / 'baseline.tar'
    archive.write_bytes(git('archive', PINS['base']))
    BASE.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(BASE, filter='data')
    shutil.copyfile(ROOT / MODULE, BASE / MODULE)
    save('baseline-overlay.json', {'base': PINS['base'], 'archive_sha256': sha(archive), 'only_overlay': MODULE, 'sha256': sha(BASE / MODULE)})
    status = 'failed'
    try:
        tool_paths = [Path(sys.executable), Path(shutil.which('clang')), Path('/usr/bin/clang'), Path(os.environ['BTRC_NATIVE_HEADER_READER'])]
        tools_before = {str(p): sha(p.resolve()) for p in tool_paths}
        save('tools-before.json', tools_before)
        assert run('tools', [sys.executable, '-c', 'import json,os,platform,subprocess,sys; print(json.dumps(dict(python=sys.executable,version=sys.version,platform=platform.platform(),environment={k:v for k,v in os.environ.items() if k.startswith("BTRC_") or k in ("SDKROOT","DEVELOPER_DIR","CC","CXX")}))); subprocess.run(["clang","--version"],check=True); subprocess.run(["/usr/bin/clang","--version"],check=True)']) == 0
        redxml = OUT / 'coordination-red.xml'
        assert run('coordination-red', [sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', *[MODULE + '::' + x for x in RED], '--junitxml=' + str(redxml)], cwd=BASE) == 1
        red = cases(redxml)
        assert {name for _, name in red} == set(RED) and len(red) == 2
        for (_, name), case in red.items():
            assert case.find('error') is None and case.find('skipped') is None
            failure = case.find('failure')
            assert failure is not None and failure.attrib.get('message', '').startswith('AssertionError: ' + RED[name]), name
        greenxml = OUT / 'coordination-green.xml'
        assert run('coordination-green', [sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', MODULE, '--junitxml=' + str(greenxml)]) == 0
        green = cases(greenxml)
        assert {name for _, name in green} == GREEN and len(green) == 7
        assert all(not any(c.find(tag) is not None for tag in ('error', 'failure', 'skipped')) for c in green.values())
        selected = selection(ROOT)
        assert selected == selection(BASE) and selected
        save('native-selectors.json', selected)
        plugin = OUT / 'lease_collection.py'
        collection = OUT / 'native-collection.json'
        plugin.write_text('import json\nfrom pathlib import Path\ndef pytest_collection_finish(session):\n    Path(' + repr(str(collection)) + ').write_text(json.dumps([(i.nodeid.split("::")[0][:-3].replace("/", "."), i.name) for i in session.items]))\n')
        assert run('native-collect', [sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', '--collect-only', '-p', 'lease_collection', *selected], addenv={'PYTHONPATH': os.pathsep.join([str(OUT), str(ROOT)])}, timeout=180) == 0
        expected = [tuple(x) for x in json.loads(collection.read_text())]
        assert len(expected) == len(set(expected)) and len(expected) == 394, 'review native inventory drift'
        native = OUT / 'native-gui.xml'
        code = run('native-gui', ['make', 'NIX=', 'PYTEST_WORKERS=3', 'BTRC_TEST_TRANSPILE_TIMEOUT=600', 'BTRC_TEST_RUN_TIMEOUT=60', 'test-native-gui'], timeout=4800, addenv={'PYTEST_ADDOPTS': '--junitxml=' + str(native) + ' --basetemp=' + str(OUT / 'pytest')})
        observed = cases(native)
        assert set(observed) == set(expected), 'incomplete or unexpected native inventory'
        # Original Make includes its original expected-skip gate. A native failure stays red.
        assert code == 0, 'original native GUI target failed; inspect retained Program.c/JUnit/logs'
        assert all(not any(c.find(tag) is not None for tag in ('error', 'failure')) for c in observed.values())
        assert observed[('src.tests.python.test_native_webgpu_imports', 'test_native_gpu_child_renders_and_reads_pixels[selfhost-Portable-True]')].find('skipped') is None
        status = 'passed'
    finally:
        try:
            assert inputs() == before and git('ls-files', '--stage') == index
            if 'tools_before' in locals():
                assert {str(p): sha(p.resolve()) for p in tool_paths} == tools_before
                save('tools-after.json', tools_before)
            assert git('status', '--porcelain', '--untracked-files=no') == b''
            save('inputs-after.json', before)
            outputs = {str(p.relative_to(OUT)): sha(p) for p in OUT.rglob('*') if p.is_file() and p.name != 'result.json' and not p.is_symlink()}
            save('output-inventory.json', outputs)
        except BaseException:
            status = 'failed-source-audit'
            raise
        finally:
            save('result.json', {'status': status, 'base': PINS['base'], 'candidate': PINS['candidate'], 'scope': 'AppKit process coordination plus original three-worker native GUI target; no historical GPU cause inference'})


def terminated(signum, frame):
    raise KeyboardInterrupt('qualification received SIGTERM')


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminated)
    main()
