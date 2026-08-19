const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');
const {
    HostRuntime,
    ProcessTree,
} = require(path.resolve(
    __dirname,
    '..', '..', '..', 'build', 'devex', 'vscode', 'out', 'runtime', 'process.js',
));

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

test('Windows taskkill resolves through SystemRoot before PATH', () => {
    assert.equal(
        new HostRuntime({ env: { SystemRoot: 'C:\\Windows' } }).windowsTaskkillPath(),
        'C:\\Windows\\System32\\taskkill.exe',
    );
    assert.equal(new HostRuntime({ env: {} }).windowsTaskkillPath(), 'taskkill.exe');
});

test('process-tree cleanup is idempotent and bounded', async (t) => {
    const detached = process.platform !== 'win32';
    const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
        detached,
        stdio: 'ignore',
        windowsHide: true,
    });
    t.after(() => {
        try { child.kill('SIGKILL'); } catch {}
    });
    assert.notEqual(child.pid, undefined);
    const processTree = new ProcessTree(
        child,
        new HostRuntime(),
        { detached, timeoutMs: 500 },
    );

    const firstStop = processTree.stop();
    const secondStop = processTree.stop();
    assert.equal(firstStop, secondStop);
    await firstStop;
    assert.equal(await waitUntilDead(child.pid), true);
});
