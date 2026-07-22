import { ChildProcess } from 'node:child_process';
import spawn from 'cross-spawn';
import { ProcessTree } from './process_tree';

const DEFAULT_PROBE_TIMEOUT_MS = 5000;
const VERSION_CHECK = 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)';

export type PythonSupportProbe = (
    command: string,
    signal?: AbortSignal,
) => Promise<boolean>;

export interface PythonProbeOptions {
    timeoutMs?: number;
    signal?: AbortSignal;
    probe?: PythonSupportProbe;
}

/** Resolve an optional setting to the conventional interpreter for this host. */
export function resolvePythonCommand(
    configured: string | undefined,
    platform: NodeJS.Platform = process.platform,
): string {
    if (configured?.trim()) { return configured; }
    return platform === 'win32' ? 'python' : 'python3';
}

/** Probe one interpreter without blocking the extension host. */
export function probeBtrcPython(
    command: string,
    signal?: AbortSignal,
    timeoutMs: number = DEFAULT_PROBE_TIMEOUT_MS,
): Promise<boolean> {
    if (!command.trim() || signal?.aborted) { return Promise.resolve(false); }

    return new Promise((resolve) => {
        let child: ChildProcess;
        let processTree: ProcessTree;
        let timer: NodeJS.Timeout | undefined;
        let settled = false;

        const finish = (supported: boolean) => {
            if (settled) { return; }
            settled = true;
            if (timer) { clearTimeout(timer); }
            signal?.removeEventListener('abort', onAbort);
            void processTree.stop().then(
                () => resolve(supported),
                () => resolve(false),
            );
        };
        const onAbort = () => finish(false);

        try {
            const detached = process.platform !== 'win32';
            child = spawn(command, ['-I', '-S', '-c', VERSION_CHECK], {
                detached,
                stdio: 'ignore',
                windowsHide: true,
            });
            processTree = new ProcessTree(child, { detached });
        } catch {
            resolve(false);
            return;
        }

        child.once('error', () => finish(false));
        child.once('exit', (code, exitSignal) => {
            finish(code === 0 && exitSignal === null);
        });
        signal?.addEventListener('abort', onAbort, { once: true });
        timer = setTimeout(() => finish(false), Math.max(1, timeoutMs));
        if (signal?.aborted) { onAbort(); }
    });
}

function awaitUnlessCancelled(
    result: Promise<boolean>,
    signal?: AbortSignal,
): Promise<boolean> {
    if (!signal) { return result; }
    if (signal.aborted) { return Promise.resolve(false); }

    return new Promise((resolve) => {
        let settled = false;
        const finish = (supported: boolean) => {
            if (settled) { return; }
            settled = true;
            signal.removeEventListener('abort', onAbort);
            resolve(supported);
        };
        const onAbort = () => finish(false);
        signal.addEventListener('abort', onAbort, { once: true });
        result.then(
            (supported) => finish(supported),
            () => finish(false),
        );
        if (signal.aborted) { onAbort(); }
    });
}

/** Create a probe that shares in-flight work without caching stale outcomes. */
export function createPythonSupportProbe(
    options: PythonProbeOptions = {},
): PythonSupportProbe {
    const results = new Map<string, Promise<boolean>>();
    const run = options.probe ?? ((command: string, signal?: AbortSignal) =>
        probeBtrcPython(command, signal, options.timeoutMs));

    return (command: string, signal?: AbortSignal) => {
        if (!command.trim() || options.signal?.aborted || signal?.aborted) {
            return Promise.resolve(false);
        }
        let result = results.get(command);
        if (!result) {
            result = Promise.resolve()
                .then(() => run(command, options.signal))
                .catch(() => false);
            results.set(command, result);
            void result.then(() => {
                // Executables and PATH entries can change during an extension
                // session. Share concurrent work, then revalidate later calls.
                if (results.get(command) === result) {
                    results.delete(command);
                }
            });
        }
        return awaitUnlessCancelled(result, signal);
    };
}

/** Shared default for callers that do not own an extension lifecycle. */
export const supportsBtrcPython = createPythonSupportProbe();
