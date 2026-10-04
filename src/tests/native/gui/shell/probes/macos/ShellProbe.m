#import <AppKit/AppKit.h>
#import "ShellProbe.h"
#import <CoreGraphics/CoreGraphics.h>
#include <assert.h>
#include <stdio.h>

static NSHashTable *observed;
static NSHashTable *editableFields;
static NSHashTable *fieldEditors;
static NSWindow *window(void) {
    for (NSWindow *candidate in NSApplication.sharedApplication.windows)
        if ([candidate.title isEqualToString:@"BTRC native shell"]) return candidate;
    assert(0 && "shell window missing");
    return nil;
}
static void observe(NSView *view) {
    /* AppKit retains the process's field editor and sometimes its first field.
     * Count owned container/control nodes; the text field retention baseline
     * is separately covered by the existing native StackProbe fixture. */
    if ([view isKindOfClass:NSTextField.class] && [(NSTextField *)view isEditable])
        [editableFields addObject:view];
    else if ([view isKindOfClass:NSTextView.class]) [fieldEditors addObject:view];
    else [observed addObject:view];
    for (NSView *child in view.subviews) observe(child);
}
void shellProbeObserve(void) {
    [observed release];
    observed = [[NSHashTable weakObjectsHashTable] retain];
    if (!editableFields) editableFields = [[NSHashTable weakObjectsHashTable] retain];
    if (!fieldEditors) fieldEditors = [[NSHashTable weakObjectsHashTable] retain];
    [observed addObject:window()];
    for (NSView *root in window().contentView.subviews) observe(root);
    assert(observed.allObjects.count > 0);
}
void shellProbeClick(double x, double y) {
    NSWindow *target = window();
    NSPoint location = NSMakePoint(x, target.contentView.bounds.size.height - y);
    for (int down = 1; down >= 0; down--) {
        NSEvent *event = [NSEvent mouseEventWithType:down ? NSEventTypeLeftMouseDown : NSEventTypeLeftMouseUp
            location:location modifierFlags:0 timestamp:0 windowNumber:target.windowNumber
            context:nil eventNumber:0 clickCount:1 pressure:1];
        [NSApplication.sharedApplication postEvent:event atStart:NO];
    }
}
static void key(NSString *characters, unsigned short code) {
    NSWindow *target = window();
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint
        modifierFlags:0 timestamp:0 windowNumber:target.windowNumber context:nil
        characters:characters charactersIgnoringModifiers:characters isARepeat:NO keyCode:code];
    [NSApplication.sharedApplication sendEvent:event];
}
void shellProbeTab(void) { key(@"\t", 48); }
void shellProbeEnter(void) { key(@"\r", 36); }
void shellProbeText(void) {
    id editor = window().firstResponder;
    assert([editor isKindOfClass:NSTextView.class]);
    [editor insertText:@"draft" replacementRange:NSMakeRange(NSNotFound, 0)];
}
void shellProbeScroll(void) {
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
void shellProbeClose(void) { [window() performClose:nil]; }
int shellProbeFocus(void) {
    NSResponder *responder = window().firstResponder;
    if ([responder isKindOfClass:NSTextView.class]) return 1;
    if ([responder isKindOfClass:NSButton.class]) return 2;
    return 0;
}
int shellProbeNativeCount(void) {
    @autoreleasepool {
        /* Retain these weak sets across cycles: a one-field-per-cycle leak
         * cannot hide behind the existing process-retained editor baseline. */
        assert(editableFields.allObjects.count <= 1);
        assert(fieldEditors.allObjects.count <= 1);
        return (int)observed.allObjects.count;
    }
}
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
    if ([window().firstResponder isKindOfClass:NSTextView.class])
        [fieldEditors addObject:window().firstResponder];
    NSDictionary *document = @{@"probe": @"macos-appkit", @"focus": @(shellProbeFocus()), @"native_handles": @(observed.allObjects.count),
        @"accessibility": accessible(window(), 0)};
    NSData *data = [NSJSONSerialization dataWithJSONObject:document options:0 error:NULL];
    assert(data);
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
}
