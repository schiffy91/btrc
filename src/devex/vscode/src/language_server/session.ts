import type {
    ChildProcessInfo,
    ServerOptions,
} from 'vscode-languageclient/node';

import { HostRuntime, ProcessTree } from '../runtime/process';
import { LanguageServerLaunch } from './launcher';

const DEFAULT_GRACEFUL_STOP_MS = 2000;
const DEFAULT_CLEANUP_TIMEOUT_MS = 1500;

export interface StartStopLanguageClient {
    start(): Promise<void>;
    stop(): Promise<void>;
}

export type LanguageClientFactory = (
    serverOptions: ServerOptions,
) => StartStopLanguageClient;

export interface LanguageServerSessionOptions {
    gracefulStopMs?: number;
    cleanupTimeoutMs?: number;
}

type SessionState =
    | 'idle'
    | 'starting'
    | 'running'
    | 'failed'
    | 'stopping'
    | 'stopped';

/** Owns the language client and every server process it can create. */
export class LanguageServerSession {
    private readonly client: StartStopLanguageClient;
    private readonly processes = new Set<ProcessTree>();
    private readonly gracefulStopMs: number;
    private readonly cleanupTimeoutMs: number;

    private state: SessionState = 'idle';
    private startResult: Promise<void> | undefined;
    private stopResult: Promise<void> | undefined;
    private processStopResult: Promise<void> | undefined;

    constructor(
        private readonly launch: LanguageServerLaunch,
        clientFactory: LanguageClientFactory,
        private readonly host: HostRuntime,
        options: LanguageServerSessionOptions = {},
    ) {
        const serverOptions: ServerOptions = () => this.spawnServer();
        this.client = clientFactory(serverOptions);
        this.gracefulStopMs = Math.max(
            1,
            options.gracefulStopMs ?? DEFAULT_GRACEFUL_STOP_MS,
        );
        this.cleanupTimeoutMs = Math.max(
            1,
            options.cleanupTimeoutMs ?? DEFAULT_CLEANUP_TIMEOUT_MS,
        );
    }

    static describeError(error: unknown): string {
        try {
            if (error instanceof Error) {
                return error.message || error.name || 'Unknown error';
            }
            return String(error);
        } catch {
            return 'Unknown error';
        }
    }

    start(): Promise<void> {
        if (this.stopResult) {
            const rejection = Promise.reject<void>(
                new Error('Cannot start a language server session after shutdown'),
            );
            void rejection.catch(() => undefined);
            return rejection;
        }
        if (!this.startResult) {
            this.state = 'starting';
            const result = Promise.resolve().then(() => this.client.start());
            this.startResult = result;
            void result.then(
                () => {
                    if (this.state === 'starting') { this.state = 'running'; }
                },
                () => {
                    if (this.state === 'starting') { this.state = 'failed'; }
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
            if (wasRunning) {
                await this.settleWithin(clientStop, this.gracefulStopMs);
            } else {
                void clientStop.catch(() => undefined);
            }
        }
        await this.settleWithin(
            this.stopProcesses(),
            this.cleanupTimeoutMs,
        );
        this.state = 'stopped';
    }

    private stopProcesses(): Promise<void> {
        this.processStopResult ??= Promise.all(
            [...this.processes].map((processTree) => processTree.stop()),
        ).then(() => undefined);
        return this.processStopResult;
    }

    private async spawnServer(): Promise<ChildProcessInfo> {
        if (this.state === 'stopping' || this.state === 'stopped') {
            throw new Error('Cannot launch the language server during shutdown');
        }
        const detached = this.host.platform !== 'win32';
        const child = this.host.spawn(this.launch.command, this.launch.args, {
            cwd: this.launch.cwd,
            detached,
            stdio: 'pipe',
            windowsHide: true,
        });
        const processTree = new ProcessTree(child, this.host, { detached });
        this.processes.add(processTree);
        const cleanup = () => {
            void processTree.stop()
                .catch(() => undefined)
                .finally(() => this.processes.delete(processTree));
        };
        child.once('error', cleanup);
        child.once('exit', cleanup);
        return { process: child, detached };
    }

    private settleWithin(
        operation: Promise<unknown>,
        timeoutMs: number,
    ): Promise<void> {
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
}
