import * as vscode from 'vscode';

import { ExtensionController } from './application/controller';

export function activate(context: vscode.ExtensionContext): Promise<void> {
    return ExtensionController.activate(context);
}

export function deactivate(): Promise<void> {
    return ExtensionController.deactivate();
}
