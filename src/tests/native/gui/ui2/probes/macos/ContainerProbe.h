#import <AppKit/AppKit.h>

/* Test-only inspection and targeted native faults. No method implements a
 * container operation on the provider's behalf. */
@interface UI2ContainerProbe : NSObject
+ (int)indexOf:(NSView *)child inParent:(NSView *)parent;
+ (int)arrangedIndexOf:(NSView *)child inStack:(NSView *)stack;
+ (void)armOrderFaults:(NSView *)parent first:(int)first second:(int)second firstAfter:(bool)firstAfter secondAfter:(bool)secondAfter hideMembership:(bool)hideMembership;
+ (void)armAttachmentFaults:(NSView *)parent child:(NSView *)child first:(int)first second:(int)second firstAfter:(bool)firstAfter secondAfter:(bool)secondAfter;
+ (int)orderCalls;
+ (void)resetFaults;
+ (NSView *)openHost;
+ (NSView *)newField;
+ (void)beginEditing:(NSView *)field;
+ (bool)editorUnchanged;
+ (int)editingNotifications;
+ (void)closeHost;
@end
