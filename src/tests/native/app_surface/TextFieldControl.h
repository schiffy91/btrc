#import <AppKit/AppKit.h>

@interface NativeTextFieldProbe : NSObject
+ (void)prepare:(NSWindow * _Nonnull)window;
+ (BOOL)mount:(NSTextField * _Nonnull)field;
+ (BOOL)replaceSelection;
+ (BOOL)selectionUnchanged;
+ (BOOL)undo;
+ (BOOL)redo;
+ (BOOL)queueKey;
+ (BOOL)finish:(NSTextField * _Nonnull)field;
@end
