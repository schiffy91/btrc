import { ChildProcess } from 'node:child_process';

import { HostRuntime, ProcessTree } from './process';

const DEFAULT_PROBE_TIMEOUT_MS = 5000;
const VERSION_CHECK = 'import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)';

export type PythonProbeOperation = (
    command: string,
    signal?: AbortSignal,
) => Promise<boolean>;

export interface PythonRuntimeOptions {
    timeoutMs?: number;
    signal?: AbortSignal;
    probe?: PythonProbeOperation;
}

/** Resolves and probes the Python interpreter used by bundled tooling. */
export class PythonRuntimeProbe {
    private readonly timeoutMs: number;
    private readonly lifecycleSignal: AbortSignal | undefined;
    private readonly operation: PythonProbeOperation;
    private readonly inFlight = new Map<string, Promise<boolean>>();

    constructor(
        private readonly host: HostRuntime,
        options: PythonRuntimeOptions = {},
    ) {
        this.timeoutMs = Math.max(1, options.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS);
        this.lifecycleSignal = options.signal;
        this.operation = options.probe ?? ((command, signal) => this.probe(command, signal));
    }

    resolveCommand(configured: string | undefined): string {
        if (configured?.trim()) { return configured; }
        return this.host.platform === 'win32' ? 'python' : 'python3';
    }

    supports(command: string, signal?: AbortSignal): Promise<boolean> {
        if (
            !command.trim()
            || this.lifecycleSignal?.aborted
            || signal?.aborted
        ) {
            return Promise.resolve(false);
        }

        let result = this.inFlight.get(command);
        if (!result) {
            result = Promise.resolve()
                .then(() => this.operation(command, this.lifecycleSignal))
                .catch(() => false);
            this.inFlight.set(command, result);
            void result.then(() => {
                // Share only concurrent work: executables and PATH entries can
                // change during a long-running editor session.
                if (this.inFlight.get(command) === result) {
                    this.inFlight.delete(command);
                }
            });
        }
        return this.awaitUnlessCancelled(result, signal);
    }

    private probe(command: string, signal?: AbortSignal): Promise<boolean> {
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
                const detached = this.host.platform !== 'win32';
                child = this.host.spawn(
                    command,
                    ['-I', '-S', '-c', VERSION_CHECK],
                    {
                        detached,
                        stdio: 'ignore',
                        windowsHide: true,
                    },
                );
                processTree = new ProcessTree(child, this.host, { detached });
            } catch {
                resolve(false);
                return;
            }

            child.once('error', () => finish(false));
            child.once('exit', (code, exitSignal) => {
                finish(code === 0 && exitSignal === null);
            });
            signal?.addEventListener('abort', onAbort, { once: true });
            timer = setTimeout(() => finish(false), this.timeoutMs);
            if (signal?.aborted) { onAbort(); }
        });
    }

    private awaitUnlessCancelled(
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
}
