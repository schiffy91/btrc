#import "UI2MacOSCancelState.h"
#include <assert.h>
#include <stdio.h>

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
    NSPoint _anchor;
    NSRect _clipBounds;
    NSRect _documentFrame;
    NSRect _scrollFrame;
    NSScrollerStyle _scrollerStyle;
    BOOL _horizontalScroller;
    BOOL _verticalScroller;
}
+ (NSPoint)documentAnchorForClipBounds:(NSRect)bounds documentFrame:(NSRect)frame flipped:(BOOL)flipped;
@end

@implementation BTRCUI2CancelState
+ (NSPoint)documentAnchorForClipBounds:(NSRect)bounds documentFrame:(NSRect)frame flipped:(BOOL)flipped {
    // Preserve the document point at the viewport's top when scroller style
    // changes the clip height. Raw unflipped origins describe its bottom.
    return NSMakePoint(NSMinX(bounds) - NSMinX(frame),
        flipped ? NSMinY(bounds) - NSMinY(frame) : NSMaxY(frame) - NSMaxY(bounds));
}
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
    _anchor = [BTRCUI2CancelState documentAnchorForClipBounds:_clip.bounds documentFrame:_document.frame flipped:_document.isFlipped];
    _clipBounds = _clip.bounds; _documentFrame = _document.frame; _scrollFrame = _scroll.frame;
    _scrollerStyle = _scroll.scrollerStyle;
    _horizontalScroller = _scroll.hasHorizontalScroller; _verticalScroller = _scroll.hasVerticalScroller;
    assert([self unchanged]);
}
- (BOOL)unchanged {
    assert([NSThread isMainThread]);
    BOOL unchanged = _window != nil && _window.visible && _window.contentView == _content &&
        _root.window == _window && _field.window == _window && _scroll.window == _window &&
        _field.superview == _fieldParent && _scroll.superview == _scrollParent &&
        [_field isDescendantOf:_root] && [_scroll isDescendantOf:_root] &&
        _scroll.contentView == _clip && _scroll.documentView == _document && _child.superview == _document &&
        _window.firstResponder == _editor && _field.currentEditor == _editor &&
        [_editor.string isEqualToString:@"draft"] && NSEqualRanges(_editor.selectedRange, _selection) &&
        NSEqualPoints([BTRCUI2CancelState documentAnchorForClipBounds:_clip.bounds documentFrame:_document.frame flipped:_document.isFlipped], _anchor);
    if (!unchanged) {
        fprintf(stderr, "UI2 native cancel state changed: visible=%d content=%d root_window=%d field_parent=%d scroll_parent=%d clip=%d document=%d child_parent=%d responder=%d editor=%d text=%s selection=%s expected_selection=%s offset=%s expected_offset=%s anchor=%s expected_anchor=%s\n",
            (int)_window.visible, _window.contentView == _content, _root.window == _window,
            _field.superview == _fieldParent, _scroll.superview == _scrollParent,
            _scroll.contentView == _clip, _scroll.documentView == _document, _child.superview == _document,
            _window.firstResponder == _editor, _field.currentEditor == _editor, _editor.string.UTF8String,
            NSStringFromRange(_editor.selectedRange).UTF8String, NSStringFromRange(_selection).UTF8String,
            NSStringFromPoint(_clip.bounds.origin).UTF8String, NSStringFromPoint(_offset).UTF8String,
            NSStringFromPoint([BTRCUI2CancelState documentAnchorForClipBounds:_clip.bounds documentFrame:_document.frame flipped:_document.isFlipped]).UTF8String,
            NSStringFromPoint(_anchor).UTF8String);
        fprintf(stderr, "UI2 native cancel geometry: clip_bounds=%s expected_clip_bounds=%s document_frame=%s expected_document_frame=%s scroll_frame=%s expected_scroll_frame=%s scroller_style=%ld expected_scroller_style=%ld horizontal_scroller=%d expected_horizontal_scroller=%d vertical_scroller=%d expected_vertical_scroller=%d document_flipped=%d clip_flipped=%d\n",
            NSStringFromRect(_clip.bounds).UTF8String, NSStringFromRect(_clipBounds).UTF8String,
            NSStringFromRect(_document.frame).UTF8String, NSStringFromRect(_documentFrame).UTF8String,
            NSStringFromRect(_scroll.frame).UTF8String, NSStringFromRect(_scrollFrame).UTF8String,
            (long)_scroll.scrollerStyle, (long)_scrollerStyle,
            (int)_scroll.hasHorizontalScroller, (int)_horizontalScroller,
            (int)_scroll.hasVerticalScroller, (int)_verticalScroller,
            (int)_document.isFlipped, (int)_clip.isFlipped);
    }
    return unchanged;
}
- (void)continueInput {
    assert([self unchanged]);
    [_editor insertText:@"Z" replacementRange:_selection];
    // This is native clip movement, not a claimed physical wheel gesture.
    NSPoint next = _clip.bounds.origin; next.y += _document.isFlipped ? 10.0 : -10.0;
    [_clip scrollToPoint:next]; [_scroll reflectScrolledClipView:_clip];
    assert([self continued]);
}
- (BOOL)continued {
    assert([NSThread isMainThread]);
    return _window.firstResponder == _editor && _field.currentEditor == _editor &&
        [_editor.string isEqualToString:@"dZt"] && NSEqualRanges(_editor.selectedRange, NSMakeRange(2, 0)) &&
        NSEqualPoints([BTRCUI2CancelState documentAnchorForClipBounds:_clip.bounds documentFrame:_document.frame flipped:_document.isFlipped],
            NSMakePoint(_anchor.x, _anchor.y + 10.0));
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
