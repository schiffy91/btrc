const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const textmate = require('vscode-textmate');
const oniguruma = require('vscode-oniguruma');

async function loadGrammar() {
    const wasmPath = require.resolve('vscode-oniguruma/release/onig.wasm');
    const wasm = fs.readFileSync(wasmPath).buffer;
    await oniguruma.loadWASM(wasm);

    const grammarPath = path.join(__dirname, '..', 'syntaxes', 'btrc.tmLanguage.json');
    const rawGrammar = textmate.parseRawGrammar(
        fs.readFileSync(grammarPath, 'utf8'),
        grammarPath,
    );
    const registry = new textmate.Registry({
        onigLib: Promise.resolve({
            createOnigScanner: (sources) => new oniguruma.OnigScanner(sources),
            createOnigString: (source) => new oniguruma.OnigString(source),
        }),
        loadGrammar: async (scopeName) => scopeName === 'source.btrc' ? rawGrammar : null,
    });
    return registry.loadGrammar('source.btrc');
}

test('f-string interpolation scopes variable identifiers', async () => {
    const grammar = await loadGrammar();
    const line = 'var command = f"printf {label} >&2";';

    const tokens = grammar.tokenizeLine(line).tokens;
    const label = tokens.find((token) => line.slice(token.startIndex, token.endIndex) === 'label');

    assert(label);
    assert(label.scopes.includes('meta.interpolation.btrc'));
    assert(label.scopes.includes('variable.other.readwrite.btrc'));
});

test('f-string escaped braces are not interpolation', async () => {
    const grammar = await loadGrammar();
    const line = 'var command = f"printf {{label}} {label}";';

    const tokens = grammar.tokenizeLine(line).tokens;
    const escapedStart = line.indexOf('{{label}}');
    const escapedEnd = escapedStart + '{{label}}'.length;
    const escapedTokens = tokens.filter((token) => token.startIndex >= escapedStart && token.endIndex <= escapedEnd);
    const liveLabel = tokens.find((token) => line.slice(token.startIndex, token.endIndex) === 'label' && token.startIndex > escapedEnd);

    assert(escapedTokens.length > 0);
    assert(escapedTokens.every((token) => !token.scopes.includes('meta.interpolation.btrc')));
    assert(liveLabel);
    assert(liveLabel.scopes.includes('meta.interpolation.btrc'));
});
