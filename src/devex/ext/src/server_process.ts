import spawn from 'cross-spawn';
import type { ChildProcessInfo, ServerOptions } from 'vscode-languageclient/node';
import type { BtrcServerLaunch } from './launch';
import { ProcessTree } from './process_tree';

/** Owns every language-server process generation created by LanguageClient. */
export class ServerProcessOwner {
    private readonly processes = new Set<ProcessTree>();
    private stopping = false;
    private stopResult: Promise<void> | undefined;

    readonly serverOptions: ServerOptions;

    constructor(private readonly launch: BtrcServerLaunch) {
        this.serverOptions = () => this.spawnServer();
    }

    stop(): Promise<void> {
        this.stopping = true;
        this.stopResult ??= Promise.all(
            [...this.processes].map((processTree) => processTree.stop()),
        ).then(() => undefined);
        return this.stopResult;
    }

    private async spawnServer(): Promise<ChildProcessInfo> {
        if (this.stopping) {
            throw new Error('Cannot launch the language server during shutdown');
        }
        const detached = process.platform !== 'win32';
        const child = spawn(this.launch.command, this.launch.args, {
            cwd: this.launch.cwd,
            detached,
            stdio: 'pipe',
            windowsHide: true,
        });
        const processTree = new ProcessTree(child, { detached });
        this.processes.add(processTree);
        const cleanup = () => {
            void processTree.stop()
                .catch(() => undefined)
                .finally(() => this.processes.delete(processTree));
        };
        child.once('error', cleanup);
        child.once('exit', cleanup);
        return { process: child, detached };
    }
}
