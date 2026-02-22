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

    // Find the project root: prefer the workspace folder (works when installed
    // as a .vsix in a devcontainer), fall back to extension-relative path
    // (works during extension development with F5).
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const extensionRelativeRoot = path.resolve(context.extensionPath, '..', '..');

    let projectRoot: string | undefined;
    for (const candidate of [workspaceRoot, extensionRelativeRoot]) {
        if (candidate && fs.existsSync(path.join(candidate, 'devex', 'lsp', 'server.py'))) {
            projectRoot = candidate;
            break;
        }
    }

    if (!projectRoot) {
        vscode.window.showErrorMessage(
            'btrc language server not found. ' +
            'Open a btrc project workspace or install the extension inside the project.'
        );
        return;
    }

    const serverScript = path.join(projectRoot, 'devex', 'lsp', 'server.py');

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
