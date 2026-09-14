# Unresolved native slider presentation

`SliderPresentation.m` is an actual AppKit-only regression reproducer, not a
passing replacement for `NativeSlider.btrc`. Compile with the active Xcode SDK:

```sh
clang -fobjc-arc -O2 -Wall -Wextra -Werror -Wno-deprecated-declarations -framework AppKit SliderPresentation.m -o SliderPresentation
```

Run the executable in a disposable directory. It writes initial, post-tracking,
and compact TIFF captures and exits nonzero if the bright knob pixels do not
occupy the high end when the native value is 100. The ordinary native fixture
independently covers min/max, every 10-percent step, 53-to-50 snapping, native
tracking, disabled input and owner teardown.

On the current macOS/AppKit SDK the initial 320-by-30 control draws its maximum
correctly; after tracking and disabling/re-enabling, the native value and cell
value are 100 but the knob remains at the left. The 64-by-30 compact case also
fails. AppKit reports intrinsic size (-1, 16) and fitting size (0, 16), not a
minimum supported width. The failure at width 320 rules out compact width as
the sole cause. An independent investigation also reproduced the mismatch at
heights 14 and 16, without hiding, and with ordinary event/run-loop pumping.

No provider reset, replacement owner, arbitrary minimum width or capture
rewrite is included. Native layout/display invalidation and a direct bitmap
draw did not resolve the mismatch. The full player harness separately proves
all ten steps reach the real audio owner's effective speed; its captured 100%
label with a left-positioned knob remains an unresolved presentation defect.
