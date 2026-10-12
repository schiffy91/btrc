#import <AppKit/AppKit.h>

/* Test-only inspection and targeted native faults. No method implements a
 * container operation on the provider's behalf. */
@interface UI2ContainerProbe : NSObject
+ (int)childCount:(NSView *)parent;
+ (int)arrangedCount:(NSView *)stack;
+ (void)observeMutations:(NSView *)parent;
+ (int)indexOf:(NSView *)child inParent:(NSView *)parent;
+ (int)arrangedIndexOf:(NSView *)child inStack:(NSView *)stack;
+ (void)armOrderFaults:(NSView *)parent first:(int)first second:(int)second firstAfter:(bool)firstAfter secondAfter:(bool)secondAfter hideMembership:(bool)hideMembership;
+ (void)armAttachmentFaults:(NSView *)parent child:(NSView *)child first:(int)first second:(int)second firstAfter:(bool)firstAfter secondAfter:(bool)secondAfter;
+ (int)orderCalls;
+ (void)resetFaults;
+ (NSView *)openHost;
+ (NSView *)newField;
+ (NSView *)newInputView;
+ (NSView *)newPlainView;
+ (NSView *)addUnarrangedChild:(NSView *)stack;
+ (void)removeForeignChild:(NSView *)child;
+ (NSEvent *)primaryDown:(NSView *)view;
+ (void)beginEditing:(NSView *)field;
+ (bool)editorUnchanged;
+ (int)editingNotifications;
+ (void)closeHost;
@end
