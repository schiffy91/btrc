/* The provider's web view; AppKitWeb.h is the contract.
 *
 * Native sources are compiled without ARC, so this file retains and releases
 * what it keeps. */
#import "AppKitWeb.h"
#import <WebKit/WebKit.h>
#import <objc/message.h>

static NSString *const BtrcWebOrigin = @"app://bundle/";

static NSString *const BtrcWebBridgeScript =
	@"window.btrc = { onMessage: null, post: function (value) { window.webkit.messageHandlers.btrc.postMessage(JSON.stringify(value)); } };";

/* One report waiting to be taken. */
@interface BtrcWebEvent : NSObject {
@public
	BtrcWebEventKind kind;
	BtrcWebNavigation outcome;
	NSString *text;
}
@end

@implementation BtrcWebEvent
- (void)dealloc {
	[text release];
	[super dealloc];
}
@end

/* The engine's view. A page that is the program's interface answers the
 * first click in a window that is not the key window, as a button does. */
@interface BtrcWebContent : WKWebView
@end

@implementation BtrcWebContent
- (BOOL)acceptsFirstMouse:(NSEvent *)event {
	(void)event;
	return YES;
}
@end

@interface BtrcWebView ()
- (void)serve:(id<WKURLSchemeTask>)task;
- (BtrcWebNavigation)decide:(WKNavigationAction *)action;
- (void)report:(BtrcWebEventKind)kind outcome:(BtrcWebNavigation)outcome text:(NSString *)text;
- (void)loadStarted;
- (void)loadFinished;
@end

/* What the engine holds on to: its configuration keeps the scheme handler and
 * the message handler for as long as the engine lives, which can be longer
 * than the view. The bridge forwards to the view while there is one and never
 * keeps it. */
@interface BtrcWebBridge : NSObject <WKURLSchemeHandler, WKScriptMessageHandler, WKNavigationDelegate> {
@public
	BtrcWebView *owner;
}
@end

@implementation BtrcWebBridge
- (void)webView:(WKWebView *)webView startURLSchemeTask:(id<WKURLSchemeTask>)task {
	(void)webView;
	if (owner) {
		[owner serve:task];
		return;
	}
	@try {
		[task didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorCancelled userInfo:nil]];
	} @catch (NSException *abandoned) {
		(void)abandoned;
	}
}

/* Every task is answered before startURLSchemeTask returns: none is left to stop. */
- (void)webView:(WKWebView *)webView stopURLSchemeTask:(id<WKURLSchemeTask>)task {
	(void)webView;
	(void)task;
}

/* The page's window.btrc.post hands over the JSON of its value. */
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
	(void)controller;
	if ([message.body isKindOfClass:[NSString class]]) {
		[owner report:BtrcWebEventMessage outcome:BtrcWebNavigationAllowed text:message.body];
	}
}

/* Every navigation is decided here, at once. */
- (void)webView:(WKWebView *)webView
	decidePolicyForNavigationAction:(WKNavigationAction *)action
	                decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
	(void)webView;
	if (!owner) {
		decisionHandler(WKNavigationActionPolicyCancel);
		return;
	}
	BtrcWebView *view = [[owner retain] autorelease];
	NSString *address = action.request.URL.absoluteString;
	BtrcWebNavigation outcome = [view decide:action];
	decisionHandler(outcome == BtrcWebNavigationAllowed ? WKNavigationActionPolicyAllow : WKNavigationActionPolicyCancel);
	[view report:BtrcWebEventNavigation outcome:outcome text:address ? address : @""];
}

- (void)webView:(WKWebView *)webView didStartProvisionalNavigation:(WKNavigation *)navigation {
	(void)webView;
	(void)navigation;
	[owner loadStarted];
}

- (void)webView:(WKWebView *)webView didFinishNavigation:(WKNavigation *)navigation {
	(void)webView;
	(void)navigation;
	[owner loadFinished];
}

/* A load that failed is over too: what was posted goes to the page there is. */
- (void)webView:(WKWebView *)webView didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
	(void)webView;
	(void)navigation;
	(void)error;
	[owner loadFinished];
}

- (void)webView:(WKWebView *)webView didFailNavigation:(WKNavigation *)navigation withError:(NSError *)error {
	(void)webView;
	(void)navigation;
	(void)error;
	[owner loadFinished];
}
@end

