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

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('btrc Language Server');
    context.subscriptions.push(outputChannel);

    const config = vscode.workspace.getConfiguration('btrc');
    const configuredPython = config.get<string>('pythonPath', 'python3');
    const configuredServerPath = config.get<string>('serverPath', '');

    // Resolve the LSP server script.  Prefer the explicit setting
    // (btrc.serverPath) so devcontainers can declare it once.  Fall back to
    // auto-detection for development / open-folder workflows.
    let serverScript: string | undefined;
    let projectRoot: string | undefined;

    if (configuredServerPath && fs.existsSync(configuredServerPath)) {
        serverScript = configuredServerPath;
        projectRoot = path.resolve(path.dirname(serverScript), '..', '..', '..');
    } else {
        const candidates = [
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
            path.resolve(context.extensionPath, '..', '..', '..'),
        ];
        for (const candidate of candidates) {
            if (!candidate) { continue; }
            const probe = path.join(candidate, 'src', 'devex', 'lsp', 'server.py');
            if (fs.existsSync(probe)) {
                serverScript = probe;
                projectRoot = candidate;
                break;
            }
        }
    }

    if (!serverScript || !projectRoot) {
        vscode.window.showErrorMessage(
            'btrc language server not found. ' +
            'Set "btrc.serverPath" in your workspace settings, or open the btrc project folder.'
        );
        return;
    }

    // Prefer the venv Python if it exists (cross-platform)
    const isWindows = process.platform === 'win32';
    const venvPython = isWindows
        ? path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'src', 'devex', 'lsp', '.venv', 'bin', 'python3');
    const pythonPath = fs.existsSync(venvPython) ? venvPython : configuredPython;

    outputChannel.appendLine(`Using Python: ${pythonPath}`);
    outputChannel.appendLine(`Server script: ${serverScript}`);
    outputChannel.appendLine(`Project root: ${projectRoot}`);

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: [serverScript],
        options: {
            cwd: projectRoot,
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
