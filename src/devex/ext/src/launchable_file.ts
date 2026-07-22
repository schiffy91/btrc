import * as fs from 'node:fs';

/** True when a path is a regular file that this host can launch as configured. */
export function isLaunchableFile(
    candidate: string,
    platform: NodeJS.Platform = process.platform,
): boolean {
    try {
        if (!fs.statSync(candidate).isFile()) { return false; }
        fs.accessSync(
            candidate,
            platform === 'win32' ? fs.constants.R_OK : fs.constants.X_OK,
        );
        return true;
    } catch {
        return false;
    }
}
