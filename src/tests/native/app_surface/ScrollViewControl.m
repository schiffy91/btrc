#import "ScrollViewControl.h"
#import <CoreGraphics/CoreGraphics.h>
#include <stdio.h>

/* Observe the real hierarchy and dispatch a real pixel-wheel NSEvent. The
 * fixture neither implements scrolling nor constructs any UI controls. */
static NSScrollView *testScroll;
static NSTextField *testHeader;
static NSTextView *editor;
static NSRect headerFrame;

@implementation NativeScrollViewProbe
+ (BOOL)prepare:(NSWindow *)window scroll:(NSScrollView *)scroll header:(NSTextField *)header {
    if (scroll.superview != window.contentView || header.superview != window.contentView ||
        ![scroll isKindOfClass:[NSScrollView class]] || scroll.documentView.superview != scroll.contentView ||
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
    testScroll = scroll;
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
+ (BOOL)finish:(NSScrollView *)scroll {
    BOOL detached = scroll == testScroll && scroll.superview == nil && scroll.documentView == nil;
    testScroll = nil;
    testHeader = nil;
    editor = nil;
    return detached;
}
@end
