const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const extensionSource = path.resolve(__dirname, '..', '..', 'devex', 'vscode');
const {
    LanguageServerSession,
} = require(path.join(extensionBuild, 'out', 'language_server', 'session.js'));
const {
    HostRuntime,
} = require(path.join(extensionBuild, 'out', 'runtime', 'process.js'));

function session(client, options = {}) {
    return new LanguageServerSession(
        {
            command: process.execPath,
            args: ['-e', 'process.exit(0)'],
            cwd: process.cwd(),
            source: 'test',
        },
        () => client,
        new HostRuntime(),
        options,
    );
}

test('running session receives one graceful client stop', async () => {
    let stops = 0;
    const languageServer = session({
        start: async () => {},
        stop: async () => { stops += 1; },
    }, { gracefulStopMs: 50, cleanupTimeoutMs: 50 });

    await languageServer.start();
    const firstStop = languageServer.stop();
    const secondStop = languageServer.stop();
    assert.equal(firstStop, secondStop);
    await firstStop;
    assert.equal(stops, 1);
});

test('shutdown before startup prevents a later client generation', async () => {
    let starts = 0;
    const languageServer = session({
        start: async () => { starts += 1; },
        stop: async () => {},
    });

    await languageServer.stop();
    await assert.rejects(languageServer.start(), /after shutdown/);
    assert.equal(starts, 0);
});

test('never-settling startup cannot block bounded cleanup', async () => {
    const languageServer = session({
        start: () => new Promise(() => {}),
        stop: () => new Promise(() => {}),
    }, { gracefulStopMs: 25, cleanupTimeoutMs: 50 });

    void languageServer.start();
    await new Promise((resolve) => setImmediate(resolve));
    const started = Date.now();
    await languageServer.stop();
    assert(Date.now() - started < 200, 'shutdown waited for a hung startup');
});

test('rejected startup still attempts client cleanup', async () => {
    let stops = 0;
    const languageServer = session({
        start: async () => { throw new Error('start failed'); },
        stop: async () => {
            stops += 1;
            throw new Error('client is not running');
        },
    });

    await assert.rejects(languageServer.start(), /start failed/);
    await languageServer.stop();
    assert.equal(stops, 1);
});

test('describeError preserves Error and non-Error details', () => {
    assert.equal(
        LanguageServerSession.describeError(new Error('object failure')),
        'object failure',
    );
    assert.equal(LanguageServerSession.describeError('string failure'), 'string failure');
    assert.equal(LanguageServerSession.describeError(undefined), 'undefined');
    assert.equal(
        LanguageServerSession.describeError(Object.create(null)),
        'Unknown error',
    );
});

test('extension controller explicitly owns the file watcher', () => {
    const source = fs.readFileSync(
        path.join(extensionSource, 'src', 'application', 'controller.ts'),
        'utf8',
    );
    assert.match(
        source,
        /const fileWatcher = vscode\.workspace\.createFileSystemWatcher/,
    );
    assert.match(source, /this\.context\.subscriptions\.push\(fileWatcher\)/);
    assert.match(source, /fileEvents: fileWatcher/);
});
