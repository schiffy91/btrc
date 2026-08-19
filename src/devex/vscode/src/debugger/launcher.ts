import * as path from 'node:path';

import type * as vscode from 'vscode';

import { HostRuntime } from '../runtime/process';
import { PythonRuntimeProbe } from '../runtime/python';

export interface DebugAdapterLaunch {
    args: string[];
    cwd: string;
}

export interface CompilerLaunch {
    command: string[];
    cwd?: string;
}

/** Resolves and registers the btrc debug adapter and compiler launch plans. */
export class DebugLaunchResolver implements
    vscode.DebugAdapterDescriptorFactory,
    vscode.DebugConfigurationProvider {
    constructor(
        private readonly extensionPath: string,
        private readonly workspaceRoot: string | undefined,
        private readonly pythonCommand: string,
        private readonly python: PythonRuntimeProbe,
        private readonly host: HostRuntime,
        private readonly editor: typeof vscode,
    ) {}

    register(context: vscode.ExtensionContext): void {
        context.subscriptions.push(
            this.editor.debug.registerDebugAdapterDescriptorFactory('btrc', this),
            this.editor.debug.registerDebugConfigurationProvider('btrc', this),
        );
    }

    createDebugAdapterDescriptor(
        _session: vscode.DebugSession,
        _executable: vscode.DebugAdapterExecutable | undefined,
    ): vscode.ProviderResult<vscode.DebugAdapterDescriptor> {
        const adapter = this.resolveAdapter();
        if (!adapter) {
            this.editor.window.showErrorMessage(
                'btrc debug adapter package not found. Open the btrc project '
                + 'folder or reinstall the extension.',
            );
            return undefined;
        }
        return new this.editor.DebugAdapterExecutable(
            this.pythonCommand,
            adapter.args,
            { cwd: adapter.cwd },
        );
    }

    async resolveDebugConfiguration(
        _folder: vscode.WorkspaceFolder | undefined,
        configuration: vscode.DebugConfiguration,
        token?: vscode.CancellationToken,
    ): Promise<vscode.DebugConfiguration | undefined> {
        if (!configuration.type && !configuration.request && !configuration.name) {
            const editor = this.editor.window.activeTextEditor;
            if (!editor || editor.document.languageId !== 'btrc') {
                return undefined;
            }
            configuration.type = 'btrc';
            configuration.request = 'launch';
            configuration.name = 'btrc: debug current file';
            configuration.program = '${file}';
            configuration.stopOnEntry = false;
        }

        if (!configuration.btrcpy) {
            const cancellation = new AbortController();
            if (token?.isCancellationRequested) { cancellation.abort(); }
            const subscription = token?.onCancellationRequested(
                () => cancellation.abort(),
            );
            let compiler: CompilerLaunch | undefined;
            try {
                compiler = await this.resolveCompiler(cancellation.signal);
            } finally {
                subscription?.dispose();
            }
            if (token?.isCancellationRequested) { return undefined; }
            if (compiler) {
                configuration.btrcpy = compiler.command;
                if (compiler.cwd) {
                    configuration.btrcpyCwd = configuration.btrcpyCwd
                        || compiler.cwd;
                    configuration.cwd = configuration.cwd || compiler.cwd;
                }
            }
        }
        return configuration;
    }

    resolveAdapter(): DebugAdapterLaunch | undefined {
        const candidates = [
            path.join(this.extensionPath, 'server'),
            path.resolve(this.extensionPath, '..', '..', '..'),
        ];
        if (this.workspaceRoot) { candidates.push(this.workspaceRoot); }

        for (const cwd of candidates) {
            const entrypoint = path.join(
                cwd,
                'src',
                'devex',
                'debug',
                '__main__.py',
            );
            if (this.host.exists(entrypoint)) {
                return { args: ['-m', 'src.devex.debug'], cwd };
            }
        }
        return undefined;
    }

    async resolveCompiler(
        signal?: AbortSignal,
    ): Promise<CompilerLaunch | undefined> {
        if (signal?.aborted) { return undefined; }
        let pythonSupport: Promise<boolean> | undefined;
        const supportsPython = () => {
            pythonSupport ??= this.python.supports(this.pythonCommand, signal);
            return pythonSupport;
        };

        if (this.workspaceRoot) {
            const wrapper = path.join(this.workspaceRoot, 'bin', 'btrcpy');
            if (
                this.host.isLaunchableFile(wrapper)
                && await supportsPython()
            ) {
                return {
                    command: [this.pythonCommand, wrapper],
                    cwd: this.workspaceRoot,
                };
            }
            if (signal?.aborted) { return undefined; }

            const compilerModule = path.join(
                this.workspaceRoot,
                'src',
                'compiler',
                'python',
                'main.py',
            );
            if (
                this.host.exists(compilerModule)
                && await supportsPython()
            ) {
                return {
                    command: [
                        this.pythonCommand,
                        '-m',
                        'src.compiler.python.main',
                    ],
                    cwd: this.workspaceRoot,
                };
            }
            if (signal?.aborted) { return undefined; }
        }

        const bundledCompiler = path.join(
            this.extensionPath,
            'server',
            'src',
            'compiler',
            'python',
            'main.py',
        );
        if (
            this.host.exists(bundledCompiler)
            && await supportsPython()
        ) {
            return {
                command: [
                    this.pythonCommand,
                    '-m',
                    'src.compiler.python.main',
                ],
                cwd: path.join(this.extensionPath, 'server'),
            };
        }
        return undefined;
    }
}
