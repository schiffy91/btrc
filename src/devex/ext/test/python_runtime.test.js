const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
    createPythonSupportProbe,
    probeBtrcPython,
} = require('../out/python_runtime.js');

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

test('async probe accepts the supported project interpreter', async () => {
    const supportsPython = createPythonSupportProbe();
    assert.equal(await supportsPython(python), true);
});

test('async probe rejects Python older than 3.13', async (t) => {
    const directory = writeSiteCustomize(
        t,
        'import sys\nsys.version_info = (3, 12, 99)\n',
    );
    const supportsPython = createPythonSupportProbe();
    assert.equal(
        await withPythonPath(directory, () => supportsPython(python)),
        false,
    );
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

test('support probe deduplicates concurrent work and caches its result', async () => {
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
    assert.equal(calls, 1);
});

test('support probe converts runner errors to a cached negative result', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            throw new Error('probe failed');
        },
    });

    assert.equal(await supportsPython('broken-python'), false);
    assert.equal(await supportsPython('broken-python'), false);
    assert.equal(calls, 1);
});

test('a cancelled caller stops waiting without corrupting the shared result', async () => {
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
    await new Promise((resolve) => setImmediate(resolve));
    cancellation.abort();

    assert.equal(await cancelledResult, false);
    finishProbe(true);
    assert.equal(await supportsPython('slow-python'), true);
    assert.equal(calls, 1);
});

test('probe timeout is bounded and does not block the event loop', async (t) => {
    const directory = writeSiteCustomize(t, 'import time\ntime.sleep(60)\n');
    let eventLoopAdvanced = false;
    const started = Date.now();

    const supported = await withPythonPath(directory, async () => {
        const result = probeBtrcPython(python, undefined, 75);
        await new Promise((resolve) => setImmediate(() => {
            eventLoopAdvanced = true;
            resolve();
        }));
        return await result;
    });

    assert.equal(supported, false);
    assert.equal(eventLoopAdvanced, true);
    assert(Date.now() - started < 2000, 'timed-out probe exceeded its bound');
});

test('lifecycle cancellation terminates an active probe promptly', async (t) => {
    const directory = writeSiteCustomize(t, 'import time\ntime.sleep(60)\n');
    const lifecycle = new AbortController();
    const started = Date.now();

    const supported = await withPythonPath(directory, async () => {
        const result = probeBtrcPython(python, lifecycle.signal, 2000);
        setTimeout(() => lifecycle.abort(), 50);
        return await result;
    });

    assert.equal(supported, false);
    assert(Date.now() - started < 1000, 'cancelled probe did not stop promptly');
});

test('runtime source contains no synchronous child-process probes', () => {
    const source = fs.readFileSync(
        path.join(__dirname, '..', 'src', 'python_runtime.ts'),
        'utf8',
    );
    assert.doesNotMatch(source, /\b(?:execFileSync|execSync|spawnSync)\b/);
});
