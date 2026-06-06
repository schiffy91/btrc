import * as fs from 'fs';
import * as path from 'path';

export interface BtrcLaunchConfig {
    pythonPath: string;
    serverPath: string;
    serverCommand: string;
    useNixDevShell: boolean;
    pythonExplicit: boolean;
}

export interface BtrcLaunchContext {
    extensionPath: string;
    workspaceRoot?: string;
    config: BtrcLaunchConfig;
    env?: NodeJS.ProcessEnv;
    exists?: (candidate: string) => boolean;
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

function commandPath(context: BtrcLaunchContext, command: string): string | undefined {
    const env = context.env ?? process.env;
    const exts = process.platform === 'win32' ? ['.exe', '.cmd', ''] : [''];
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
            if (pathExists(context, candidate)) { return candidate; }
        }
    }
    return undefined;
}

function resolveCommand(context: BtrcLaunchContext, command: string): string | undefined {
    if (!command) { return undefined; }
    if (path.isAbsolute(command)) {
        return pathExists(context, command) ? command : undefined;
    }
    return commandPath(context, command);
}

function sourceTreeServer(context: BtrcLaunchContext): { serverScript: string, projectRoot: string, source: string } | undefined {
    const candidates = [
        context.workspaceRoot,
        path.resolve(context.extensionPath, '..', '..', '..'),
        path.join(context.extensionPath, 'server'),
    ];
    for (const candidate of candidates) {
        if (!candidate) { continue; }
        const probe = path.join(candidate, 'src', 'devex', 'lsp', 'server.py');
        if (pathExists(context, probe)) {
            return {
                serverScript: probe,
                projectRoot: candidate,
                source: candidate.endsWith(`${path.sep}server`) ? 'bundledServer' : 'sourceTree',
            };
        }
    }
    return undefined;
}

function pythonLaunch(
    context: BtrcLaunchContext,
    serverScript: string,
    projectRoot: string,
    source: string,
): BtrcServerLaunch {
    const isWindows = process.platform === 'win32';
    const venvPython = isWindows
        ? path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'bin', 'python3');
    const nixBin = commandPath(context, 'nix');
    const flakePath = path.join(projectRoot, 'flake.nix');

    if (context.config.pythonExplicit) {
        return { command: context.config.pythonPath, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot };
    }
    if (pathExists(context, venvPython)) {
        return { command: venvPython, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot };
    }
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
    return { command: context.config.pythonPath, args: [serverScript], cwd: projectRoot, source, serverScript, projectRoot };
}

export function resolveServerLaunch(context: BtrcLaunchContext): BtrcServerLaunch | undefined {
    const workspaceRoot = context.workspaceRoot;
    const command = context.config.serverCommand.trim();
    const defaultCwd = workspaceRoot ?? context.extensionPath;

    if (context.config.serverPath && pathExists(context, context.config.serverPath)) {
        const serverScript = context.config.serverPath;
        const projectRoot = path.resolve(path.dirname(serverScript), '..', '..', '..');
        return pythonLaunch(context, serverScript, projectRoot, 'serverPath');
    }

    if (path.isAbsolute(command)) {
        const absoluteCommand = resolveCommand(context, command);
        if (absoluteCommand) {
            return { command: absoluteCommand, args: [], cwd: defaultCwd, source: 'serverCommand' };
        }
    }

    if (workspaceRoot && command) {
        const direnv = commandPath(context, 'direnv');
        if (direnv && pathExists(context, path.join(workspaceRoot, '.envrc'))) {
            return {
                command: direnv,
                args: ['exec', workspaceRoot, command],
                cwd: workspaceRoot,
                source: 'direnv',
            };
        }

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
    }

    const commandCandidate = resolveCommand(context, command);
    if (commandCandidate) {
        return { command: commandCandidate, args: [], cwd: defaultCwd, source: 'serverCommand' };
    }

    const localServer = sourceTreeServer(context);
    if (localServer) {
        return pythonLaunch(context, localServer.serverScript, localServer.projectRoot, localServer.source);
    }

    return undefined;
}
