const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { once } = require('node:events');
const test = require('node:test');

const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const {
    LanguageServerSession,
} = require(path.join(extensionBuild, 'out', 'language_server', 'session.js'));
const {
    HostRuntime,
} = require(path.join(extensionBuild, 'out', 'runtime', 'process.js'));

function launch(args, command = process.execPath) {
    return { command, args, cwd: process.cwd(), source: 'test' };
}

function ownedSession(serverLaunch, clientFactory, options = {}) {
    return new LanguageServerSession(
        serverLaunch,
        clientFactory,
        new HostRuntime(),
        options,
    );
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
    let child;
    const languageServer = ownedSession(
        launch(['-e', 'setInterval(() => {}, 1000)']),
        (serverOptions) => ({
            start: async () => {
                child = (await serverOptions()).process;
                return new Promise(() => {});
            },
            stop: () => new Promise(() => {}),
        }),
        { gracefulStopMs: 25, cleanupTimeoutMs: 1000 },
    );
    t.after(() => languageServer.stop());

    void languageServer.start();
    assert.equal(await waitUntil(() => child !== undefined), true);
    const started = Date.now();
    await languageServer.stop();
    assert(Date.now() - started < 1500, 'owned server cleanup exceeded its bound');
    assert.equal(await waitUntilDead(child.pid), true);
});

test('rejected startup terminates its owned server process', async (t) => {
    let child;
    const languageServer = ownedSession(
        launch(['-e', 'setInterval(() => {}, 1000)']),
        (serverOptions) => ({
            start: async () => {
                child = (await serverOptions()).process;
                throw new Error('invalid initialize response');
            },
            stop: async () => {
                throw new Error('client never reached running state');
            },
        }),
        { gracefulStopMs: 25, cleanupTimeoutMs: 1000 },
    );
    t.after(() => languageServer.stop());

    await assert.rejects(languageServer.start(), /invalid initialize response/);
    assert.equal(
        await waitUntilDead(child.pid),
        true,
        'failed initialization left its server alive until deactivation',
    );
    await languageServer.stop();
});

test('session rejects new generations after shutdown begins', async () => {
    let starts = 0;
    const languageServer = ownedSession(
        launch(['-e', 'process.exit(0)']),
        () => ({
            start: async () => { starts += 1; },
            stop: async () => {},
        }),
    );
    await languageServer.stop();
    await assert.rejects(languageServer.start(), /after shutdown/);
    assert.equal(starts, 0);
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
    let info;
    t.after(() => {
        if (descendantPid === undefined) { return; }
        try { process.kill(descendantPid, 'SIGKILL'); } catch {}
    });
    const childSource = [
        "require('node:fs').writeFileSync(process.argv[1], String(process.pid));",
        'setInterval(() => {}, 1000)',
    ].join(' ');
    fs.writeFileSync(command, [
        '@echo off',
        `"${process.execPath}" -e "${childSource}" "${marker}"`,
        '',
    ].join('\r\n'));

    const languageServer = ownedSession(launch([], command), (serverOptions) => ({
        start: async () => { info = await serverOptions(); },
        stop: async () => {},
    }));
    t.after(() => languageServer.stop());
    await languageServer.start();
    assert.notEqual(info.process.pid, undefined);
    assert.equal(await waitUntil(() => fs.existsSync(marker)), true);
    descendantPid = Number(fs.readFileSync(marker, 'utf8'));
    assert.equal(Number.isSafeInteger(descendantPid) && descendantPid > 0, true);
    await languageServer.stop();
    assert.equal(await waitUntilDead(info.process.pid), true);
    assert.equal(
        await waitUntilDead(descendantPid),
        true,
        'command-script descendant survived session shutdown',
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
    let info;
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
    const languageServer = ownedSession(
        launch(['-e', source]),
        (serverOptions) => ({
            start: async () => { info = await serverOptions(); },
            stop: async () => {},
        }),
    );
    t.after(() => languageServer.stop());
    await languageServer.start();
    const exited = once(info.process, 'exit');

    assert.equal(await waitUntil(() => fs.existsSync(pidFile)), true);
    descendantPid = Number(fs.readFileSync(pidFile, 'utf8'));
    await exited;
    await languageServer.stop();
    assert.equal(
        await waitUntilDead(descendantPid),
        true,
        'server descendant survived normal root-process exit',
    );
    descendantPid = undefined;
});