static NSString *btrcWebType(NSString *path) {
	static const struct {
		NSString *extension;
		NSString *type;
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
static NSString *btrcWebRelative(NSString *path) {
	NSUInteger start = 0;
	while (start < path.length && [path characterAtIndex:start] == '/') { start++; }
	return [path substringFromIndex:start];
}

@implementation BtrcWebView {
	WKWebView *_web;
	BtrcWebBridge *_bridge;
	/* The bundle: a directory, or files in memory by their path. */
	NSString *_directory;
	NSMutableDictionary<NSString *, NSData *> *_files;
	/* Origins beyond the bundle that pages may load from and navigate to. */
	NSMutableArray<NSString *> *_origins;
	/* Messages for a page that has not finished loading yet. */
	NSMutableArray<NSString *> *_waiting;
	BOOL _loaded;
	/* What the engine reported and nobody has taken, oldest first, and the
	 * event taken last. */
	NSMutableArray<BtrcWebEvent *> *_events;
	BtrcWebEvent *_taken;
}

- (instancetype)initWithFrame:(NSRect)frame {
	self = [super initWithFrame:frame];
	if (!self) { return nil; }
	_files = [[NSMutableDictionary alloc] init];
	_origins = [[NSMutableArray alloc] init];
	_waiting = [[NSMutableArray alloc] init];
	_events = [[NSMutableArray alloc] init];
	_bridge = [[BtrcWebBridge alloc] init];
	_bridge->owner = self;
	/* Its own configuration, so that app: means this view's bundle and no
	 * other's, and a store that keeps nothing. */
	WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
	configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
	[configuration setURLSchemeHandler:_bridge forURLScheme:@"app"];
	WKUserScript *script = [[WKUserScript alloc] initWithSource:BtrcWebBridgeScript
	                                              injectionTime:WKUserScriptInjectionTimeAtDocumentStart
	                                           forMainFrameOnly:YES];
	[configuration.userContentController addUserScript:script];
	[script release];
	[configuration.userContentController addScriptMessageHandler:_bridge name:@"btrc"];
	_web = [[BtrcWebContent alloc] initWithFrame:self.bounds configuration:configuration];
	[configuration release];
	_web.navigationDelegate = _bridge;
	_web.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
	[self addSubview:_web];
	return self;
}

- (void)dealloc {
	[self closeWeb];
	[_bridge release];
	[_directory release];
	[_files release];
	[_origins release];
	[_waiting release];
	[_events release];
	[super dealloc];
}

/* The engine fills the view, whatever size the view had before. */
- (void)resizeSubviewsWithOldSize:(NSSize)oldSize {
	(void)oldSize;
	_web.frame = self.bounds;
}

- (void)serveDirectory:(NSString *)directory {
	[_files removeAllObjects];
	[_directory release];
	_directory = [directory copy];
}

- (void)serveFiles {
	[_files removeAllObjects];
	[_directory release];
	_directory = nil;
}

- (void)serveFile:(NSString *)path bytes:(const void *)bytes length:(NSUInteger)length {
	_files[btrcWebRelative(path)] = [NSData dataWithBytes:bytes length:length];
}

- (void)allowOrigin:(NSString *)origin {
	[_origins addObject:[[origin copy] autorelease]];
}

/* The bundle's file at a path from the origin, or nil. A directory bundle
 * serves only what lies inside it: a path that climbs out names nothing. */
- (nullable NSData *)fileAtPath:(NSString *)path {
	NSString *relative = btrcWebRelative(path);
	if (!_directory) { return _files[relative]; }
	NSMutableArray<NSString *> *inside = [NSMutableArray array];
	for (NSString *part in [relative componentsSeparatedByString:@"/"]) {
		if (part.length == 0 || [part isEqualToString:@"."]) { continue; }
		if (![part isEqualToString:@".."]) {
			[inside addObject:part];
		} else if (inside.count == 0) {
			return nil;
		} else {
			[inside removeLastObject];
		}
	}
	if (inside.count == 0) { return nil; }
	return [NSData dataWithContentsOfFile:[_directory stringByAppendingPathComponent:[inside componentsJoinedByString:@"/"]]];
}

/* What a page of the bundle may load: the bundle, itself, and the origins
 * the program allowed. Everything else the engine refuses. */
- (NSString *)policy {
	NSMutableString *policy = [NSMutableString stringWithString:@"default-src app://bundle 'unsafe-inline' 'unsafe-eval' data: blob:"];
	for (NSString *origin in _origins) { [policy appendFormat:@" %@", origin]; }
	return policy;
}

- (void)serve:(id<WKURLSchemeTask>)task {
	NSURL *address = task.request.URL;
	NSString *path = address.path;
	NSData *file = (path && [address.absoluteString hasPrefix:BtrcWebOrigin]) ? [self fileAtPath:path] : nil;
	NSHTTPURLResponse *response = nil;
	if (file) {
		NSDictionary<NSString *, NSString *> *headers = @{
			@"Content-Type" : btrcWebType(path),
			@"Content-Length" : [NSString stringWithFormat:@"%lu", (unsigned long)file.length],
			@"Content-Security-Policy" : [self policy],
		};
		response = [[[NSHTTPURLResponse alloc] initWithURL:address statusCode:200 HTTPVersion:@"HTTP/1.1" headerFields:headers] autorelease];
	}
	if (!response) {
		@try {
			[task didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorFileDoesNotExist userInfo:nil]];
		} @catch (NSException *abandoned) {
			(void)abandoned;
		}
		return;
	}
	/* A task the engine has already given up raises when it is answered. */
	@try {
		[task didReceiveResponse:response];
		[task didReceiveData:file];
		[task didFinish];
	} @catch (NSException *abandoned) {
		(void)abandoned;
	}
}

- (BOOL)reaches:(NSString *)address {
	if ([address hasPrefix:BtrcWebOrigin] || [address isEqualToString:@"about:blank"]) { return YES; }
	for (NSString *origin in _origins) {
		if ([address hasPrefix:origin] && (address.length == origin.length || [address characterAtIndex:origin.length] == '/')) { return YES; }
	}
	return NO;
}

/* Inside the bundle or to an allowed origin a navigation goes ahead. Anywhere
 * else it does not, and neither does one that asks for a new window; a link a
 * person clicked is handed to the system, which opens it in a browser. */
- (BtrcWebNavigation)decide:(WKNavigationAction *)action {
	NSURL *address = action.request.URL;
	NSString *text = address.absoluteString;
	if (!text) { return BtrcWebNavigationRefused; }
	if (action.targetFrame && [self reaches:text]) { return BtrcWebNavigationAllowed; }
	/* A link a person clicked, and nothing a script did: a click a script
	 * makes up has no mouse button behind it. */
	BOOL clicked = action.navigationType == WKNavigationTypeLinkActivated && action.buttonNumber != 0;
	if (clicked && ([text hasPrefix:@"https://"] || [text hasPrefix:@"http://"])) {
		[NSWorkspace.sharedWorkspace openURL:address];
		return BtrcWebNavigationHandedToSystem;
	}
	return BtrcWebNavigationRefused;
}

- (void)deliver:(NSString *)json {
	NSString *script = [NSString stringWithFormat:@"if (window.btrc && typeof window.btrc.onMessage === 'function') { window.btrc.onMessage(%@); }", json];
	[_web evaluateJavaScript:script completionHandler:nil];
}

- (void)loadStarted {
	_loaded = NO;
}

- (void)loadFinished {
	_loaded = YES;
	NSArray<NSString *> *waiting = [[_waiting copy] autorelease];
	[_waiting removeAllObjects];
	for (NSString *json in waiting) { [self deliver:json]; }
}

- (void)loadEntryPath:(NSString *)entryPath {
	NSString *text = [BtrcWebOrigin stringByAppendingString:btrcWebRelative(entryPath)];
	NSURL *address = [NSURL URLWithString:text];
	if (!address) {
		NSString *escaped = [text stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLQueryAllowedCharacterSet];
		address = escaped ? [NSURL URLWithString:escaped] : nil;
	}
	_loaded = NO;
	[_waiting removeAllObjects];
	if (address) { [_web loadRequest:[NSURLRequest requestWithURL:address]]; }
}

- (void)postMessage:(NSString *)json {
	if (_loaded) {
		[self deliver:json];
	} else {
		[_waiting addObject:[[json copy] autorelease]];
	}
}

- (void)report:(BtrcWebEventKind)kind outcome:(BtrcWebNavigation)outcome text:(NSString *)text {
	if (!_web || !_target || !_action) { return; }
	BtrcWebEvent *event = [[BtrcWebEvent alloc] init];
	event->kind = kind;
	event->outcome = outcome;
	event->text = [text copy];
	[_events addObject:event];
	[event release];
	[[self retain] autorelease];
	((void (*)(id, SEL, id))objc_msgSend)(_target, _action, self);
}

- (BOOL)takeEvent {
	[_taken release];
	_taken = nil;
	if (_events.count == 0) { return NO; }
	_taken = [_events[0] retain];
	[_events removeObjectAtIndex:0];
	return YES;
}

- (BtrcWebEventKind)eventKind {
	return _taken ? _taken->kind : BtrcWebEventNone;
}

- (BtrcWebNavigation)eventOutcome {
	return _taken ? _taken->outcome : BtrcWebNavigationRefused;
}

- (NSString *)eventText {
	return _taken ? [[_taken->text retain] autorelease] : @"";
}

- (void)closeWeb {
	if (!_web) { return; }
	_bridge->owner = nil;
	[_web stopLoading];
	_web.navigationDelegate = nil;
	[_web.configuration.userContentController removeScriptMessageHandlerForName:@"btrc"];
	[_web removeFromSuperview];
	[_web release];
	_web = nil;
	[_waiting removeAllObjects];
	[_events removeAllObjects];
	[_taken release];
	_taken = nil;
}
@end
