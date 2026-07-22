const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { once } = require('node:events');
const test = require('node:test');
const { ClientLifecycle } = require('../out/client_lifecycle.js');
const { ServerProcessOwner } = require('../out/server_process.js');

function launch(args, command = process.execPath) {
    return {
        command,
        args,
        cwd: process.cwd(),
        source: 'test',
    };
}

async function waitUntil(predicate, timeoutMs = 2000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        if (predicate()) { return true; }
        await new Promise((resolve) => setTimeout(resolve, 20));
    }
    return false;
}

async function waitUntilDead(pid, timeoutMs = 2000) {
    return waitUntil(() => {
        try {
            process.kill(pid, 0);
            return false;
        } catch {
            return true;
        }
    }, timeoutMs);
}

test('owned server process makes hung startup shutdown bounded', async (t) => {
    const owner = new ServerProcessOwner(launch(['-e', 'setInterval(() => {}, 1000)']));
    t.after(() => owner.stop());
    let child;
    const lifecycle = new ClientLifecycle({
        start: async () => {
            const info = await owner.serverOptions();
            child = info.process;
            return new Promise(() => {});
        },
        stop: () => new Promise(() => {}),
    }, owner, 25, 1000);

    void lifecycle.start();
    assert.equal(await waitUntil(() => child !== undefined), true);
    const started = Date.now();
    await lifecycle.stop();
    assert(Date.now() - started < 1500, 'owned server cleanup exceeded its bound');
    assert.equal(await waitUntilDead(child.pid), true);
});

test('rejected startup still terminates its owned server process', async (t) => {
    const owner = new ServerProcessOwner(launch(['-e', 'setInterval(() => {}, 1000)']));
    t.after(() => owner.stop());
    let child;
    const lifecycle = new ClientLifecycle({
        start: async () => {
            const info = await owner.serverOptions();
            child = info.process;
            throw new Error('invalid initialize response');
        },
        stop: async () => { throw new Error('client never reached running state'); },
    }, owner, 25, 1000);

    await assert.rejects(lifecycle.start(), /invalid initialize response/);
    assert.equal(
        await waitUntilDead(child.pid),
        true,
        'failed initialization left its server alive until deactivation',
    );
    await lifecycle.stop();
});

test('server owner rejects new generations after shutdown begins', async () => {
    const owner = new ServerProcessOwner(launch(['-e', 'process.exit(0)']));
    await owner.stop();
    await assert.rejects(
        owner.serverOptions(),
        /Cannot launch the language server during shutdown/,
    );
});

test('Windows command-script servers launch through an owned process', {
    skip: process.platform !== 'win32' && 'Windows command-script execution',
}, async (t) => {
    const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-server-cmd-'));
    t.after(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));
    const directory = path.join(temporaryRoot, 'path & metachar');
    fs.mkdirSync(directory);
    const marker = path.join(directory, 'descendant.pid');
    const command = path.join(directory, 'server.cmd');
    let descendantPid;
    t.after(() => {
        if (descendantPid === undefined) { return; }
        try { process.kill(descendantPid, 'SIGKILL'); } catch {}
    });
    const childSource = [
        "require('node:fs').writeFileSync(process.argv[1], String(process.pid));",
        'setInterval(() => {}, 1000)',
    ].join(' ');
    const source = [
        '@echo off',
        `"${process.execPath}" -e "${childSource}" "${marker}"`,
        '',
    ].join('\r\n');
    fs.writeFileSync(command, source);

    const owner = new ServerProcessOwner(launch([], command));
    t.after(() => owner.stop());
    const info = await owner.serverOptions();
    assert.notEqual(info.process.pid, undefined);
    assert.equal(await waitUntil(() => fs.existsSync(marker)), true);
    descendantPid = Number(fs.readFileSync(marker, 'utf8'));
    assert.equal(Number.isSafeInteger(descendantPid) && descendantPid > 0, true);
    await owner.stop();
    assert.equal(await waitUntilDead(info.process.pid), true);
    assert.equal(
        await waitUntilDead(descendantPid),
        true,
        'command-script descendant survived owner shutdown',
    );
    descendantPid = undefined;
});

test('normal server exit cleans up residual descendants', {
    skip: process.platform === 'win32' && 'requires a POSIX process group',
}, async (t) => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-server-owner-'));
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const pidFile = path.join(directory, 'descendant.pid');
    let descendantPid;
    t.after(() => {
        if (descendantPid === undefined) { return; }
        try { process.kill(descendantPid, 'SIGKILL'); } catch {}
    });
    const source = [
        "const { spawn } = require('node:child_process');",
        "const fs = require('node:fs');",
        "const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });",
        'child.unref();',
        `fs.writeFileSync(${JSON.stringify(pidFile)}, String(child.pid));`,
    ].join('\n');
    const owner = new ServerProcessOwner(launch(['-e', source]));
    t.after(() => owner.stop());
    const info = await owner.serverOptions();
    const exited = once(info.process, 'exit');

    assert.equal(await waitUntil(() => fs.existsSync(pidFile)), true);
    descendantPid = Number(fs.readFileSync(pidFile, 'utf8'));
    await exited;
    await owner.stop();
    assert.equal(
        await waitUntilDead(descendantPid),
        true,
        'server descendant survived normal root-process exit',
    );
    descendantPid = undefined;
});
