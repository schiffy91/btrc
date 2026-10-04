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
/* Identity comes from the fixture's actual provider-created children, not AX
 * role guesses. The GPU provider currently hosts an ordinary NSView. */
static NSDictionary *controls(NSWindow *target) {
    NSView *root = target.contentView.subviews.firstObject;
    assert(root && root.subviews.count == 4);
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSView *view in root.subviews) {
        NSString *name = [view isKindOfClass:NSTextField.class] ? @"field" :
            [view isKindOfClass:NSButton.class] ? @"button" :
            [view isKindOfClass:NSScrollView.class] ? @"scroll" : @"gpu";
        assert(!result[name]);
        result[name] = view;
    }
    assert(result.count == 4);
    return result;
}
static NSString *identity(id object, NSDictionary *views) {
    for (NSString *name in views)
        if (object == views[name]) return name;
    /* AppKit edits an NSTextField through its window-owned field editor. */
    if ([object isKindOfClass:NSTextView.class] && [(NSTextView *)object isFieldEditor] &&
        [(NSTextView *)object delegate] == views[@"field"]) return @"field";
    return @"other";
}
static NSString *responderIdentity(NSResponder *responder, NSDictionary *views) {
    NSString *name = identity(responder, views);
    if (![name isEqualToString:@"other"]) return name;
    if ([responder isKindOfClass:NSView.class]) {
        for (NSView *parent = [(NSView *)responder superview]; parent; parent = parent.superview) {
            name = identity(parent, views);
            if (![name isEqualToString:@"other"]) return name;
        }
    }
    return @"other";
}
static NSString *responderClass(NSResponder *responder) {
    return responder ? NSStringFromClass(responder.class) : @"nil";
}
static NSArray *rectangle(NSRect value) {
    return @[@(value.origin.x), @(value.origin.y), @(value.size.width), @(value.size.height)];
}
static id jsonValue(id value) {
    if (!value) return NSNull.null;
    if ([value isKindOfClass:NSString.class] || [value isKindOfClass:NSNumber.class]) return value;
    if ([value isKindOfClass:NSAttributedString.class]) return [value string];
    /* Do not turn an arbitrary native object's description into an AX value. */
    return NSNull.null;
}
static NSDictionary *accessible(id element, NSDictionary *views, NSHashTable *seen, int depth) {
    if (depth > 16 || seen.count >= 512) return @{@"truncated": @YES};
    if ([seen containsObject:element]) return @{@"cycle": @YES};
    [seen addObject:element];
    NSMutableArray *children = [NSMutableArray array];
    if ([element respondsToSelector:@selector(accessibilityChildren)])
        for (id child in [element accessibilityChildren])
            [children addObject:accessible(child, views, seen, depth + 1)];
    id value = [element respondsToSelector:@selector(accessibilityValue)] ? [element accessibilityValue] : nil;
    return @{
        @"fixture_id": identity(element, views),
        @"native_class": NSStringFromClass([element class]),
        @"role": [element respondsToSelector:@selector(accessibilityRole)] ? jsonValue([element accessibilityRole]) : NSNull.null,
        @"label": [element respondsToSelector:@selector(accessibilityLabel)] ? jsonValue([element accessibilityLabel]) : NSNull.null,
        @"value": jsonValue(value),
        @"value_class": value ? NSStringFromClass([value class]) : (id)NSNull.null,
        @"focused": [element respondsToSelector:@selector(isAccessibilityFocused)] ? @([element isAccessibilityFocused]) : (id)NSNull.null,
        @"frame": [element respondsToSelector:@selector(accessibilityFrame)] ? rectangle([element accessibilityFrame]) : (id)NSNull.null,
        @"children": children
    };
}
static NSUInteger subviewTotal(NSView *view) {
    NSUInteger total = view.subviews.count;
    for (NSView *child in view.subviews) total += subviewTotal(child);
    return total;
}
static NSDictionary *keyViews(NSWindow *target, NSDictionary *views) {
    NSResponder *saved = [target.firstResponder retain];
    BOOL fieldAccepted = [target makeFirstResponder:views[@"field"]];
    NSMutableArray *traversal = [NSMutableArray arrayWithObject:responderIdentity(target.firstResponder, views)];
    NSMutableArray *classes = [NSMutableArray arrayWithObject:responderClass(target.firstResponder)];
    for (int turn = 0; turn < 3; turn++) {
        key(@"\t", 48);
        [traversal addObject:responderIdentity(target.firstResponder, views)];
        [classes addObject:responderClass(target.firstResponder)];
    }
    NSMutableArray *native = [NSMutableArray array];
    for (NSString *name in @[@"field", @"button", @"scroll", @"gpu"]) {
        NSView *view = views[name];
        [native addObject:@{
            @"fixture_id": name, @"native_class": NSStringFromClass(view.class),
            @"accepts_first_responder": @(view.acceptsFirstResponder),
            @"can_become_key_view": @(view.canBecomeKeyView),
            @"next_key_view": responderIdentity(view.nextKeyView, views),
            @"next_valid_key_view": responderIdentity(view.nextValidKeyView, views)
        }];
    }
    BOOL gpuAccepted = [target makeFirstResponder:views[@"gpu"]];
    NSString *gpuResponder = responderIdentity(target.firstResponder, views);
    BOOL restored = [target makeFirstResponder:saved];
    [saved release];
    return @{
        @"method": @"NSEvent Tab through NSApplication.sendEvent; unchanged native key-view loop",
        @"full_keyboard_access": @([NSApplication.sharedApplication isFullKeyboardAccessEnabled]),
        @"field_accepted": @(fieldAccepted), @"tab_order": traversal, @"responder_classes": classes,
        @"controls": native, @"gpu_make_first_responder": @(gpuAccepted),
        @"gpu_responder": gpuResponder, @"restored": @(restored)
    };
}
void shellProbeDump(void) {
    @autoreleasepool {
        NSWindow *target = window();
        if ([target.firstResponder isKindOfClass:NSTextView.class])
            [privateObjects addObject:target.firstResponder];
        int originalFocus = shellProbeFocus();
        BOOL disabled = getenv("BTRC_UI_SHELL_NO_AX") != NULL;
        id accessibility = @"disabled diagnostic";
        id traversal = @{@"disabled": @YES};
        NSMutableArray *native = [NSMutableArray array];
        if (!disabled) {
            NSDictionary *views = controls(target);
            NSHashTable *seen = [NSHashTable hashTableWithOptions:NSPointerFunctionsObjectPointerPersonality];
            accessibility = accessible(target, views, seen, 0);
            for (NSString *name in @[@"field", @"button", @"scroll", @"gpu"]) {
                NSView *view = views[name];
                [native addObject:@{
                    @"fixture_id": name, @"native_class": NSStringFromClass(view.class),
                    @"ax_exposed": @([seen containsObject:view]),
                    @"is_accessibility_element": @([view isAccessibilityElement]),
                    @"frame": rectangle([view convertRect:view.bounds toView:target.contentView])
                }];
            }
            traversal = keyViews(target, views);
        }
        /* Newly-created field-editor/AX descendants belong in the separate
         * private-object observation, never excluded from provider accounting. */
        observePrivate(target.contentView);
        NSDictionary *document = @{
            @"probe": @"macos-appkit", @"focus": @(originalFocus),
            @"provider_objects": @(owned.allObjects.count), @"private_objects": @(privateObjects.allObjects.count),
            @"subview_total": @(subviewTotal(target.contentView)),
            @"ax_frame_space": @"AppKit screen points; origin bottom-left",
            @"native_frame_space": @"window content points; origin bottom-left",
            @"accessibility": accessibility, @"native_controls": native, @"key_views": traversal
        };
        NSData *data = [NSJSONSerialization dataWithJSONObject:document options:0 error:NULL];
        assert(data);
        fwrite(data.bytes, 1, data.length, stdout);
        fputc('\n', stdout);
    }
}
