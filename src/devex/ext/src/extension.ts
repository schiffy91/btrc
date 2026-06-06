import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';
import { resolveServerLaunch } from './launch';

let client: LanguageClient | undefined;
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('btrc Language Server');
    context.subscriptions.push(outputChannel);

    const config = vscode.workspace.getConfiguration('btrc');
    const pythonInspect = config.inspect<string>('pythonPath');
    const pythonExplicit = !!(pythonInspect && (
        pythonInspect.workspaceFolderValue ??
        pythonInspect.workspaceValue ??
        pythonInspect.globalValue));
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    const launch = resolveServerLaunch({
        extensionPath: context.extensionPath,
        workspaceRoot,
        config: {
            pythonPath: config.get<string>('pythonPath', 'python3'),
            serverPath: config.get<string>('serverPath', ''),
            serverCommand: config.get<string>('serverCommand', 'btrc-lsp').trim(),
            useNixDevShell: config.get<boolean>('useNixDevShell', true),
            pythonExplicit,
        },
    });

    if (!launch) {
        vscode.window.showErrorMessage(
            'btrc language server not found. Install `btrc-lsp`, set "btrc.serverCommand", ' +
            'set "btrc.serverPath", or open the btrc project folder.'
        );
        return;
    }

    outputChannel.appendLine(`Launch: ${launch.command} ${launch.args.join(' ')}`);
    outputChannel.appendLine(`Launch source: ${launch.source}`);
    if (launch.serverScript) { outputChannel.appendLine(`Server script: ${launch.serverScript}`); }
    if (launch.projectRoot) { outputChannel.appendLine(`Project root: ${launch.projectRoot}`); }
    outputChannel.appendLine(`Working directory: ${launch.cwd}`);

    const serverOptions: ServerOptions = {
        command: launch.command,
        args: launch.args,
        options: {
            cwd: launch.cwd,
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
