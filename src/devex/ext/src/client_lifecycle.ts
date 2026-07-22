const DEFAULT_GRACEFUL_STOP_MS = 2000;
const DEFAULT_CLEANUP_TIMEOUT_MS = 1500;

export interface StartStopClient {
    start(): Promise<void>;
    stop(): Promise<void>;
}

export interface AsyncProcessOwner {
    stop(): Promise<void>;
}

type ClientState = 'idle' | 'starting' | 'running' | 'failed' | 'stopping' | 'stopped';

function settleWithin(operation: Promise<unknown>, timeoutMs: number): Promise<void> {
    return new Promise((resolve) => {
        let settled = false;
        const finish = () => {
            if (settled) { return; }
            settled = true;
            clearTimeout(timer);
            resolve();
        };
        const timer = setTimeout(finish, Math.max(1, timeoutMs));
        operation.then(finish, finish);
    });
}

export function errorMessage(error: unknown): string {
    try {
        if (error instanceof Error) {
            return error.message || error.name || 'Unknown error';
        }
        return String(error);
    } catch {
        return 'Unknown error';
    }
}

/** Coordinates graceful client stop with bounded, independently owned cleanup. */
export class ClientLifecycle {
    private state: ClientState = 'idle';
    private startResult: Promise<void> | undefined;
    private stopResult: Promise<void> | undefined;
    private processStopResult: Promise<void> | undefined;

    constructor(
        private readonly client: StartStopClient,
        private readonly processOwner: AsyncProcessOwner,
        private readonly gracefulStopMs: number = DEFAULT_GRACEFUL_STOP_MS,
        private readonly cleanupTimeoutMs: number = DEFAULT_CLEANUP_TIMEOUT_MS,
    ) {}

    start(): Promise<void> {
        if (this.stopResult) {
            const rejection = Promise.reject<void>(
                new Error('Cannot start a client after shutdown'),
            );
            void rejection.catch(() => undefined);
            return rejection;
        }
        if (!this.startResult) {
            this.state = 'starting';
            const result = Promise.resolve().then(() => this.client.start());
            this.startResult = result;
            // Track state and always consume the rejection even when a caller
            // starts the client without awaiting the returned promise.
            void result.then(
                () => { if (this.state === 'starting') { this.state = 'running'; } },
                () => {
                    if (this.state === 'starting') { this.state = 'failed'; }
                    // LanguageClient can reject initialization while the
                    // spawned server is still alive. Reap it immediately;
                    // waiting for extension deactivation would leak a broken
                    // server for the rest of the editor session.
                    void this.stopProcesses().catch(() => undefined);
                },
            );
        }
        return this.startResult;
    }

    stop(): Promise<void> {
        this.stopResult ??= this.stopOnce();
        return this.stopResult;
    }

    private async stopOnce(): Promise<void> {
        const wasRunning = this.state === 'running';
        this.state = 'stopping';
        if (this.startResult) {
            const clientStop = Promise.resolve().then(() => this.client.stop());
            // A running client gets a graceful LSP shutdown window. During a
            // pending or rejected start, force cleanup immediately instead.
            if (wasRunning) {
                await settleWithin(clientStop, this.gracefulStopMs);
            } else {
                void clientStop.catch(() => undefined);
            }
        }
        await settleWithin(
            this.stopProcesses(),
            this.cleanupTimeoutMs,
        );
        this.state = 'stopped';
    }

    private stopProcesses(): Promise<void> {
        this.processStopResult ??= Promise.resolve()
            .then(() => this.processOwner.stop());
        return this.processStopResult;
    }
}
