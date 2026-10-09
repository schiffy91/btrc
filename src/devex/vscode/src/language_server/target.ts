/** The slice of a VS Code configuration the target setting reads. */
export interface TargetConfigurationReader {
    get<T>(section: string, defaultValue: T): T;
}

/** The slice of a configuration change event the target setting tests. */
export interface TargetConfigurationChange {
    affectsConfiguration(section: string): boolean;
}

/**
 * Owns ``btrc.target`` on the client (platform-target-contract.md §1.10).
 *
 * The value reaches the server in ``initializationOptions.target`` when the
 * server starts, so a reopened workspace keeps its setting, and in
 * ``workspace/didChangeConfiguration`` whenever it changes. The empty
 * default means the host; the server validates every other value.
 */
export class TargetSetting {
    static readonly SECTION = 'btrc';
    static readonly KEY = 'target';
    static readonly QUALIFIED = `${TargetSetting.SECTION}.${TargetSetting.KEY}`;

    static read(configuration: TargetConfigurationReader): string {
        const value = configuration.get<unknown>(TargetSetting.KEY, '');
        return typeof value === 'string' ? value : '';
    }

    static initializationOptions(
        configuration: TargetConfigurationReader,
    ): { target: string } {
        return { target: TargetSetting.read(configuration) };
    }

    static affects(event: TargetConfigurationChange): boolean {
        return event.affectsConfiguration(TargetSetting.QUALIFIED);
    }

    static changeNotification(
        configuration: TargetConfigurationReader,
    ): { settings: { btrc: { target: string } } } {
        return { settings: { btrc: { target: TargetSetting.read(configuration) } } };
    }
}
