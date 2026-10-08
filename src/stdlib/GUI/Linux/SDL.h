/* SDL3 windowing for the Linux GUI provider. The manifest binds ordinary SDL
 * functions directly; this header keeps only what the typed importer cannot
 * express, each for its stated reason:
 * - SDL_Event is a union, so btrcSdlPollEvent/WaitEvent flatten it and the
 *   btrcSdlPush* helpers build one (synthetic input for automation/tests);
 * - the folder dialog's callback may run on another thread, so its
 *   transaction (atomic state, two owners) lives on the C side. */
#include <SDL3/SDL.h>
#include <stdlib.h>
#include <string.h>

typedef struct BtrcSdlEvent {
	unsigned int type;
	unsigned int window;
	float x;
	float y;
	float wheelX;
	float wheelY;
	unsigned int button;
	unsigned int clicks;
	unsigned int scancode;
	unsigned int key;
	unsigned int modifiers;
	int data1;
	int data2;
	int down;
	int repeat;
	const char* text;
} BtrcSdlEvent;

/* Synthetic text events point into this ring (see btrcSdlPushText). */
static char btrcSdlTextRing[16][64];
static unsigned int btrcSdlTextRingPushed = 0u;
static unsigned int btrcSdlTextRingTaken = 0u;

static inline void btrcSdlFlatten(const SDL_Event* source, BtrcSdlEvent* out) {
	memset(out, 0, sizeof(*out));
	out->type = source->type;
	if (source->type >= SDL_EVENT_WINDOW_FIRST && source->type <= SDL_EVENT_WINDOW_LAST) {
		out->window = source->window.windowID;
		out->data1 = source->window.data1;
		out->data2 = source->window.data2;
	} else if (source->type == SDL_EVENT_MOUSE_MOTION) {
		out->window = source->motion.windowID;
		out->x = source->motion.x;
		out->y = source->motion.y;
		out->button = source->motion.state;
	} else if (source->type == SDL_EVENT_MOUSE_BUTTON_DOWN || source->type == SDL_EVENT_MOUSE_BUTTON_UP) {
		out->window = source->button.windowID;
		out->x = source->button.x;
		out->y = source->button.y;
		out->button = source->button.button;
		out->clicks = source->button.clicks;
		out->down = source->button.down ? 1 : 0;
	} else if (source->type == SDL_EVENT_MOUSE_WHEEL) {
		out->window = source->wheel.windowID;
		out->x = source->wheel.mouse_x;
		out->y = source->wheel.mouse_y;
		float flip = source->wheel.direction == SDL_MOUSEWHEEL_FLIPPED ? -1.0f : 1.0f;
		out->wheelX = source->wheel.x * flip;
		out->wheelY = source->wheel.y * flip;
	} else if (source->type == SDL_EVENT_KEY_DOWN || source->type == SDL_EVENT_KEY_UP) {
		out->window = source->key.windowID;
		out->scancode = (unsigned int)source->key.scancode;
		out->key = (unsigned int)source->key.key;
		out->modifiers = (unsigned int)source->key.mod;
		out->down = source->key.down ? 1 : 0;
		out->repeat = source->key.repeat ? 1 : 0;
	} else if (source->type == SDL_EVENT_TEXT_EDITING) {
		out->window = source->edit.windowID;
		out->text = source->edit.text;
		out->data1 = source->edit.start;
		out->data2 = source->edit.length;
	} else if (source->type == SDL_EVENT_TEXT_INPUT) {
		out->window = source->text.windowID;
		out->text = source->text.text;
		for (int slot = 0; slot < 16; slot++) { if (source->text.text == btrcSdlTextRing[slot]) { btrcSdlTextRingTaken++; break; } }
	}
}

/* Poll one event; the text pointer is valid only until the next poll. */
static inline int btrcSdlPollEvent(BtrcSdlEvent* out) {
	SDL_Event event;
	if (!SDL_PollEvent(&event)) { return 0; }
	btrcSdlFlatten(&event, out);
	return 1;
}

static inline int btrcSdlWaitEvent(BtrcSdlEvent* out, int timeoutMilliseconds) {
	SDL_Event event;
	if (!SDL_WaitEventTimeout(&event, timeoutMilliseconds)) { return 0; }
	btrcSdlFlatten(&event, out);
	return 1;
}

/* SDL owns this thread-safe native wake; rejection is never hidden. */
static inline bool btrcSdlPushWake(void) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = SDL_EVENT_USER;
	return SDL_PushEvent(&event);
}

/* One folder-dialog transaction. SDL may deliver the callback on another
 * thread (the zenity backend does), so the result is published through an
 * atomic state after the path is written, and the transaction has two owners:
 * the caller and the pending callback. Whichever releases last frees it, so a
 * caller that stops waiting never leaves SDL a dangling userdata. */
typedef struct BtrcSdlFolderDialog {
	SDL_AtomicInt state;
	SDL_AtomicInt owners;
	char* path;
} BtrcSdlFolderDialog;

static inline void btrcSdlFolderDialogRelease(BtrcSdlFolderDialog* dialog) {
	if (dialog == NULL) { return; }
	if (SDL_AddAtomicInt(&dialog->owners, -1) != 1) { return; }
	free(dialog->path);
	free(dialog);
}

