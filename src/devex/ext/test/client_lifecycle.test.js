const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {
    ClientLifecycle,
    errorMessage,
} = require('../out/client_lifecycle.js');

function owner(stop = async () => {}) {
    return { stop };
}

test('running client receives one graceful stop before process cleanup', async () => {
    let clientStops = 0;
    let processStops = 0;
    const lifecycle = new ClientLifecycle({
        start: async () => {},
        stop: async () => { clientStops += 1; },
    }, owner(async () => { processStops += 1; }), 50, 50);

    await lifecycle.start();
    const firstStop = lifecycle.stop();
    const secondStop = lifecycle.stop();
    assert.equal(firstStop, secondStop);
    await firstStop;
    assert.equal(clientStops, 1);
    assert.equal(processStops, 1);
});

test('shutdown before startup prevents a later client generation', async () => {
    let clientStarts = 0;
    let processStops = 0;
    const lifecycle = new ClientLifecycle({
        start: async () => { clientStarts += 1; },
        stop: async () => {},
    }, owner(async () => { processStops += 1; }), 50, 50);

    await lifecycle.stop();
    await assert.rejects(lifecycle.start(), /after shutdown/);
    assert.equal(clientStarts, 0);
    assert.equal(processStops, 1);
});

test('never-settling startup cannot block bounded process cleanup', async () => {
    let processStops = 0;
    const lifecycle = new ClientLifecycle({
        start: () => new Promise(() => {}),
        stop: () => new Promise(() => {}),
    }, owner(async () => { processStops += 1; }), 25, 50);

    void lifecycle.start();
    await new Promise((resolve) => setImmediate(resolve));
    const started = Date.now();
    await lifecycle.stop();
    assert(Date.now() - started < 200, 'shutdown waited for a hung startup');
    assert.equal(processStops, 1);
});

test('rejected startup still attempts client and process cleanup', async () => {
    let clientStops = 0;
    let processStops = 0;
    const lifecycle = new ClientLifecycle({
        start: async () => { throw new Error('start failed'); },
        stop: async () => {
            clientStops += 1;
            throw new Error('client is not running');
        },
    }, owner(async () => { processStops += 1; }), 25, 50);

    await assert.rejects(lifecycle.start(), /start failed/);
    await lifecycle.stop();
    assert.equal(clientStops, 1);
    assert.equal(processStops, 1);
});

test('ignored startup rejection does not become unhandled during cleanup', async () => {
    const lifecycle = new ClientLifecycle({
        start: async () => { throw new Error('start failed'); },
        stop: async () => { throw new Error('not running'); },
    }, owner(), 25, 50);

    void lifecycle.start();
    await new Promise((resolve) => setImmediate(resolve));
    await lifecycle.stop();
    await new Promise((resolve) => setImmediate(resolve));
});

test('errorMessage preserves Error and non-Error rejection details', () => {
    assert.equal(errorMessage(new Error('object failure')), 'object failure');
    assert.equal(errorMessage('string failure'), 'string failure');
    assert.equal(errorMessage(undefined), 'undefined');
    assert.equal(errorMessage(Object.create(null)), 'Unknown error');
});

test('extension context explicitly owns the file watcher', () => {
    const source = fs.readFileSync(
        path.join(__dirname, '..', 'src', 'extension.ts'),
        'utf8',
    );
    assert.match(source, /const fileWatcher = vscode\.workspace\.createFileSystemWatcher/);
    assert.match(source, /context\.subscriptions\.push\(fileWatcher\)/);
    assert.match(source, /fileEvents: fileWatcher/);
});
