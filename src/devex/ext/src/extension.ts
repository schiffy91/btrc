import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
} from 'vscode-languageclient/node';
import { resolveServerLaunch } from './launch';
import { findDebugAdapterScript, findBtrcpy } from './debug_launch';
import {
    createPythonSupportProbe,
    PythonSupportProbe,
    resolvePythonCommand,
} from './python_runtime';
import { ClientLifecycle, errorMessage } from './client_lifecycle';
import { ServerProcessOwner } from './server_process';

let activationController: AbortController | undefined;
let languageClientLifecycle: ClientLifecycle | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
    const outputChannel = vscode.window.createOutputChannel('btrc Language Server');
    context.subscriptions.push(outputChannel);

    const lifecycle = new AbortController();
    activationController = lifecycle;
    const supportsPython = createPythonSupportProbe({ signal: lifecycle.signal });
    context.subscriptions.push({ dispose: () => lifecycle.abort() });

    const config = vscode.workspace.getConfiguration('btrc');
    const pythonPath = resolvePythonCommand(config.get<string>('pythonPath', ''));
    registerDebugging(context, pythonPath, supportsPython);
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

    const launch = await resolveServerLaunch({
        extensionPath: context.extensionPath,
        workspaceRoot,
        config: {
            pythonPath,
            serverPath: config.get<string>('serverPath', ''),
            serverCommand: config.get<string>('serverCommand', 'btrc-lsp').trim(),
            serverCommandExplicit,
            useNixDevShell: config.get<boolean>('useNixDevShell', true),
            pythonExplicit,
        },
        supportsPython,
        signal: lifecycle.signal,
    });

    if (lifecycle.signal.aborted) { return; }
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

    const serverProcess = new ServerProcessOwner(launch);
    const fileWatcher = vscode.workspace.createFileSystemWatcher('**/*.btrc');
    context.subscriptions.push(fileWatcher);

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'btrc' }],
        synchronize: {
            fileEvents: fileWatcher,
        },
        outputChannel,
    };

    const client = new LanguageClient(
        'btrc',
        'btrc Language Server',
        serverProcess.serverOptions,
        clientOptions
    );

    const managedClient = new ClientLifecycle(client, serverProcess);
    languageClientLifecycle = managedClient;
    const startResult = managedClient.start();
    void startResult.then(
        () => {
            if (lifecycle.signal.aborted) { return; }
            outputChannel.appendLine('btrc language server started successfully.');
        },
        (error: unknown) => {
            if (lifecycle.signal.aborted) { return; }
            const message = errorMessage(error);
            outputChannel.appendLine(`Failed to start btrc language server: ${message}`);
            vscode.window.showErrorMessage(
                `btrc language server failed to start: ${message}. ` +
                'Check the "btrc Language Server" output channel for details.'
            );
        },
    ).catch(() => undefined);

    context.subscriptions.push({
        dispose: () => {
            // VS Code disposables cannot await asynchronous cleanup. Consume
            // errors here; deactivate() returns the same shared stop operation.
            void managedClient.stop().catch(() => undefined);
        },
    });
}

function registerDebugging(
    context: vscode.ExtensionContext,
    pythonPath: string,
    supportsPython: PythonSupportProbe,
) {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

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
            // Any supported Python works as the launcher: the adapter re-execs itself under
            // an interpreter that can import the lldb module.
            return new vscode.DebugAdapterExecutable(pythonPath, [adapter]);
        },
    };
    context.subscriptions.push(
        vscode.debug.registerDebugAdapterDescriptorFactory('btrc', factory));

    // Fill in a default config for F5-with-no-launch.json, and auto-detect the
    // btrc compiler command when the user didn't specify one.
    const provider: vscode.DebugConfigurationProvider = {
        async resolveDebugConfiguration(_folder, cfg, token) {
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
                const cancellation = new AbortController();
                if (token?.isCancellationRequested) { cancellation.abort(); }
                const subscription = token?.onCancellationRequested(() => cancellation.abort());
                let resolved: Awaited<ReturnType<typeof findBtrcpy>>;
                try {
                    resolved = await findBtrcpy(
                        workspaceRoot,
                        pythonPath,
                        context.extensionPath,
                        supportsPython,
                        cancellation.signal,
                    );
                } finally {
                    subscription?.dispose();
                }
                if (token?.isCancellationRequested) { return undefined; }
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

export async function deactivate(): Promise<void> {
    activationController?.abort();
    const managedClient = languageClientLifecycle;
    activationController = undefined;
    languageClientLifecycle = undefined;
    if (managedClient) { await managedClient.stop(); }
}
