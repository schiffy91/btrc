const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const test = require('node:test');
const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const extensionSource = path.resolve(__dirname, '..', '..', 'devex', 'vscode');
const extensionRequire = createRequire(path.join(extensionBuild, 'package.json'));
const textmate = extensionRequire('vscode-textmate');
const oniguruma = extensionRequire('vscode-oniguruma');

async function loadGrammar() {
    const wasmPath = extensionRequire.resolve('vscode-oniguruma/release/onig.wasm');
    const wasm = fs.readFileSync(wasmPath).buffer;
    await oniguruma.loadWASM(wasm);

    const grammarPath = path.join(extensionSource, 'config', 'grammar.json');
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

test('glob imports do not open an unterminated block comment', async () => {
    const grammar = await loadGrammar();
    const lines = [
        'import ./semu/core/*;',
        'import ./semu/cli/**;',
        'import std.{vector, strings}',
        'import std.*',
        'import "quoted/path.btrc";',
        '',
        'class SemuApp {',
        '    class int run(int argc, char** argv) { return main(argc, argv); }',
        '}',
        'string launcherNameFromProgram(string program) {',
        '    if (!base.startsWith("semu-")) {',
    ];

    let ruleStack = textmate.INITIAL;
    for (const line of lines) {
        const result = grammar.tokenizeLine(line, ruleStack);
        for (const token of result.tokens) {
            for (const scope of token.scopes) {
                assert(
                    !scope.startsWith('comment.block'),
                    `unexpected scope ${scope} on line ${JSON.stringify(line)}`,
                );
            }
        }
        ruleStack = result.ruleStack;
    }
});

test('import keyword is scoped keyword.control.import.btrc', async () => {
    const grammar = await loadGrammar();
    const lines = [
        'import std.{vector, strings}',
        'import std.*',
        'import std.name',
        'import ./relative/path.btrc;',
        'import ./dir/*;',
        'import ./dir/**;',
        'import "quoted/path.btrc";',
    ];

    for (const line of lines) {
        const tokens = grammar.tokenizeLine(line).tokens;
        const keyword = tokens.find((token) => line.slice(token.startIndex, token.endIndex) === 'import');
        assert(keyword, `no import token in ${JSON.stringify(line)}`);
        assert(
            keyword.scopes.includes('keyword.control.import.btrc'),
            `${JSON.stringify(line)}: got scopes ${keyword.scopes.join(', ')}`,
        );
    }
});

test('real block comments still highlight and do not trigger the import rule', async () => {
    const grammar = await loadGrammar();

    const singleLine = 'int y = 0; /* block */ int z = 1;';
    const singleTokens = grammar.tokenizeLine(singleLine).tokens;
    const block = singleTokens.find((token) => singleLine.slice(token.startIndex, token.endIndex).includes('block'));
    assert(block);
    assert(block.scopes.includes('comment.block.btrc'));

    const first = grammar.tokenizeLine('/* import std.*', textmate.INITIAL);
    assert(first.tokens.every((token) => token.scopes.includes('comment.block.btrc')));
    assert(first.tokens.every((token) => !token.scopes.includes('keyword.control.import.btrc')));

    const second = grammar.tokenizeLine('still comment */', first.ruleStack);
    const still = second.tokens.find((token) => 'still comment */'.slice(token.startIndex, token.endIndex).includes('still'));
    assert(still);
    assert(still.scopes.includes('comment.block.btrc'));

    const third = grammar.tokenizeLine('int after = 1;', second.ruleStack);
    assert(third.tokens.every((token) => token.scopes.every((scope) => !scope.startsWith('comment.block'))));
});

test('line comments still highlight and do not trigger the import rule', async () => {
    const grammar = await loadGrammar();
    const line = 'int x = 1; // import ./dir/*;';

    const tokens = grammar.tokenizeLine(line).tokens;
    const comment = tokens.find((token) => token.scopes.includes('comment.line.double-slash.btrc'));

    assert(comment);
    assert(tokens.every((token) => !token.scopes.includes('keyword.control.import.btrc')));
});

test('import inside a string literal does not trigger the import rule', async () => {
    const grammar = await loadGrammar();
    const line = 'var s = "import ./dir/*;";';

    const tokens = grammar.tokenizeLine(line).tokens;
    const inString = tokens.filter((token) => token.scopes.includes('string.quoted.double.btrc'));

    assert(inString.length > 0);
    assert(tokens.every((token) => !token.scopes.includes('keyword.control.import.btrc')));
});
