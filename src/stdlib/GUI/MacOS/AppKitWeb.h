#ifndef BTRC_APPKIT_WEB_H
#define BTRC_APPKIT_WEB_H
/* The provider's web view: an AppKit view that owns a WKWebView filling it,
 * placed among the window's other views like any of them. It is bound and
 * linked only by programs that import the web view, which is why it is a
 * module of its own: WebKit is a large framework. This header names AppKit
 * alone; the engine stays inside AppKitWeb.m.
 *
 * A web view serves one bundle of files under the private origin
 * app://bundle/ and loads nothing from anywhere else, unless the program
 * allows an origin. Its storage is not kept. The page and the program
 * exchange JSON messages; neither calls into the other.
 *
 * What the engine reports waits here, in order, until the program takes it.
 * Each report sends `action` to `target` on the main thread, with the view as
 * the sender, as a control does; with no target, a report is not kept. */
#import <AppKit/AppKit.h>

NS_ASSUME_NONNULL_BEGIN

/* What a taken event is. */
typedef NS_ENUM(NSInteger, BtrcWebEventKind) {
	BtrcWebEventNone = 0,
	/* Its text is the JSON of a value the page passed to window.btrc.post. */
	BtrcWebEventMessage = 1,
	/* Its text is the address of a navigation; its outcome is what became of it. */
	BtrcWebEventNavigation = 2
};

/* What became of a navigation. */
typedef NS_ENUM(NSInteger, BtrcWebNavigation) {
	/* Inside the bundle or to an allowed origin: it went ahead. */
	BtrcWebNavigationAllowed = 0,
	/* Somewhere else, and not a person's doing: nothing happened. */
	BtrcWebNavigationRefused = 1,
	/* Somewhere else, by a person's click: the system's handler for the
	 * address (a browser) was asked to open it. */
	BtrcWebNavigationHandedToSystem = 2
};

@interface BtrcWebView : NSView
@property(nonatomic, assign, nullable) id target;
@property(nonatomic, assign, nullable) SEL action;
/* The bundle is this directory's files, */
- (void)serveDirectory:(NSString *)directory;
/* or these files, each added under its path from the origin (copied). Either
 * replaces what was served before. */
- (void)serveFiles;
- (void)serveFile:(NSString *)path bytes:(nullable const void *)bytes length:(NSUInteger)length;
/* Let pages load from, and navigate to, this origin too ("https://host"). */
- (void)allowOrigin:(NSString *)origin;
/* Show the bundle's file at this path from the origin. */
- (void)loadEntryPath:(NSString *)entryPath;
/* Hand the page a JSON value: window.btrc.onMessage is called with it, once
 * the page has loaded. */
- (void)postMessage:(NSString *)json;
/* Take the oldest event that has not been taken; NO when there is none. The
 * three readers describe the event taken last. */
- (BOOL)takeEvent;
- (BtrcWebEventKind)eventKind;
- (BtrcWebNavigation)eventOutcome;
- (NSString *)eventText;
/* Stop the engine and forget what it reported. The view reports nothing
 * afterwards. */
- (void)closeWeb;
@end

NS_ASSUME_NONNULL_END
#endif
