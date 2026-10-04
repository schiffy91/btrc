#import <AppKit/AppKit.h>
#import "ShellProbe.h"
#import <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

/* Weak sets survive all cycles. Provider objects are selected by the exact
 * fixture hierarchy, never by excluding inconvenient AppKit subclasses. */
static NSHashTable *owned;
static NSHashTable *privateObjects;
static NSWindow *window(void) {
    for (NSWindow *candidate in NSApplication.sharedApplication.windows)
        if ([candidate.title isEqualToString:@"BTRC native shell"]) return candidate;
    assert(0 && "shell window missing");
    return nil;
}
static void observePrivate(NSView *view) {
    if (![owned containsObject:view]) [privateObjects addObject:view];
    for (NSView *child in view.subviews) observePrivate(child);
}
void shellProbeObserve(void) {
    @autoreleasepool {
        if (!owned) owned = [[NSHashTable weakObjectsHashTable] retain];
        if (!privateObjects) privateObjects = [[NSHashTable weakObjectsHashTable] retain];
        NSWindow *target = window();
        [owned addObject:target];
        assert(target.contentView.subviews.count == 1);
        NSView *root = target.contentView.subviews.firstObject;
        [owned addObject:root];
        assert(root.subviews.count == 4);
        int scrolls = 0;
        for (NSView *child in root.subviews) {
            [owned addObject:child]; /* field, button, scroll view and GPU view */
            if ([child isKindOfClass:NSScrollView.class]) {
                scrolls++;
                NSView *document = [(NSScrollView *)child documentView];
                assert(document && document.subviews.count == 50);
                [owned addObject:document];
                for (NSView *label in document.subviews) [owned addObject:label];
            }
        }
        assert(scrolls == 1 && owned.allObjects.count >= 57);
        observePrivate(target.contentView);
    }
}
void shellProbeClick(double x, double y) {
    @autoreleasepool {
        NSWindow *target = window();
        NSPoint location = NSMakePoint(x, target.contentView.bounds.size.height - y);
        for (int down = 1; down >= 0; down--) {
            NSEvent *event = [NSEvent mouseEventWithType:down ? NSEventTypeLeftMouseDown : NSEventTypeLeftMouseUp
                location:location modifierFlags:0 timestamp:0 windowNumber:target.windowNumber
                context:nil eventNumber:0 clickCount:1 pressure:1];
            [NSApplication.sharedApplication postEvent:event atStart:NO];
        }
    }
}
static void key(NSString *characters, unsigned short code) {
    NSWindow *target = window();
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
        modifierFlags:0 timestamp:0 windowNumber:target.windowNumber context:nil
        characters:characters charactersIgnoringModifiers:characters isARepeat:NO keyCode:code];
    [NSApplication.sharedApplication sendEvent:event];
}
void shellProbeTab(void) {
    @autoreleasepool {
        key(@"\t", 48);
    }
}
void shellProbeEnter(void) {
    @autoreleasepool {
        key(@"\r", 36);
    }
}
void shellProbeText(void) {
    @autoreleasepool {
        id editor = window().firstResponder;
        assert([editor isKindOfClass:NSTextView.class]);
        [editor insertText:@"draft" replacementRange:NSMakeRange(NSNotFound, 0)];
    }
}
void shellProbeScroll(void) {
    @autoreleasepool {
        NSScrollView *scroll = nil;
        for (NSView *root in window().contentView.subviews)
            for (NSView *child in root.subviews)
                if ([child isKindOfClass:NSScrollView.class]) scroll = (NSScrollView *)child;
        assert(scroll);
        CGEventRef wheel = CGEventCreateScrollWheelEvent(NULL, kCGScrollEventUnitPixel, 1, -120);
        assert(wheel);
        [scroll scrollWheel:[NSEvent eventWithCGEvent:wheel]];
        CFRelease(wheel);
    }
}
void shellProbeClose(void) {
    @autoreleasepool {
        NSWindow *target = window();
        /* Editing/AX/scrolling may create private descendants after Observe.
         * Snapshot again before teardown without taking owning references. */
        observePrivate(target.contentView);
        if ([target.firstResponder isKindOfClass:NSView.class])
            observePrivate((NSView *)target.firstResponder);
        [target performClose:nil];
    }
}
int shellProbeFocus(void) {
    @autoreleasepool {
        NSResponder *responder = window().firstResponder;
        if ([responder isKindOfClass:NSTextView.class]) return 1;
        if ([responder isKindOfClass:NSButton.class]) return 2;
        return 0;
    }
}
void shellProbeDrain(void) {
    /* Ten bounded turns let window/CA teardown and delayed scroller work run.
     * The deadline is diagnostic, not permission to forgive provider survivors. */
    for (int turn = 0; turn < 10; turn++) {
        @autoreleasepool {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
        }
    }
}
static int survivors(NSHashTable *objects, const char *scope) {
    @autoreleasepool {
        NSArray *remaining = objects.allObjects;
        for (id object in remaining)
            fprintf(stderr, "SHELL survivor scope=%s class=%s identity=%p\n",
                scope, NSStringFromClass([object class]).UTF8String, (void *)object);
        return (int)remaining.count;
    }
}
int shellProbeNativeCount(void) { return survivors(owned, "provider"); }
int shellProbePrivateCount(void) { return survivors(privateObjects, "appkit-private"); }
static NSDictionary *accessible(id element, int depth) {
    if (depth > 12) return @{@"truncated": @YES};
    if (![element respondsToSelector:@selector(accessibilityRole)]) return @{@"role": @"unknown"};
    NSMutableArray *children = [NSMutableArray array];
    if ([element respondsToSelector:@selector(accessibilityChildren)])
        for (id child in [element accessibilityChildren]) [children addObject:accessible(child, depth + 1)];
    NSString *role = [element accessibilityRole] ?: @"unknown";
    return @{@"role": role, @"children": children};
}
void shellProbeDump(void) {
    @autoreleasepool {
        if ([window().firstResponder isKindOfClass:NSTextView.class])
            [privateObjects addObject:window().firstResponder];
        id accessibility = getenv("BTRC_UI_SHELL_NO_AX") ? (id)@"disabled diagnostic" : accessible(window(), 0);
        NSDictionary *document = @{@"probe": @"macos-appkit", @"focus": @(shellProbeFocus()),
            @"provider_objects": @(owned.allObjects.count), @"private_objects": @(privateObjects.allObjects.count),
            @"accessibility": accessibility};
        NSData *data = [NSJSONSerialization dataWithJSONObject:document options:0 error:NULL];
        assert(data);
        fwrite(data.bytes, 1, data.length, stdout);
        fputc('\n', stdout);
    }
}
