/* Keep the UIKit launch handshake responsive while the C fixture waits for
 * its executor's acknowledgement. Only trusted, child-free fixtures run here. */
#import <UIKit/UIKit.h>
#include <stdlib.h>

int btrc_fixture_host_main(int argc, char **argv);
static int fixtureArgc;
static char **fixtureArgv;

@interface BTRCTestHostDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end

@implementation BTRCTestHostDelegate
- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application;
    (void)options;
    self.window = [[UIWindow alloc] initWithFrame:CGRectMake(0, 0, 1, 1)];
    self.window.rootViewController = [[UIViewController alloc] init];
    [self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        exit(btrc_fixture_host_main(fixtureArgc, fixtureArgv));
    });
    return YES;
}
@end

int main(int argc, char **argv) {
    fixtureArgc = argc;
    fixtureArgv = argv;
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([BTRCTestHostDelegate class]));
    }
}
