#import "UI2MacOSControlLifetime.h"
#include <assert.h>
#include <stdio.h>

// Only actual provider objects and the fixture host are tracked. These weak
// sets are not a census or allowance for unobserved AppKit-private objects.
static NSMutableDictionary<NSString *, NSHashTable *> *owned;
static NSMutableDictionary<NSString *, NSNumber *> *counts;
static NSMutableDictionary<NSString *, NSMutableDictionary *> *classes;
static NSWindow *cycleWindow;
static long lastCycle;
static long lastGeneration;

static void observe(NSString *role, id object) {
    assert(object != nil);
    if (!owned[role]) owned[role] = [[NSHashTable alloc] initWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality capacity:0];
    if ([owned[role] containsObject:object]) return;
    [owned[role] addObject:object];
    counts[role] = @([counts[role] integerValue] + 1);
    if (!classes[role]) classes[role] = [NSMutableDictionary dictionary];
    NSString *name = NSStringFromClass([object class]);
    classes[role][name] = @([classes[role][name] integerValue] + 1);
}

static NSUInteger survivors(BOOL report) {
    NSUInteger total = 0;
    for (NSString *role in owned) {
        for (id object in owned[role].allObjects) {
            total++;
            if (report) fprintf(stderr, "CONTROL survivor cycle=%ld role=%s class=%s identity=%p\n",
                lastCycle, role.UTF8String, NSStringFromClass([object class]).UTF8String, (__bridge void *)object);
        }
    }
    return total;
}

@implementation BTRCUI2ControlLifetimeProbe
+ (void)runCycle:(long)cycle callback:(void (^)(void))callback {
    assert([NSThread isMainThread] && cycle == lastCycle + 1 && cycle <= 100);
    if (cycle == 1) {
        // Complete AppKit launch bookkeeping before the cycle's ownership pool,
        // as the native shell control does, without permitting activation.
        @autoreleasepool {
            [NSApplication sharedApplication];
            [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
            [NSApp finishLaunching];
        }
    }
    assert(NSApp.activationPolicy == NSApplicationActivationPolicyProhibited);
    if (!owned) owned = [NSMutableDictionary dictionary];
    assert(cycleWindow == nil && survivors(NO) == 0);
    lastCycle = cycle; lastGeneration = 0;
    counts = [NSMutableDictionary dictionary]; classes = [NSMutableDictionary dictionary];
    @autoreleasepool { callback(); }
    assert(lastGeneration == 2);
    NSDictionary *expected = @{ @"host": @1, @"select": @1, @"select-cell": @1,
        @"menu": @2, @"item": @4, @"presentation": @2, @"slider": @1, @"slider-cell": @1 };
    assert([counts isEqualToDictionary:expected]);
    NSTimeInterval start = NSProcessInfo.processInfo.systemUptime;
    NSUInteger remaining = 0; int turns = 0;
    do {
        @autoreleasepool {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
            remaining = survivors(NO);
        }
        turns++;
    } while (turns < 10 || (remaining && NSProcessInfo.processInfo.systemUptime - start < 2.0));
    @autoreleasepool {
        NSDictionary *record = @{ @"cycle": @(cycle), @"counts": counts, @"classes": classes,
            @"survivors": @(survivors(YES)), @"drain_turns": @(turns),
            @"drain_seconds": @(NSProcessInfo.processInfo.systemUptime - start), @"drain_deadline_seconds": @2 };
        NSError *error = nil; NSData *data = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:&error];
        assert(data && !error);
        fprintf(stdout, "CONTROL_LIFETIME %s\n", [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); fflush(stdout);
    }
    assert(remaining == 0);
}
+ (void)host:(NSView *)select slider:(NSView *)slider {
    assert([select isKindOfClass:NSPopUpButton.class] && [slider isKindOfClass:NSSlider.class]);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(-10000, -10000, 300, 120)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    [window.contentView addSubview:select]; [window.contentView addSubview:slider];
    select.frame = NSMakeRect(0, 0, 200, 40); slider.frame = NSMakeRect(0, 50, 200, 40);
    assert(!window.visible && !window.keyWindow && NSApp.activationPolicy == NSApplicationActivationPolicyProhibited);
    assert(cycleWindow == nil); cycleWindow = window; observe(@"host", window);
}
+ (void)observe:(NSView *)select slider:(NSView *)slider generation:(long)generation {
    assert(generation == lastGeneration + 1); lastGeneration = generation;
    assert([select isKindOfClass:NSPopUpButton.class] && [slider isKindOfClass:NSSlider.class]);
    NSPopUpButton *button = (NSPopUpButton *)select; NSPopUpButtonCell *cell = button.cell;
    assert([cell isKindOfClass:NSPopUpButtonCell.class]);
    assert(button.menu == cell.menu && button.menu.numberOfItems == 2);
    observe(@"select", button); observe(@"select-cell", cell); observe(@"menu", button.menu);
    for (NSMenuItem *item in button.menu.itemArray) observe(@"item", item);
    observe(@"presentation", cell.menuItem);
    assert(![button.menu.itemArray containsObject:cell.menuItem]);
    observe(@"slider", slider); observe(@"slider-cell", [(NSSlider *)slider cell]);
}
+ (void)choose:(NSView *)select {
    assert([select isKindOfClass:NSPopUpButton.class]);
    [[(NSPopUpButton *)select menu] performActionForItemAtIndex:1];
}
+ (BOOL)increment:(NSView *)slider {
    assert([slider isKindOfClass:NSSlider.class]); return [slider accessibilityPerformIncrement];
}
+ (void)finish {
    NSWindow *window = cycleWindow; assert(window != nil);
    assert(!window.visible && !window.keyWindow && NSApp.activationPolicy == NSApplicationActivationPolicyProhibited);
    window.contentView = nil; [window close]; cycleWindow = nil;
}
@end
