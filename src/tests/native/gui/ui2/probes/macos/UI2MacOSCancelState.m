#import "UI2MacOSCancelState.h"
#include <assert.h>

@interface BTRCUI2CancelState () {
    NSWindow *_window;
    NSView *_root;
    NSView *_content;
    NSTextField *_field;
    NSView *_fieldParent;
    NSScrollView *_scroll;
    NSView *_scrollParent;
    NSClipView *_clip;
    NSView *_document;
    NSView *_child;
    NSTextView *_editor;
    NSRange _selection;
    NSPoint _offset;
}
@end

@implementation BTRCUI2CancelState
+ (void)prepareHost {
    [NSApplication sharedApplication];
    assert([NSThread isMainThread]);
    assert([NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory]);
    [NSApp finishLaunching];
}
+ (instancetype)new { return [super new]; }
- (void)begin:(NSView *)root field:(NSView *)field scroll:(NSView *)scroll child:(NSView *)child {
    assert([NSThread isMainThread] && _window == nil);
    assert([field isKindOfClass:NSTextField.class] && [scroll isKindOfClass:NSScrollView.class]);
    _root = [root retain]; _field = [(NSTextField *)field retain];
    _scroll = [(NSScrollView *)scroll retain]; _child = [child retain];
    _window = [field.window retain]; _content = [_window.contentView retain];
    _fieldParent = [field.superview retain]; _scrollParent = [scroll.superview retain];
    _clip = [_scroll.contentView retain]; _document = [_scroll.documentView retain];
    assert(_window != nil && _window.visible && root.window == _window && scroll.window == _window);
    assert([_window makeFirstResponder:_field]);
    assert([_field.currentEditor isKindOfClass:NSTextView.class]);
    _editor = [(NSTextView *)_field.currentEditor retain];
    [_editor insertText:@"draft" replacementRange:NSMakeRange(0, _editor.string.length)];
    [_editor setSelectedRange:NSMakeRange(1, 3)];
    _selection = _editor.selectedRange; _offset = _clip.bounds.origin;
    assert([self unchanged]);
}
- (BOOL)unchanged {
    assert([NSThread isMainThread]);
    return _window != nil && _window.visible && _window.contentView == _content &&
        _root.window == _window && _field.window == _window && _scroll.window == _window &&
        _field.superview == _fieldParent && _scroll.superview == _scrollParent &&
        [_field isDescendantOf:_root] && [_scroll isDescendantOf:_root] &&
        _scroll.contentView == _clip && _scroll.documentView == _document && _child.superview == _document &&
        _window.firstResponder == _editor && _field.currentEditor == _editor &&
        [_editor.string isEqualToString:@"draft"] && NSEqualRanges(_editor.selectedRange, _selection) &&
        NSEqualPoints(_clip.bounds.origin, _offset);
}
- (void)continueInput {
    assert([self unchanged]);
    [_editor insertText:@"Z" replacementRange:_selection];
    // This is native clip movement, not a claimed physical wheel gesture.
    NSPoint next = _offset; next.y -= 10.0;
    [_clip scrollToPoint:next]; [_scroll reflectScrolledClipView:_clip];
    assert([self continued]);
}
- (BOOL)continued {
    assert([NSThread isMainThread]);
    return _window.firstResponder == _editor && _field.currentEditor == _editor &&
        [_editor.string isEqualToString:@"dZt"] && NSEqualRanges(_editor.selectedRange, NSMakeRange(2, 0)) &&
        _clip.bounds.origin.x == _offset.x && _clip.bounds.origin.y == _offset.y - 10.0;
}
- (void)finish {
    assert([NSThread isMainThread]);
    // Observation releases its claims without changing focus or attachment.
    [_editor release]; _editor = nil; [_child release]; _child = nil;
    [_document release]; _document = nil; [_clip release]; _clip = nil;
    [_scrollParent release]; _scrollParent = nil; [_fieldParent release]; _fieldParent = nil;
    [_scroll release]; _scroll = nil; [_field release]; _field = nil;
    [_content release]; _content = nil; [_root release]; _root = nil;
    [_window release]; _window = nil;
}
- (void)dealloc { [self finish]; [super dealloc]; }
@end
