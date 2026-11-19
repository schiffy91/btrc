/* The UIKit shim's web view; ../Shim/ShimWeb.h is the contract. The view is
 * the system's WKWebView, placed among the window's other controls.
 *
 * The program's bundle is the origin app://bundle, which a scheme handler
 * serves; the page and the program exchange JSON through a script message
 * handler. Nothing is kept between runs. */
#import "UIKitShimPrivate.h"
#include "../Shim/ShimWeb.h"

#import <WebKit/WebKit.h>

static NSString* const BtrcUIKitWebOrigin = @"app://bundle/";

static NSString* const BtrcUIKitWebBridgeScript = @"window.btrc = { onMessage: null, post: function (value) { window.webkit.messageHandlers.btrc.postMessage(JSON.stringify(value)); } };";

@class BtrcUIKitWebView;

/* What the engine holds on to: its configuration keeps the scheme handler
 * and the message handler for as long as the engine lives, which can be
 * longer than the view. The bridge forwards to the view while there is one
 * and never keeps it. */
@interface BtrcUIKitWebBridge : NSObject <WKURLSchemeHandler, WKScriptMessageHandler, WKNavigationDelegate> {
@public
	BtrcUIKitWebView* owner;
}
@end

@interface BtrcUIKitWebView : UIView {
@public
	BtrcUIKitControl* control;
	WKWebView* web;
	BtrcUIKitWebBridge* bridge;
	/* The bundle: a directory, or files in memory by their path. */
	NSString* directory;
	NSMutableDictionary<NSString*, NSData*>* files;
	/* Origins beyond the bundle that pages may load from and navigate to. */
	NSMutableArray<NSString*>* origins;
	/* Messages for a page that has not finished loading yet. */
	NSMutableArray<NSString*>* waiting;
	BOOL loaded;
}
- (void)serve:(id<WKURLSchemeTask>)task;
- (int)decide:(WKNavigationAction*)action;
- (void)loadFinished;
- (void)closeWeb;
@end

static NSString* btrcUIKitWebType(NSString* path) {
	static const struct {
		NSString* extension;
		NSString* type;
	} types[] = {
		{@".html", @"text/html"}, {@".htm", @"text/html"}, {@".js", @"text/javascript"}, {@".mjs", @"text/javascript"},
		{@".css", @"text/css"}, {@".json", @"application/json"}, {@".svg", @"image/svg+xml"}, {@".png", @"image/png"},
		{@".jpg", @"image/jpeg"}, {@".jpeg", @"image/jpeg"}, {@".gif", @"image/gif"}, {@".webp", @"image/webp"},
		{@".wasm", @"application/wasm"}, {@".txt", @"text/plain"}, {@".woff2", @"font/woff2"},
	};
	for (size_t index = 0; index < sizeof types / sizeof types[0]; index++) {
		if ([path hasSuffix:types[index].extension]) { return types[index].type; }
	}
	return @"application/octet-stream";
}

/* A path from the origin, without the slashes that lead it. */
static NSString* btrcUIKitWebRelative(NSString* path) {
	NSUInteger start = 0;
	while (start < path.length && [path characterAtIndex:start] == '/') { start++; }
	return [path substringFromIndex:start];
}

@implementation BtrcUIKitWebBridge
- (void)webView:(WKWebView*)webView startURLSchemeTask:(id<WKURLSchemeTask>)task {
	(void)webView;
	if (owner != nil) {
		[owner serve:task];
		return;
	}
	@try {
		[task didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCancelled userInfo:nil]];
	} @catch (NSException* abandoned) {
		(void)abandoned;
	}
}

/* Every task is answered before startURLSchemeTask returns: none is left to stop. */
- (void)webView:(WKWebView*)webView stopURLSchemeTask:(id<WKURLSchemeTask>)task {
	(void)webView;
	(void)task;
}

