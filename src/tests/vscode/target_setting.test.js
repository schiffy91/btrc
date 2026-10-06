const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const extensionSource = path.resolve(__dirname, '..', '..', 'devex', 'vscode');
const {
    TargetSetting,
} = require(path.join(extensionBuild, 'out', 'language_server', 'target.js'));
const manifest = JSON.parse(fs.readFileSync(
    path.join(extensionSource, 'package.json'),
    'utf8',
));

// A workspace's persisted settings: each "session" reads them afresh, as a
// reopened VS Code window does.
class SettingsStore {
    constructor() { this.values = new Map(); }

    update(key, value) { this.values.set(key, value); }

    configuration(section) {
        return {
            get: (key, defaultValue) => {
                const qualified = `${section}.${key}`;
                return this.values.has(qualified)
                    ? this.values.get(qualified)
                    : defaultValue;
            },
        };
    }
}

function change(...affected) {
    return { affectsConfiguration: (section) => affected.includes(section) };
}

test('btrc.target is a string setting whose empty default is the host', () => {
    const setting = manifest.contributes.configuration.properties['btrc.target'];
    assert.equal(setting.type, 'string');
    assert.equal(setting.default, '');
    assert.equal(setting.enum[0], '');
    assert.ok(setting.enum.includes('linux-x86_64'));
    assert.ok(setting.enum.includes('windows-x86_64'));
    assert.equal(setting.enumDescriptions.length, setting.enum.length);
});

test('the server starts with the setting in initializationOptions.target', () => {
    const store = new SettingsStore();
    assert.deepEqual(
        TargetSetting.initializationOptions(store.configuration('btrc')),
        { target: '' },
    );
    store.update('btrc.target', 'windows-x86_64');
    assert.deepEqual(
        TargetSetting.initializationOptions(store.configuration('btrc')),
        { target: 'windows-x86_64' },
    );
});

test('a reopened workspace keeps the setting', () => {
    const store = new SettingsStore();
    store.update('btrc.target', 'linux-aarch64');
    for (let session = 0; session < 2; session += 1) {
        const configuration = store.configuration(TargetSetting.SECTION);
        assert.deepEqual(
            TargetSetting.initializationOptions(configuration),
            { target: 'linux-aarch64' },
        );
    }
});

test('a changed setting is sent as workspace/didChangeConfiguration', () => {
    const store = new SettingsStore();
    store.update('btrc.target', 'linux-x86_64');
    assert.equal(TargetSetting.affects(change('btrc.target')), true);
    assert.equal(TargetSetting.affects(change('btrc.pythonPath')), false);
    assert.deepEqual(
        TargetSetting.changeNotification(store.configuration('btrc')),
        { settings: { btrc: { target: 'linux-x86_64' } } },
    );
    // The server validates labels, so an invalid one is sent unchanged.
    store.update('btrc.target', 'windows-x86_64-msvc');
    assert.deepEqual(
        TargetSetting.changeNotification(store.configuration('btrc')),
        { settings: { btrc: { target: 'windows-x86_64-msvc' } } },
    );
});

test('a non-string value is the host', () => {
    const store = new SettingsStore();
    store.update('btrc.target', 42);
    assert.equal(TargetSetting.read(store.configuration('btrc')), '');
});

test('the controller wires the setting into the language client', () => {
    const controller = fs.readFileSync(
        path.join(extensionSource, 'src', 'application', 'controller.ts'),
        'utf8',
    );
    assert.match(controller, /initializationOptions: \(\) => \{\s+const options = TargetSetting\.initializationOptions\(/);
    assert.match(controller, /onDidChangeConfiguration\(/);
    // A change made while the server starts is sent once it has started.
    assert.match(controller, /started successfully\.',\s+\);\s+sendTarget\(\);/);
    assert.match(controller, /DidChangeConfigurationNotification\.type/);
    assert.match(controller, /TargetSetting\.changeNotification\(/);
});
