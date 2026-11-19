package dev.btrc.probe;

import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;

/** Real input for the conformance probe (probes/android/AndroidInput.c): what
 * a person's mouse and keyboard do, sent through the system to this
 * program's own windows. Called from the program's thread, never the UI
 * thread, which has to be free to receive it. Positions are the screen's,
 * in pixels. */
public final class Input {
    private Input() {}

    /* The instrumentation the program was started under (Runner); without
     * one, the system refuses every event. */
    private static android.app.Instrumentation instrumentation() {
        android.app.Instrumentation current = Runner.current;
        if (current == null) {
            throw new IllegalStateException("the program was not started under instrumentation");
        }
        return current;
    }

    private static boolean down;
    private static long downAt;
    private static boolean hovering;

    private static boolean send(int action, int source, int tool, float x, float y, float deltaX, float deltaY, long began) {
        long now = android.os.SystemClock.uptimeMillis();
        MotionEvent.PointerProperties[] properties = {new MotionEvent.PointerProperties()};
        properties[0].id = 0;
        properties[0].toolType = tool;
        MotionEvent.PointerCoords[] coordinates = {new MotionEvent.PointerCoords()};
        coordinates[0].x = x;
        coordinates[0].y = y;
        coordinates[0].pressure = source == InputDevice.SOURCE_TOUCHSCREEN && action != MotionEvent.ACTION_UP ? 1.0f : 0.0f;
        coordinates[0].size = 1.0f;
        coordinates[0].setAxisValue(MotionEvent.AXIS_VSCROLL, deltaY);
        coordinates[0].setAxisValue(MotionEvent.AXIS_HSCROLL, deltaX);
        MotionEvent event = MotionEvent.obtain(began, now, action, 1, properties, coordinates, 0, 0, 1.0f, 1.0f, 0, 0, source, 0);
        try {
            instrumentation().sendPointerSync(event);
            return true;
        } catch (RuntimeException refused) {
            android.util.Log.e("btrc-probe", "input refused", refused);
            return false;
        } finally {
            event.recycle();
        }
    }

    /** A pointer event at a screen position: 0 move, 1 press, 2 release, 3
     * wheel (by deltaX, deltaY notches). A press is a finger's, as it is on
     * a phone, and so is a move while it is down; a move with nothing down
     * and a wheel are a mouse's, the one pointer that has them. */
    public static boolean pointer(int kind, float x, float y, float deltaX, float deltaY) {
        long now = android.os.SystemClock.uptimeMillis();
        int mouse = InputDevice.SOURCE_MOUSE;
        int touch = InputDevice.SOURCE_TOUCHSCREEN;
        if (kind == 1) {
            /* As a mouse's own press does: the hover ends where the press begins. */
            if (hovering && !send(MotionEvent.ACTION_HOVER_EXIT, mouse, MotionEvent.TOOL_TYPE_MOUSE, x, y, 0, 0, now)) {
                return false;
            }
            hovering = false;
            down = true;
            downAt = now;
            return send(MotionEvent.ACTION_DOWN, touch, MotionEvent.TOOL_TYPE_FINGER, x, y, 0, 0, downAt);
        }
        if (kind == 2) {
            down = false;
            return send(MotionEvent.ACTION_UP, touch, MotionEvent.TOOL_TYPE_FINGER, x, y, 0, 0, downAt);
        }
        if (kind == 3) {
            return send(MotionEvent.ACTION_SCROLL, mouse, MotionEvent.TOOL_TYPE_MOUSE, x, y, deltaX, deltaY, now);
        }
        if (down) {
            return send(MotionEvent.ACTION_MOVE, touch, MotionEvent.TOOL_TYPE_FINGER, x, y, 0, 0, downAt);
        }
        hovering = true;
        return send(MotionEvent.ACTION_HOVER_MOVE, mouse, MotionEvent.TOOL_TYPE_MOUSE, x, y, 0, 0, now);
    }

    /** One key, pressed and released, with Control held or not. */
    public static boolean key(int code, boolean control) {
        long now = android.os.SystemClock.uptimeMillis();
        int meta = control ? KeyEvent.META_CTRL_ON | KeyEvent.META_CTRL_LEFT_ON : 0;
        try {
            instrumentation().sendKeySync(new KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0, meta));
            instrumentation().sendKeySync(new KeyEvent(now, now, KeyEvent.ACTION_UP, code, 0, meta));
            return true;
        } catch (RuntimeException refused) {
            android.util.Log.e("btrc-probe", "input refused", refused);
            return false;
        }
    }

    public static boolean text(String text) {
        try {
            instrumentation().sendStringSync(text);
            return true;
        } catch (RuntimeException refused) {
            android.util.Log.e("btrc-probe", "input refused", refused);
            return false;
        }
    }
}