static void btrcSdlFolderDialogCallback(void* userdata, const char* const* filelist, int filter) {
	BtrcSdlFolderDialog* dialog = (BtrcSdlFolderDialog*)userdata;
	(void)filter;
	if (dialog == NULL) { return; }
	int state = 3;
	if (filelist != NULL && filelist[0] == NULL) { state = 2; }
	else if (filelist != NULL) {
		size_t length = strlen(filelist[0]);
		char* path = (char*)malloc(length + 1);
		if (path != NULL) { memcpy(path, filelist[0], length + 1); dialog->path = path; state = 1; }
	}
	SDL_SetAtomicInt(&dialog->state, state);  /* full barrier: the path is visible before the state */
	btrcSdlFolderDialogRelease(dialog);
}

/* Returns NULL when no transaction could be allocated; otherwise the caller
 * owns one reference and must release it. */
static inline BtrcSdlFolderDialog* btrcSdlFolderDialogOpen(SDL_Window* window, const char* initialDirectory, const char* title) {
	BtrcSdlFolderDialog* dialog = (BtrcSdlFolderDialog*)calloc(1, sizeof(BtrcSdlFolderDialog));
	if (dialog == NULL) { return NULL; }
	SDL_PropertiesID properties = SDL_CreateProperties();
	if (properties == 0) { free(dialog); return NULL; }
	if (window != NULL) { SDL_SetPointerProperty(properties, SDL_PROP_FILE_DIALOG_WINDOW_POINTER, window); }
	if (initialDirectory != NULL && initialDirectory[0] != '\0') { SDL_SetStringProperty(properties, SDL_PROP_FILE_DIALOG_LOCATION_STRING, initialDirectory); }
	if (title != NULL && title[0] != '\0') { SDL_SetStringProperty(properties, SDL_PROP_FILE_DIALOG_TITLE_STRING, title); }
	SDL_SetBooleanProperty(properties, SDL_PROP_FILE_DIALOG_MANY_BOOLEAN, false);
	SDL_SetAtomicInt(&dialog->owners, 2);
	SDL_ShowFileDialogWithProperties(SDL_FILEDIALOG_OPENFOLDER, btrcSdlFolderDialogCallback, dialog, properties);
	SDL_DestroyProperties(properties);
	return dialog;
}

/* 0 while pending, then 1 selected, 2 cancelled, 3 failed. */
static inline int btrcSdlFolderDialogState(BtrcSdlFolderDialog* dialog) { return SDL_GetAtomicInt(&dialog->state); }

/* Valid only after the state reports a selection. */
static inline const char* btrcSdlFolderDialogPath(const BtrcSdlFolderDialog* dialog) { return dialog->path == NULL ? "" : dialog->path; }

/* Synthetic input for automation and tests: events enter SDL's own queue and
 * reach the window exactly like device events. Coordinates are window points. */
static inline void btrcSdlPushPointerMotion(unsigned int window, float x, float y) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = SDL_EVENT_MOUSE_MOTION;
	event.motion.windowID = window;
	event.motion.x = x;
	event.motion.y = y;
	SDL_PushEvent(&event);
}

static inline void btrcSdlPushPointerButton(unsigned int window, float x, float y, unsigned int button, int down, unsigned int clicks) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = down ? SDL_EVENT_MOUSE_BUTTON_DOWN : SDL_EVENT_MOUSE_BUTTON_UP;
	event.button.windowID = window;
	event.button.x = x;
	event.button.y = y;
	event.button.button = (Uint8)button;
	event.button.clicks = (Uint8)clicks;
	event.button.down = down ? true : false;
	SDL_PushEvent(&event);
}

static inline void btrcSdlPushWheel(unsigned int window, float x, float y, float deltaX, float deltaY) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = SDL_EVENT_MOUSE_WHEEL;
	event.wheel.windowID = window;
	event.wheel.mouse_x = x;
	event.wheel.mouse_y = y;
	event.wheel.x = deltaX;
	event.wheel.y = deltaY;
	SDL_PushEvent(&event);
}

static inline void btrcSdlPushKey(unsigned int window, unsigned int scancode, unsigned int key, unsigned int modifiers, int down, int repeat) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
	event.key.windowID = window;
	event.key.scancode = (SDL_Scancode)scancode;
	event.key.key = (SDL_Keycode)key;
	event.key.mod = (SDL_Keymod)modifiers;
	event.key.down = down ? true : false;
	event.key.repeat = repeat ? true : false;
	SDL_PushEvent(&event);
}

/* Pushed text lives in a small ring until the pump flattens its event: at
 * most 16 pushes may be pending and at most 63 bytes each. A push that would
 * overwrite pending text or truncate this one is rejected and returns 0. */
static inline int btrcSdlPushText(unsigned int window, const char* text) {
	size_t length = strlen(text);
	if (length > 63u || btrcSdlTextRingPushed - btrcSdlTextRingTaken >= 16u) { return 0; }
	char* slot = btrcSdlTextRing[btrcSdlTextRingPushed % 16u];
	memcpy(slot, text, length);
	slot[length] = '\0';
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = SDL_EVENT_TEXT_INPUT;
	event.text.windowID = window;
	event.text.text = slot;
	if (!SDL_PushEvent(&event)) { return 0; }
	btrcSdlTextRingPushed++;
	return 1;
}
