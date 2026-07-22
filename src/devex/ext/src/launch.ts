import * as fs from 'fs';
import * as path from 'path';
import { PythonSupportProbe, supportsBtrcPython } from './python_runtime';
import { isLaunchableFile } from './launchable_file';

export interface BtrcLaunchConfig {
    pythonPath: string;
    serverPath: string;
    serverCommand: string;
    serverCommandExplicit: boolean;
    useNixDevShell: boolean;
    pythonExplicit: boolean;
}

export interface BtrcLaunchContext {
    extensionPath: string;
    workspaceRoot?: string;
    config: BtrcLaunchConfig;
    env?: NodeJS.ProcessEnv;
    exists?: (candidate: string) => boolean;
    isExecutableFile?: (candidate: string) => boolean;
    supportsPython?: PythonSupportProbe;
    signal?: AbortSignal;
}

export interface BtrcServerLaunch {
    command: string;
    args: string[];
    cwd: string;
    source: string;
    serverScript?: string;
    projectRoot?: string;
}

function pathExists(context: BtrcLaunchContext, candidate: string): boolean {
    return (context.exists ?? fs.existsSync)(candidate);
}

function isExecutableFile(context: BtrcLaunchContext, candidate: string): boolean {
    if (context.isExecutableFile) { return context.isExecutableFile(candidate); }
    return isLaunchableFile(candidate);
}

function commandPath(context: BtrcLaunchContext, command: string): string | undefined {
    const env = context.env ?? process.env;
    const windowsExecutableExtensions = (
        env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD'
    ).split(';').map((extension) => {
        const normalized = extension.trim().toLowerCase();
        return normalized && !normalized.startsWith('.') ? `.${normalized}` : normalized;
    }).filter(Boolean);
    const exts = process.platform === 'win32'
        ? [...new Set([...windowsExecutableExtensions, ''])]
        : [''];
    const extraDirs = [
        path.join(env.HOME || '', '.nix-profile', 'bin'),
        path.join('/etc', 'profiles', 'per-user', env.USER || '', 'bin'),
        '/run/current-system/sw/bin',
        '/nix/var/nix/profiles/default/bin',
        '/opt/homebrew/bin',
        '/usr/local/bin',
    ];
    const dirs = [...new Set([...(env.PATH || '').split(path.delimiter), ...extraDirs])];
    for (const dir of dirs) {
        if (!dir) { continue; }
        for (const ext of exts) {
            const candidate = path.join(dir, command + ext);
            if (isExecutableFile(context, candidate)) { return candidate; }
        }
    }
    return undefined;
}

function resolveCommand(context: BtrcLaunchContext, command: string): string | undefined {
    if (!command) { return undefined; }
    if (path.isAbsolute(command)) {
        return isExecutableFile(context, command) ? command : undefined;
    }
    return commandPath(context, command);
}

interface LocalServer {
    serverScript: string;
    projectRoot: string;
    source: string;
}

function sourceTreeServers(context: BtrcLaunchContext): LocalServer[] {
    const candidates = [
        { projectRoot: context.workspaceRoot, source: 'sourceTree' },
        {
            projectRoot: path.resolve(context.extensionPath, '..', '..', '..'),
            source: 'sourceTree',
        },
        {
            projectRoot: path.join(context.extensionPath, 'server'),
            source: 'bundledServer',
        },
    ];
    const servers: LocalServer[] = [];
    const seen = new Set<string>();
    for (const candidate of candidates) {
        if (!candidate.projectRoot) { continue; }
        const projectRoot = path.resolve(candidate.projectRoot);
        if (seen.has(projectRoot)) { continue; }
        seen.add(projectRoot);
        const probe = path.join(projectRoot, 'src', 'devex', 'lsp', 'server.py');
        if (pathExists(context, probe)) {
            servers.push({
                serverScript: probe,
                projectRoot,
                source: candidate.source,
            });
        }
    }
    return servers;
}

async function pythonLaunch(
    context: BtrcLaunchContext,
    serverScript: string,
    projectRoot: string,
    source: string,
): Promise<BtrcServerLaunch | undefined> {
    const isWindows = process.platform === 'win32';
    const venvPython = isWindows
        ? path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'bin', 'python3');
    const nixBin = commandPath(context, 'nix');
    const flakePath = path.join(projectRoot, 'flake.nix');
    const supportsPython = context.supportsPython ?? supportsBtrcPython;

    if (context.config.pythonExplicit) {
        return await supportsPython(context.config.pythonPath, context.signal)
            ? { command: context.config.pythonPath, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot }
            : undefined;
    }
    if (pathExists(context, venvPython)) {
        if (await supportsPython(venvPython, context.signal)) {
            return { command: venvPython, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot };
        }
    }
    if (context.signal?.aborted) { return undefined; }
    if (context.config.useNixDevShell && nixBin && pathExists(context, flakePath)) {
        return {
            command: nixBin,
            args: ['develop', projectRoot, '--command', 'python3', serverScript],
            cwd: projectRoot,
            source,
            serverScript,
            projectRoot,
        };
    }
    return await supportsPython(context.config.pythonPath, context.signal)
        ? { command: context.config.pythonPath, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot }
        : undefined;
}

