const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const extensionBuild = path.resolve(__dirname, '..', '..', '..', 'build', 'devex', 'vscode');
const {
    LanguageServerLaunchResolver,
} = require(path.join(extensionBuild, 'out', 'language_server', 'launcher.js'));
const {
    HostRuntime,
} = require(path.join(extensionBuild, 'out', 'runtime', 'process.js'));
const {
    PythonRuntimeProbe,
} = require(path.join(extensionBuild, 'out', 'runtime', 'python.js'));

function portablePath(value) {
    return value
        .replace(/^[A-Za-z]:[\\/]/, '/')
        .replaceAll('\\', '/');
}

async function resolveServerLaunch(context) {
    const host = new HostRuntime(context.hostOptions);
    const python = new PythonRuntimeProbe(host, {
        probe: context.supportsPython,
        signal: context.signal,
    });
    const launch = await new LanguageServerLaunchResolver(host, python).resolve({
        extensionPath: context.extensionPath,
        workspaceRoot: context.workspaceRoot,
        config: context.config,
        signal: context.signal,
    });
    if (!launch) { return launch; }
    return {
        ...launch,
        command: portablePath(launch.command),
        args: launch.args.map(portablePath),
        cwd: portablePath(launch.cwd),
        entrypoint: launch.entrypoint && portablePath(launch.entrypoint),
        projectRoot: launch.projectRoot && portablePath(launch.projectRoot),
    };
}

function venvPython(projectRoot) {
    return process.platform === 'win32'
        ? `${projectRoot}/src/devex/lsp/.venv/Scripts/python.exe`
        : `${projectRoot}/src/devex/lsp/.venv/bin/python3`;
}

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
    const nonExecutable = new Set(overrides.nonExecutable ?? []);
    const supportsPython = overrides.supportsPython ?? (() => true);
    return {
        extensionPath: '/extension',
        workspaceRoot: overrides.workspaceRoot ?? '/workspace',
        config: { ...config, ...overrides.config },
        hostOptions: {
            platform: process.platform,
            env: {
            HOME: '/home/alex',
            USER: 'alex',
            PATH: ['/bin', '/profile/bin'].join(path.delimiter),
            ...overrides.env,
            },
            stat: (candidate) => {
                if (!existing.has(portablePath(candidate))) {
                    throw new Error('ENOENT');
                }
                return { isFile: () => true };
            },
            access: (candidate) => {
                if (nonExecutable.has(portablePath(candidate))) {
                    throw new Error('EACCES');
                }
            },
        },
        supportsPython: (candidate, signal) => Promise.resolve(supportsPython(
            portablePath(candidate),
            signal,
        )),
        signal: overrides.signal,
    };
}

test('explicit serverPath wins over commands and workspace shells', async () => {
    const launch = await resolveServerLaunch(context([
        '/repo/src/devex/lsp/__main__.py',
        '/workspace/.envrc',
        '/bin/direnv',
        '/bin/btrc-lsp',
    ], {
        config: { serverPath: '/repo/src/devex/lsp/__main__.py' },
    }));

    assert.equal(launch.source, 'serverPath');
    assert.equal(launch.command, 'python3');
    assert.deepEqual(launch.args, ['-m', 'src.devex.lsp']);
    assert.equal(launch.cwd, '/repo');
});

