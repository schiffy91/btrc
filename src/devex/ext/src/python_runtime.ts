import { ChildProcess, spawn } from 'node:child_process';

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

function stopProbe(child: ChildProcess): void {
    if (child.exitCode !== null || child.signalCode !== null) { return; }
    try {
        child.kill('SIGKILL');
    } catch {
        // A concurrently exiting process needs no further cleanup.
    }
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
        let timer: NodeJS.Timeout | undefined;
        let settled = false;

        const finish = (supported: boolean, stop: boolean = false) => {
            if (settled) { return; }
            settled = true;
            if (timer) { clearTimeout(timer); }
            signal?.removeEventListener('abort', onAbort);
            if (stop) { stopProbe(child); }
            resolve(supported);
        };
        const onAbort = () => finish(false, true);

        try {
            child = spawn(command, ['-c', VERSION_CHECK], {
                stdio: 'ignore',
                windowsHide: true,
            });
        } catch {
            resolve(false);
            return;
        }

        child.once('error', () => finish(false));
        child.once('exit', (code, exitSignal) => {
            finish(code === 0 && exitSignal === null);
        });
        signal?.addEventListener('abort', onAbort, { once: true });
        timer = setTimeout(() => finish(false, true), Math.max(1, timeoutMs));
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

/** Create a probe that shares in-flight work and caches outcomes by command. */
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
        }
        return awaitUnlessCancelled(result, signal);
    };
}

/** Shared default for callers that do not own an extension lifecycle. */
export const supportsBtrcPython = createPythonSupportProbe();
