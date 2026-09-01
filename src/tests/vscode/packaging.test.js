const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const extensionSource = path.resolve(__dirname, '..', '..', 'devex', 'vscode');

test('packaging entry point delegates one transaction to ExtensionBundler', () => {
    const source = fs.readFileSync(
        path.join(extensionSource, 'packaging', 'prepare.js'),
        'utf8',
    );
    assert.match(source, /function main\(\)/);
    assert.match(source, /path\.join\(__dirname, 'bundle\.py'\)/);
    assert.match(source, /--repository-root/);
    assert.match(source, /BTRC_PACKAGING_PYTHON/);
    assert.match(source, /BTRC_PACKAGING_OUTPUT_ROOT/);
    assert.match(source, /--output-root/);
    assert.doesNotMatch(source, /module\.exports/);
});

test('Python bundler owns the fixed source and build roots', () => {
    const source = fs.readFileSync(
        path.join(extensionSource, 'packaging', 'bundle.py'),
        'utf8',
    );
    assert.match(source, /class ExtensionBundler:/);
    assert.match(
        source,
        /self\.source_root = self\.repository_root \/ "src" \/ "devex" \/ "vscode"/,
    );
    assert.match(
        source,
        /else self\.repository_root \/ "build" \/ "devex" \/ "vscode"/,
    );
    assert.match(source, /source \/ "devex" \/ "lsp"/);
    assert.match(source, /source \/ "devex" \/ "debug"/);
    assert.match(source, /parser\.add_argument\("--output-root", type=Path\)/);
});
