#import "UI2MacOSViewOrder.h"

@interface BTRCUI2OrderField : NSTextField
@property NSUInteger lostWindow;
@end
@implementation BTRCUI2OrderField
- (void)viewWillMoveToWindow:(NSWindow *)window {
    if (window == nil && self.window != nil) { self.lostWindow++; }
    [super viewWillMoveToWindow:window];
}
@end

@interface BTRCUI2ViewOrder () <NSTextFieldDelegate> {
    NSWindow *_window;
    NSView *_parent;
    BTRCUI2OrderField *_child;
    NSView *_sibling;
    NSTextView *_editor;
    NSRange _marked;
    NSRange _selected;
    NSUInteger _ended;
}
@end

@implementation BTRCUI2ViewOrder
+ (instancetype)new {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
    return [super new];
}
- (instancetype)init {
    self = [super init];
    if (self == nil) { return nil; }
    _window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 120)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    _window.releasedWhenClosed = NO;
    _parent = [NSView new];
    _window.contentView = _parent;
    _child = [[BTRCUI2OrderField alloc] initWithFrame:NSMakeRect(0, 0, 120, 30)];
    _sibling = [[NSView alloc] initWithFrame:NSMakeRect(130, 0, 120, 30)];
    _child.delegate = self;
    [_parent addSubview:_child];
    [_parent addSubview:_sibling];
    if (![_window makeFirstResponder:_child]) {
        [NSException raise:NSInternalInconsistencyException format:@"Cannot establish field editor"];
    }
    _editor = (NSTextView *)_child.currentEditor;
    if (_editor == nil || _window.firstResponder != _editor) {
        [NSException raise:NSInternalInconsistencyException format:@"No active field editor"];
    }
    [_editor setMarkedText:@"composition" selectedRange:NSMakeRange(3, 0)
        replacementRange:NSMakeRange(NSNotFound, 0)];
    _marked = _editor.markedRange;
    _selected = _editor.selectedRange;
    _child.lostWindow = 0;
    return self;
}
- (NSView *)parentView { return _parent; }
- (NSView *)childView { return _child; }
- (NSView *)siblingView { return _sibling; }
- (void)controlTextDidEndEditing:(NSNotification *)notification {
    (void)notification;
    _ended++;
}
- (BOOL)verifyChildFirst:(BOOL)first {
    NSArray<NSView *> *order = _parent.subviews;
    return order.count == 2 && order[first ? 0 : 1] == _child && order[first ? 1 : 0] == _sibling &&
        _child.window == _window && _child.superview == _parent && _child.lostWindow == 0 &&
        _child.currentEditor == _editor && _window.firstResponder == _editor && _editor.hasMarkedText &&
        NSEqualRanges(_editor.markedRange, _marked) && NSEqualRanges(_editor.selectedRange, _selected) &&
        _ended == 0;
}
- (void)finish {
    _child.delegate = nil;
    [_window makeFirstResponder:nil];
    [_window close];
    _editor = nil;
}
- (void)dealloc {
    [self finish];
    [_window release];
    [_parent release];
    [_child release];
    [_sibling release];
    [super dealloc];
}
@end
