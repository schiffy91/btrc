const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const { resolveServerLaunch } = require('../out/launch.js');
const { createPythonSupportProbe } = require('../out/python_runtime.js');

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
        supportsPython: overrides.supportsPython ?? (() => true),
        signal: overrides.signal,
    };
}

test('explicit serverPath wins over commands and workspace shells', async () => {
    const launch = await resolveServerLaunch(context([
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

test('explicit serverPath skips an unsupported project venv and uses Nix', async () => {
    const staleVenv = '/repo/src/devex/lsp/.venv/bin/python3';
    const launch = await resolveServerLaunch(context([
        '/repo/src/devex/lsp/server.py',
        staleVenv,
        '/repo/flake.nix',
        '/bin/nix',
    ], {
        config: { serverPath: '/repo/src/devex/lsp/server.py' },
        supportsPython: (candidate) => candidate !== staleVenv,
    }));

    assert.equal(launch.source, 'serverPath');
    assert.equal(launch.command, '/bin/nix');
    assert.deepEqual(launch.args, [
        'develop',
        '/repo',
        '--command',
        'python3',
        '/repo/src/devex/lsp/server.py',
    ]);
});

test('explicit relative serverCommand prefers workspace direnv before PATH', async () => {
    const launch = await resolveServerLaunch(context([
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

test('explicit relative serverCommand finds direnv when VS Code has a sparse PATH', async () => {
    const launch = await resolveServerLaunch(context([
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

test('explicit relative serverCommand prefers workspace shell.nix before PATH', async () => {
    const launch = await resolveServerLaunch(context([
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

test('useNixDevShell false skips workspace shell.nix and resolves on PATH', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/shell.nix',
        '/bin/nix-shell',
        '/bin/btrc-lsp',
    ], {
        config: { serverCommandExplicit: true, useNixDevShell: false },
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp');
    assert.deepEqual(launch.args, []);
});

test('useNixDevShell false skips workspace flake and resolves on PATH', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/flake.nix',
        '/bin/nix',
        '/bin/btrc-lsp',
    ], {
        config: { serverCommandExplicit: true, useNixDevShell: false },
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp');
    assert.deepEqual(launch.args, []);
});

test('useNixDevShell false skips workspace flake before bundled fallback', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/flake.nix',
        '/extension/server/src/devex/lsp/server.py',
        '/extension/server/flake.nix',
        '/bin/nix',
    ], {
        config: { useNixDevShell: false },
    }));

    assert.equal(launch.source, 'bundledServer');
    assert.equal(launch.command, 'python3');
    assert.deepEqual(launch.args, ['/extension/server/src/devex/lsp/server.py']);
});

test('useNixDevShell false still allows workspace direnv', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/.envrc',
        '/workspace/flake.nix',
        '/bin/direnv',
        '/bin/nix',
        '/bin/btrc-lsp',
    ], {
        config: { serverCommandExplicit: true, useNixDevShell: false },
    }));

    assert.equal(launch.source, 'direnv');
    assert.equal(launch.command, '/bin/direnv');
    assert.deepEqual(launch.args, ['exec', '/workspace', 'btrc-lsp']);
});

test('absolute serverCommand is respected directly', async () => {
    const launch = await resolveServerLaunch(context([
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

test('explicit relative serverCommand resolves on PATH before local server fallback', async () => {
    // No direnv/.envrc/shell.nix/flake.nix: the explicitly configured command
    // must win over a discovered bundled server instead of being ignored.
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/server.py',
        '/bin/btrc-lsp-dev',
    ], {
        config: { serverCommand: 'btrc-lsp-dev', serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp-dev');
    assert.deepEqual(launch.args, []);
    assert.equal(launch.cwd, '/workspace');
});

test('default serverCommand prefers workspace direnv before bundled server', async () => {
    const launch = await resolveServerLaunch(context([
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

test('source-tree server falls back to project nix dev shell', async () => {
    const launch = await resolveServerLaunch(context([
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

test('unsupported ambient Python falls back to an installed server command', async () => {
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/server.py',
        '/bin/btrc-lsp',
    ], {
        supportsPython: () => false,
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp');
});

test('unsupported ambient Python never launches the bundled server', async () => {
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/server.py',
    ], {
        config: { serverCommand: '' },
        supportsPython: () => false,
    }));

    assert.equal(launch, undefined);
});

test('revisited source-tree fallback reuses the cached Python result', async () => {
    let calls = 0;
    const supportsPython = createPythonSupportProbe({
        probe: async () => {
            calls += 1;
            return false;
        },
    });
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/server.py',
    ], {
        config: { serverCommand: '' },
        supportsPython,
    }));

    assert.equal(launch, undefined);
    assert.equal(calls, 1);
});

test('cancellation stops a pending Python server resolution', async () => {
    const cancellation = new AbortController();
    let calls = 0;
    const resolution = resolveServerLaunch(context([
        '/workspace/src/devex/lsp/server.py',
    ], {
        config: { serverCommand: '' },
        signal: cancellation.signal,
        supportsPython: (_candidate, signal) => new Promise((resolve) => {
            calls += 1;
            if (signal.aborted) {
                resolve(false);
            } else {
                signal.addEventListener('abort', () => resolve(false), { once: true });
            }
        }),
    }));
    await new Promise((resolve) => setImmediate(resolve));
    cancellation.abort();

    assert.equal(await resolution, undefined);
    assert.equal(calls, 1);
});

test('btrc checkout in workspace prefers live source tree over workspace flake', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/server.py',
        '/workspace/flake.nix',
        '/bin/nix',
    ]));

    assert.equal(launch.source, 'sourceTree');
    assert.equal(launch.command, '/bin/nix');
    assert.deepEqual(launch.args, [
        'develop',
        '/workspace',
        '--command',
        'python3',
        '/workspace/src/devex/lsp/server.py',
    ]);
});

test('explicit serverCommand still prefers workspace flake over live source tree', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/server.py',
        '/workspace/flake.nix',
        '/bin/nix',
    ], {
        config: { serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'workspaceFlake');
    assert.deepEqual(launch.args, ['develop', '/workspace', '--command', 'btrc-lsp']);
});
