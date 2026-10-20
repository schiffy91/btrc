#import "UI2MacOSImages.h"
#include <stdio.h>
#include <assert.h>
#include <stdatomic.h>

// Weak identity sets observe actual provider objects. They neither retain
// images nor count unobserved AppKit-private allocations.
static NSMutableDictionary<NSString *, NSHashTable *> *lifetimeObjects;
static NSMutableDictionary<NSString *, NSNumber *> *lifetimeCounts;
static long lifetimeCycle;
static atomic_int workers;
static void observeObject(NSString *role, id value) {
    assert(value != nil);
    if (!lifetimeObjects[role]) lifetimeObjects[role] = [[NSHashTable alloc]
        initWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality capacity:0];
    if ([lifetimeObjects[role] containsObject:value]) return;
    [lifetimeObjects[role] addObject:value];
    lifetimeCounts[role] = @([lifetimeCounts[role] integerValue] + 1);
}
static NSUInteger liveObjects(void) {
    NSUInteger total = 0;
    for (NSString *role in lifetimeObjects) total += lifetimeObjects[role].allObjects.count;
    return total;
}
@implementation BTRCUI2ImageProbe
+ (void)requireWorker { assert(!NSThread.isMainThread); atomic_fetch_add(&workers, 1); }
+ (void)runCycle:(long)cycle callback:(void (^)(void))callback {
    assert(NSThread.isMainThread && cycle == lifetimeCycle + 1 && cycle <= 100);
    assert(liveObjects() == 0);
    lifetimeCycle = cycle; atomic_store(&workers, 0);
    lifetimeObjects = [NSMutableDictionary dictionary]; lifetimeCounts = [NSMutableDictionary dictionary];
    @autoreleasepool { callback(); }
    assert(atomic_load(&workers) == 2);
    NSDictionary *expected = @{ @"view": @2, @"cell": @2, @"image": @2, @"bitmap": @2 };
    assert([lifetimeCounts isEqualToDictionary:expected]);
    NSTimeInterval start = NSProcessInfo.processInfo.systemUptime;
    NSUInteger survivors = liveObjects();
    while (survivors && NSProcessInfo.processInfo.systemUptime - start < 2.0) {
        @autoreleasepool {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
            survivors = liveObjects();
        }
    }
    NSDictionary *record = @{ @"cycle": @(cycle), @"order": @((cycle - 1) % 4),
        @"explicit_original_close": @((cycle - 1) / 4 % 2 == 1), @"workers": @(atomic_load(&workers)),
        @"counts": lifetimeCounts, @"survivors": @(survivors), @"drain_deadline_seconds": @2 };
    NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:&error];
    assert(data && !error);
    fprintf(stdout, "UI2_IMAGE_LIFETIME %s\n", [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); fflush(stdout);
    assert(survivors == 0);
}
+ (void)observe:(NSView *)view {
    assert(NSThread.isMainThread && [view isKindOfClass:NSImageView.class]);
    NSImageView *native = (NSImageView *)view;
    observeObject(@"view", native); observeObject(@"cell", native.cell);
    observeObject(@"image", native.image);
    assert(native.image.representations.count == 1);
    for (NSImageRep *representation in native.image.representations) {
        assert([representation isKindOfClass:NSBitmapImageRep.class]); observeObject(@"bitmap", representation);
    }
}
+ (void)sample:(NSView *)view cycle:(long)cycle stage:(long)stage slot:(long)slot red:(long)red {
    assert(NSThread.isMainThread && cycle == lifetimeCycle);
    assert(!view || [view isKindOfClass:NSImageView.class]);
    NSImage *image = [(NSImageView *)view image];
    if (red) assert([self image:image red:red]); else assert(image == nil);
    fprintf(stdout, "UI2_IMAGE_PIXEL {\"cycle\":%ld,\"stage\":%ld,\"slot\":%ld,\"expected_red\":%ld,\"open\":%s,\"image_present\":%s}\n",
        cycle, stage, slot, red, view ? "true" : "false", image ? "true" : "false");
}

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
