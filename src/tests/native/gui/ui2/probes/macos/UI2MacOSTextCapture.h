#import "UI2MacOSTextField.h"
@interface BTRCUI2TextCaptureProbe : NSObject
+ (NSWindow *)host:(NSTextField *)first second:(NSTextField *)second;
+ (BOOL)focus:(NSTextField *)field route:(NSInteger)route;
+ (void)failFocus:(NSTextField *)field;
@end