/* The page's window.btrc.post hands over the JSON of its value. */
- (void)userContentController:(WKUserContentController*)controller didReceiveScriptMessage:(WKScriptMessage*)message {
	(void)controller;
	if (owner != nil && owner->control != nil && [message.body isKindOfClass:NSString.class]) { btrcUIKitPushControl(owner->control, BTRC_SHIM_EVENT_CONTROL_WEB_MESSAGE, 0, 0.0, message.body); }
}

/* Every navigation is decided here, at once. */
- (void)webView:(WKWebView*)webView decidePolicyForNavigationAction:(WKNavigationAction*)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
	(void)webView;
	if (owner == nil) {
		decisionHandler(WKNavigationActionPolicyCancel);
		return;
	}
	BtrcUIKitWebView* view = [[owner retain] autorelease];
	NSString* address = action.request.URL.absoluteString;
	int outcome = [view decide:action];
	decisionHandler(outcome == BTRC_SHIM_WEB_NAVIGATION_ALLOWED ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
	/* Only what a page shows is a navigation: a frame within it is not. */
	if (view->control != nil && (action.targetFrame == nil || action.targetFrame.isMainFrame)) { btrcUIKitPushControl(view->control, BTRC_SHIM_EVENT_CONTROL_WEB_NAVIGATION, outcome, 0.0, address != nil ? address : @""); }
}

- (void)webView:(WKWebView*)webView didStartProvisionalNavigation:(WKNavigation*)navigation {
	(void)webView;
	(void)navigation;
	if (owner != nil) { owner->loaded = NO; }
}

- (void)webView:(WKWebView*)webView didFinishNavigation:(WKNavigation*)navigation {
	(void)webView;
	(void)navigation;
	[owner loadFinished];
}

/* A load that failed is over too: what was posted goes to the page there is. */
- (void)webView:(WKWebView*)webView didFailProvisionalNavigation:(WKNavigation*)navigation withError:(NSError*)error {
	(void)webView;
	(void)navigation;
	(void)error;
	[owner loadFinished];
}

- (void)webView:(WKWebView*)webView didFailNavigation:(WKNavigation*)navigation withError:(NSError*)error {
	(void)webView;
	(void)navigation;
	(void)error;
	[owner loadFinished];
}
@end

@implementation BtrcUIKitWebView
- (instancetype)initWithFrame:(CGRect)frame {
	self = [super initWithFrame:frame];
	if (self == nil) { return nil; }
	files = [[NSMutableDictionary alloc] init];
	origins = [[NSMutableArray alloc] init];
	waiting = [[NSMutableArray alloc] init];
	bridge = [[BtrcUIKitWebBridge alloc] init];
	bridge->owner = self;
	/* Its own configuration, so that app: means this view's bundle and no
	 * other's, and a store that keeps nothing. */
	WKWebViewConfiguration* configuration = [[WKWebViewConfiguration alloc] init];
	configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
	[configuration setURLSchemeHandler:bridge forURLScheme:@"app"];
	WKUserScript* script = [[WKUserScript alloc] initWithSource:BtrcUIKitWebBridgeScript injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:YES];
	[configuration.userContentController addUserScript:script];
	[script release];
	[configuration.userContentController addScriptMessageHandler:bridge name:@"btrc"];
	web = [[WKWebView alloc] initWithFrame:self.bounds configuration:configuration];
	[configuration release];
	web.navigationDelegate = bridge;
	web.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
	/* The page is the program's interface, placed by the program: it does
	 * not slide under the bars by itself. */
	web.scrollView.contentInsetAdjustmentBehavior = UIScrollViewContentInsetAdjustmentNever;
	[self addSubview:web];
	return self;
}

- (void)dealloc {
	[self closeWeb];
	[bridge release];
	[directory release];
	[files release];
	[origins release];
	[waiting release];
	[super dealloc];
}

/* The bundle's file at a path from the origin, or nil. A directory bundle
 * serves only what lies inside it: a path that climbs out names nothing. */
