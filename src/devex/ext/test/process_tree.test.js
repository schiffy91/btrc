const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const test = require('node:test');
const {
    ProcessTree,
    windowsTaskkillPath,
} = require('../out/process_tree.js');

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
        windowsTaskkillPath({ SystemRoot: 'C:\\Windows' }),
        'C:\\Windows\\System32\\taskkill.exe',
    );
    assert.equal(windowsTaskkillPath({}), 'taskkill.exe');
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
    const processTree = new ProcessTree(child, { detached, timeoutMs: 500 });

    const firstStop = processTree.stop();
    const secondStop = processTree.stop();
    assert.equal(firstStop, secondStop);
    await firstStop;
    assert.equal(await waitUntilDead(child.pid), true);
});
