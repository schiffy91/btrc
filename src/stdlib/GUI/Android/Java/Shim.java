package dev.btrc.shim;

import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.PorterDuff;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.util.SparseArray;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.ListPopupWindow;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.TextView;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** The Android side of the shim provider (GUI/Shim/Shim.h is the contract;
 * GUI/Android/AndroidShim.c calls this class through JNI).
 *
 * The program runs on its own thread. Every method here is called from it,
 * does its work on the activity's UI thread and returns when that is done.
 * What a person does is not called back: it is pushed, as plain values, onto
 * the queue the program polls (push). Sizes and positions cross this
 * boundary in dp, the contract's logical points. */
public final class Shim {
    private Shim() {}

    /* Shim.h's event types, keys and modifiers: AndroidShim.c asserts each value. */
    static final int WINDOW_SHOWN = 3, WINDOW_HIDDEN = 4, WINDOW_EXPOSED = 5, WINDOW_RESIZED = 6, WINDOW_PIXEL_SIZE_CHANGED = 7;
    static final int WINDOW_MOUSE_ENTER = 11, WINDOW_MOUSE_LEAVE = 12, WINDOW_FOCUS_GAINED = 13, WINDOW_FOCUS_LOST = 14, WINDOW_CLOSE_REQUESTED = 15;
    static final int KEY_DOWN = 16, KEY_UP = 17, TEXT_INPUT = 19, MOUSE_MOTION = 20, MOUSE_BUTTON_DOWN = 21, MOUSE_BUTTON_UP = 22, MOUSE_WHEEL = 23;
    static final int CONTROL_ACTIVATED = 24, CONTROL_FOCUS_GAINED = 25, CONTROL_FOCUS_LOST = 26;
    static final int SLIDER_PRESSED = 27, SLIDER_CHANGED = 28, SLIDER_RELEASED = 29, SLIDER_CANCELLED = 30;
    static final int SELECT_OPENED = 31, SELECT_CANDIDATE = 32, SELECT_CHOSEN = 33, SELECT_DISMISSED = 34;
    static final int TEXT_CHANGED = 35, TEXT_ACTIVATED = 36, TEXT_ESCAPED = 37, SCROLLBAR_CHANGED = 38, WEB_MESSAGE = 39, WEB_NAVIGATION = 40;
    static final int KEY_ESCAPE = 1, KEY_RETURN = 2, KEY_SPACE = 4, KEY_LEFT = 5, KEY_RIGHT = 6, KEY_UP_ARROW = 7, KEY_DOWN_ARROW = 8, KEY_TAB = 9;
    static final int KEY_BACKSPACE = 10, KEY_DELETE = 11, KEY_HOME = 12, KEY_END = 13, KEY_A = 18, KEY_C = 19, KEY_V = 20;
    static final int MOD_SHIFT = 1, MOD_CTRL = 2, MOD_ALT = 4;

    static final int BUTTON = 1, LABEL = 2, SPINNER = 3, LEVEL = 4, SLIDER = 5, SELECT = 6, TEXT = 7, PICTURE = 8, FILL = 9, SCROLLBAR = 10, WEB = 11;

    private static ShimActivity activity;
    private static Handler ui;
    private static float density = 1.0f;
    private static final SparseArray<Window> windows = new SparseArray<>();
    private static final SparseArray<Control> controls = new SparseArray<>();
    private static final ArrayList<Window> shown = new ArrayList<>();
    private static int nextHandle = 1;
    private static final CountDownLatch attached = new CountDownLatch(1);

    /** One event for the program's queue. Safe from any thread. */
    static native void push(int type, int window, int control, float x, float y, float wheelX, float wheelY, int button, int clicks, int scancode, int key, int modifiers, int data1, int data2, int down, double value, String text);

    static void attach(ShimActivity host) {
        activity = host;
        ui = new Handler(Looper.getMainLooper());
        density = host.getResources().getDisplayMetrics().density;
        attached.countDown();
    }

    static Context context() {
        return activity;
    }

    /* The appearance the program asked for: controls are made in its theme. */
    private static boolean dark = true;
    private static Context themed;

    private static Context themed() {
        if (themed == null) {
            themed = new android.view.ContextThemeWrapper(activity, dark ? android.R.style.Theme_DeviceDefault : android.R.style.Theme_DeviceDefault_Light);
        }
        return themed;
    }

    /** Dark or light, for the controls made from now on and what lies behind the windows. */
    static void setDark(final boolean wanted) {
        onUi(new Runnable() {
            @Override
            public void run() {
                if (dark != wanted) {
                    dark = wanted;
                    themed = null;
                }
                activity.frame().setBackgroundColor(dark ? 0xFF1E1E21 : 0xFFEEEEF0);
            }
        });
    }

    static float density() {
        return density;
    }

    static int pixels(double points) {
        return (int) Math.round(points * density);
    }

    static double points(double pixels) {
        return pixels / density;
    }

