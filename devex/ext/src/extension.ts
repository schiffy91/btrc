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

    // The LSP server lives at <project_root>/devex/lsp/server.py
    // Extension is at <project_root>/devex/ext/
    const projectRoot = path.resolve(context.extensionPath, '..', '..');
    const serverScript = path.join(projectRoot, 'devex', 'lsp', 'server.py');

    if (!fs.existsSync(serverScript)) {
        vscode.window.showErrorMessage(
            `btrc language server not found at ${serverScript}. ` +
            'Make sure the extension is installed inside the btrc project.'
        );
        return;
    }

    // Prefer the venv Python if it exists (cross-platform)
    const isWindows = process.platform === 'win32';
    const venvPython = isWindows
        ? path.join(projectRoot, 'devex', 'lsp', '.venv', 'Scripts', 'python.exe')
        : path.join(projectRoot, 'devex', 'lsp', '.venv', 'bin', 'python3');
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
