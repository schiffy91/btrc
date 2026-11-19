package dev.btrc.shim;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.view.MotionEvent;
import android.widget.FrameLayout;
import java.util.ArrayList;

/** One control in a window: clipped to what its ancestors show, and cut out
 * where drawn content placed after it shows through. */
final class Slot extends FrameLayout {
    final ArrayList<Rect> holes = new ArrayList<>();
    final Rect clip = new Rect();
    boolean placed;
    int order;

    Slot(Context context) {
        super(context);
        setClipChildren(true);
    }

    @Override
    protected void dispatchDraw(Canvas canvas) {
        int saved = canvas.save();
        canvas.clipRect(clip);
        for (Rect hole : holes) {
            canvas.clipOutRect(hole);
        }
        super.dispatchDraw(canvas);
        canvas.restoreToCount(saved);
    }

    /** A touch outside what shows of the control is not the control's. */
    private boolean shows(float x, float y) {
        if (!clip.contains((int) x, (int) y)) {
            return false;
        }
        for (Rect hole : holes) {
            if (hole.contains((int) x, (int) y)) {
                return false;
            }
        }
        return true;
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN && !shows(event.getX(), event.getY())) {
            return false;
        }
        return super.dispatchTouchEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        return shows(event.getX(), event.getY()) && super.dispatchGenericMotionEvent(event);
    }
}