- (NSData*)fileAtPath:(NSString*)path {
	NSString* relative = btrcUIKitWebRelative(path);
	if (directory == nil) { return files[relative]; }
	NSMutableArray<NSString*>* inside = [NSMutableArray array];
	for (NSString* part in [relative componentsSeparatedByString:@"/"]) {
		if (part.length == 0u || [part isEqualToString:@"."]) { continue; }
		if (![part isEqualToString:@".."]) {
			[inside addObject:part];
		} else if (inside.count == 0u) {
			return nil;
		} else {
			[inside removeLastObject];
		}
	}
	if (inside.count == 0u) { return nil; }
	return [NSData dataWithContentsOfFile:[directory stringByAppendingPathComponent:[inside componentsJoinedByString:@"/"]]];
}

/* What a page of the bundle may load: the bundle, itself, and the origins
 * the program allowed. Everything else the engine refuses. */
- (NSString*)policy {
	NSMutableString* policy = [NSMutableString stringWithString:@"default-src app://bundle 'unsafe-inline' 'unsafe-eval' data: blob:"];
	for (NSString* origin in origins) { [policy appendFormat:@" %@", origin]; }
	return policy;
}

- (void)serve:(id<WKURLSchemeTask>)task {
	NSURL* address = task.request.URL;
	NSString* path = address.path;
	NSData* file = (path != nil && [address.absoluteString hasPrefix:BtrcUIKitWebOrigin]) ? [self fileAtPath:path] : nil;
	NSHTTPURLResponse* response = nil;
	if (file != nil) {
		NSDictionary<NSString*, NSString*>* headers = @{
			@"Content-Type" : btrcUIKitWebType(path),
			@"Content-Length" : [NSString stringWithFormat:@"%lu", (unsigned long)file.length],
			@"Content-Security-Policy" : [self policy],
			@"Cache-Control" : @"no-store",
		};
		response = [[[NSHTTPURLResponse alloc] initWithURL:address statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:headers] autorelease];
	}
	/* A task the engine has already given up raises when it is answered. */
	@try {
		if (response == nil) {
			[task didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorFileDoesNotExist userInfo:nil]];
		} else {
			[task didReceiveResponse:response];
			[task didReceiveData:file];
			[task didFinish];
		}
	} @catch (NSException* abandoned) {
		(void)abandoned;
	}
}

- (BOOL)reaches:(NSString*)address {
	if ([address hasPrefix:BtrcUIKitWebOrigin] || [address isEqualToString:@"about:blank"]) { return YES; }
	for (NSString* origin in origins) {
		if ([address hasPrefix:origin] && (address.length == origin.length || [address characterAtIndex:origin.length] == '/')) { return YES; }
	}
	return NO;
}

/* Inside the bundle or to an allowed origin a navigation goes ahead. Anywhere
 * else it does not, and neither does one that asks for a new window; a link
 * a person tapped is handed to the system, which opens it in a browser. */
- (int)decide:(WKNavigationAction*)action {
	NSURL* address = action.request.URL;
	NSString* text = address.absoluteString;
	if (text == nil) { return BTRC_SHIM_WEB_NAVIGATION_REFUSED; }
	if (action.targetFrame != nil && [self reaches:text]) { return BTRC_SHIM_WEB_NAVIGATION_ALLOWED; }
	if (action.navigationType == WKNavigationTypeLinkActivated && ([text hasPrefix:@"https://"] || [text hasPrefix:@"http://"])) {
		[UIApplication.sharedApplication openURL:address options:@{} completionHandler:nil];
		return BTRC_SHIM_WEB_NAVIGATION_HANDED_TO_SYSTEM;
	}
	return BTRC_SHIM_WEB_NAVIGATION_REFUSED;
}

- (void)deliver:(NSString*)json {
	NSString* script = [NSString stringWithFormat:@"if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(%@); }", json];
	[web evaluateJavaScript:script completionHandler:nil];
}

