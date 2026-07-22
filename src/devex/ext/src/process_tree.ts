import { ChildProcess, spawn } from 'node:child_process';
import * as path from 'node:path';

const DEFAULT_TERMINATION_TIMEOUT_MS = 1000;

export interface ProcessTreeOptions {
    detached?: boolean;
    timeoutMs?: number;
}

function isRunning(child: ChildProcess): boolean {
    return child.exitCode === null && child.signalCode === null;
}

function killDirectly(child: ChildProcess): void {
    if (!isRunning(child)) { return; }
    try {
        child.kill('SIGKILL');
    } catch {
        // Concurrent process exit needs no further direct cleanup.
    }
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<void> {
    if (!isRunning(child)) { return Promise.resolve(); }
    return new Promise((resolve) => {
        let settled = false;
        const finish = () => {
            if (settled) { return; }
            settled = true;
            clearTimeout(timer);
            child.removeListener('close', finish);
            resolve();
        };
        const timer = setTimeout(finish, timeoutMs);
        child.once('close', finish);
    });
}

function remainingTime(deadline: number): number {
    return Math.max(1, deadline - Date.now());
}

export function windowsTaskkillPath(env: NodeJS.ProcessEnv = process.env): string {
    const systemRoot = env.SystemRoot ?? env.SYSTEMROOT ?? env.windir ?? env.WINDIR;
    return systemRoot
        ? path.win32.join(systemRoot, 'System32', 'taskkill.exe')
        : 'taskkill.exe';
}

function taskkill(pid: number, timeoutMs: number): Promise<boolean> {
    return new Promise((resolve) => {
        let killer: ChildProcess;
        try {
            killer = spawn(
                windowsTaskkillPath(),
                ['/PID', String(pid), '/T', '/F'],
                { stdio: 'ignore', windowsHide: true },
            );
        } catch {
            resolve(false);
            return;
        }
        let settled = false;
        const finish = (success: boolean) => {
            if (settled) { return; }
            settled = true;
            clearTimeout(timer);
            resolve(success);
        };
        const timer = setTimeout(() => {
            killDirectly(killer);
            finish(false);
        }, timeoutMs);
        killer.once('error', () => finish(false));
        killer.once('exit', (code, signal) => {
            finish(code === 0 && signal === null);
        });
    });
}

/**
 * Idempotently terminates one live process tree. Detached POSIX groups remain
 * addressable after their leader exits; Windows taskkill trees do not.
 */
export class ProcessTree {
    private readonly pid: number | undefined;
    private readonly detached: boolean;
    private readonly timeoutMs: number;
    private stopResult: Promise<void> | undefined;

    constructor(
        private readonly child: ChildProcess,
        options: ProcessTreeOptions = {},
    ) {
        this.pid = child.pid;
        this.detached = options.detached ?? false;
        this.timeoutMs = Math.max(1, options.timeoutMs ?? DEFAULT_TERMINATION_TIMEOUT_MS);
    }

    stop(): Promise<void> {
        this.stopResult ??= this.stopOnce();
        return this.stopResult;
    }

    private async stopOnce(): Promise<void> {
        const deadline = Date.now() + this.timeoutMs;
        const pid = this.pid;
        if (pid === undefined) {
            killDirectly(this.child);
            await waitForExit(this.child, remainingTime(deadline));
            return;
        }

        if (process.platform === 'win32') {
            // Never taskkill a PID after Node observed its exit: Windows may
            // reuse that PID, and taskkill cannot safely recover an orphaned
            // tree from a dead root. Active roots still get recursive /T.
            if (isRunning(this.child)
                && !await taskkill(pid, remainingTime(deadline))) {
                killDirectly(this.child);
            }
        } else if (this.detached) {
            try {
                // The group may outlive its leader, so attempt this even after
                // the direct child has reported exit.
                process.kill(-pid, 'SIGKILL');
            } catch {
                killDirectly(this.child);
            }
        } else {
            killDirectly(this.child);
        }
        await waitForExit(this.child, remainingTime(deadline));
    }
}