function workspaceCommandLaunch(
    context: BtrcLaunchContext,
    workspaceRoot: string | undefined,
    command: string,
): BtrcServerLaunch | undefined {
    if (!workspaceRoot || !command) { return undefined; }

    const direnv = commandPath(context, 'direnv');
    if (direnv && pathExists(context, path.join(workspaceRoot, '.envrc'))) {
        return {
            command: direnv,
            args: ['exec', workspaceRoot, command],
            cwd: workspaceRoot,
            source: 'direnv',
        };
    }

    if (!context.config.useNixDevShell) { return undefined; }

    const nixShell = commandPath(context, 'nix-shell');
    const nix = commandPath(context, 'nix');
    const shellNix = path.join(workspaceRoot, 'shell.nix');
    const workspaceFlake = path.join(workspaceRoot, 'flake.nix');
    if (nixShell && pathExists(context, shellNix)) {
        return {
            command: nixShell,
            args: [shellNix, '--run', command],
            cwd: workspaceRoot,
            source: 'workspaceShellNix',
        };
    }
    if (nix && pathExists(context, workspaceFlake)) {
        return {
            command: nix,
            args: ['develop', workspaceRoot, '--command', command],
            cwd: workspaceRoot,
            source: 'workspaceFlake',
        };
    }
    return undefined;
}

export async function resolveServerLaunch(context: BtrcLaunchContext): Promise<BtrcServerLaunch | undefined> {
    if (context.signal?.aborted) { return undefined; }
    const sharedSupportsPython = context.supportsPython ?? supportsBtrcPython;
    const supportResults = new Map<string, Promise<boolean>>();
    const resolutionContext: BtrcLaunchContext = {
        ...context,
        supportsPython: (command, signal) => {
            let result = supportResults.get(command);
            if (!result) {
                result = Promise.resolve()
                    .then(() => sharedSupportsPython(command, signal))
                    .catch(() => false);
                supportResults.set(command, result);
            }
            return result;
        },
    };
    const workspaceRoot = context.workspaceRoot;
    const command = context.config.serverCommand.trim();
    const defaultCwd = workspaceRoot ?? context.extensionPath;
    const localServers = sourceTreeServers(context);
    const attemptedLocalServers = new Set<string>();

    const launchLocalServers = async (
        candidates: LocalServer[],
    ): Promise<BtrcServerLaunch | undefined> => {
        for (const localServer of candidates) {
            if (attemptedLocalServers.has(localServer.serverScript)) { continue; }
            attemptedLocalServers.add(localServer.serverScript);
            const launch = await pythonLaunch(
                resolutionContext,
                localServer.serverScript,
                localServer.projectRoot,
                localServer.source,
            );
            if (launch) { return launch; }
            if (context.signal?.aborted) { return undefined; }
        }
        return undefined;
    };

    if (context.config.serverPath && pathExists(context, context.config.serverPath)) {
        const serverScript = context.config.serverPath;
        const projectRoot = path.resolve(path.dirname(serverScript), '..', '..', '..');
        return await pythonLaunch(resolutionContext, serverScript, projectRoot, 'serverPath');
    }

    if (context.config.serverCommandExplicit && path.isAbsolute(command)) {
        const absoluteCommand = resolveCommand(context, command);
        if (absoluteCommand) {
            return { command: absoluteCommand, args: [], cwd: defaultCwd, source: 'serverCommand' };
        }
    }

    // A live btrc checkout in the workspace is the most accurate server (it
    // tracks uncommitted compiler/LSP changes, unlike a nix store snapshot).
    // Prefer it unless the user explicitly configured a server command.
    const preferredLocalServer = localServers[0];
    if (
        preferredLocalServer?.source === 'sourceTree'
        && !context.config.serverCommandExplicit
    ) {
        const launch = await launchLocalServers([preferredLocalServer]);
        if (launch) { return launch; }
        if (context.signal?.aborted) { return undefined; }
    }

    const workspaceLaunch = workspaceCommandLaunch(context, workspaceRoot, command);
    if (workspaceLaunch) { return workspaceLaunch; }

    // The user explicitly configured a server command: resolve it on PATH
    // before falling back to a discovered local server, otherwise the
    // explicit setting is silently ignored whenever a checkout/bundle exists.
    const commandCandidate = command ? resolveCommand(context, command) : undefined;
    if (context.config.serverCommandExplicit && commandCandidate) {
        return { command: commandCandidate, args: [], cwd: defaultCwd, source: 'serverCommand' };
    }

    if (localServers.length > 0) {
        const launch = await launchLocalServers(localServers);
        if (launch) { return launch; }
        if (context.signal?.aborted) { return undefined; }
    }

    if (commandCandidate) {
        return { command: commandCandidate, args: [], cwd: defaultCwd, source: 'serverCommand' };
    }

    return undefined;
}
