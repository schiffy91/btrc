const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const {
    DebugLaunchResolver,
} = require(path.join(extensionBuild, 'out', 'debugger', 'launcher.js'));
const {
    HostRuntime,
} = require(path.join(extensionBuild, 'out', 'runtime', 'process.js'));
const {
    PythonRuntimeProbe,
} = require(path.join(extensionBuild, 'out', 'runtime', 'python.js'));

function tmp() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-dbg-'));
}
function touch(file) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, '');
}

function resolver(extensionPath, workspaceRoot, supportsPython = async () => true) {
    const host = new HostRuntime();
    const python = new PythonRuntimeProbe(host, { probe: supportsPython });
    return new DebugLaunchResolver(
        extensionPath,
        workspaceRoot,
        'python3',
        python,
        host,
        {},
    );
}

test('findDebugAdapterLaunch prefers the bundled adapter package', () => {
    const ext = tmp();
    touch(path.join(ext, 'server', 'src', 'devex', 'debug', '__main__.py'));
    assert.deepEqual(resolver(ext, undefined).resolveAdapter(), {
        args: ['-m', 'src.devex.debug'],
        cwd: path.join(ext, 'server'),
    });
});

test('findDebugAdapterLaunch finds the dev-checkout package in the workspace', () => {
    const ext = tmp();
    const ws = tmp();
    touch(path.join(ws, 'src', 'devex', 'debug', '__main__.py'));
    assert.deepEqual(resolver(ext, ws).resolveAdapter(), {
        args: ['-m', 'src.devex.debug'],
        cwd: ws,
    });
});

test('findDebugAdapterLaunch returns undefined when absent', () => {
    assert.equal(resolver(tmp(), tmp()).resolveAdapter(), undefined);
});

test('findBtrcpy prefers the bin/btrcpy wrapper', async () => {
    const ws = tmp();
    const wrapper = path.join(ws, 'bin', 'btrcpy');
    touch(wrapper);
    fs.chmodSync(wrapper, 0o755);
    let calls = 0;
    const r = await resolver(undefined, ws, async () => {
        calls += 1;
        return true;
    }).resolveCompiler();
    assert.deepEqual(r.command, ['python3', wrapper]);
    assert.equal(r.cwd, ws);
    assert.equal(calls, 1);
});

test('findBtrcpy skips an unlaunchable wrapper for the source module', {
    skip: process.platform === 'win32' && 'Windows launches readable wrappers through Python',
}, async () => {
    const ws = tmp();
    touch(path.join(ws, 'bin', 'btrcpy'));
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));

    const host = new HostRuntime();
    const python = new PythonRuntimeProbe(host, { probe: async () => true });
    const r = await new DebugLaunchResolver(
        tmp(), ws, 'py', python, host, {},
    ).resolveCompiler();

    assert.deepEqual(r.command, ['py', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the source checkout module', async () => {
    const ws = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    const host = new HostRuntime();
    const python = new PythonRuntimeProbe(host, { probe: async () => true });
    const r = await new DebugLaunchResolver(
        tmp(), ws, 'py', python, host, {},
    ).resolveCompiler();
    assert.deepEqual(r.command, ['py', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, ws);
});

test('findBtrcpy falls back to the bundled compiler payload', async () => {
    const ws = tmp();   // empty workspace
    const ext = tmp();
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    const r = await resolver(ext, ws).resolveCompiler();
    assert.deepEqual(r.command, ['python3', '-m', 'src.compiler.python.main']);
    assert.equal(r.cwd, path.join(ext, 'server'));
});

test('findBtrcpy returns undefined when nothing is available', async () => {
    assert.equal(await resolver(tmp(), tmp()).resolveCompiler(), undefined);
});

test('findBtrcpy rejects module fallbacks under unsupported Python', async () => {
    const ws = tmp();
    const ext = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    assert.equal(
        await resolver(ext, ws, async () => false).resolveCompiler(),
        undefined,
    );
});

test('findBtrcpy probes one interpreter only once across module fallbacks', async () => {
    const ws = tmp();
    const ext = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    touch(path.join(ext, 'server', 'src', 'compiler', 'python', 'main.py'));
    let calls = 0;

    const resolved = await resolver(ext, ws, async () => {
        calls += 1;
        return false;
    }).resolveCompiler();

    assert.equal(resolved, undefined);
    assert.equal(calls, 1);
});

test('findBtrcpy honors cancellation before starting a Python probe', async () => {
    const ws = tmp();
    touch(path.join(ws, 'src', 'compiler', 'python', 'main.py'));
    const cancellation = new AbortController();
    cancellation.abort();
    let calls = 0;

    const resolved = await resolver(
        tmp(),
        ws,
        async () => {
            calls += 1;
            return true;
        },
    ).resolveCompiler(cancellation.signal);

    assert.equal(resolved, undefined);
    assert.equal(calls, 0);
});
