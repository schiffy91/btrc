const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { findDebugAdapterScript, findBtrcpy } = require('../out/debug_launch.js');

function tmp() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-dbg-'));
}
function touch(file) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, '');
}

test('findDebugAdapterScript prefers the bundled adapter', () => {
    const ext = tmp();
    touch(path.join(ext, 'debug', 'btrc_dap.py'));
    assert.equal(findDebugAdapterScript(ext, undefined),
        path.join(ext, 'debug', 'btrc_dap.py'));
});

test('findDebugAdapterScript finds the dev-checkout adapter in the workspace', () => {
    const ext = tmp();
    const ws = tmp();
    touch(path.join(ws, 'src', 'devex', 'debug', 'btrc_dap.py'));
    assert.equal(findDebugAdapterScript(ext, ws),
        path.join(ws, 'src', 'devex', 'debug', 'btrc_dap.py'));
});

test('findDebugAdapterScript returns undefined when absent', () => {
    assert.equal(findDebugAdapterScript(tmp(), tmp()), undefined);
});

test('findBtrcpy prefers the bin/btrcpy wrapper', async () => {
    const ws = tmp();
    const wrapper = path.join(ws, 'bin', 'btrcpy');
    touch(wrapper);
    fs.chmodSync(wrapper, 0o755);
    let calls = 0;
    const r = await findBtrcpy(ws, 'python3', undefined, async () => {
        calls += 1;
        return true;
    });
    assert.deepEqual(r.cmd, ['python3', wrapper]);
    assert.equal(r.cwd, ws);
    assert.equal(calls, 1);
});

test('findBtrcpy skips an unlaunchable wrapper for the source module', {
    skip: process.platform === 'win32' && 'Windows launches readable wrappers through Python',
}, async () => {
    const ws = tmp();
    touch(path.join(ws, 'bin', 'btrcpy'));
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));

    const r = await findBtrcpy(ws, 'py', undefined, async () => true);

    assert.deepEqual(r.cmd, ['py', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the source checkout module', async () => {
    const ws = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    const r = await findBtrcpy(ws, 'py', undefined, async () => true);
    assert.deepEqual(r.cmd, ['py', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the bundled compiler payload', async () => {
    const ws = tmp();   // empty workspace
    const ext = tmp();
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    const r = await findBtrcpy(ws, 'python3', ext, async () => true);
    assert.deepEqual(r.cmd, ['python3', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, path.join(ext, 'server'));
});

test('findBtrcpy returns undefined when nothing is available', async () => {
    assert.equal(await findBtrcpy(tmp(), 'python3', tmp(), async () => true), undefined);
});

test('findBtrcpy rejects module fallbacks under unsupported Python', async () => {
    const ws = tmp();
    const ext = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    assert.equal(await findBtrcpy(ws, 'python3', ext, async () => false), undefined);
});

test('findBtrcpy probes one interpreter only once across module fallbacks', async () => {
    const ws = tmp();
    const ext = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    let calls = 0;

    const resolved = await findBtrcpy(ws, 'python3', ext, async () => {
        calls += 1;
        return false;
    });

    assert.equal(resolved, undefined);
    assert.equal(calls, 1);
});

test('findBtrcpy honors cancellation before starting a Python probe', async () => {
    const ws = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    const cancellation = new AbortController();
    cancellation.abort();
    let calls = 0;

    const resolved = await findBtrcpy(
        ws,
        'python3',
        undefined,
        async () => {
            calls += 1;
            return true;
        },
        cancellation.signal,
    );

    assert.equal(resolved, undefined);
    assert.equal(calls, 0);
});
