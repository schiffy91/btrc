#import <AppKit/AppKit.h>

@interface StackProbe : NSObject
+ (void)verifyLayout:(double)width;
+ (void)beginEditing;
+ (void)verifyEditing;
+ (void)undoEditing;
+ (void)observeViews;
+ (NSInteger)remainingViews;
+ (void)reset;
+ (NSView *)contentView;
+ (void)verifyDetachedButton;
+ (void)verifyHiddenButton;
@end
