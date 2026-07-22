const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const manifest = JSON.parse(fs.readFileSync(
    path.join(__dirname, '..', 'package.json'),
    'utf8',
));

test('extension cannot execute project launch paths in restricted workspaces', () => {
    assert.equal(manifest.capabilities.untrustedWorkspaces.supported, false);
    assert.equal(manifest.capabilities.virtualWorkspaces, false);
});

test('configured server commands declare their foreground lifetime contract', () => {
    const description = manifest.contributes.configuration.properties[
        'btrc.serverCommand'
    ].description;
    assert.match(description, /Foreground command/);
    assert.match(description, /must remain alive/);
    assert.match(description, /Windows/);
});
