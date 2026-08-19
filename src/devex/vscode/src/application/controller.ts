import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
} from 'vscode-languageclient/node';

import { DebugLaunchResolver } from '../debugger/launcher';
import { LanguageServerLaunchResolver } from '../language_server/launcher';
import { LanguageServerSession } from '../language_server/session';
import { HostRuntime } from '../runtime/process';
import { PythonRuntimeProbe } from '../runtime/python';

/** Composition root and lifecycle owner for one activated extension. */
export class ExtensionController {
    private static active: ExtensionController | undefined;

    private readonly cancellation = new AbortController();
    private languageServer: LanguageServerSession | undefined;
    private stopResult: Promise<void> | undefined;

    private constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly host: HostRuntime = new HostRuntime(),
    ) {}

    static async activate(context: vscode.ExtensionContext): Promise<void> {
        const controller = new ExtensionController(context);
        ExtensionController.active = controller;
        try {
            await controller.start();
        } catch (error) {
            if (ExtensionController.active === controller) {
                ExtensionController.active = undefined;
            }
            throw error;
        }
    }

    static async deactivate(): Promise<void> {
        const controller = ExtensionController.active;
        ExtensionController.active = undefined;
        if (controller) { await controller.stop(); }
    }

    private async start(): Promise<void> {
        const output = vscode.window.createOutputChannel('btrc Language Server');
        this.context.subscriptions.push(
            output,
            { dispose: () => this.cancellation.abort() },
            { dispose: () => { void this.stop().catch(() => undefined); } },
        );

        const python = new PythonRuntimeProbe(this.host, {
            signal: this.cancellation.signal,
        });
        const configuration = vscode.workspace.getConfiguration('btrc');
        const pythonCommand = python.resolveCommand(
            configuration.get<string>('pythonPath', ''),
        );
        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

        new DebugLaunchResolver(
            this.context.extensionPath,
            workspaceRoot,
            pythonCommand,
            python,
            this.host,
            vscode,
        ).register(this.context);

        const launch = await new LanguageServerLaunchResolver(
            this.host,
            python,
        ).resolve({
            extensionPath: this.context.extensionPath,
            workspaceRoot,
            config: {
                pythonPath: pythonCommand,
                serverPath: configuration.get<string>('serverPath', ''),
                serverCommand: configuration
                    .get<string>('serverCommand', 'btrc-lsp')
                    .trim(),
                serverCommandExplicit: this.hasExplicitSetting(
                    configuration,
                    'serverCommand',
                ),
                useNixDevShell: configuration.get<boolean>(
                    'useNixDevShell',
                    true,
                ),
                pythonExplicit: this.hasExplicitSetting(
                    configuration,
                    'pythonPath',
                ),
            },
            signal: this.cancellation.signal,
        });

        if (this.cancellation.signal.aborted) { return; }
        if (!launch) {
            vscode.window.showErrorMessage(
                'btrc language server not found. Install `btrc-lsp`, set '
                + '"btrc.serverCommand", set "btrc.serverPath", or open the '
                + 'btrc project folder.',
            );
            return;
        }

        output.appendLine(`Launch: ${launch.command} ${launch.args.join(' ')}`);
        output.appendLine(`Launch source: ${launch.source}`);
        if (launch.entrypoint) {
            output.appendLine(`Server entry point: ${launch.entrypoint}`);
        }
        if (launch.projectRoot) {
            output.appendLine(`Project root: ${launch.projectRoot}`);
        }
        output.appendLine(`Working directory: ${launch.cwd}`);

        const fileWatcher = vscode.workspace.createFileSystemWatcher('**/*.btrc');
        this.context.subscriptions.push(fileWatcher);
        const clientOptions: LanguageClientOptions = {
            documentSelector: [{ scheme: 'file', language: 'btrc' }],
            synchronize: { fileEvents: fileWatcher },
            outputChannel: output,
        };
        const session = new LanguageServerSession(
            launch,
            (serverOptions) => new LanguageClient(
                'btrc',
                'btrc Language Server',
                serverOptions,
                clientOptions,
            ),
            this.host,
        );
        this.languageServer = session;

        const startResult = session.start();
        void startResult.then(
            () => {
                if (!this.cancellation.signal.aborted) {
                    output.appendLine(
                        'btrc language server started successfully.',
                    );
                }
            },
            (error: unknown) => {
                if (this.cancellation.signal.aborted) { return; }
                const message = LanguageServerSession.describeError(error);
                output.appendLine(
                    `Failed to start btrc language server: ${message}`,
                );
                vscode.window.showErrorMessage(
                    `btrc language server failed to start: ${message}. `
                    + 'Check the "btrc Language Server" output channel for details.',
                );
            },
        ).catch(() => undefined);
    }

    private stop(): Promise<void> {
        this.stopResult ??= this.stopOnce();
        return this.stopResult;
    }

    private async stopOnce(): Promise<void> {
        this.cancellation.abort();
        if (this.languageServer) { await this.languageServer.stop(); }
    }

    private hasExplicitSetting(
        configuration: vscode.WorkspaceConfiguration,
        key: string,
    ): boolean {
        const inspection = configuration.inspect<string>(key);
        return !!(inspection && (
            inspection.workspaceFolderValue
            ?? inspection.workspaceValue
            ?? inspection.globalValue
        ));
    }
}
