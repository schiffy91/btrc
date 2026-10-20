#import "UI2MacOSContainer.h"
@interface BTRCUI2ContainerProbe () <NSTextFieldDelegate> {
    NSWindow *_window;
    NSTextField *_field;
    NSView *_parent;
    NSTextView *_editor;
    NSRange _marked;
    NSRange _selected;
    NSUInteger _ended;
}
@end
@implementation BTRCUI2ContainerProbe
+ (void)prepare { [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited]; }
+ (instancetype)new { [self prepare]; return [super new]; }
- (instancetype)init {
    self = [super init];
    if (self) {
        _window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 120)
            styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
        _window.releasedWhenClosed = NO;
        _field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 120, 30)];
        _field.delegate = self;
    }
    return self;
}
- (NSTextField *)field { return _field; }
- (void)begin:(NSView *)parent {
    _parent = [parent retain]; _window.contentView = parent;
    if (![_window makeFirstResponder:_field]) { [NSException raise:NSInternalInconsistencyException format:@"No field editor"]; }
    _editor = (NSTextView *)_field.currentEditor;
    [_editor setMarkedText:@"composition" selectedRange:NSMakeRange(3, 0) replacementRange:NSMakeRange(NSNotFound, 0)];
    _marked = _editor.markedRange; _selected = _editor.selectedRange;
}
- (void)controlTextDidEndEditing:(NSNotification *)notification { (void)notification; _ended++; }
- (BOOL)verifyFieldFirst:(BOOL)first {
    return _parent.subviews.count == 2 && _parent.subviews[first ? 0 : 1] == _field &&
        _field.superview == _parent && _field.window == _window && _field.currentEditor == _editor &&
        _window.firstResponder == _editor && _editor.hasMarkedText && _ended == 0 &&
        NSEqualRanges(_editor.markedRange, _marked) && NSEqualRanges(_editor.selectedRange, _selected);
}
+ (BOOL)imageView:(NSView *)view red:(NSInteger)red {
    if (![view isKindOfClass:NSImageView.class]) return NO;
    for (NSImageRep *representation in ((NSImageView *)view).image.representations) {
        if (![representation isKindOfClass:NSBitmapImageRep.class]) continue;
        NSBitmapImageRep *bitmap = (NSBitmapImageRep *)representation;
        if (bitmap.pixelsWide != 2 || bitmap.pixelsHigh != 2 ||
            bitmap.bitsPerSample != 8 || bitmap.samplesPerPixel < 3 || bitmap.samplesPerPixel > 4) return NO;
        NSUInteger samples[4] = {0, 0, 0, 0};
        [bitmap getPixel:samples atX:0 y:0];
        return samples[0] == (NSUInteger)red && samples[1] == 17 && samples[2] == 39;
    }
    return NO;
}
- (void)finish { _field.delegate = nil; [_window makeFirstResponder:nil]; _window.contentView = nil; [_window close]; _editor = nil; }
- (void)dealloc { [self finish]; [_parent release]; [_field release]; [_window release]; [super dealloc]; }
@end
