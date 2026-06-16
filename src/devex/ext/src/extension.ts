import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from 'vscode-languageclient/node';
import { resolveServerLaunch } from './launch';
import { findDebugAdapterScript, findBtrcpy } from './debug_launch';

let client: LanguageClient | undefined;
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('btrc Language Server');
    context.subscriptions.push(outputChannel);

    const config = vscode.workspace.getConfiguration('btrc');
    registerDebugging(context, config);
    const pythonInspect = config.inspect<string>('pythonPath');
    const pythonExplicit = !!(pythonInspect && (
        pythonInspect.workspaceFolderValue ??
        pythonInspect.workspaceValue ??
        pythonInspect.globalValue));
    const serverCommandInspect = config.inspect<string>('serverCommand');
    const serverCommandExplicit = !!(serverCommandInspect && (
        serverCommandInspect.workspaceFolderValue ??
        serverCommandInspect.workspaceValue ??
        serverCommandInspect.globalValue));
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    const launch = resolveServerLaunch({
        extensionPath: context.extensionPath,
        workspaceRoot,
        config: {
            pythonPath: config.get<string>('pythonPath', 'python3'),
            serverPath: config.get<string>('serverPath', ''),
            serverCommand: config.get<string>('serverCommand', 'btrc-lsp').trim(),
            serverCommandExplicit,
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

function registerDebugging(
    context: vscode.ExtensionContext,
    config: vscode.WorkspaceConfiguration,
) {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const pythonPath = config.get<string>('pythonPath', 'python3') || 'python3';

    // Build the native debug binary + drive lldb via the btrc DAP adapter.
    const factory: vscode.DebugAdapterDescriptorFactory = {
        createDebugAdapterDescriptor() {
            const adapter = findDebugAdapterScript(context.extensionPath, workspaceRoot);
            if (!adapter) {
                vscode.window.showErrorMessage(
                    'btrc debug adapter not found (btrc_dap.py). Open the btrc project ' +
                    'folder or reinstall the extension.');
                return undefined;
            }
            // Any python3 works as the launcher: the adapter re-execs itself under
            // an interpreter that can import the lldb module.
            return new vscode.DebugAdapterExecutable(pythonPath, [adapter]);
        },
    };
    context.subscriptions.push(
        vscode.debug.registerDebugAdapterDescriptorFactory('btrc', factory));

    // Fill in a default config for F5-with-no-launch.json, and auto-detect the
    // btrc compiler command when the user didn't specify one.
    const provider: vscode.DebugConfigurationProvider = {
        resolveDebugConfiguration(_folder, cfg) {
            if (!cfg.type && !cfg.request && !cfg.name) {
                const editor = vscode.window.activeTextEditor;
                if (!editor || editor.document.languageId !== 'btrc') {
                    return undefined;
                }
                cfg.type = 'btrc';
                cfg.request = 'launch';
                cfg.name = 'btrc: debug current file';
                cfg.program = '${file}';
                cfg.stopOnEntry = false;
            }
            if (!cfg.btrcpy) {
                const resolved = findBtrcpy(workspaceRoot, pythonPath, context.extensionPath);
                if (resolved) {
                    cfg.btrcpy = resolved.cmd;
                    // btrcpyCwd is the build-step cwd (needed for the `-m` form);
                    // keep it distinct from the debugged program's runtime cwd.
                    if (resolved.cwd) { cfg.btrcpyCwd = cfg.btrcpyCwd || resolved.cwd; }
                    if (!cfg.cwd && resolved.cwd) { cfg.cwd = resolved.cwd; }
                }
            }
            return cfg;
        },
    };
    context.subscriptions.push(
        vscode.debug.registerDebugConfigurationProvider('btrc', provider));
}

export function deactivate(): Thenable<void> | undefined {
    if (client) {
        return client.stop();
    }
    return undefined;
}
