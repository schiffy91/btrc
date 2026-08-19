const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
    HostRuntime,
} = require(path.resolve(
    __dirname,
    '..', '..', '..', 'build', 'devex', 'vscode', 'out', 'runtime', 'process.js',
));
const {
    PythonRuntimeProbe,
} = require(path.resolve(
    __dirname,
    '..', '..', '..', 'build', 'devex', 'vscode', 'out', 'runtime', 'python.js',
));

function createPythonSupportProbe(options = {}) {
    const runtime = new PythonRuntimeProbe(new HostRuntime(), options);
    return runtime.supports.bind(runtime);
}

function probeBtrcPython(command, signal, timeoutMs) {
    const runtime = new PythonRuntimeProbe(new HostRuntime(), {
        signal,
        timeoutMs,
    });
    return runtime.supports(command, signal);
}

function resolvePythonCommand(configured, platform) {
    return new PythonRuntimeProbe(new HostRuntime({ platform }))
        .resolveCommand(configured);
}

const python = process.env.BTRC_TEST_PYTHON
    || (process.platform === 'win32' ? 'python' : 'python3');

function tmp() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-python-runtime-'));
}

async function withPythonPath(directory, callback) {
    const previous = process.env.PYTHONPATH;
    process.env.PYTHONPATH = previous
        ? `${directory}${path.delimiter}${previous}`
        : directory;
    try {
        return await callback();
    } finally {
        if (previous === undefined) {
            delete process.env.PYTHONPATH;
        } else {
            process.env.PYTHONPATH = previous;
        }
    }
}

function writeSiteCustomize(t, source) {
    const directory = tmp();
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    fs.writeFileSync(path.join(directory, 'sitecustomize.py'), source);
    return directory;
}

function writePythonCommand(t, source) {
    const directory = tmp();
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const command = path.join(directory, 'probe-python');
    const shebang = path.isAbsolute(python)
        ? `#!${python}`
        : `#!/usr/bin/env ${python}`;
    fs.writeFileSync(command, `${shebang}\n${source}\n`);
    fs.chmodSync(command, 0o755);
    return command;
}

test('runtime Python default follows the host platform', () => {
    assert.equal(resolvePythonCommand(undefined, 'win32'), 'python');
    assert.equal(resolvePythonCommand('', 'win32'), 'python');
    assert.equal(resolvePythonCommand('   ', 'linux'), 'python3');
    assert.equal(resolvePythonCommand(undefined, 'darwin'), 'python3');
});

test('runtime Python preserves an explicit interpreter path', () => {
    const configured = 'C:\\Program Files\\Python 3.14\\python.exe';
    assert.equal(resolvePythonCommand(configured, 'win32'), configured);
});

async function waitUntilDead(pid, timeoutMs = 2000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        try {
            process.kill(pid, 0);
            await new Promise((resolve) => setTimeout(resolve, 20));
        } catch {
            return true;
        }
    }
    return false;
}

test('async probe accepts the supported project interpreter', async () => {
    const supportsPython = createPythonSupportProbe();
    assert.equal(await supportsPython(python), true);
});

test('async probe isolates version checks from sitecustomize startup hooks', async (t) => {
    const marker = path.join(tmp(), 'startup-hook-ran');
    t.after(() => fs.rmSync(path.dirname(marker), { recursive: true, force: true }));
    const directory = writeSiteCustomize(
        t,
        [
            'import os, sys',
            "with open(os.environ['BTRC_PROBE_MARKER'], 'w') as output:",
            "    output.write('ran')",
            'sys.version_info = (3, 12, 99)',
            '',
        ].join('\n'),
    );
    const previousMarker = process.env.BTRC_PROBE_MARKER;
    process.env.BTRC_PROBE_MARKER = marker;
    try {
        const supportsPython = createPythonSupportProbe();
        assert.equal(
            await withPythonPath(directory, () => supportsPython(python)),
            true,
        );
        assert.equal(fs.existsSync(marker), false);
    } finally {
        if (previousMarker === undefined) {
            delete process.env.BTRC_PROBE_MARKER;
        } else {
            process.env.BTRC_PROBE_MARKER = previousMarker;
        }
    }
});

test('async probe rejects a non-Python executable', async () => {
    const supportsPython = createPythonSupportProbe();
    assert.equal(await supportsPython(process.execPath), false);
});

test('async probe rejects a missing executable', async (t) => {
    const directory = tmp();
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const supportsPython = createPythonSupportProbe();
    assert.equal(await supportsPython(path.join(directory, 'missing-python')), false);
});

test('async probe rejects a blank command without spawning', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            return true;
        },
    });
    assert.equal(await supportsPython('   '), false);
    assert.equal(calls, 0);
});

test('support probe deduplicates concurrent work and revalidates later calls', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            await new Promise((resolve) => setImmediate(resolve));
            return true;
        },
    });

    assert.deepEqual(
        await Promise.all([supportsPython('python3'), supportsPython('python3')]),
        [true, true],
    );
    assert.equal(await supportsPython('python3'), true);
    assert.equal(calls, 2);
});

test('support probe does not let a runner error poison later probes', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            if (calls === 1) { throw new Error('probe failed'); }
            return true;
        },
    });

    assert.equal(await supportsPython('broken-python'), false);
    assert.equal(await supportsPython('broken-python'), true);
    assert.equal(calls, 2);
});

