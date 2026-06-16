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

test('findBtrcpy prefers the bin/btrcpy wrapper', () => {
    const ws = tmp();
    touch(path.join(ws, 'bin', 'btrcpy'));
    const r = findBtrcpy(ws, 'python3');
    assert.deepEqual(r.cmd, [path.join(ws, 'bin', 'btrcpy')]);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the source checkout module', () => {
    const ws = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    const r = findBtrcpy(ws, 'py');
    assert.deepEqual(r.cmd, ['py', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the bundled compiler payload', () => {
    const ws = tmp();   // empty workspace
    const ext = tmp();
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    const r = findBtrcpy(ws, 'python3', ext);
    assert.deepEqual(r.cmd, ['python3', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, path.join(ext, 'server'));
});

test('findBtrcpy returns undefined when nothing is available', () => {
    assert.equal(findBtrcpy(tmp(), 'python3', tmp()), undefined);
});