- (void)loadFinished {
	loaded = YES;
	NSArray<NSString*>* pending = [[waiting copy] autorelease];
	[waiting removeAllObjects];
	for (NSString* json in pending) { [self deliver:json]; }
}

- (void)loadEntryPath:(NSString*)entryPath {
	NSString* text = [BtrcUIKitWebOrigin stringByAppendingString:btrcUIKitWebRelative(entryPath)];
	NSURL* address = [NSURL URLWithString:text];
	if (address == nil) {
		NSString* escaped = [text stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLQueryAllowedCharacterSet];
		address = escaped != nil ? [NSURL URLWithString:escaped] : nil;
	}
	loaded = NO;
	[waiting removeAllObjects];
	if (address != nil) { [web loadRequest:[NSURLRequest requestWithURL:address]]; }
}

- (void)postMessage:(NSString*)json {
	if (loaded) {
		[self deliver:json];
	} else {
		[waiting addObject:[[json copy] autorelease]];
	}
}

- (void)closeWeb {
	if (web == nil) { return; }
	bridge->owner = nil;
	control = nil;
	[web stopLoading];
	web.navigationDelegate = nil;
	[web.configuration.userContentController removeScriptMessageHandlerForName:@"btrc"];
	[web removeFromSuperview];
	[web release];
	web = nil;
	[waiting removeAllObjects];
}
@end

static BtrcUIKitWebView* btrcUIKitWeb(BtrcShimControl* handle) { return (BtrcUIKitWebView*)btrcUIKitControl(handle)->view; }

BtrcShimControl* btrcShimWebCreate(unsigned int id) {
	__block BtrcShimControl* made = NULL;
	btrcUIKitOnMain(^{
		BtrcUIKitWebView* view = [[BtrcUIKitWebView alloc] initWithFrame:CGRectZero];
		if (view == nil) { return; }
		made = btrcUIKitControlAdopt(BTRC_UIKIT_WEB, id, view);
		view->control = btrcUIKitControl(made);
		[view release];
	});
	if (made == NULL) { btrcUIKitFail("the system has no web view"); }
	return made;
}

void btrcShimWebServeDirectory(BtrcShimControl* handle, const char* directory) {
	NSString* path = btrcUIKitString(directory);
	btrcUIKitOnMain(^{
		BtrcUIKitWebView* view = btrcUIKitWeb(handle);
		[view->files removeAllObjects];
		[view->directory release];
		view->directory = [path copy];
	});
	[path release];
}

void btrcShimWebServeFiles(BtrcShimControl* handle) {
	btrcUIKitOnMain(^{
		BtrcUIKitWebView* view = btrcUIKitWeb(handle);
		[view->files removeAllObjects];
		[view->directory release];
		view->directory = nil;
	});
}

void btrcShimWebServeFile(BtrcShimControl* handle, const char* path, const unsigned char* bytes, unsigned long long length) {
	NSString* name = btrcUIKitString(path);
	btrcUIKitOnMain(^{ btrcUIKitWeb(handle)->files[btrcUIKitWebRelative(name)] = [NSData dataWithBytes:bytes length:(NSUInteger)length]; });
	[name release];
}

void btrcShimWebAllowOrigin(BtrcShimControl* handle, const char* origin) {
	NSString* allowed = btrcUIKitString(origin);
	btrcUIKitOnMain(^{ [btrcUIKitWeb(handle)->origins addObject:allowed]; });
	[allowed release];
}

void btrcShimWebLoad(BtrcShimControl* handle, const char* entryPath) {
	NSString* path = btrcUIKitString(entryPath);
	btrcUIKitOnMain(^{ [btrcUIKitWeb(handle) loadEntryPath:path]; });
	[path release];
}

void btrcShimWebPost(BtrcShimControl* handle, const char* json) {
	NSString* value = btrcUIKitString(json);
	btrcUIKitOnMain(^{ [btrcUIKitWeb(handle) postMessage:value]; });
	[value release];
}
