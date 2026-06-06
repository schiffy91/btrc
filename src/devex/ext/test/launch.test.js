const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const { resolveServerLaunch } = require('../out/launch.js');

const config = {
    pythonPath: 'python3',
    serverPath: '',
    serverCommand: 'btrc-lsp',
    serverCommandExplicit: false,
    useNixDevShell: true,
    pythonExplicit: false,
};

function context(files, overrides = {}) {
    const existing = new Set(files);
    return {
        extensionPath: '/extension',
        workspaceRoot: '/workspace',
        config: { ...config, ...overrides.config },
        env: {
            HOME: '/home/alex',
            USER: 'alex',
            PATH: ['/bin', '/profile/bin'].join(path.delimiter),
            ...overrides.env,
        },
        exists: (candidate) => existing.has(candidate),
    };
}

test('explicit serverPath wins over commands and workspace shells', () => {
    const launch = resolveServerLaunch(context([
        '/repo/src/devex/lsp/server.py',
        '/workspace/.envrc',
        '/bin/direnv',
        '/bin/btrc-lsp',
    ], {
        config: { serverPath: '/repo/src/devex/lsp/server.py' },
    }));

    assert.equal(launch.source, 'serverPath');
    assert.equal(launch.command, 'python3');
    assert.deepEqual(launch.args, ['/repo/src/devex/lsp/server.py']);
    assert.equal(launch.cwd, '/repo');
});

test('explicit relative serverCommand prefers workspace direnv before PATH', () => {
    const launch = resolveServerLaunch(context([
        '/workspace/.envrc',
        '/bin/direnv',
        '/bin/btrc-lsp',
    ], {
        config: { serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'direnv');
    assert.equal(launch.command, '/bin/direnv');
    assert.deepEqual(launch.args, ['exec', '/workspace', 'btrc-lsp']);
    assert.equal(launch.cwd, '/workspace');
});

test('explicit relative serverCommand finds direnv when VS Code has a sparse PATH', () => {
    const launch = resolveServerLaunch(context([
        '/workspace/.envrc',
        '/opt/homebrew/bin/direnv',
    ], {
        config: { serverCommandExplicit: true },
        env: { PATH: '' },
    }));

    assert.equal(launch.source, 'direnv');
    assert.equal(launch.command, '/opt/homebrew/bin/direnv');
    assert.deepEqual(launch.args, ['exec', '/workspace', 'btrc-lsp']);
});

test('explicit relative serverCommand prefers workspace shell.nix before PATH', () => {
    const launch = resolveServerLaunch(context([
        '/workspace/shell.nix',
        '/bin/nix-shell',
        '/bin/btrc-lsp',
    ], {
        config: { serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'workspaceShellNix');
    assert.equal(launch.command, '/bin/nix-shell');
    assert.deepEqual(launch.args, ['/workspace/shell.nix', '--run', 'btrc-lsp']);
});

test('absolute serverCommand is respected directly', () => {
    const launch = resolveServerLaunch(context([
        '/custom/bin/btrc-lsp',
        '/workspace/.envrc',
        '/bin/direnv',
    ], {
        config: { serverCommand: '/custom/bin/btrc-lsp', serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/custom/bin/btrc-lsp');
    assert.deepEqual(launch.args, []);
});

test('default serverCommand prefers workspace direnv before bundled server', () => {
    const launch = resolveServerLaunch(context([
        '/workspace/.envrc',
        '/workspace/shell.nix',
        '/workspace/flake.nix',
        '/extension/server/src/devex/lsp/server.py',
        '/extension/server/flake.nix',
        '/bin/direnv',
        '/bin/nix-shell',
        '/bin/nix',
    ]));

    assert.equal(launch.source, 'direnv');
    assert.equal(launch.command, '/bin/direnv');
    assert.deepEqual(launch.args, ['exec', '/workspace', 'btrc-lsp']);
});

test('source-tree server falls back to project nix dev shell', () => {
    const launch = resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/server.py',
        '/extension/server/flake.nix',
        '/bin/nix',
    ], {
        config: { serverCommand: '' },
    }));

    assert.equal(launch.source, 'bundledServer');
    assert.equal(launch.command, '/bin/nix');
    assert.deepEqual(launch.args, [
        'develop',
        '/extension/server',
        '--command',
        'python3',
        '/extension/server/src/devex/lsp/server.py',
    ]);
});
