package dev.btrc.shim;

import android.app.Activity;
import android.os.Bundle;
import android.widget.FrameLayout;

/** The one activity of a BTRC program: a frame for its windows, and the
 * thread its main() runs on. The program is libbtrcprogram.so. Its views
 * live on this activity's UI thread (Shim); its own code never does. */
public final class ShimActivity extends Activity {
    static {
        System.loadLibrary("btrcprogram");
    }

    private FrameLayout frame;
    private volatile boolean ended;

    /** Run the program's main(arguments) to its end; its result. */
    private static native int nativeMain(String directory, String[] arguments);

    FrameLayout frame() {
        return frame;
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        frame = new FrameLayout(this);
        /* The windows keep clear of the system's bars. */
        frame.setFitsSystemWindows(true);
        setContentView(frame);
        Shim.attach(this);
        watchBack();
        String[] given = getIntent().getStringArrayExtra("arguments");
        final String[] arguments = given == null ? new String[0] : given;
        final String directory = getFilesDir().getAbsolutePath();
        Thread program = new Thread(null, new Runnable() {
            @Override
            public void run() {
                nativeMain(directory, arguments);
                ended = true;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        finishAndRemoveTask();
                    }
                });
            }
        }, "btrc-main", 16 * 1024 * 1024);
        program.start();
    }

    /* A program runs once in its process: when it has ended, so does the process. */
    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (ended) {
            System.exit(0);
        }
    }

    /* What a person does reaches the program's queue before any view acts on it. */
    @Override
    public boolean dispatchKeyEvent(android.view.KeyEvent event) {
        Shim.observeKey(event);
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean dispatchTouchEvent(android.view.MotionEvent event) {
        Shim.observePointer(event);
        return super.dispatchTouchEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(android.view.MotionEvent event) {
        Shim.observePointer(event);
        return super.dispatchGenericMotionEvent(event);
    }

    @Override
    public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        Shim.observeFocus(focused);
    }

    /** Back is the system's close request for the window on show. Newer
     * systems tell a callback; older ones call onBackPressed. */
    private void watchBack() {
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, new android.window.OnBackInvokedCallback() {
                @Override
                public void onBackInvoked() {
                    if (!Shim.closeRequested()) {
                        finish();
                    }
                }
            });
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        if (Shim.handleActivityResult(requestCode, resultCode, data)) {
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (!Shim.closeRequested()) {
            super.onBackPressed();
        }
    }
}
