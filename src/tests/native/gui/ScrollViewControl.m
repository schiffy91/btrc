#import "ScrollViewControl.h"
#import <CoreGraphics/CoreGraphics.h>
#include <stdio.h>

/* Observe the real hierarchy and dispatch a real pixel-wheel NSEvent. The
 * fixture neither implements scrolling nor constructs any UI controls; it
 * builds them through the portable GUI factory and the probe finds them. */
static NSScrollView *testScroll;
static NSTextField *testHeader;
static NSTextView *editor;
static NSRect headerFrame;

@implementation NativeScrollViewProbe
+ (NSWindow *)window {
    for (NSWindow *window in NSApp.windows) {
        if ([window.title isEqualToString:@"Native scrolling"]) { return window; }
    }
    return nil;
}
/* The window root is the only content subview; header and scroll view are its children. */
+ (NSView *)root {
    NSWindow *window = [self window];
    return window.contentView.subviews.count == 1 ? window.contentView.subviews.firstObject : nil;
}
+ (NSScrollView *)scroll {
    for (NSView *view in [self root].subviews) {
        if ([view isKindOfClass:[NSScrollView class]]) { return (NSScrollView *)view; }
    }
    return nil;
}
+ (double)topOfDocumentChild:(NSInteger)index {
    NSView *document = [self scroll].documentView;
    if (document == nil || index < 0 || (NSUInteger)index >= document.subviews.count) { return -1.0; }
    NSRect frame = document.subviews[(NSUInteger)index].frame;
    return document.frame.size.height - frame.origin.y - frame.size.height;
}
+ (BOOL)prepare {
    NSWindow *window = [self window];
    NSView *root = [self root];
    NSScrollView *scroll = [self scroll];
    NSTextField *header = nil;
    for (NSView *view in root.subviews) {
        if ([view isKindOfClass:[NSTextField class]]) { header = (NSTextField *)view; }
    }
    if (window == nil || root == nil || scroll == nil || header == nil ||
        !NSEqualRects(root.frame, window.contentView.bounds) ||
        scroll.documentView.superview != scroll.contentView ||
        !scroll.hasVerticalScroller || scroll.hasHorizontalScroller || !scroll.autohidesScrollers ||
        scroll.scrollerStyle != NSScrollerStyleOverlay || scroll.borderType != NSNoBorder ||
        !NSEqualRects(scroll.frame, NSMakeRect(0, 0, 480, 400)) ||
        scroll.documentView.subviews.count != 2 ||
        ![scroll.documentView.subviews.lastObject isKindOfClass:[NSScrollView class]]) { return NO; }
    [window makeKeyAndOrderFront:nil];
    [window displayIfNeeded];
    if (![window makeFirstResponder:header]) { return NO; }
    editor = (NSTextView *)header.currentEditor;
    if (editor == nil) { return NO; }
    [editor setSelectedRange:NSMakeRange(0, 6)];
    testScroll = [scroll retain];
    testHeader = header;
    headerFrame = header.frame;
    return YES;
}
+ (BOOL)wheel {
    CGFloat before = testScroll.contentView.bounds.origin.y;
    CGEventRef wheel = CGEventCreateScrollWheelEvent(NULL, kCGScrollEventUnitPixel, 1, -80);
    if (!wheel) { return NO; }
    NSEvent *event = [NSEvent eventWithCGEvent:wheel];
    [testScroll scrollWheel:event];
    CFRelease(wheel);
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:0.5];
    while (testScroll.contentView.bounds.origin.y == before && deadline.timeIntervalSinceNow > 0) {
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    }
    if (testScroll.contentView.bounds.origin.y == before) {
        fprintf(stderr, "wheel did not move native viewport: delta=%g origin=%g document=%g viewport=%g\n",
            event.scrollingDeltaY, (double)before, (double)testScroll.documentView.frame.size.height,
            (double)testScroll.contentView.bounds.size.height);
    }
    return testScroll.contentView.bounds.origin.y != before &&
        NSEqualRects(testHeader.frame, headerFrame) && testHeader.currentEditor == editor &&
        NSEqualRanges(editor.selectedRange, NSMakeRange(0, 6));
}
+ (BOOL)finish {
    BOOL detached = testScroll.superview == nil && testScroll.documentView == nil;
    [testScroll release];
    testScroll = nil;
    testHeader = nil;
    editor = nil;
    return detached;
}
@end
