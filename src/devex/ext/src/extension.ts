import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient | undefined;
let outputChannel: vscode.OutputChannel;

/** Resolve an executable on PATH (sync), returning its full path or undefined. */
function which(cmd: string): string | undefined {
    const exts = process.platform === 'win32' ? ['.exe', '.cmd', ''] : [''];
    for (const dir of (process.env.PATH || '').split(path.delimiter)) {
        if (!dir) { continue; }
        for (const ext of exts) {
            const candidate = path.join(dir, cmd + ext);
            try {
                if (fs.existsSync(candidate)) { return candidate; }
            } catch {
                // ignore unreadable PATH entries
            }
        }
    }
    return undefined;
}

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('btrc Language Server');
    context.subscriptions.push(outputChannel);

    const config = vscode.workspace.getConfiguration('btrc');
    const configuredPython = config.get<string>('pythonPath', 'python3');
    const configuredServerPath = config.get<string>('serverPath', '');
    const configuredServerCommand = config.get<string>('serverCommand', 'btrc-lsp').trim();

    // Prefer the packaged executable when it is available. It brings the Python
    // dependencies with it, so diagnostics and navigation work outside this
    // repository without hand-maintaining a venv.
    let command: string | undefined;
    let args: string[] = [];
    let cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? context.extensionPath;
    let serverScript: string | undefined;
    let projectRoot: string | undefined;
    let launchSource = 'unresolved';

    const commandCandidate = configuredServerCommand
        ? (path.isAbsolute(configuredServerCommand)
            ? configuredServerCommand
            : which(configuredServerCommand))
        : undefined;
    if (commandCandidate && fs.existsSync(commandCandidate)) {
        command = commandCandidate;
        launchSource = 'serverCommand';
    }

    // Resolve the LSP server script. Prefer the explicit setting
    // (btrc.serverPath) so devcontainers can declare it once. Fall back to
    // source-tree detection for development, then the packaged server payload.
    if (!command && configuredServerPath && fs.existsSync(configuredServerPath)) {
        serverScript = configuredServerPath;
        projectRoot = path.resolve(path.dirname(serverScript), '..', '..', '..');
        launchSource = 'serverPath';
    } else if (!command) {
        const candidates = [
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
            path.resolve(context.extensionPath, '..', '..', '..'),
            path.join(context.extensionPath, 'server'),
        ];
        for (const candidate of candidates) {
            if (!candidate) { continue; }
            const probe = path.join(candidate, 'src', 'devex', 'lsp', 'server.py');
            if (fs.existsSync(probe)) {
                serverScript = probe;
                projectRoot = candidate;
                launchSource = candidate.endsWith(`${path.sep}server`) ? 'bundledServer' : 'sourceTree';
                break;
            }
        }
    }

    if (!command && (!serverScript || !projectRoot)) {
        vscode.window.showErrorMessage(
            'btrc language server not found. Install `btrc-lsp`, set "btrc.serverCommand", ' +
            'set "btrc.serverPath", or open the btrc project folder.'
        );
        return;
    }

    // Decide how to launch the server. Precedence:
    //   1. an explicitly-configured btrc.pythonPath
    //   2. a local venv at src/devex/lsp/.venv
    //   3. the Nix dev shell (flake.nix) — gives the pinned Python 3.13+ with
    //      pygls/lsprotocol already installed, so no manual venv is needed
    //   4. the default `python3` on PATH
    const isWindows = process.platform === 'win32';
    const venvPython = isWindows
        ? path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'bin', 'python3');

    const pythonInspect = config.inspect<string>('pythonPath');
    const pythonExplicit = !!(pythonInspect && (
        pythonInspect.workspaceFolderValue ??
        pythonInspect.workspaceValue ??
        pythonInspect.globalValue));
    const useNix = config.get<boolean>('useNixDevShell', true);
    const nixBin = which('nix');
    const flakePath = path.join(projectRoot, 'flake.nix');

    if (!command && serverScript && projectRoot) {
        cwd = projectRoot;
        if (pythonExplicit) {
            command = configuredPython;
            args = [serverScript];
        } else if (fs.existsSync(venvPython)) {
            command = venvPython;
            args = [serverScript];
        } else if (useNix && nixBin && fs.existsSync(flakePath)) {
            // Run the server inside the project's Nix dev shell.
            command = nixBin;
            args = ['develop', projectRoot, '--command', 'python3', serverScript];
        } else {
            command = configuredPython;
            args = [serverScript];
        }
    }

    outputChannel.appendLine(`Launch: ${command} ${args.join(' ')}`);
    outputChannel.appendLine(`Launch source: ${launchSource}`);
    if (serverScript) { outputChannel.appendLine(`Server script: ${serverScript}`); }
    if (projectRoot) { outputChannel.appendLine(`Project root: ${projectRoot}`); }
    outputChannel.appendLine(`Working directory: ${cwd}`);

    const serverOptions: ServerOptions = {
        command,
        args,
        options: {
            cwd,
        },
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'btrc' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.btrc'),
        },
        outputChannel,
    };

    client = new LanguageClient(
        'btrc',
        'btrc Language Server',
        serverOptions,
        clientOptions
    );

    client.start().then(
        () => {
            outputChannel.appendLine('btrc language server started successfully.');
        },
        (error: Error) => {
            outputChannel.appendLine(`Failed to start btrc language server: ${error.message}`);
            vscode.window.showErrorMessage(
                `btrc language server failed to start: ${error.message}. ` +
                'Check the "btrc Language Server" output channel for details.'
            );
        }
    );

    context.subscriptions.push({
        dispose: () => {
            if (client) {
                client.stop();
            }
        },
    });
}

export function deactivate(): Thenable<void> | undefined {
    if (client) {
        return client.stop();
    }
    return undefined;
}
