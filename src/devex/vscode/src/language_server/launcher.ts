import * as path from 'node:path';

import { HostRuntime } from '../runtime/process';
import { PythonRuntimeProbe } from '../runtime/python';

export interface LanguageServerConfiguration {
    pythonPath: string;
    serverPath: string;
    serverCommand: string;
    serverCommandExplicit: boolean;
    useNixDevShell: boolean;
    pythonExplicit: boolean;
}

export interface LanguageServerLaunchContext {
    extensionPath: string;
    workspaceRoot?: string;
    config: LanguageServerConfiguration;
    signal?: AbortSignal;
}

export interface LanguageServerLaunch {
    command: string;
    args: string[];
    cwd: string;
    source: string;
    entrypoint?: string;
    projectRoot?: string;
}

interface LocalLanguageServer {
    entrypoint: string;
    projectRoot: string;
    source: string;
}

/** Resolves one launch plan for an installed, bundled, or source LSP. */
export class LanguageServerLaunchResolver {
    constructor(
        private readonly host: HostRuntime,
        private readonly python: PythonRuntimeProbe,
    ) {}

    async resolve(
        context: LanguageServerLaunchContext,
    ): Promise<LanguageServerLaunch | undefined> {
        if (context.signal?.aborted) { return undefined; }

        const supportResults = new Map<string, Promise<boolean>>();
        const workspaceRoot = context.workspaceRoot;
        const command = context.config.serverCommand.trim();
        const defaultCwd = workspaceRoot ?? context.extensionPath;
        const localServers = this.sourceTreeServers(context);
        const attemptedLocalServers = new Set<string>();

        if (
            context.config.serverPath
            && this.host.exists(context.config.serverPath)
        ) {
            const entrypoint = path.resolve(context.config.serverPath);
            const server = {
                entrypoint,
                projectRoot: path.resolve(
                    path.dirname(entrypoint),
                    '..',
                    '..',
                    '..',
                ),
                source: 'serverPath',
            };
            return this.pythonLaunch(server, context, supportResults);
        }

        if (context.config.serverCommandExplicit && path.isAbsolute(command)) {
            const absoluteCommand = this.host.resolveCommand(command);
            if (absoluteCommand) {
                return {
                    command: absoluteCommand,
                    args: [],
                    cwd: defaultCwd,
                    source: 'serverCommand',
                };
            }
        }

        const preferredLocalServer = localServers[0];
        if (
            preferredLocalServer?.source === 'sourceTree'
            && !context.config.serverCommandExplicit
        ) {
            const launch = await this.launchFirstLocalServer(
                [preferredLocalServer],
                context,
                attemptedLocalServers,
                supportResults,
            );
            if (launch) { return launch; }
            if (context.signal?.aborted) { return undefined; }
        }

        const workspaceLaunch = this.workspaceCommandLaunch(
            context,
            workspaceRoot,
            command,
        );
        if (workspaceLaunch) { return workspaceLaunch; }

        const commandCandidate = command
            ? this.host.resolveCommand(command)
            : undefined;
        if (context.config.serverCommandExplicit && commandCandidate) {
            return {
                command: commandCandidate,
                args: [],
                cwd: defaultCwd,
                source: 'serverCommand',
            };
        }

        if (localServers.length > 0) {
            const launch = await this.launchFirstLocalServer(
                localServers,
                context,
                attemptedLocalServers,
                supportResults,
            );
            if (launch) { return launch; }
            if (context.signal?.aborted) { return undefined; }
        }

        if (commandCandidate) {
            return {
                command: commandCandidate,
                args: [],
                cwd: defaultCwd,
                source: 'serverCommand',
            };
        }
        return undefined;
    }

    private sourceTreeServers(
        context: LanguageServerLaunchContext,
    ): LocalLanguageServer[] {
        const candidates = [
            { projectRoot: context.workspaceRoot, source: 'sourceTree' },
            {
                projectRoot: path.resolve(
                    context.extensionPath,
                    '..',
                    '..',
                    '..',
                ),
                source: 'sourceTree',
            },
            {
                projectRoot: path.join(context.extensionPath, 'server'),
                source: 'bundledServer',
            },
        ];
        const servers: LocalLanguageServer[] = [];
        const seen = new Set<string>();
        for (const candidate of candidates) {
            if (!candidate.projectRoot) { continue; }
            const projectRoot = path.resolve(candidate.projectRoot);
            if (seen.has(projectRoot)) { continue; }
            seen.add(projectRoot);
            const entrypoint = path.join(
                projectRoot,
                'src',
                'devex',
                'lsp',
                '__main__.py',
            );
            if (this.host.exists(entrypoint)) {
                servers.push({ entrypoint, projectRoot, source: candidate.source });
            }
        }
        return servers;
    }

