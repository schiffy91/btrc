#import "Text.h"

@implementation BTRCMacOSTextField {
    __weak id<BTRCMacOSTextEvents> _semanticEvents;
}
+ (BTRCMacOSTextField *)fieldWithText:(NSString *)text {
    BTRCMacOSTextField *field = [self textFieldWithString:text];
    field.delegate = field;
    return field;
}
- (void)setSemanticEvents:(id<BTRCMacOSTextEvents>)events { _semanticEvents = events; }
- (id<BTRCMacOSTextEvents>)semanticEvents { return _semanticEvents; }
- (NSString *)liveText { NSText *editor = self.currentEditor; return editor ? editor.string : self.stringValue; }
- (BOOL)composing {
    NSText *editor = self.currentEditor;
    return [editor isKindOfClass:NSTextView.class] && [(NSTextView *)editor hasMarkedText];
}
- (void)discardCompositionKeepingText:(NSString *)text {
    NSText *editor = self.currentEditor;
    if ([editor isKindOfClass:NSTextView.class]) {
        NSTextView *view = (NSTextView *)editor;
        [view.inputContext discardMarkedText];
        [view unmarkText];
        view.string = text;
    }
    self.stringValue = text;
}
- (void)replaceText:(NSString *)text {
    [self discardCompositionKeepingText:text];
    [self abortEditing];
    self.stringValue = text;
}
- (BOOL)control:(NSControl *)control textShouldBeginEditing:(NSText *)fieldEditor {
    (void)control; (void)fieldEditor;
    id<BTRCMacOSTextEvents> sink = _semanticEvents;
    return sink && [sink shouldBegin];
}
- (void)controlTextDidChange:(NSNotification *)notification {
    (void)notification; [_semanticEvents changed];
}
- (void)controlTextDidEndEditing:(NSNotification *)notification {
    (void)notification; [_semanticEvents ended];
}
- (BOOL)control:(NSControl *)control textView:(NSTextView *)textView doCommandBySelector:(SEL)selector {
    (void)control; (void)textView;
    int kind = 0;
    if (selector == @selector(insertNewline:)) kind = 1;
    else if (selector == @selector(cancelOperation:)) kind = 2;
    return kind != 0 && [_semanticEvents command:kind];
}
@end
