#import "UI2MacOSImages.h"
#include <stdio.h>

@implementation BTRCUI2ImageProbe
+ (BOOL)image:(NSImage *)image red:(NSInteger)red {
    if (!image) return NO;
    for (NSImageRep *representation in image.representations) {
        if (![representation isKindOfClass:NSBitmapImageRep.class]) continue;
        NSBitmapImageRep *bitmap = (NSBitmapImageRep *)representation;
        if (bitmap.pixelsWide != 2 || bitmap.pixelsHigh != 2 || bitmap.bitsPerSample != 8 || bitmap.samplesPerPixel < 3 || bitmap.samplesPerPixel > 4) {
            fprintf(stderr, "image bitmap width=%ld height=%ld bits=%ld samples=%ld\n", (long)bitmap.pixelsWide, (long)bitmap.pixelsHigh, (long)bitmap.bitsPerSample, (long)bitmap.samplesPerPixel);
            return NO;
        }
        /* Inspect the decoded sample values, without display-profile color conversion. */
        NSUInteger samples[4] = {0, 0, 0, 0};
        [bitmap getPixel:samples atX:0 y:0];
        BOOL matches = samples[0] == (NSUInteger)red && samples[1] == 17 && samples[2] == 39;
        if (!matches) {
            fprintf(stderr, "image bitmap format=%lu samples=%lu,%lu,%lu,%lu expected=%ld,17,39\n", (unsigned long)bitmap.bitmapFormat, (unsigned long)samples[0], (unsigned long)samples[1], (unsigned long)samples[2], (unsigned long)samples[3], (long)red);
        }
        return matches;
    }
    fprintf(stderr, "image has no bitmap representation\n");
    return NO;
}
+ (BOOL)view:(NSView *)view red:(NSInteger)red {
    return [view isKindOfClass:NSImageView.class] && [self image:((NSImageView *)view).image red:red];
}
@end
