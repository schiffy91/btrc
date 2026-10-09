"""Exact-source Linux Window close component qualification; no public UI2 claim."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from collections import Counter

sys.dont_write_bytecode = True
WORKSPACE = Path('/workspace')
COMPILER = WORKSPACE / 'compiler'
PROVIDER = WORKSPACE / 'provider'
EVIDENCE = WORKSPACE / 'evidence'
HERE = Path(__file__).resolve().parent
PINS = json.loads((HERE / 'pins.json').read_text())
DRIVER = 'src/tests/python/test_native_ui_core_linux.py'
FIXTURES = 'src/tests/native/gui/ui2/probes/linux'
OWNER_PATHS = {
    'src/stdlib/GUI/Linux/LinuxWindow.btrc',
    'src/stdlib/GUI/Linux/LinuxContext.btrc',
    'src/stdlib/GUI/Linux/LinuxApplication.btrc',
    'src/stdlib/GUI/Linux/GUIProvider.btrc',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def git(root, *args):
    return subprocess.check_output(['git', '-c', f'safe.directory={root}', '-C', str(root), *args], timeout=120)


def inventory(root):
    result = {}
    for prefix in ('src', 'tools'):
        for path in sorted((root / prefix).rglob('*')):
            assert not path.is_symlink(), path
            if path.is_file():
                result[str(path.relative_to(root))] = {'sha256': sha(path), 'mode': stat.S_IMODE(path.stat().st_mode)}
    return result


def authenticate_checkout(root, revision):
    expected = {}
    for row in git(root, 'ls-tree', '-rz', revision).split(b'\0'):
        if not row:
            continue
        info, raw_name = row.split(b'\t', 1)
        name = raw_name.decode()
        if not name.startswith(('src/', 'tools/')):
            continue
        mode, kind, oid = info.decode().split()
        assert kind == 'blob' and mode in {'100644', '100755'}, name
        path = root / name
        assert path.is_file() and not path.is_symlink(), name
        data = path.read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == oid, name
        assert bool(path.stat().st_mode & 0o111) == (mode == '100755'), name
        expected[name] = {'sha256': sha(path), 'mode': stat.S_IMODE(path.stat().st_mode)}
    assert inventory(root) == expected
    return expected


def extract(root, revision, target, *paths):
    data = git(root, 'archive', revision, *paths)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            name = Path(entry.name)
            assert not name.is_absolute() and '..' not in name.parts and (entry.isfile() or entry.isdir()), entry.name
        archive.extractall(target, filter='data')


def start():
    assert sys.platform == 'linux' and os.uname().machine == 'x86_64'
    assert git(COMPILER, 'rev-parse', 'HEAD').decode().strip() == PINS['compiler']
    assert git(PROVIDER, 'cat-file', '-t', PINS['candidate']).strip() == b'commit'
    assert git(PROVIDER, 'cat-file', '-t', PINS['baseline']).strip() == b'commit'
    for name, expected in PINS['helpers'].items():
        assert sha(HERE / name) == expected, name
    records = {'compiler': authenticate_checkout(COMPILER, PINS['compiler']), 'helpers': PINS['helpers'], 'pins_sha256': sha(HERE / 'pins.json')}
    for role, revision in [('B', PINS['baseline']), ('C', PINS['candidate'])]:
        destination = WORKSPACE / role
        destination.mkdir(exist_ok=False)
        extract(COMPILER, PINS['compiler'], destination)
        shutil.rmtree(destination / 'src/stdlib')
        extract(PROVIDER, revision, destination, 'src/stdlib', DRIVER, 'src/tests/gui_provider_root.py', FIXTURES)
        # Identical actual native prerequisite on the fixture-only side. No
        # typed implementation or assertion is overlaid into the baseline.
        manifest = destination / 'src/stdlib/GUI/btrc.toml'
        if role == 'B':
            text = manifest.read_text()
            for old, new in PINS['fragment']:
                assert text.count(old) == 1 and new not in text, old
                text = text.replace(old, new)
            manifest.write_text(text)
        records[role] = inventory(destination)
        for name, row in records['compiler'].items():
            if name.startswith(('src/compiler/', 'src/language/', 'src/runtime/', 'tools/')):
                assert records[role][name] == row, (role, name)
        assert sha(destination / DRIVER) == PINS['driver_sha256']
        for name, digest in PINS['fixtures'].items():
            assert sha(destination / FIXTURES / name) == digest, (role, name)
    assert records['B'].keys() == records['C'].keys()
    difference = {name for name in records['B'] if records['B'][name] != records['C'][name]}
    assert difference == OWNER_PATHS, difference
    assert (WORKSPACE / 'B/src/stdlib/GUI/btrc.toml').read_bytes() == (WORKSPACE / 'C/src/stdlib/GUI/btrc.toml').read_bytes()
    tools = {}
    for name in ('cc', 'c++', 'python3', 'make', 'pkg-config'):
        path = Path(shutil.which(name)).resolve(strict=True)
        tools[name] = {'path': str(path), 'sha256': sha(path)}
    assert os.environ['BTRC_NATIVE_TARGET'] == 'x86_64-unknown-linux-gnu'
    assert Path(os.environ['BTRC_NATIVE_SYSROOT']).is_dir()
    reader = Path(os.environ['BTRC_NATIVE_HEADER_READER']).resolve(strict=True)
    tools['reader'] = {'path': str(reader), 'sha256': sha(reader)}
    shell = Path(os.environ['BASH_ENV']).resolve(strict=True)
    tools['shell'] = {'path': str(shell), 'sha256': sha(shell)}
    records['tools'] = tools
    records['environment'] = {key: value for key, value in os.environ.items() if key.startswith(('BTRC_NATIVE_', 'NIX_CFLAGS_')) or key in ('CC', 'CXX', 'PKG_CONFIG_PATH', 'PATH')}
    save('inputs.json', records)


def build():
    assert (EVIDENCE / 'compiler_build-process.json').is_file()
    receipt = json.loads((EVIDENCE / 'compiler_build-process.json').read_text())
    assert receipt['state'] == 'completed' and receipt['returncode'] == 0 and receipt['leader_reaped']
    save('build.json', {'compiler_revision': PINS['compiler'], 'receipt_sha256': sha(EVIDENCE / 'compiler_build-process.json'), 'binary_sha256': sha(COMPILER / 'bin/btrcc'), 'generated_c_sha256': sha(COMPILER / 'dist/btrcc.c')})


def baseline_errors(frontend):
    # This is the missing-owner dependency graph of the hash-pinned full
    # fixture, not a general permission to ignore type-inference errors.
    # f75 selfhost stops at its first interface error; reference continues
    # into calls to the absent methods and their registration result uses.
    if frontend == 'selfhost':
        return [('window', 116, 1, "Class 'LinuxWindow' does not implement interface method 'IWindow.requestClose'")]
    assert frontend == 'python'
    errors = [
        ('window', 116, 1, "Class 'LinuxWindow' does not implement interface method 'requestClose' from 'ILinuxWindow'"),
        ('window', 116, 1, "Class 'LinuxWindow' does not implement interface method 'onCloseRequested' from 'ILinuxWindow'"),
    ]
    for method, sites in (
        ('onCloseRequested', [(68, 11), (68, 54), (70, 8), (101, 87), (109, 42), (126, 67), (136, 8)]),
        ('requestClose', [(77, 34), (78, 39), (93, 9), (94, 39), (98, 9), (102, 40), (118, 42), (127, 40), (138, 9)]),
    ):
        errors.extend(('fixture', line, column, f"Class 'LinuxWindow' has no field or method '{method}'") for line, column in sites)
    # ar, br and cr are the three var declarations initialized by the absent
    # onCloseRequested method. Only their exact declaration/use sites cascade.
    for name, line, column, use_line, use_column, method in (
        ('ar', 68, 2, 71, 30, 'isOpen'),
        ('br', 68, 45, 92, 9, 'cancel'),
        ('cr', 101, 78, 104, 49, 'pollCompletion'),
    ):
        errors.append(('fixture', line, column, f"Cannot infer type for 'var' declaration of '{name}'"))
        errors.append(('fixture', use_line, use_column, f"Type 'int' has no method '{method}'"))
    # The close-decision guard belongs to the same candidate's LinuxContext
    # owner; this fixture checks it after an actual throwing close receiver.
    errors.append(('fixture', 130, 18, "Class 'LinuxContext' has no field or method 'requireNoCloseDecision'"))
    return errors


def require_baseline_errors(text, frontend):
    lines = [re.sub(r'^E\s+', '', line) for line in text.splitlines()]
    actual = []
    for index, line in enumerate(lines):
        if not re.search(r'\berror:', line, re.I):
            continue
        message = re.fullmatch(r'(?:AssertionError: )?error: (.+)', line)
        assert message is not None, line
        assert index + 1 < len(lines), line
        location = re.fullmatch(r'\s*--> (.+):(\d+):(\d+)', lines[index + 1])
        assert location is not None, lines[index:index + 2]
        path = location.group(1)
        if re.fullmatch(r'/workspace/evidence/B-tmp/gui-provider\d+/data/stdlib/GUI/Linux/LinuxWindow\.btrc', path):
            owner = 'window'
        else:
            assert re.fullmatch(r'/workspace/evidence/B-tmp/test_linux_ui2_executor_and_li\d+/fixture/UI2LinuxWindowClose\.btrc', path), path
            owner = 'fixture'
        actual.append((owner, int(location.group(2)), int(location.group(3)), message.group(1)))
    assert Counter(actual) == Counter(baseline_errors(frontend)), actual


def classify(role):
    assert role in {'B', 'C'}
    xml = EVIDENCE / f'{role}.xml'
    cases = list(ET.parse(xml).getroot().iter('testcase'))
    assert len(cases) == 4 and len({(c.get('classname'), c.get('name')) for c in cases}) == 4
    assert all('test_linux_ui2_executor_and_lifecycle' in c.get('name', '') and 'UI2LinuxWindowClose.btrc' in c.get('name', '') for c in cases)
    assert {suffix for suffix in ('plain-python]', 'plain-selfhost]', 'sanitized-python]', 'sanitized-selfhost]') if any(c.get('name', '').endswith('-' + suffix) for c in cases)} == {'plain-python]', 'plain-selfhost]', 'sanitized-python]', 'sanitized-selfhost]'}
    assert all(c.find('skipped') is None and c.find('error') is None for c in cases)
    for case in cases:
        failure = case.find('failure')
        if role == 'B':
            assert failure is not None
            frontend = 'selfhost' if case.get('name', '').endswith('-selfhost]') else 'python'
            require_baseline_errors(failure.text or '', frontend)
        else:
            assert failure is None, failure.text if failure is not None else ''
    save(f'{role}-accepted.json', {'cases': 4, 'kind': 'missing-close-api-red' if role == 'B' else 'paired-plain-sanitized-native-pass', 'junit_sha256': sha(xml)})


def close():
    before = json.loads((EVIDENCE / 'inputs.json').read_text())
    for role, path in [('compiler', COMPILER), ('B', WORKSPACE / 'B'), ('C', WORKSPACE / 'C')]:
        assert inventory(path) == before[role], role
    for row in before['tools'].values():
        assert sha(Path(row['path'])) == row['sha256'], row
    for name, expected in before['helpers'].items():
        assert sha(HERE / name) == expected
    assert sha(HERE / 'pins.json') == before['pins_sha256']
    if (EVIDENCE / 'build.json').exists():
        compiled = json.loads((EVIDENCE / 'build.json').read_text())
        assert sha(COMPILER / 'bin/btrcc') == compiled['binary_sha256']
        assert sha(COMPILER / 'dist/btrcc.c') == compiled['generated_c_sha256']
    save('closure.json', {'source_tools_binary_unchanged': True})


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'classify':
        classify(sys.argv[2])
    else:
        {'start': start, 'build': build, 'close': close}[action]()