test('support probe deduplicates concurrent failures before permitting a retry', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            await new Promise((resolve) => setImmediate(resolve));
            return false;
        },
    });

    assert.deepEqual(
        await Promise.all([supportsPython('broken-python'), supportsPython('broken-python')]),
        [false, false],
    );
    assert.equal(calls, 1);
    assert.equal(await supportsPython('broken-python'), false);
    assert.equal(calls, 2);
});

test('a cancelled caller stops waiting without corrupting concurrent work', async () => {
    let finishProbe;
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: () => {
            calls += 1;
            return new Promise((resolve) => { finishProbe = resolve; });
        },
    });
    const cancellation = new AbortController();
    const cancelledResult = supportsPython('slow-python', cancellation.signal);
    const survivingResult = supportsPython('slow-python');
    await new Promise((resolve) => setImmediate(resolve));
    cancellation.abort();

    assert.equal(await cancelledResult, false);
    finishProbe(true);
    assert.equal(await survivingResult, true);
    assert.equal(calls, 1);
});

test('probe timeout is bounded and does not block the event loop', {
    skip: process.platform === 'win32' && 'POSIX executable fixture',
}, async (t) => {
    const command = writePythonCommand(t, 'import time\ntime.sleep(60)');
    let eventLoopAdvanced = false;
    const started = Date.now();

    const result = probeBtrcPython(command, undefined, 75);
    await new Promise((resolve) => setImmediate(() => {
        eventLoopAdvanced = true;
        resolve();
    }));
    const supported = await result;

    assert.equal(supported, false);
    assert.equal(eventLoopAdvanced, true);
    assert(Date.now() - started < 2000, 'timed-out probe exceeded its bound');
});

test('lifecycle cancellation terminates an active probe promptly', {
    skip: process.platform === 'win32' && 'POSIX executable fixture',
}, async (t) => {
    const command = writePythonCommand(t, 'import time\ntime.sleep(60)');
    const lifecycle = new AbortController();
    const started = Date.now();

    const result = probeBtrcPython(command, lifecycle.signal, 2000);
    setTimeout(() => lifecycle.abort(), 50);
    const supported = await result;

    assert.equal(supported, false);
    assert(Date.now() - started < 1000, 'cancelled probe did not stop promptly');
});

test('probe timeout terminates descendants created by an interpreter wrapper', {
    skip: process.platform === 'win32' && 'POSIX executable fixture',
}, async (t) => {
    const pidFile = path.join(tmp(), 'child.pid');
    t.after(() => fs.rmSync(path.dirname(pidFile), { recursive: true, force: true }));
    const command = writePythonCommand(t, [
        'import os, subprocess, sys, time',
        "child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time; time.sleep(60)'])",
        "with open(os.environ['BTRC_PROBE_CHILD_PID'], 'w') as output:",
        '    output.write(str(child.pid))',
        'time.sleep(60)',
        '',
    ].join('\n'));
    const previousPidFile = process.env.BTRC_PROBE_CHILD_PID;
    process.env.BTRC_PROBE_CHILD_PID = pidFile;
    let childPid;
    try {
        const supported = await probeBtrcPython(command, undefined, 1000);
        assert.equal(supported, false);
        childPid = Number(fs.readFileSync(pidFile, 'utf8'));
        assert.equal(await waitUntilDead(childPid), true, 'probe descendant survived timeout cleanup');
        childPid = undefined;
    } finally {
        if (childPid !== undefined) {
            try { process.kill(childPid, 'SIGKILL'); } catch {}
        }
        if (previousPidFile === undefined) {
            delete process.env.BTRC_PROBE_CHILD_PID;
        } else {
            process.env.BTRC_PROBE_CHILD_PID = previousPidFile;
        }
    }
});

test('successful probe cleanup terminates wrapper descendants', {
    skip: process.platform === 'win32' && 'POSIX executable fixture',
}, async (t) => {
    const pidFile = path.join(tmp(), 'child.pid');
    t.after(() => fs.rmSync(path.dirname(pidFile), { recursive: true, force: true }));
    const command = writePythonCommand(t, [
        'import os, subprocess, sys',
        "child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time; time.sleep(60)'])",
        "with open(os.environ['BTRC_PROBE_CHILD_PID'], 'w') as output:",
        '    output.write(str(child.pid))',
        '',
    ].join('\n'));
    const previousPidFile = process.env.BTRC_PROBE_CHILD_PID;
    process.env.BTRC_PROBE_CHILD_PID = pidFile;
    let childPid;
    try {
        assert.equal(await probeBtrcPython(command, undefined, 2000), true);
        childPid = Number(fs.readFileSync(pidFile, 'utf8'));
        assert.equal(await waitUntilDead(childPid), true, 'probe descendant survived successful cleanup');
        childPid = undefined;
    } finally {
        if (childPid !== undefined) {
            try { process.kill(childPid, 'SIGKILL'); } catch {}
        }
        if (previousPidFile === undefined) {
            delete process.env.BTRC_PROBE_CHILD_PID;
        } else {
            process.env.BTRC_PROBE_CHILD_PID = previousPidFile;
        }
    }
});

test('runtime source contains no synchronous child-process probes', () => {
    const source = fs.readFileSync(
        path.resolve(
            __dirname,
            '..', '..', 'devex', 'vscode', 'src', 'runtime', 'python.ts',
        ),
        'utf8',
    );
    assert.doesNotMatch(source, /\b(?:execFileSync|execSync|spawnSync)\b/);
});
