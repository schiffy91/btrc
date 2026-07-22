const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const {
    packagingPython,
    prepareLsp,
} = require('../scripts/run_prepare_lsp.js');

test('packaging launcher uses the setup-python command on Windows', () => {
    assert.equal(packagingPython('win32', {}), 'python');
});

test('packaging launcher uses python3 on POSIX', () => {
    assert.equal(packagingPython('darwin', {}), 'python3');
    assert.equal(packagingPython('linux', {}), 'python3');
});

test('packaging launcher preserves an explicitly configured interpreter path', () => {
    const configured = 'C:\\Program Files\\Python313\\python.exe';
    assert.equal(
        packagingPython('win32', { BTRC_PACKAGING_PYTHON: configured }),
        configured,
    );
});

test('packaging launcher spawns without a shell and propagates exit status', () => {
    const calls = [];
    const env = { BTRC_PACKAGING_PYTHON: '/opt/Python 3.14/bin/python3' };
    const status = prepareLsp({
        platform: 'linux',
        env,
        spawn(command, args, options) {
            calls.push({ command, args, options });
            return { status: 7 };
        },
    });

    assert.equal(status, 7);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].command, env.BTRC_PACKAGING_PYTHON);
    assert.equal(path.basename(calls[0].args[0]), 'prepare_lsp_package.py');
    assert.equal(calls[0].options.shell, false);
    assert.equal(calls[0].options.env, env);
});

test('packaging launcher reports executable lookup failures', () => {
    assert.throws(
        () => prepareLsp({
            spawn() {
                return { error: new Error('ENOENT') };
            },
        }),
        /could not run extension packaging Python/,
    );
});
