package dev.btrc.probe;

import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;

/** Starts the program's activity under instrumentation, which is the one way
 * the system lets a program send input to its own windows: `am instrument`
 * from a test host's shell lends the shell's right to inject events. The
 * program then runs as it does when a person starts it. */
public final class Runner extends Instrumentation {
    static volatile Instrumentation current;
    private Bundle given;

    @Override
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        given = arguments;
        current = this;
        start();
    }

    @Override
    public void onStart() {
        String arguments = given.getString("arguments");
        Intent intent = new Intent(Intent.ACTION_MAIN);
        intent.setClassName(getTargetContext(), "dev.btrc.shim.ShimActivity");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra("arguments", arguments == null || arguments.isEmpty() ? new String[0] : arguments.split(","));
        startActivitySync(intent);
    }
}
