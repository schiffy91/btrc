#import <AppKit/AppKit.h>

/* Standalone actual-SDK reproducer for the unresolved slider presentation bug.
 * This does not replace NativeSlider.btrc's range/tracking/ownership tests.
 * Run in a disposable working directory; captures are written there. */
static BOOL maximumIsDrawn(NSSlider *slider, NSString *name) {
    slider.doubleValue = 100;
    slider.needsDisplay = YES;
    NSBitmapImageRep *bitmap = [slider bitmapImageRepForCachingDisplayInRect:slider.bounds];
    [slider cacheDisplayInRect:slider.bounds toBitmapImageRep:bitmap];
    [bitmap.TIFFRepresentation writeToFile:name atomically:YES];
    CGFloat scale = bitmap.pixelsWide / slider.bounds.size.width;
    CGFloat xSum = 0;
    NSUInteger ink = 0;
    // The bright knob extends above the thin horizontal track. Sampling that
    // band distinguishes its actual pixels from the filled 100-percent track.
    for (NSInteger y = (NSInteger)(9 * scale); y < (NSInteger)(12 * scale); y++) {
        for (NSInteger x = 0; x < bitmap.pixelsWide; x++) {
            NSColor *color = [[bitmap colorAtX:x y:y] colorUsingColorSpace:NSColorSpace.genericRGBColorSpace];
            if (color.alphaComponent > 0.5 && color.redComponent > 0.85 && color.greenComponent > 0.85 && color.blueComponent > 0.85) {
                xSum += x;
                ink++;
            }
        }
    }
    CGFloat center = ink == 0 ? -1 : xSum / ink / scale;
    NSRect knob = [(NSSliderCell *)slider.cell knobRectFlipped:slider.flipped];
    printf("%s: width=%.0f range=%.0f..%.0f value=%.0f cell=%.0f knobX=%.1f pixelCenter=%.1f ink=%lu\n",
           name.UTF8String, slider.bounds.size.width, slider.minValue, slider.maxValue,
           slider.doubleValue, slider.cell.doubleValue, knob.origin.x, center, (unsigned long)ink);
    return slider.doubleValue == 100 && ink > 0 && center > slider.bounds.size.width * 0.75;
}

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 360, 160)
                                                      styleMask:NSWindowStyleMaskTitled
                                                        backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO;
        window.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
        NSSlider *slider = [NSSlider new];
        slider.minValue = 10;
        slider.maxValue = 100;
        slider.numberOfTickMarks = 10;
        slider.allowsTickMarkValuesOnly = YES;
        slider.continuous = NO;
        slider.frame = NSMakeRect(20, 65, 320, 30);
        [window.contentView addSubview:slider];
        [window makeKeyAndOrderFront:nil];
        printf("intrinsic=%s fitting=%s\n", NSStringFromSize(slider.intrinsicContentSize).UTF8String,
               NSStringFromSize(slider.fittingSize).UTF8String);
        BOOL initial = maximumIsDrawn(slider, @"SliderPresentation-initial.tiff");
        NSPoint point = NSMakePoint(305, 80);
        for (NSNumber *enabled in @[@YES, @NO]) {
            slider.enabled = enabled.boolValue;
            slider.doubleValue = enabled.boolValue ? 10 : 20;
            NSEvent *down = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:point modifierFlags:0 timestamp:0
                                         windowNumber:window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
            NSEvent *up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:point modifierFlags:0 timestamp:0
                                       windowNumber:window.windowNumber context:nil eventNumber:2 clickCount:1 pressure:0];
            [NSApp postEvent:up atStart:NO];
            [window sendEvent:down];
        }
        slider.enabled = YES;
        BOOL tracked = maximumIsDrawn(slider, @"SliderPresentation-tracked.tiff");
        slider.hidden = YES;
        slider.frame = NSMakeRect(120, 65, 64, 30);
        slider.hidden = NO;
        BOOL compact = maximumIsDrawn(slider, @"SliderPresentation-compact.tiff");
        [window close];
        return initial && tracked && compact ? 0 : 1;
    }
}