    private async launchFirstLocalServer(
        candidates: LocalLanguageServer[],
        context: LanguageServerLaunchContext,
        attempted: Set<string>,
        supportResults: Map<string, Promise<boolean>>,
    ): Promise<LanguageServerLaunch | undefined> {
        for (const candidate of candidates) {
            if (attempted.has(candidate.entrypoint)) { continue; }
            attempted.add(candidate.entrypoint);
            const launch = await this.pythonLaunch(
                candidate,
                context,
                supportResults,
            );
            if (launch) { return launch; }
            if (context.signal?.aborted) { return undefined; }
        }
        return undefined;
    }

    private async pythonLaunch(
        server: LocalLanguageServer,
        context: LanguageServerLaunchContext,
        supportResults: Map<string, Promise<boolean>>,
    ): Promise<LanguageServerLaunch | undefined> {
        const virtualEnvironmentPython = this.host.platform === 'win32'
            ? path.join(
                server.projectRoot,
                'src',
                'devex',
                'lsp',
                '.venv',
                'Scripts',
                'python.exe',
            )
            : path.join(
                server.projectRoot,
                'src',
                'devex',
                'lsp',
                '.venv',
                'bin',
                'python3',
            );
        const nix = this.host.resolveCommand('nix');
        const flake = path.join(server.projectRoot, 'flake.nix');

        if (context.config.pythonExplicit) {
            return await this.supportsPython(
                context.config.pythonPath,
                context.signal,
                supportResults,
            )
                ? this.moduleLaunch(context.config.pythonPath, server)
                : undefined;
        }
        if (
            this.host.exists(virtualEnvironmentPython)
            && await this.supportsPython(
                virtualEnvironmentPython,
                context.signal,
                supportResults,
            )
        ) {
            return this.moduleLaunch(virtualEnvironmentPython, server);
        }
        if (context.signal?.aborted) { return undefined; }
        if (
            context.config.useNixDevShell
            && nix
            && this.host.exists(flake)
        ) {
            return {
                command: nix,
                args: [
                    'develop',
                    server.projectRoot,
                    '--command',
                    'python3',
                    '-m',
                    'src.devex.lsp',
                ],
                cwd: server.projectRoot,
                source: server.source,
                entrypoint: server.entrypoint,
                projectRoot: server.projectRoot,
            };
        }
        return await this.supportsPython(
            context.config.pythonPath,
            context.signal,
            supportResults,
        )
            ? this.moduleLaunch(context.config.pythonPath, server)
            : undefined;
    }

    private moduleLaunch(
        command: string,
        server: LocalLanguageServer,
    ): LanguageServerLaunch {
        return {
            command,
            args: ['-m', 'src.devex.lsp'],
            cwd: server.projectRoot,
            source: server.source,
            entrypoint: server.entrypoint,
            projectRoot: server.projectRoot,
        };
    }

    private supportsPython(
        command: string,
        signal: AbortSignal | undefined,
        results: Map<string, Promise<boolean>>,
    ): Promise<boolean> {
        let result = results.get(command);
        if (!result) {
            result = this.python.supports(command, signal).catch(() => false);
            results.set(command, result);
        }
        return result;
    }

    private workspaceCommandLaunch(
        context: LanguageServerLaunchContext,
        workspaceRoot: string | undefined,
        command: string,
    ): LanguageServerLaunch | undefined {
        if (!workspaceRoot || !command) { return undefined; }

        const direnv = this.host.resolveCommand('direnv');
        if (direnv && this.host.exists(path.join(workspaceRoot, '.envrc'))) {
            return {
                command: direnv,
                args: ['exec', workspaceRoot, command],
                cwd: workspaceRoot,
                source: 'direnv',
            };
        }
        if (!context.config.useNixDevShell) { return undefined; }

        const nixShell = this.host.resolveCommand('nix-shell');
        const nix = this.host.resolveCommand('nix');
        const shellNix = path.join(workspaceRoot, 'shell.nix');
        const flake = path.join(workspaceRoot, 'flake.nix');
        if (nixShell && this.host.exists(shellNix)) {
            return {
                command: nixShell,
                args: [shellNix, '--run', command],
                cwd: workspaceRoot,
                source: 'workspaceShellNix',
            };
        }
        if (nix && this.host.exists(flake)) {
            return {
                command: nix,
                args: ['develop', workspaceRoot, '--command', command],
                cwd: workspaceRoot,
                source: 'workspaceFlake',
            };
        }
        return undefined;
    }
}
