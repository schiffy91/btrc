#import <AppKit/AppKit.h>

@interface NativeTextFieldProbe : NSObject
+ (BOOL)prepare;
+ (BOOL)matchesFittingWidth:(double)width height:(double)height;
+ (BOOL)mount;
+ (BOOL)replaceSelection;
+ (BOOL)selectionUnchanged;
+ (BOOL)undo;
+ (BOOL)redo;
+ (BOOL)queueKey;
+ (BOOL)finish;
@end
