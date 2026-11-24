package dev.btrc.shim;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.BitmapDrawable;
import android.hardware.HardwareBuffer;
import android.widget.ImageView;

/** Display the producer's buffer directly. A software snapshot takes its own copy. */
final class SharedFrameImage extends ImageView {
    SharedFrameImage(Context context) {
        super(context);
        setScaleType(ScaleType.FIT_CENTER);
    }

    boolean present(HardwareBuffer buffer) {
        Bitmap image = Bitmap.wrapHardwareBuffer(buffer, null);
        if (image == null) { return false; }
        setImageBitmap(image);
        return true;
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (canvas.isHardwareAccelerated() || !(getDrawable() instanceof BitmapDrawable)) {
            super.onDraw(canvas);
            return;
        }
        BitmapDrawable source = (BitmapDrawable) getDrawable();
        Bitmap copy = source.getBitmap().copy(Bitmap.Config.ARGB_8888, false);
        if (copy == null) { return; }
        int saved = canvas.save();
        try {
            canvas.translate(getPaddingLeft(), getPaddingTop());
            canvas.concat(getImageMatrix());
            canvas.drawBitmap(copy, null, source.getBounds(), source.getPaint());
        } finally {
            canvas.restoreToCount(saved);
            copy.recycle();
        }
    }
}
