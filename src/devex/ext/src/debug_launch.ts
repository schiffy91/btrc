import * as fs from 'fs';
import * as path from 'path';

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
export function findBtrcpy(
    workspaceRoot: string | undefined,
    pythonPath: string,
    extensionPath?: string,
): BtrcpyResolution | undefined {
    if (workspaceRoot) {
        const wrapper = path.join(workspaceRoot, 'bin', 'btrcpy');
        if (fs.existsSync(wrapper)) {
            return { cmd: [wrapper], cwd: workspaceRoot };
        }
        const mainPy = path.join(workspaceRoot, 'src', 'compiler', 'python', 'main.py');
        if (fs.existsSync(mainPy)) {
            return { cmd: [pythonPath, '-m', 'src.compiler.python.main'], cwd: workspaceRoot };
        }
    }
    // Fallback: the compiler payload bundled alongside the language server.
    if (extensionPath) {
        const bundled = path.join(extensionPath, 'server', 'src', 'compiler', 'python', 'main.py');
        if (fs.existsSync(bundled)) {
            return {
                cmd: [pythonPath, '-m', 'src.compiler.python.main'],
                cwd: path.join(extensionPath, 'server'),
            };
        }
    }
    return undefined;
}
