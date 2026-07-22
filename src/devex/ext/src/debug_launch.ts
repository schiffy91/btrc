import * as fs from 'fs';
import * as path from 'path';
import { PythonSupportProbe, supportsBtrcPython } from './python_runtime';
import { isLaunchableFile } from './launchable_file';

/**
 * Locate the btrc debug adapter entry script (btrc_dap.py).
 *
 * Search order: the bundled copy inside the packaged extension, then the dev
 * checkout layouts (the extension lives at src/devex/ext, the adapter at
 * src/devex/debug), then the open workspace.
 */
export function findDebugAdapterScript(
    extensionPath: string,
    workspaceRoot?: string,
): string | undefined {
    const candidates = [
        path.join(extensionPath, 'debug', 'btrc_dap.py'),
        path.join(extensionPath, '..', 'debug', 'btrc_dap.py'),
    ];
    if (workspaceRoot) {
        candidates.push(path.join(workspaceRoot, 'src', 'devex', 'debug', 'btrc_dap.py'));
    }
    for (const c of candidates) {
        if (fs.existsSync(c)) { return c; }
    }
    return undefined;
}

export interface BtrcpyResolution {
    cmd: string[];
    cwd?: string;
}

/**
 * Determine how to invoke the btrc compiler for a build-before-debug step.
 * Prefers the project's `bin/btrcpy` wrapper, then `python -m
 * src.compiler.python.main` from a source checkout.
 */
export async function findBtrcpy(
    workspaceRoot: string | undefined,
    pythonPath: string,
    extensionPath?: string,
    supportsPython: PythonSupportProbe = supportsBtrcPython,
    signal?: AbortSignal,
): Promise<BtrcpyResolution | undefined> {
    if (signal?.aborted) { return undefined; }
    let pythonSupport: Promise<boolean> | undefined;
    const pythonIsSupported = () => {
        pythonSupport ??= supportsPython(pythonPath, signal);
        return pythonSupport;
    };
    if (workspaceRoot) {
        const wrapper = path.join(workspaceRoot, 'bin', 'btrcpy');
        if (isLaunchableFile(wrapper)) {
            // The checkout wrapper is a Python script. Always use the
            // configured interpreter so debugging cannot silently select a
            // different Python through its shebang.
            if (await pythonIsSupported()) {
                return { cmd: [pythonPath, wrapper], cwd: workspaceRoot };
            }
            if (signal?.aborted) { return undefined; }
        }
        const mainPy = path.join(workspaceRoot, 'src', 'compiler', 'python', 'main.py');
        if (fs.existsSync(mainPy)) {
            if (await pythonIsSupported()) {
                return { cmd: [pythonPath, '-m', 'src.compiler.python.main'], cwd: workspaceRoot };
            }
            if (signal?.aborted) { return undefined; }
        }
    }
    // Fallback: the compiler payload bundled alongside the language server.
    if (extensionPath) {
        const bundled = path.join(extensionPath, 'server', 'src', 'compiler', 'python', 'main.py');
        if (fs.existsSync(bundled)) {
            if (await pythonIsSupported()) {
                return {
                    cmd: [pythonPath, '-m', 'src.compiler.python.main'],
                    cwd: path.join(extensionPath, 'server'),
                };
            }
            if (signal?.aborted) { return undefined; }
        }
    }
    return undefined;
}
