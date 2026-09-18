/* SDL3 windowing for the Linux GUI provider. The union-typed SDL_Event and
 * the dialog callback cannot cross the typed importer, so these inline
 * adapters flatten them into plain C values; no policy lives here. */
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
	} else if (source->type == SDL_EVENT_TEXT_INPUT) {
		out->window = source->text.windowID;
		out->text = source->text.text;
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

/* Wake a blocked wait from the UI thread's own scheduling decisions. */
static inline void btrcSdlPushWake(void) {
	SDL_Event event;
	memset(&event, 0, sizeof(event));
	event.type = SDL_EVENT_USER;
	SDL_PushEvent(&event);
}

static inline void* btrcSdlWindowPointerProperty(SDL_Window* window, const char* name) { return SDL_GetPointerProperty(SDL_GetWindowProperties(window), name, NULL); }

static inline long long btrcSdlWindowNumberProperty(SDL_Window* window, const char* name) { return (long long)SDL_GetNumberProperty(SDL_GetWindowProperties(window), name, 0); }

static inline int btrcSdlWindowFlag(SDL_Window* window, unsigned long long flag) { return (SDL_GetWindowFlags(window) & (SDL_WindowFlags)flag) != 0 ? 1 : 0; }

static inline void btrcSdlSetTextInputArea(SDL_Window* window, int x, int y, int width, int height, int cursor) {
	SDL_Rect area;
	area.x = x; area.y = y; area.w = width; area.h = height;
	SDL_SetTextInputArea(window, &area, cursor);
}

static inline int btrcSdlSimpleMessageBox(const char* title, const char* message, SDL_Window* window) { return SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_INFORMATION, title, message, window) ? 1 : 0; }

/* One folder-dialog transaction. SDL delivers the callback on the thread
 * pumping events; the owner polls the state and frees it afterward. */
typedef struct BtrcSdlFolderDialog {
	int state;
	char* path;
} BtrcSdlFolderDialog;

static void btrcSdlFolderDialogCallback(void* userdata, const char* const* filelist, int filter) {
	BtrcSdlFolderDialog* dialog = (BtrcSdlFolderDialog*)userdata;
	(void)filter;
	if (dialog == NULL) { return; }
	if (filelist == NULL) { dialog->state = 3; return; }
	if (filelist[0] == NULL) { dialog->state = 2; return; }
	size_t length = strlen(filelist[0]);
	dialog->path = (char*)malloc(length + 1);
	if (dialog->path == NULL) { dialog->state = 3; return; }
	memcpy(dialog->path, filelist[0], length + 1);
	dialog->state = 1;
}

static inline BtrcSdlFolderDialog* btrcSdlFolderDialogOpen(SDL_Window* window, const char* initialDirectory) {
	BtrcSdlFolderDialog* dialog = (BtrcSdlFolderDialog*)calloc(1, sizeof(BtrcSdlFolderDialog));
	if (dialog == NULL) { return NULL; }
	SDL_ShowOpenFolderDialog(btrcSdlFolderDialogCallback, dialog, window, initialDirectory != NULL && initialDirectory[0] != '\0' ? initialDirectory : NULL, false);
	return dialog;
}

static inline int btrcSdlFolderDialogState(const BtrcSdlFolderDialog* dialog) { return dialog->state; }

static inline const char* btrcSdlFolderDialogPath(const BtrcSdlFolderDialog* dialog) { return dialog->path == NULL ? "" : dialog->path; }

static inline void btrcSdlFolderDialogFree(BtrcSdlFolderDialog* dialog) {
	if (dialog == NULL) { return; }
	free(dialog->path);
	free(dialog);
}

static inline char* btrcSdlClipboardText(void) { return SDL_GetClipboardText(); }

static inline void btrcSdlFree(void* memory) { SDL_free(memory); }
