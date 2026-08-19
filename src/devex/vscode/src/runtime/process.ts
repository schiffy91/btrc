import { ChildProcess, SpawnOptions } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';

import crossSpawn from 'cross-spawn';

const DEFAULT_TERMINATION_TIMEOUT_MS = 1000;

export type ProcessSpawner = (
    command: string,
    args: string[],
    options: SpawnOptions,
) => ChildProcess;

export interface HostRuntimeOptions {
    platform?: NodeJS.Platform;
    env?: NodeJS.ProcessEnv;
    spawn?: ProcessSpawner;
    stat?: (candidate: string) => fs.Stats;
    access?: (candidate: string, mode: number) => void;
    kill?: (pid: number, signal: NodeJS.Signals) => boolean;
    now?: () => number;
}

/** Owns operating-system discovery and process operations for the extension. */
export class HostRuntime {
    readonly platform: NodeJS.Platform;
    readonly env: NodeJS.ProcessEnv;

    private readonly spawnProcess: ProcessSpawner;
    private readonly stat: (candidate: string) => fs.Stats;
    private readonly access: (candidate: string, mode: number) => void;
    private readonly kill: (pid: number, signal: NodeJS.Signals) => boolean;
    private readonly clock: () => number;

    constructor(options: HostRuntimeOptions = {}) {
        this.platform = options.platform ?? process.platform;
        this.env = options.env ?? process.env;
        this.spawnProcess = options.spawn ?? crossSpawn;
        this.stat = options.stat ?? fs.statSync;
        this.access = options.access ?? fs.accessSync;
        this.kill = options.kill ?? process.kill;
        this.clock = options.now ?? Date.now;
    }

    exists(candidate: string): boolean {
        try {
            this.stat(candidate);
            return true;
        } catch {
            return false;
        }
    }

    isLaunchableFile(candidate: string): boolean {
        try {
            if (!this.stat(candidate).isFile()) { return false; }
            this.access(
                candidate,
                this.platform === 'win32' ? fs.constants.R_OK : fs.constants.X_OK,
            );
            return true;
        } catch {
            return false;
        }
    }

    resolveCommand(command: string): string | undefined {
        if (!command) { return undefined; }
        if (path.isAbsolute(command)) {
            return this.isLaunchableFile(command) ? command : undefined;
        }

        const windowsExtensions = (this.env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD')
            .split(';')
            .map((extension) => {
                const normalized = extension.trim().toLowerCase();
                return normalized && !normalized.startsWith('.')
                    ? `.${normalized}`
                    : normalized;
            })
            .filter(Boolean);
        const extensions = this.platform === 'win32'
            ? [...new Set([...windowsExtensions, ''])]
            : [''];
        const extraDirectories = [
            path.join(this.env.HOME || '', '.nix-profile', 'bin'),
            path.join('/etc', 'profiles', 'per-user', this.env.USER || '', 'bin'),
            '/run/current-system/sw/bin',
            '/nix/var/nix/profiles/default/bin',
            '/opt/homebrew/bin',
            '/usr/local/bin',
        ];
        const directories = [
            ...new Set([
                ...(this.env.PATH || '').split(path.delimiter),
                ...extraDirectories,
            ]),
        ];
        for (const directory of directories) {
            if (!directory) { continue; }
            for (const extension of extensions) {
                const candidate = path.join(directory, command + extension);
                if (this.isLaunchableFile(candidate)) { return candidate; }
            }
        }
        return undefined;
    }

    spawn(command: string, args: string[], options: SpawnOptions): ChildProcess {
        return this.spawnProcess(command, args, options);
    }

    now(): number {
        return this.clock();
    }

    killProcessGroup(pid: number): void {
        this.kill(-pid, 'SIGKILL');
    }

    windowsTaskkillPath(): string {
        const systemRoot = this.env.SystemRoot
            ?? this.env.SYSTEMROOT
            ?? this.env.windir
            ?? this.env.WINDIR;
        return systemRoot
            ? path.win32.join(systemRoot, 'System32', 'taskkill.exe')
            : 'taskkill.exe';
    }

    terminateWindowsTree(pid: number, timeoutMs: number): Promise<boolean> {
        return new Promise((resolve) => {
            let killer: ChildProcess;
            try {
                killer = this.spawn(
                    this.windowsTaskkillPath(),
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
                try { killer.kill('SIGKILL'); } catch { /* already exited */ }
                finish(false);
            }, Math.max(1, timeoutMs));
            killer.once('error', () => finish(false));
            killer.once('exit', (code, signal) => {
                finish(code === 0 && signal === null);
            });
        });
    }
}

export interface ProcessTreeOptions {
    detached?: boolean;
    timeoutMs?: number;
}

/** Idempotently owns termination of one child process and its descendants. */
export class ProcessTree {
    private readonly pid: number | undefined;
    private readonly detached: boolean;
    private readonly timeoutMs: number;
    private stopResult: Promise<void> | undefined;

    constructor(
        private readonly child: ChildProcess,
        private readonly host: HostRuntime,
        options: ProcessTreeOptions = {},
    ) {
        this.pid = child.pid;
        this.detached = options.detached ?? false;
        this.timeoutMs = Math.max(
            1,
            options.timeoutMs ?? DEFAULT_TERMINATION_TIMEOUT_MS,
        );
    }

    stop(): Promise<void> {
        this.stopResult ??= this.stopOnce();
        return this.stopResult;
    }

    private isRunning(): boolean {
        return this.child.exitCode === null && this.child.signalCode === null;
    }

    private killDirectly(): void {
        if (!this.isRunning()) { return; }
        try {
            this.child.kill('SIGKILL');
        } catch {
            // A concurrent exit already completed the requested cleanup.
        }
    }

    private waitForExit(timeoutMs: number): Promise<void> {
        if (!this.isRunning()) { return Promise.resolve(); }
        return new Promise((resolve) => {
            let settled = false;
            const finish = () => {
                if (settled) { return; }
                settled = true;
                clearTimeout(timer);
                this.child.removeListener('close', finish);
                resolve();
            };
            const timer = setTimeout(finish, Math.max(1, timeoutMs));
            this.child.once('close', finish);
        });
    }

    private remainingTime(deadline: number): number {
        return Math.max(1, deadline - this.host.now());
    }

    private async stopOnce(): Promise<void> {
        const deadline = this.host.now() + this.timeoutMs;
        const pid = this.pid;
        if (pid === undefined) {
            this.killDirectly();
            await this.waitForExit(this.remainingTime(deadline));
            return;
        }

        if (this.host.platform === 'win32') {
            if (
                this.isRunning()
                && !await this.host.terminateWindowsTree(
                    pid,
                    this.remainingTime(deadline),
                )
            ) {
                this.killDirectly();
            }
        } else if (this.detached) {
            try {
                // Detached process groups can outlive their direct child.
                this.host.killProcessGroup(pid);
            } catch {
                this.killDirectly();
            }
        } else {
            this.killDirectly();
        }
        await this.waitForExit(this.remainingTime(deadline));
    }
}