test('explicit serverPath skips an unsupported project venv and uses Nix', async () => {
    const staleVenv = venvPython('/repo');
    const launch = await resolveServerLaunch(context([
        '/repo/src/devex/lsp/__main__.py',
        staleVenv,
        '/repo/flake.nix',
        '/bin/nix',
    ], {
        config: { serverPath: '/repo/src/devex/lsp/__main__.py' },
        supportsPython: (candidate) => candidate !== staleVenv,
    }));

    assert.equal(launch.source, 'serverPath');
    assert.equal(launch.command, '/bin/nix');
    assert.deepEqual(launch.args, [
        'develop',
        '/repo',
        '--command',
        'python3',
        '-m',
        'src.devex.lsp',
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

test('command discovery skips an existing but unlaunchable PATH candidate', async () => {
    const launch = await resolveServerLaunch(context([
        '/bin/btrc-lsp',
        '/profile/bin/btrc-lsp',
    ], {
        nonExecutable: ['/bin/btrc-lsp'],
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/profile/bin/btrc-lsp');
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
        '/extension/server/src/devex/lsp/__main__.py',
        '/extension/server/flake.nix',
        '/bin/nix',
    ], {
        config: { useNixDevShell: false },
    }));

    assert.equal(launch.source, 'bundledServer');
    assert.equal(launch.command, 'python3');
    assert.deepEqual(launch.args, ['-m', 'src.devex.lsp']);
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

test('Windows command discovery honors PATHEXT command scripts', {
    skip: process.platform !== 'win32' && 'Windows PATHEXT behavior',
}, async () => {
    const launch = await resolveServerLaunch(context([
        '/bin/btrc-lsp.bat',
    ], { env: { PATHEXT: '.BAT' } }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp.bat');
});

test('explicit relative serverCommand resolves on PATH before local server fallback', async () => {
    // No direnv/.envrc/shell.nix/flake.nix: the explicitly configured command
    // must win over a discovered bundled server instead of being ignored.
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/__main__.py',
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
        '/extension/server/src/devex/lsp/__main__.py',
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
        '/extension/server/src/devex/lsp/__main__.py',
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
        '-m',
        'src.devex.lsp',
    ]);
});

test('unsupported ambient Python falls back to an installed server command', async () => {
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/__main__.py',
        '/bin/btrc-lsp',
    ], {
        supportsPython: () => false,
    }));

    assert.equal(launch.source, 'serverCommand');
    assert.equal(launch.command, '/bin/btrc-lsp');
});

test('unsupported ambient Python never launches the bundled server', async () => {
    const launch = await resolveServerLaunch(context([
        '/extension/server/src/devex/lsp/__main__.py',
    ], {
        config: { serverCommand: '' },
        supportsPython: () => false,
    }));

    assert.equal(launch, undefined);
});

test('source-tree resolution does not retry the same failed candidate', async () => {
    let calls = 0;
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/__main__.py',
    ], {
        config: { serverCommand: '' },
        supportsPython: async () => {
            calls += 1;
            return false;
        },
    }));

    assert.equal(launch, undefined);
    assert.equal(calls, 1);
});

test('an unlaunchable workspace server does not mask a bundled server', async () => {
    const bundledPython = venvPython('/extension/server');
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/__main__.py',
        '/extension/server/src/devex/lsp/__main__.py',
        bundledPython,
    ], {
        config: { serverCommand: '' },
        supportsPython: async (candidate) => candidate === bundledPython,
    }));

    assert.equal(launch.source, 'bundledServer');
    assert.equal(launch.command, bundledPython);
    assert.equal(launch.entrypoint, '/extension/server/src/devex/lsp/__main__.py');
});

test('workspace command still precedes lower-priority local fallbacks', async () => {
    const bundledPython = venvPython('/extension/server');
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/__main__.py',
        '/workspace/.envrc',
        '/bin/direnv',
        '/extension/server/src/devex/lsp/__main__.py',
        bundledPython,
    ], {
        supportsPython: async (candidate) => candidate === bundledPython,
    }));

    assert.equal(launch.source, 'direnv');
    assert.equal(launch.command, '/bin/direnv');
});

test('cancellation stops a pending Python server resolution', async () => {
    const cancellation = new AbortController();
    let calls = 0;
    const resolution = resolveServerLaunch(context([
        '/workspace/src/devex/lsp/__main__.py',
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
        '/workspace/src/devex/lsp/__main__.py',
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
        '-m',
        'src.devex.lsp',
    ]);
});

test('a workspace directory named server remains a live source tree', async () => {
    const workspaceRoot = '/checkout/server';
    const launch = await resolveServerLaunch(context([
        `${workspaceRoot}/src/devex/lsp/__main__.py`,
        `${workspaceRoot}/.envrc`,
        '/bin/direnv',
    ], { workspaceRoot }));

    assert.equal(launch.source, 'sourceTree');
    assert.equal(launch.command, 'python3');
    assert.deepEqual(launch.args, ['-m', 'src.devex.lsp']);
});

test('explicit serverCommand still prefers workspace flake over live source tree', async () => {
    const launch = await resolveServerLaunch(context([
        '/workspace/src/devex/lsp/__main__.py',
        '/workspace/flake.nix',
        '/bin/nix',
    ], {
        config: { serverCommandExplicit: true },
    }));

    assert.equal(launch.source, 'workspaceFlake');
    assert.deepEqual(launch.args, ['develop', '/workspace', '--command', 'btrc-lsp']);
});
