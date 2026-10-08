#import "Text.h"

@implementation BTRCMacOSTextField {
    /* Handwritten native units use MRC. This container owns no sink: the
     * generated CallbackScope registration remains its sole lifetime owner. */
    NSHashTable<id<BTRCMacOSTextEvents>> *_semanticEvents;
}
+ (BTRCMacOSTextField *)fieldWithText:(NSString *)text {
    BTRCMacOSTextField *field = [self textFieldWithString:text];
    field.delegate = field;
    return field;
}
- (void)setSemanticEvents:(id<BTRCMacOSTextEvents>)events {
    if (events && !_semanticEvents) {
        _semanticEvents = [[NSHashTable alloc]
            initWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality
                   capacity:1];
        if (!_semanticEvents) {
            [NSException raise:NSMallocException format:@"Cannot allocate native text event slot"];
        }
    }
    [_semanticEvents removeAllObjects];
    if (events) { [_semanticEvents addObject:events]; }
}
- (id<BTRCMacOSTextEvents>)semanticEvents {
    /* Retain the selected weak object through its synchronous callback and the
     * surrounding generated adapter's autorelease pool. */
    return [[[_semanticEvents anyObject] retain] autorelease];
}
- (void)dealloc {
    [_semanticEvents release];
    [super dealloc];
}
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
    id<BTRCMacOSTextEvents> sink = [self semanticEvents];
    return sink && [sink shouldBegin];
}
- (void)controlTextDidChange:(NSNotification *)notification {
    (void)notification; [[self semanticEvents] changed];
}
- (void)controlTextDidEndEditing:(NSNotification *)notification {
    (void)notification; [[self semanticEvents] ended];
}
- (BOOL)control:(NSControl *)control textView:(NSTextView *)textView doCommandBySelector:(SEL)selector {
    (void)control; (void)textView;
    int kind = 0;
    if (selector == @selector(insertNewline:)) kind = 1;
    else if (selector == @selector(cancelOperation:)) kind = 2;
    return kind != 0 && [[self semanticEvents] command:kind];
}
@end
