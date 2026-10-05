const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const path = require('node:path');
const test = require('node:test');
const {
    HostRuntime,
    ProcessTree,
} = require(path.resolve(
    __dirname,
    '..', '..', '..', 'build', 'devex', 'vscode', 'out', 'runtime', 'process.js',
));

// A Windows tree kill finishes in the background when taskkill outruns the
// stop budget, so death on a loaded runner can take seconds.
const DEATH_TIMEOUT_MS = process.platform === 'win32' ? 10000 : 2000;

async function waitUntilDead(pid, timeoutMs = DEATH_TIMEOUT_MS) {
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

/** A child process double: records kills and lets the test drive exit. */
class FakeProcess extends EventEmitter {
    constructor(pid) {
        super();
        this.pid = pid;
        this.exitCode = null;
        this.signalCode = null;
        this.kills = [];
        this.unrefs = 0;
    }

    kill(signal) {
        this.kills.push(signal);
        return true;
    }

    unref() {
        this.unrefs += 1;
    }

    exit(code) {
        this.exitCode = code;
        this.emit('exit', code, null);
        this.emit('close', code, null);
    }
}

function windowsHost(killer) {
    return new HostRuntime({
        platform: 'win32',
        env: { SystemRoot: 'C:\\Windows' },
        spawn: (command, args) => {
            killer.command = command;
            killer.args = args;
            return killer;
        },
    });
}

test('a slow Windows tree kill keeps running and leaves the root to it', async () => {
    const child = new FakeProcess(4242);
    const killer = new FakeProcess(7);
    const processTree = new ProcessTree(child, windowsHost(killer), { timeoutMs: 20 });

    await processTree.stop();
    assert.deepEqual(killer.args, ['/PID', '4242', '/T', '/F']);
    assert.deepEqual(killer.kills, [], 'taskkill was killed mid-walk');
    assert.equal(killer.unrefs, 1);
    assert.deepEqual(child.kills, [], 'the root was killed before taskkill reached its descendants');

    killer.exit(0);
    assert.deepEqual(child.kills, []);
});

test('a pending Windows tree kill that later fails falls back to the root once', async () => {
    const child = new FakeProcess(4242);
    const killer = new FakeProcess(7);
    await new ProcessTree(child, windowsHost(killer), { timeoutMs: 20 }).stop();

    killer.emit('error', new Error('taskkill failed'));
    killer.exit(1);
    assert.deepEqual(child.kills, ['SIGKILL']);
});

test('a Windows tree kill that fails in time kills the root directly', async () => {
    const child = new FakeProcess(4242);
    const killer = new FakeProcess(7);
    const stopped = new ProcessTree(child, windowsHost(killer), { timeoutMs: 5000 }).stop();
    killer.exit(128);
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(child.kills, ['SIGKILL']);
    child.exit(1);
    await stopped;
    assert.equal(killer.unrefs, 0);
});

test('a Windows tree kill that succeeds in time needs no direct kill', async () => {
    const child = new FakeProcess(4242);
    const killer = new FakeProcess(7);
    const stopped = new ProcessTree(child, windowsHost(killer), { timeoutMs: 5000 }).stop();
    killer.exit(0);
    await new Promise((resolve) => setImmediate(resolve));
    child.exit(1);
    await stopped;
    assert.deepEqual(child.kills, []);
});