    /** Do the work on the UI thread and wait for it. */
    static <T> T onUi(Callable<T> work) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            try {
                return work.call();
            } catch (Exception error) {
                throw new RuntimeException(error);
            }
        }
        FutureTask<T> task = new FutureTask<>(work);
        ui.post(task);
        try {
            return task.get();
        } catch (Exception error) {
            throw new RuntimeException(error);
        }
    }

    static void onUi(final Runnable work) {
        onUi(new Callable<Void>() {
            @Override
            public Void call() {
                work.run();
                return null;
            }
        });
    }

    static void pushWindow(Window window, int type) {
        push(type, window.id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, null);
    }

    static void pushControl(Control control, int type, int data, double value, String text) {
        push(type, control.window == null ? 0 : control.window.id, control.id, 0, 0, 0, 0, 0, 0, 0, 0, 0, data, 0, 0, value, text);
    }

    /** A window: one layer of the activity's frame. The session gives every
     * window the whole of it, so one window is on the screen at a time: the
     * last one shown. Every other window is in the frame all the same, moved
     * off the screen, because the system makes a view's drawing surface only
     * for a view that is in a window, and a program may draw before it shows. */
    static final class Window extends FrameLayout {
        final int id;
        String title;
        final SurfaceView content;
        volatile Surface surface;
        final CountDownLatch surfaceReady = new CountDownLatch(1);
        final ArrayList<Slot> placedSlots = new ArrayList<>();
        boolean inside;
        float pointerX;
        float pointerY;

        Window(Context context, int id, String title) {
            super(context);
            this.id = id;
            this.title = title;
            setFocusable(true);
            setFocusableInTouchMode(true);
            content = new SurfaceView(context);
            content.getHolder().setFormat(PixelFormat.RGBA_8888);
            content.getHolder().addCallback(new SurfaceHolder.Callback() {
                @Override
                public void surfaceCreated(SurfaceHolder holder) {
                    surface = holder.getSurface();
                    surfaceReady.countDown();
                }

                @Override
                public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
                    surface = holder.getSurface();
                    pushWindow(Window.this, WINDOW_PIXEL_SIZE_CHANGED);
                    pushWindow(Window.this, WINDOW_EXPOSED);
                }

                @Override
                public void surfaceDestroyed(SurfaceHolder holder) {
                    surface = null;
                }
            });
            addView(content, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
        }

        /* A window is a whole number of points each way, the most the frame
         * holds: a point is rarely a whole number of pixels, and a window
         * whose size in points is rounded would not be the size it says. */
        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            int width = pixels(Math.floor(points(MeasureSpec.getSize(widthSpec))));
            int height = pixels(Math.floor(points(MeasureSpec.getSize(heightSpec))));
            super.onMeasure(MeasureSpec.makeMeasureSpec(width, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(height, MeasureSpec.EXACTLY));
        }

        @Override
        protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
            super.onSizeChanged(width, height, oldWidth, oldHeight);
            if (width > 0 && height > 0) {
                pushWindow(this, WINDOW_RESIZED);
                pushWindow(this, WINDOW_PIXEL_SIZE_CHANGED);
                pushWindow(this, WINDOW_EXPOSED);
            }
        }
    }

    /** A control: a view in a slot, with what its kind keeps. */
    static final class Control {
        int handle;
        int id;
        int kind;
        View view;
        Slot slot;
        Window window;
        boolean silent;
        boolean tracking;
        boolean cancelledDrag;
        boolean selectedLook;
        double minimum, maximum = 1.0, value;
        final ArrayList<String> items = new ArrayList<>();
        final ArrayList<Boolean> enabledItems = new ArrayList<>();
        int selected = -1;
        int candidate = -1;
        boolean chose;
        boolean escaped;
        ListPopupWindow popup;
        Symbol symbol;
        double warning, critical;
    }

    /* The slider a person is dragging, and the one whose drag Escape ended. */
    private static Control dragging;
    private static Control cancelled;

    private static Window topWindow() {
        return shown.isEmpty() ? null : shown.get(shown.size() - 1);
    }

    private static final float OFF_SCREEN = 1.0e5f;

    /* Put the window on show on the screen and every other window off it. */
    private static void arrange() {
        Window top = topWindow();
        for (int index = 0; index < windows.size(); index++) {
            Window window = windows.valueAt(index);
            window.setTranslationX(window == top ? 0.0f : OFF_SCREEN);
        }
        if (top != null) {
            top.bringToFront();
            activity.setTitle(top.title);
            top.requestFocus();
        }
    }

    /** What the activity's Back does: ask the window on show to close. */
    static boolean closeRequested() {
        Window window = topWindow();
        if (window == null) {
            return false;
        }
        pushWindow(window, WINDOW_CLOSE_REQUESTED);
        return true;
    }

    private static int modifiers(int meta) {
        return ((meta & KeyEvent.META_SHIFT_ON) != 0 ? MOD_SHIFT : 0) | ((meta & KeyEvent.META_CTRL_ON) != 0 ? MOD_CTRL : 0) | ((meta & KeyEvent.META_ALT_ON) != 0 ? MOD_ALT : 0);
    }

    private static int key(int code) {
        switch (code) {
            case KeyEvent.KEYCODE_ESCAPE: return KEY_ESCAPE;
            case KeyEvent.KEYCODE_ENTER: case KeyEvent.KEYCODE_NUMPAD_ENTER: return KEY_RETURN;
            case KeyEvent.KEYCODE_SPACE: return KEY_SPACE;
            case KeyEvent.KEYCODE_DPAD_LEFT: return KEY_LEFT;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return KEY_RIGHT;
            case KeyEvent.KEYCODE_DPAD_UP: return KEY_UP_ARROW;
            case KeyEvent.KEYCODE_DPAD_DOWN: return KEY_DOWN_ARROW;
            case KeyEvent.KEYCODE_TAB: return KEY_TAB;
            case KeyEvent.KEYCODE_DEL: return KEY_BACKSPACE;
            case KeyEvent.KEYCODE_FORWARD_DEL: return KEY_DELETE;
            case KeyEvent.KEYCODE_MOVE_HOME: return KEY_HOME;
            case KeyEvent.KEYCODE_MOVE_END: return KEY_END;
            case KeyEvent.KEYCODE_A: return KEY_A;
            case KeyEvent.KEYCODE_C: return KEY_C;
            case KeyEvent.KEYCODE_V: return KEY_V;
            default: return 0;
        }
    }

    /* Letters and brackets as their unshifted character; Shim.h's two named codes. */
    private static int scancode(int code) {
        if (code >= KeyEvent.KEYCODE_A && code <= KeyEvent.KEYCODE_Z) {
            return 'a' + (code - KeyEvent.KEYCODE_A);
        }
        switch (code) {
            case KeyEvent.KEYCODE_LEFT_BRACKET: return '[';
            case KeyEvent.KEYCODE_RIGHT_BRACKET: return ']';
            case KeyEvent.KEYCODE_DEL: return 8;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 0x100;
            case KeyEvent.KEYCODE_MOVE_END: return 0x101;
            default: return 0;
        }
    }

    /** Every key the activity's own window is given: the window on show hears of it first. */
    static void observeKey(KeyEvent event) {
        Window window = topWindow();
        if (window == null || event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
            return;
        }
        boolean down = event.getAction() == KeyEvent.ACTION_DOWN;
        if (!down && event.getAction() != KeyEvent.ACTION_UP) {
            return;
        }
        if (down && event.getKeyCode() == KeyEvent.KEYCODE_ESCAPE && dragging != null) {
            /* Escape abandons the drag: what the finger does until it lifts is no longer the slider's. */
            cancelled = dragging;
            dragging = null;
            cancelled.tracking = false;
            cancelled.cancelledDrag = true;
            pushControl(cancelled, SLIDER_CANCELLED, 0, 0.0, null);
            showSlider(cancelled);
        }
        push(down ? KEY_DOWN : KEY_UP, window.id, 0, 0, 0, 0, 0, 0, 0, scancode(event.getKeyCode()), key(event.getKeyCode()), modifiers(event.getMetaState()), event.getScanCode(), event.getRepeatCount(), down ? 1 : 0, 0.0, null);
        int typed = event.getUnicodeChar();
        if (down && typed >= 0x20 && typed != 0x7f && (event.getMetaState() & KeyEvent.META_CTRL_ON) == 0) {
            push(TEXT_INPUT, window.id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, new String(Character.toChars(typed)));
        }
    }

    private static final Runnable leaving = new Runnable() {
        @Override
        public void run() {
            Window window = topWindow();
            if (window != null && window.inside) {
                window.inside = false;
                pushWindow(window, WINDOW_MOUSE_LEAVE);
            }
        }
    };

    /** Every pointer event the activity's own window is given. */
    static void observePointer(MotionEvent event) {
        Window window = topWindow();
        if (window == null) {
            return;
        }
        int[] origin = new int[2];
        window.getLocationInWindow(origin);
        float x = (float) points(event.getX() - origin[0]);
        float y = (float) points(event.getY() - origin[1]);
        int action = event.getActionMasked();
        boolean within = x >= 0 && y >= 0 && x < points(window.getWidth()) && y < points(window.getHeight());
        ui.removeCallbacks(leaving);
        if (action == MotionEvent.ACTION_HOVER_EXIT && within) {
            /* A hover ends when the pointer leaves, and also when its button
             * goes down, which is not leaving: the press that follows says so. */
            ui.postDelayed(leaving, 50);
            return;
        }
        if (!within) {
            leaving.run();
            return;
        }
        if (!window.inside) {
            window.inside = true;
            pushWindow(window, WINDOW_MOUSE_ENTER);
        }
        window.pointerX = x;
        window.pointerY = y;
        int state = modifiers(event.getMetaState());
        switch (action) {
            case MotionEvent.ACTION_DOWN:
                if (cancelled != null) {
                    cancelled.cancelledDrag = false;
                    cancelled = null;
                }
                push(MOUSE_MOTION, window.id, 0, x, y, 0, 0, 0, 0, 0, 0, state, 0, 0, 0, 0.0, null);
                push(MOUSE_BUTTON_DOWN, window.id, 0, x, y, 0, 0, 1, 1, 0, 0, state, 0, 0, 1, 0.0, null);
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                push(MOUSE_BUTTON_UP, window.id, 0, x, y, 0, 0, 1, 1, 0, 0, state, 0, 0, 0, 0.0, null);
                break;
            case MotionEvent.ACTION_MOVE:
            case MotionEvent.ACTION_HOVER_MOVE:
            case MotionEvent.ACTION_HOVER_ENTER:
                push(MOUSE_MOTION, window.id, 0, x, y, 0, 0, 0, 0, 0, 0, state, 0, 0, 0, 0.0, null);
                break;
            case MotionEvent.ACTION_SCROLL:
                push(MOUSE_WHEEL, window.id, 0, x, y, event.getAxisValue(MotionEvent.AXIS_HSCROLL), event.getAxisValue(MotionEvent.AXIS_VSCROLL), 0, 0, 0, 0, state, 0, 0, 0, 0.0, null);
                break;
            default:
                break;
        }
    }

    static void observeFocus(boolean focused) {
        Window window = topWindow();
        if (window != null) {
            pushWindow(window, focused ? WINDOW_FOCUS_GAINED : WINDOW_FOCUS_LOST);
        }
    }

    /* Windows. */

    static int windowCreate(final String title) {
        try {
            attached.await(30, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            return 0;
        }
        return onUi(new Callable<Integer>() {
            @Override
            public Integer call() {
                int id = nextHandle++;
                Window window = new Window(activity, id, title);
                windows.put(id, window);
                window.setTranslationX(OFF_SCREEN);
                activity.frame().addView(window, 0, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
                return id;
            }
        });
    }

    static void windowDestroy(final int id) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Window window = windows.get(id);
                if (window == null) {
                    return;
                }
                shown.remove(window);
                windows.remove(id);
                activity.frame().removeView(window);
                arrange();
            }
        });
    }

    static void windowShow(final int id) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Window window = windows.get(id);
                if (window == null || shown.contains(window)) {
                    return;
                }
                Window before = topWindow();
                if (before != null) {
                    pushWindow(before, WINDOW_FOCUS_LOST);
                }
                shown.add(window);
                arrange();
                pushWindow(window, WINDOW_SHOWN);
                if (activity.hasWindowFocus()) {
                    pushWindow(window, WINDOW_FOCUS_GAINED);
                }
            }
        });
    }

    static void windowHide(final int id) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Window window = windows.get(id);
                if (window == null || !shown.contains(window)) {
                    return;
                }
                boolean top = topWindow() == window;
                shown.remove(window);
                window.clearFocus();
                arrange();
                if (top) {
                    pushWindow(window, WINDOW_FOCUS_LOST);
                }
                pushWindow(window, WINDOW_HIDDEN);
                Window next = topWindow();
                if (top && next != null) {
                    pushWindow(next, WINDOW_FOCUS_GAINED);
                }
            }
        });
    }

    static boolean windowIsShown(final int id) {
        return onUi(new Callable<Boolean>() {
            @Override
            public Boolean call() {
                Window window = windows.get(id);
                return window != null && shown.contains(window);
            }
        });
    }

    static void windowSetTitle(final int id, final String title) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Window window = windows.get(id);
                if (window == null) {
                    return;
                }
                window.title = title;
                if (topWindow() == window) {
                    activity.setTitle(title);
                }
            }
        });
    }

    /** {width, height} in pixels: the window's when it is on show, the frame's otherwise. */
    static int[] windowPixelSize(final int id) {
        return onUi(new Callable<int[]>() {
            @Override
            public int[] call() {
                Window window = windows.get(id);
                if (window != null && window.getWidth() > 0) {
                    return new int[] {window.getWidth(), window.getHeight()};
                }
                View frame = activity.frame();
                int width = frame.getWidth() - frame.getPaddingLeft() - frame.getPaddingRight();
                int height = frame.getHeight() - frame.getPaddingTop() - frame.getPaddingBottom();
                return new int[] {pixels(Math.floor(points(width))), pixels(Math.floor(points(height)))};
            }
        });
    }

    static float windowDensity() {
        return density;
    }

    /** The surface drawn content is presented on, once the system has made it; null if it has not. */
    static Surface windowSurface(int id, int milliseconds) {
        final Window window = onUi(new Callable<Window>() {
            @Override
            public Window call() {
                return windows.get(id);
            }
        });
        if (window == null) {
            return null;
        }
        try {
            window.surfaceReady.await(milliseconds, TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            return null;
        }
        return window.surface;
    }

    /** {x, y} of the window's content on the screen, in pixels; null when it is not on show. */
    static int[] windowOrigin(final int id) {
        return onUi(new Callable<int[]>() {
            @Override
            public int[] call() {
                Window window = windows.get(id);
                if (window == null || topWindow() != window) {
                    return null;
                }
                int[] origin = new int[2];
                window.getLocationOnScreen(origin);
                return origin;
            }
        });
    }

    /** {inside, x, y}: where the pointer last was in the window, in points. */
    static float[] windowPointer(final int id) {
        return onUi(new Callable<float[]>() {
            @Override
            public float[] call() {
                Window window = windows.get(id);
                return window == null ? null : new float[] {window.inside ? 1.0f : 0.0f, window.pointerX, window.pointerY};
            }
        });
    }

    static boolean windowTextFocused(final int id) {
        return onUi(new Callable<Boolean>() {
            @Override
            public Boolean call() {
                Window window = windows.get(id);
                return window != null && window.findFocus() instanceof EditText;
            }
        });
    }

    /** A modal message with one button; returns when it is dismissed. */
    static void windowShowMessage(final String title, final String message) {
        final CountDownLatch dismissed = new CountDownLatch(1);
        onUi(new Runnable() {
            @Override
            public void run() {
                new AlertDialog.Builder(themed()).setTitle(title).setMessage(message).setPositiveButton(android.R.string.ok, null).setOnDismissListener(new DialogInterface.OnDismissListener() {
                    @Override
                    public void onDismiss(DialogInterface dialog) {
                        dismissed.countDown();
                    }
                }).show();
            }
        });
        try {
            dismissed.await();
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    static boolean clipboardSet(final String text) {
        return onUi(new Callable<Boolean>() {
            @Override
            public Boolean call() {
                ClipboardManager clipboard = (ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
                clipboard.setPrimaryClip(ClipData.newPlainText("text", text));
                return true;
            }
        });
    }

    static String clipboardGet() {
        return onUi(new Callable<String>() {
            @Override
            public String call() {
                ClipboardManager clipboard = (ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
                ClipData clip = clipboard.getPrimaryClip();
                if (clip == null || clip.getItemCount() == 0) {
                    return null;
                }
                CharSequence text = clip.getItemAt(0).coerceToText(activity);
                return text == null ? null : text.toString();
            }
        });
    }

    /** One line of text as coverage: {width, height} then width * height bytes, or null. */
    static byte[] rasterizeText(String text, float pixelSize, boolean bold, int lineHeight) {
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setTextSize(pixelSize);
        paint.setTypeface(Typeface.create(Typeface.SANS_SERIF, bold ? Typeface.BOLD : Typeface.NORMAL));
        paint.setColor(Color.WHITE);
        Paint.FontMetrics metrics = paint.getFontMetrics();
        int width = Math.max(1, (int) Math.ceil(paint.measureText(text)));
        int line = (int) Math.ceil(metrics.descent - metrics.ascent);
        int height = Math.max(lineHeight, line);
        if (width > 4096 || height > 4096) {
            return null;
        }
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ALPHA_8);
        new Canvas(bitmap).drawText(text, 0, (height - line) / 2.0f - metrics.ascent, paint);
        ByteBuffer coverage = ByteBuffer.allocate(width * height);
        bitmap.copyPixelsToBuffer(coverage);
        bitmap.recycle();
        byte[] result = new byte[8 + width * height];
        ByteBuffer.wrap(result).putInt(width).putInt(height).put(coverage.array(), 0, width * height);
        return result;
    }

    /* Controls. */

    private static Control control(int handle) {
        return controls.get(handle);
    }

    static Control controlOf(int handle) {
        return controls.get(handle);
    }

    private static void watchFocus(final Control control) {
        control.view.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View view, boolean focused) {
                pushControl(control, focused ? CONTROL_FOCUS_GAINED : CONTROL_FOCUS_LOST, 0, 0.0, null);
            }
        });
    }

    static int controlCreate(final int kind, final int id, final String text, final String more, final boolean flag) {
        return onUi(new Callable<Integer>() {
            @Override
            public Integer call() {
                final Control control = new Control();
                control.handle = nextHandle++;
                control.id = id;
                control.kind = kind;
                switch (kind) {
                    case BUTTON: {
                        Button button = new Button(themed());
                        button.setAllCaps(false);
                        button.setText(text);
                        button.setSingleLine(true);
                        button.setMinWidth(0);
                        button.setMinimumWidth(0);
                        button.setMinHeight(0);
                        button.setMinimumHeight(0);
                        button.setOnClickListener(new View.OnClickListener() {
                            @Override
                            public void onClick(View view) {
                                pushControl(control, CONTROL_ACTIVATED, 0, 0.0, null);
                            }
                        });
                        control.view = button;
                        watchFocus(control);
                        break;
                    }
                    case LABEL: {
                        TextView label = new TextView(themed());
                        label.setText(text);
                        label.setSingleLine(true);
                        control.view = label;
                        break;
                    }
                    case SPINNER: {
                        ProgressBar spinner = new ProgressBar(themed());
                        spinner.setIndeterminate(true);
                        spinner.setVisibility(View.INVISIBLE);
                        control.view = spinner;
                        break;
                    }
                    case LEVEL: {
                        ProgressBar level = new ProgressBar(themed(), null, android.R.attr.progressBarStyleHorizontal);
                        level.setMax(1000);
                        control.view = level;
                        break;
                    }
                    case SLIDER:
                        control.view = slider(control);
                        watchFocus(control);
                        break;
                    case SELECT:
                        control.view = select(control);
                        watchFocus(control);
                        break;
                    case TEXT:
                        control.view = field(control, text, more);
                        watchFocus(control);
                        break;
                    case PICTURE: {
                        ImageView picture = new ImageView(activity);
                        picture.setScaleType(ImageView.ScaleType.FIT_CENTER);
                        control.view = picture;
                        break;
                    }
                    case FILL:
                        control.view = new View(activity);
                        break;
                    case SCROLLBAR:
                        control.view = new Scrollbar(activity, control, flag);
                        break;
                    case WEB:
                        control.view = ShimWeb.create(control);
                        break;
                    default:
                        return 0;
                }
                control.slot = new Slot(activity);
                control.slot.addView(control.view);
                controls.put(control.handle, control);
                return control.handle;
            }
        });
    }

    /* A slider shows the value it is given and never changes it itself: what a
     * person asks for is reported, and the bar put back until the program answers. */
    private static View slider(final Control control) {
        final SeekBar bar = new SeekBar(themed());
        bar.setMax(10000);
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seek, int progress, boolean fromPerson) {
                if (!fromPerson || control.silent) {
                    return;
                }
                if (control.cancelledDrag) {
                    showSlider(control);
                    return;
                }
                double asked = control.minimum + (control.maximum - control.minimum) * progress / 10000.0;
                pushControl(control, SLIDER_CHANGED, 0, asked, null);
                showSlider(control);
            }

            @Override
            public void onStartTrackingTouch(SeekBar seek) {
                if (control.cancelledDrag) {
                    return;
                }
                control.tracking = true;
                dragging = control;
                pushControl(control, SLIDER_PRESSED, 0, 0.0, null);
            }

            @Override
            public void onStopTrackingTouch(SeekBar seek) {
                if (dragging == control) {
                    dragging = null;
                }
                if (control.tracking) {
                    control.tracking = false;
                    pushControl(control, SLIDER_RELEASED, 0, 0.0, null);
                }
                showSlider(control);
            }
        });
        return bar;
    }

    private static void showSlider(Control control) {
        double span = control.maximum - control.minimum;
        control.silent = true;
        ((SeekBar) control.view).setProgress(span > 0 ? (int) Math.round((control.value - control.minimum) / span * 10000.0) : 0);
        control.silent = false;
    }

    /* A select is a button that opens a list. The list's keys are read here,
     * so that what a person steps to and chooses is the same on every device:
     * a list in touch mode has no selection for a key to move. */
    private static View select(final Control control) {
        final Button button = new Button(themed());
        button.setAllCaps(false);
        button.setSingleLine(true);
        button.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        button.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                openSelect(control);
            }
        });
        return button;
    }

    private static int step(Control control, int from, int direction) {
        for (int index = from + direction; index >= 0 && index < control.items.size(); index += direction) {
            if (control.enabledItems.get(index)) {
                return index;
            }
        }
        return from;
    }

    private static void openSelect(final Control control) {
        if (control.popup != null) {
            return;
        }
        final ListPopupWindow popup = new ListPopupWindow(themed());
        control.popup = popup;
        control.chose = false;
        control.escaped = false;
        control.candidate = control.selected;
        popup.setAnchorView(control.view);
        popup.setModal(true);
        popup.setAdapter(new ArrayAdapter<String>(themed(), android.R.layout.simple_list_item_single_choice, control.items) {
            @Override
            public boolean isEnabled(int position) {
                return control.enabledItems.get(position);
            }

            @Override
            public boolean areAllItemsEnabled() {
                return false;
            }
        });
        popup.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View view, int position, long row) {
                control.chose = true;
                pushControl(control, SELECT_CHOSEN, position, 0.0, null);
                popup.dismiss();
            }
        });
        popup.setOnDismissListener(new android.widget.PopupWindow.OnDismissListener() {
            @Override
            public void onDismiss() {
                control.popup = null;
                if (!control.chose) {
                    pushControl(control, SELECT_DISMISSED, control.escaped ? 1 : 0, 0.0, null);
                }
            }
        });
        pushControl(control, SELECT_OPENED, 0, 0.0, null);
        popup.show();
        final ListView list = popup.getListView();
        if (list == null) {
            return;
        }
        list.setChoiceMode(ListView.CHOICE_MODE_SINGLE);
        if (control.candidate >= 0) {
            list.setItemChecked(control.candidate, true);
        }
        list.setOnKeyListener(new View.OnKeyListener() {
            @Override
            public boolean onKey(View view, int code, KeyEvent event) {
                boolean down = event.getAction() == KeyEvent.ACTION_DOWN;
                if (code == KeyEvent.KEYCODE_DPAD_DOWN || code == KeyEvent.KEYCODE_DPAD_UP) {
                    if (down) {
                        int next = step(control, control.candidate, code == KeyEvent.KEYCODE_DPAD_DOWN ? 1 : -1);
                        if (next != control.candidate && next >= 0) {
                            control.candidate = next;
                            list.setItemChecked(next, true);
                            list.smoothScrollToPosition(next);
                            pushControl(control, SELECT_CANDIDATE, next, 0.0, null);
                        }
                    }
                    return true;
                }
                if (code == KeyEvent.KEYCODE_ENTER || code == KeyEvent.KEYCODE_NUMPAD_ENTER || code == KeyEvent.KEYCODE_SPACE) {
                    if (down && control.candidate >= 0 && control.enabledItems.get(control.candidate)) {
                        control.chose = true;
                        pushControl(control, SELECT_CHOSEN, control.candidate, 0.0, null);
                        popup.dismiss();
                    }
                    return true;
                }
                if (code == KeyEvent.KEYCODE_ESCAPE) {
                    if (down) {
                        control.escaped = true;
                        popup.dismiss();
                    }
                    return true;
                }
                return false;
            }
        });
        list.requestFocus();
    }

    /* A one-line text field. The system owns the editing; what it leaves is reported. */
    private static View field(final Control control, String text, String placeholder) {
        /* Escape is the field's, before the system's keyboard can take it to hide itself. */
        final EditText field = new EditText(themed()) {
            @Override
            public boolean onKeyPreIme(int code, KeyEvent event) {
                if (code == KeyEvent.KEYCODE_ESCAPE) {
                    if (event.getAction() == KeyEvent.ACTION_DOWN) {
                        pushControl(control, TEXT_ESCAPED, 0, 0.0, null);
                    }
                    return true;
                }
                return super.onKeyPreIme(code, event);
            }
        };
        field.setSingleLine(true);
        field.setText(text);
        field.setHint(placeholder);
        field.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence before, int start, int count, int after) {}

            @Override
            public void onTextChanged(CharSequence now, int start, int before, int count) {}

            @Override
            public void afterTextChanged(Editable edited) {
                if (!control.silent) {
                    pushControl(control, TEXT_CHANGED, 0, 0.0, edited.toString());
                }
            }
        });
        field.setOnKeyListener(new View.OnKeyListener() {
            @Override
            public boolean onKey(View view, int code, KeyEvent event) {
                boolean down = event.getAction() == KeyEvent.ACTION_DOWN;
                if (code == KeyEvent.KEYCODE_ENTER || code == KeyEvent.KEYCODE_NUMPAD_ENTER) {
                    if (down) {
                        pushControl(control, TEXT_ACTIVATED, 0, 0.0, null);
                    }
                    return true;
                }
                return false;
            }
        });
        field.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView view, int action, KeyEvent event) {
                if (event == null) {
                    pushControl(control, TEXT_ACTIVATED, 0, 0.0, null);
                }
                return true;
            }
        });
        return field;
    }

    static void controlDestroy(final int handle) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                if (control == null) {
                    return;
                }
                if (control.popup != null) {
                    control.chose = true;
                    control.popup.dismiss();
                }
                if (control.kind == WEB) {
                    ShimWeb.destroy(control);
                }
                if (dragging == control) {
                    dragging = null;
                }
                if (cancelled == control) {
                    cancelled = null;
                }
                if (control.window != null) {
                    control.window.placedSlots.remove(control.slot);
                    control.window.removeView(control.slot);
                }
                controls.remove(handle);
            }
        });
    }

    static void controlSetEnabled(final int handle, final boolean enabled) {
        onUi(new Runnable() {
            @Override
            public void run() {
                control(handle).view.setEnabled(enabled);
            }
        });
    }

    static void controlSetToolTip(final int handle, final String text) {
        onUi(new Runnable() {
            @Override
            public void run() {
                control(handle).view.setTooltipText(text == null || text.isEmpty() ? null : text);
            }
        });
    }

    static void controlSetFont(final int handle, final double size, final boolean bold) {
        onUi(new Runnable() {
            @Override
            public void run() {
                View view = control(handle).view;
                if (view instanceof TextView) {
                    TextView text = (TextView) view;
                    text.setTextSize(TypedValue.COMPLEX_UNIT_DIP, (float) size);
                    text.setTypeface(Typeface.create(Typeface.SANS_SERIF, bold ? Typeface.BOLD : Typeface.NORMAL));
                }
            }
        });
    }

    /** {width, height} in points: what the control takes when nothing constrains it, or at this width. */
    static int[] controlNatural(final int handle, final int forWidth) {
        return onUi(new Callable<int[]>() {
            @Override
            public int[] call() {
                Control control = control(handle);
                int width = forWidth > 0 ? View.MeasureSpec.makeMeasureSpec(pixels(forWidth), View.MeasureSpec.EXACTLY) : View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED);
                control.view.measure(width, View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED));
                int natural = control.view.getMeasuredWidth();
                if (control.kind == SELECT) {
                    /* Wide enough for the longest item, not only the one shown. */
                    Paint paint = ((Button) control.view).getPaint();
                    float widest = 0;
                    for (String item : control.items) {
                        widest = Math.max(widest, paint.measureText(item));
                    }
                    natural = Math.max(natural, (int) Math.ceil(widest) + control.view.getPaddingLeft() + control.view.getPaddingRight() + pixels(24));
                }
                control.view.forceLayout();
                return new int[] {(int) Math.ceil(points(natural)), (int) Math.ceil(points(control.view.getMeasuredHeight()))};
            }
        });
    }

    /** One placement: for each entry a control's handle (zero for a hole) and
     * eight numbers, its frame and its clip, in points. Back to front. */
    static void windowPlace(final int id, final int[] handles, final float[] rectangles) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Window window = windows.get(id);
                if (window == null) {
                    return;
                }
                ArrayList<Slot> before = new ArrayList<>(window.placedSlots);
                ArrayList<Slot> now = new ArrayList<>();
                ArrayList<Rect> holes = new ArrayList<>();
                /* Holes cut the controls placed before them: walk front to back. */
                for (int index = handles.length - 1; index >= 0; index--) {
                    int base = index * 8;
                    Rect frame = new Rect(pixels(rectangles[base]), pixels(rectangles[base + 1]), pixels(rectangles[base] + rectangles[base + 2]), pixels(rectangles[base + 1] + rectangles[base + 3]));
                    Rect clip = new Rect(pixels(rectangles[base + 4]), pixels(rectangles[base + 5]), pixels(rectangles[base + 4] + rectangles[base + 6]), pixels(rectangles[base + 5] + rectangles[base + 7]));
                    if (handles[index] == 0) {
                        Rect hole = new Rect(frame);
                        if (hole.intersect(clip)) {
                            holes.add(hole);
                        }
                        continue;
                    }
                    Control control = control(handles[index]);
                    if (control == null) {
                        continue;
                    }
                    Slot slot = control.slot;
                    if (control.window != window) {
                        if (control.window != null) {
                            control.window.placedSlots.remove(slot);
                            control.window.removeView(slot);
                        }
                        control.window = window;
                    }
                    FrameLayout.LayoutParams where = new FrameLayout.LayoutParams(frame.width(), frame.height());
                    where.leftMargin = frame.left;
                    where.topMargin = frame.top;
                    where.gravity = Gravity.TOP | Gravity.START;
                    slot.setLayoutParams(where);
                    control.view.setLayoutParams(new FrameLayout.LayoutParams(frame.width(), frame.height()));
                    slot.clip.set(clip.left - frame.left, clip.top - frame.top, clip.right - frame.left, clip.bottom - frame.top);
                    slot.holes.clear();
                    for (Rect hole : holes) {
                        slot.holes.add(new Rect(hole.left - frame.left, hole.top - frame.top, hole.right - frame.left, hole.bottom - frame.top));
                    }
                    slot.invalidate();
                    now.add(0, slot);
                }
                for (Slot slot : before) {
                    if (!now.contains(slot)) {
                        window.removeView(slot);
                        for (int index = 0; index < controls.size(); index++) {
                            Control control = controls.valueAt(index);
                            if (control.slot == slot) {
                                control.window = null;
                            }
                        }
                    }
                }
                /* The content's surface is the first child; controls follow in order. */
                for (int index = 0; index < now.size(); index++) {
                    Slot slot = now.get(index);
                    int at = index + 1;
                    if (slot.getParent() != window) {
                        window.addView(slot, Math.min(at, window.getChildCount()));
                    } else if (window.indexOfChild(slot) != at) {
                        window.removeView(slot);
                        window.addView(slot, Math.min(at, window.getChildCount()));
                    }
                }
                window.placedSlots.clear();
                window.placedSlots.addAll(now);
            }
        });
    }

    /** The window's controls as the system draws them, over nothing: RGBA rows, premultiplied. */
    static byte[] windowDrawControls(final int id, final int pixelWidth, final int pixelHeight) {
        return onUi(new Callable<byte[]>() {
            @Override
            public byte[] call() {
                Window window = windows.get(id);
                if (window == null || pixelWidth <= 0 || pixelHeight <= 0) {
                    return null;
                }
                if (window.getWidth() == 0 || window.isLayoutRequested()) {
                    /* A capture may follow a placement at once: lay the controls out first. */
                    int width = window.getWidth() > 0 ? window.getWidth() : pixelWidth;
                    int height = window.getHeight() > 0 ? window.getHeight() : pixelHeight;
                    window.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY));
                    window.layout(window.getLeft(), window.getTop(), window.getLeft() + width, window.getTop() + height);
                }
                Bitmap bitmap = Bitmap.createBitmap(pixelWidth, pixelHeight, Bitmap.Config.ARGB_8888);
                Canvas canvas = new Canvas(bitmap);
                canvas.scale(pixelWidth / (float) Math.max(1, window.getWidth()), pixelHeight / (float) Math.max(1, window.getHeight()));
                for (Slot slot : window.placedSlots) {
                    int saved = canvas.save();
                    canvas.translate(slot.getLeft(), slot.getTop());
                    slot.draw(canvas);
                    canvas.restoreToCount(saved);
                }
                ByteBuffer pixels = ByteBuffer.allocate(pixelWidth * pixelHeight * 4);
                bitmap.copyPixelsToBuffer(pixels);
                bitmap.recycle();
                return pixels.array();
            }
        });
    }

    static void buttonSetTitle(final int handle, final String title) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((Button) control(handle).view).setText(title);
            }
        });
    }

    static void buttonSetCentered(final int handle, final boolean centered) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((Button) control(handle).view).setGravity((centered ? Gravity.CENTER_HORIZONTAL : Gravity.START) | Gravity.CENTER_VERTICAL);
            }
        });
    }

    /** A symbol beside the title: `shapes` holds seven numbers each (kind, then six), in points. */
    static void buttonSetSymbol(final int handle, final double size, final double[] shapes) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                Button button = (Button) control.view;
                control.symbol = size > 0 && shapes.length > 0 ? new Symbol(button, size, shapes) : null;
                if (control.symbol != null) {
                    control.symbol.setBounds(0, 0, pixels(size), pixels(size));
                }
                button.setCompoundDrawablesRelative(control.symbol, null, null, null);
                button.setCompoundDrawablePadding(pixels(6));
            }
        });
    }

    static void buttonSetBordered(final int handle, final boolean bordered) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                if (!bordered) {
                    control.view.setBackground(null);
                } else if (control.view.getBackground() == null) {
                    control.view.setBackground(new Button(themed()).getBackground());
                }
            }
        });
    }

    static void buttonSetSelected(final int handle, final boolean selected) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                control.selectedLook = selected;
                control.view.setSelected(selected);
                Drawable background = control.view.getBackground();
                if (background != null) {
                    if (selected) {
                        background.mutate().setColorFilter(new android.graphics.PorterDuffColorFilter(0x40000000, PorterDuff.Mode.SRC_ATOP));
                    } else {
                        background.mutate().clearColorFilter();
                    }
                }
            }
        });
    }

    static void buttonSetTransparent(final int handle, final boolean transparent) {
        onUi(new Runnable() {
            @Override
            public void run() {
                control(handle).view.setAlpha(transparent ? 0.0f : 1.0f);
            }
        });
    }

    static void labelSetText(final int handle, final String text) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((TextView) control(handle).view).setText(text);
            }
        });
    }

    static void labelSetSecondary(final int handle, final boolean secondary) {
        onUi(new Runnable() {
            @Override
            public void run() {
                control(handle).view.setAlpha(secondary ? 0.6f : 1.0f);
            }
        });
    }

    static void labelSetCentered(final int handle, final boolean centered) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((TextView) control(handle).view).setGravity((centered ? Gravity.CENTER_HORIZONTAL : Gravity.START) | Gravity.CENTER_VERTICAL);
            }
        });
    }

    static void labelSetWrapping(final int handle, final boolean wrapping) {
        onUi(new Runnable() {
            @Override
            public void run() {
                TextView label = (TextView) control(handle).view;
                label.setSingleLine(!wrapping);
                label.setEllipsize(wrapping ? null : TextUtils.TruncateAt.END);
            }
        });
    }

    static void spinnerSetRunning(final int handle, final boolean running) {
        onUi(new Runnable() {
            @Override
            public void run() {
                control(handle).view.setVisibility(running ? View.VISIBLE : View.INVISIBLE);
            }
        });
    }

    static void levelSet(final int handle, final double warning, final double critical, final double value) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ProgressBar level = (ProgressBar) control(handle).view;
                double shown = Math.max(0.0, Math.min(1.0, value));
                int colour = shown >= critical ? 0xFFFF3B30 : shown >= warning ? 0xFFFF9F0A : 0xFF34C759;
                level.setProgressTintList(android.content.res.ColorStateList.valueOf(colour));
                level.setProgress((int) Math.round(shown * 1000.0));
            }
        });
    }

    static void sliderSet(final int handle, final double minimum, final double maximum, final double value) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                control.minimum = minimum;
                control.maximum = maximum;
                control.value = value;
                showSlider(control);
            }
        });
    }

    static void selectSetItems(final int handle, final String[] titles, final boolean[] enabled) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                control.items.clear();
                control.enabledItems.clear();
                for (int index = 0; index < titles.length; index++) {
                    control.items.add(titles[index]);
                    control.enabledItems.add(enabled[index]);
                }
                control.selected = -1;
            }
        });
    }

    static void selectShow(final int handle, final int selected, final String shownText, final boolean available) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                control.selected = selected >= 0 && selected < control.items.size() ? selected : -1;
                ((Button) control.view).setText(shownText);
                control.view.setEnabled(available);
            }
        });
    }

    static void selectDismiss(final int handle) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                if (control.popup != null) {
                    control.popup.dismiss();
                }
            }
        });
    }

    /** The program's own text: not an edit, so not reported. The caret goes to its end. */
    static void textSet(final int handle, final String text) {
        onUi(new Runnable() {
            @Override
            public void run() {
                Control control = control(handle);
                EditText field = (EditText) control.view;
                if (field.getText().toString().equals(text)) {
                    return;
                }
                control.silent = true;
                field.setText(text);
                field.setSelection(field.getText().length());
                control.silent = false;
            }
        });
    }

    static void textSetPlaceholder(final int handle, final String placeholder) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((EditText) control(handle).view).setHint(placeholder);
            }
        });
    }

    /** RGBA rows, not premultiplied; null shows nothing. */
    static void pictureSet(final int handle, final byte[] pixels, final int width, final int height) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ImageView picture = (ImageView) control(handle).view;
                if (pixels == null || width <= 0 || height <= 0) {
                    picture.setImageBitmap(null);
                    return;
                }
                int[] colours = new int[width * height];
                for (int index = 0; index < colours.length; index++) {
                    int at = index * 4;
                    colours[index] = Color.argb(pixels[at + 3] & 0xff, pixels[at] & 0xff, pixels[at + 1] & 0xff, pixels[at + 2] & 0xff);
                }
                picture.setImageBitmap(Bitmap.createBitmap(colours, width, height, Bitmap.Config.ARGB_8888));
            }
        });
    }

    static void fillSet(final int handle, final int red, final int green, final int blue, final int alpha, final double radius) {
        onUi(new Runnable() {
            @Override
            public void run() {
                GradientDrawable fill = new GradientDrawable();
                fill.setColor(Color.argb(alpha, red, green, blue));
                fill.setCornerRadius((float) (radius * density));
                control(handle).view.setBackground(fill);
            }
        });
    }

    static void scrollbarSet(final int handle, final double offset, final double viewport, final double content) {
        onUi(new Runnable() {
            @Override
            public void run() {
                ((Scrollbar) control(handle).view).set(offset, viewport, content);
            }
        });
    }

    /** A scroll bar for a view the program scrolls itself: it shows where the
     * view is, and reports where a person drags it to. */
    static final class Scrollbar extends View {
        private final Control control;
        private final boolean vertical;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private double offset, viewport, content;
        private double grabbed;

        Scrollbar(Context context, Control control, boolean vertical) {
            super(context);
            this.control = control;
            this.vertical = vertical;
        }

        void set(double offset, double viewport, double content) {
            this.offset = offset;
            this.viewport = viewport;
            this.content = content;
            invalidate();
        }

        @Override
        protected void onMeasure(int widthSpec, int heightSpec) {
            int thick = pixels(8);
            int length = pixels(40);
            setMeasuredDimension(resolveSize(vertical ? thick : length, widthSpec), resolveSize(vertical ? length : thick, heightSpec));
        }

        private float length() {
            return vertical ? getHeight() : getWidth();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            if (content <= viewport || content <= 0) {
                return;
            }
            float thumb = Math.max(pixels(16), (float) (length() * viewport / content));
            float start = (float) ((length() - thumb) * offset / (content - viewport));
            paint.setColor(0x66808080);
            float inset = pixels(2);
            RectF bar = vertical ? new RectF(inset, start, getWidth() - inset, start + thumb) : new RectF(start, inset, start + thumb, getHeight() - inset);
            canvas.drawRoundRect(bar, pixels(3), pixels(3), paint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent event) {
            if (content <= viewport) {
                return false;
            }
            float thumb = Math.max(pixels(16), (float) (length() * viewport / content));
            double travel = length() - thumb;
            float at = vertical ? event.getY() : event.getX();
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    grabbed = at - travel * offset / (content - viewport);
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    double asked = travel > 0 ? (at - grabbed) / travel * (content - viewport) : 0;
                    asked = Math.max(0, Math.min(content - viewport, asked));
                    pushControl(control, SCROLLBAR_CHANGED, vertical ? 1 : 0, asked, null);
                    return true;
                }
                default:
                    return true;
            }
        }
    }

    /** A button's symbol: lines, triangles, rectangles and circles in the title's colour. */
    static final class Symbol extends Drawable {
        private final Button button;
        private final double size;
        private final double[] shapes;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        Symbol(Button button, double size, double[] shapes) {
            this.button = button;
            this.size = size;
            this.shapes = shapes;
        }

        @Override
        public void draw(Canvas canvas) {
            Rect bounds = getBounds();
            float scale = density;
            paint.setColor(button.getCurrentTextColor());
            paint.setStrokeCap(Paint.Cap.ROUND);
            for (int at = 0; at + 6 < shapes.length; at += 7) {
                int kind = (int) shapes[at];
                float a = bounds.left + (float) shapes[at + 1] * scale, b = bounds.top + (float) shapes[at + 2] * scale;
                if (kind == 1) {
                    paint.setStyle(Paint.Style.STROKE);
                    paint.setStrokeWidth((float) shapes[at + 5] * scale);
                    canvas.drawLine(a, b, bounds.left + (float) shapes[at + 3] * scale, bounds.top + (float) shapes[at + 4] * scale, paint);
                } else if (kind == 2) {
                    Path path = new Path();
                    path.moveTo(a, b);
                    path.lineTo(bounds.left + (float) shapes[at + 3] * scale, bounds.top + (float) shapes[at + 4] * scale);
                    path.lineTo(bounds.left + (float) shapes[at + 5] * scale, bounds.top + (float) shapes[at + 6] * scale);
                    path.close();
                    paint.setStyle(Paint.Style.FILL);
                    canvas.drawPath(path, paint);
                } else if (kind == 3) {
                    float stroke = (float) shapes[at + 6] * scale;
                    paint.setStyle(stroke > 0 ? Paint.Style.STROKE : Paint.Style.FILL);
                    paint.setStrokeWidth(stroke);
                    float radius = (float) shapes[at + 5] * scale;
                    canvas.drawRoundRect(new RectF(a, b, a + (float) shapes[at + 3] * scale, b + (float) shapes[at + 4] * scale), radius, radius, paint);
                } else if (kind == 4) {
                    float stroke = (float) shapes[at + 4] * scale;
                    paint.setStyle(stroke > 0 ? Paint.Style.STROKE : Paint.Style.FILL);
                    paint.setStrokeWidth(stroke);
                    canvas.drawCircle(a, b, (float) shapes[at + 3] * scale, paint);
                }
            }
        }

        @Override
        public void setAlpha(int alpha) {
            paint.setAlpha(alpha);
        }

        @Override
        public void setColorFilter(ColorFilter filter) {
            paint.setColorFilter(filter);
        }

        @Override
        @SuppressWarnings("deprecation")
        public int getOpacity() {
            return PixelFormat.TRANSLUCENT;
        }

        @Override
        public int getIntrinsicWidth() {
            return pixels(size);
        }

        @Override
        public int getIntrinsicHeight() {
            return pixels(size);
        }
    }
}
