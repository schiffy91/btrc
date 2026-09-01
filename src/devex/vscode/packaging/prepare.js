'use strict';

const path = require('node:path');
const { spawnSync } = require('node:child_process');

function main() {
    const repositoryRoot = path.resolve(__dirname, '..', '..', '..', '..');
    const python = process.env.BTRC_PACKAGING_PYTHON?.trim()
        || (process.platform === 'win32' ? 'python' : 'python3');
    const outputRoot = process.env.BTRC_PACKAGING_OUTPUT_ROOT?.trim();
    const spawnArguments = [
        path.join(__dirname, 'bundle.py'),
        '--repository-root',
        repositoryRoot,
    ];
    if (outputRoot) {
        spawnArguments.push('--output-root', path.resolve(outputRoot));
    }
    const result = spawnSync(
        python,
        spawnArguments,
        {
            env: process.env,
            shell: false,
            stdio: 'inherit',
            windowsHide: true,
        },
    );
    if (result.error) {
        throw new Error(
            `could not run extension packaging Python ${JSON.stringify(python)}`,
            { cause: result.error },
        );
    }
    if (result.signal) {
        throw new Error(
            `extension packaging Python terminated by signal ${result.signal}`,
        );
    }
    return result.status ?? 1;
}

try {
    process.exitCode = main();
} catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
}
