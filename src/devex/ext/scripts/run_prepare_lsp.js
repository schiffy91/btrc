'use strict';

const path = require('node:path');
const { spawnSync } = require('node:child_process');

function packagingPython(platform = process.platform, env = process.env) {
    const configured = env.BTRC_PACKAGING_PYTHON;
    if (configured && configured.trim()) {
        return configured;
    }
    return platform === 'win32' ? 'python' : 'python3';
}

function prepareLsp({
    platform = process.platform,
    env = process.env,
    spawn = spawnSync,
} = {}) {
    const python = packagingPython(platform, env);
    const script = path.join(__dirname, 'prepare_lsp_package.py');
    const result = spawn(python, [script], {
        env,
        shell: false,
        stdio: 'inherit',
        windowsHide: true,
    });
    if (result.error) {
        throw new Error(`could not run extension packaging Python ${JSON.stringify(python)}`, {
            cause: result.error,
        });
    }
    if (result.signal) {
        throw new Error(`extension packaging Python terminated by signal ${result.signal}`);
    }
    return result.status ?? 1;
}

if (require.main === module) {
    try {
        process.exitCode = prepareLsp();
    } catch (error) {
        console.error(error instanceof Error ? error.message : String(error));
        process.exitCode = 1;
    }
}

module.exports = { packagingPython, prepareLsp };
