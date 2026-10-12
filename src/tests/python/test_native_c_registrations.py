"""Stored C callback registrations: a Win32-shaped window subclass held until removal.

A C SDK stores a function pointer with pointer-width integer context words and
calls it until the matching unregister call returns. The binding maps both
context words to the registration's context, names the unregister function
whose parameters repeat the registration's, and declares which integer status
means success (package-manifest.md, "Stored C registrations"). This fixture
mimics comctl32's SetWindowSubclass/RemoveWindowSubclass on any host: the
window handle is opaque, the owner thread is checked, and a repeated
(proc, id) pair silently replaces its reference data.
"""

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import run_native_executable

HEADER = """#include <stdint.h>
typedef int BOOL;
typedef unsigned int UINT;
typedef uintptr_t WPARAM;
typedef intptr_t LPARAM;
typedef intptr_t LRESULT;
typedef uintptr_t UINT_PTR;
typedef uintptr_t DWORD_PTR;
typedef struct HWND__ *HWND;
typedef LRESULT (*SUBCLASSPROC)(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam, UINT_PTR uIdSubclass, DWORD_PTR dwRefData);
enum { WM_NCDESTROY = 0x0082, WM_USER = 0x0400 };
HWND FakeCreateWindow(void);
void FakeDestroyWindow(HWND hWnd);
BOOL SetWindowSubclass(HWND hWnd, SUBCLASSPROC pfnSubclass, UINT_PTR uIdSubclass, DWORD_PTR dwRefData);
BOOL RemoveWindowSubclass(HWND hWnd, SUBCLASSPROC pfnSubclass, UINT_PTR uIdSubclass);
LRESULT FakeSendMessage(HWND hWnd, UINT uMsg, WPARAM wParam, LPARAM lParam);
int FakeSubclassCount(HWND hWnd);
int FakeWindowsLive(void);
void FakeFailNextSubclass(void);
"""

SOURCE = """#include "WinShape.h"
#include <pthread.h>
#include <stdlib.h>
struct Subclass { SUBCLASSPROC proc; UINT_PTR id; DWORD_PTR data; struct Subclass *next; };
struct HWND__ { struct Subclass *chain; pthread_t owner; };
static int live, failNext;
HWND FakeCreateWindow(void) {
    HWND window = calloc(1, sizeof *window);
    if (!window) abort();
    window->owner = pthread_self();
    live++;
    return window;
}
void FakeDestroyWindow(HWND window) {
    FakeSendMessage(window, WM_NCDESTROY, 0, 0);
    while (window->chain) { struct Subclass *next = window->chain->next; free(window->chain); window->chain = next; }
    live--;
    free(window);
}
BOOL SetWindowSubclass(HWND window, SUBCLASSPROC proc, UINT_PTR id, DWORD_PTR data) {
    if (failNext) { failNext = 0; return 0; }
    if (!pthread_equal(window->owner, pthread_self())) return 0;
    for (struct Subclass *entry = window->chain; entry; entry = entry->next) {
        if (entry->proc == proc && entry->id == id) { entry->data = data; return 1; }
    }
    struct Subclass *entry = calloc(1, sizeof *entry);
    if (!entry) abort();
    entry->proc = proc; entry->id = id; entry->data = data; entry->next = window->chain;
    window->chain = entry;
    return 1;
}
BOOL RemoveWindowSubclass(HWND window, SUBCLASSPROC proc, UINT_PTR id) {
    if (!pthread_equal(window->owner, pthread_self())) return 0;
    for (struct Subclass **link = &window->chain; *link; link = &(*link)->next) {
        if ((*link)->proc == proc && (*link)->id == id) {
            struct Subclass *removed = *link;
            *link = removed->next;
            free(removed);
            return 1;
        }
    }
    return 0;
}
LRESULT FakeSendMessage(HWND window, UINT message, WPARAM wParam, LPARAM lParam) {
    struct Subclass *entry = window->chain;
    return entry ? entry->proc(window, message, wParam, lParam, entry->id, entry->data) : 0;
}
int FakeSubclassCount(HWND window) { int count = 0; for (struct Subclass *entry = window->chain; entry; entry = entry->next) count++; return count; }
int FakeWindowsLive(void) { return live; }
void FakeFailNextSubclass(void) { failNext = 1; }
"""

MANIFEST = """manifest-version = 1
[package]
name = "storedCRegistrations"
[[native.bindings]]
module = "WinShape"
header = "WinShape.h"
language = "c"
standard = "c11"
symbols = ["FakeCreateWindow", "FakeDestroyWindow", "SetWindowSubclass", "RemoveWindowSubclass", "FakeSendMessage", "FakeSubclassCount", "FakeWindowsLive", "FakeFailNextSubclass", "WM_USER", "WM_NCDESTROY"]
[native.bindings.callbacks."SetWindowSubclass.pfnSubclass"]
interface = "IWindowSubclass"
context = ["uIdSubclass", "dwRefData"]
context-index = [4, 5]
lifetime = "stored"
executor = "caller"
failure = "abort"
registration-status = "nonzero"
activation-failure = "unpublished"
unregister = "RemoveWindowSubclass"
unregister-status = "nonzero"
captured-handles = ["hWnd"]
cancellation = "entry-barrier"
[[native.sources]]
path = "WinShape.c"
language = "c"
standard = "c11"
"""

PROGRAM = """import Library.Callback;
import ./WinShape.btrc;
#include <assert.h>
int destroyed = 0;
class Window implements IWindowSubclass {
	private CallbackScope scope;
	public int messages = 0;
	public Window(CallbackScope scope) { self.scope = scope; }
	public LRESULT invoke(HWND window, UINT message, WPARAM wParam, LPARAM lParam) {
		self.messages++;
		if (message == WM_USER + 1) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
		return lParam + 1;
	}
	public void __del__() { destroyed++; }
}
void lifecycle() {
	var scope = CallbackScope();
	var window = FakeCreateWindow();
	int before = destroyed;
	ICallbackRegistration registration = SetWindowSubclass(window, Window(scope), scope);
	assert(registration.isOpen() && FakeSubclassCount(window) == 1);
	assert(FakeSendMessage(window, WM_USER, 0, 41) == 42);
	assert(FakeSendMessage(window, WM_USER, 0, 1) == 2);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(FakeSubclassCount(window) == 0 && destroyed == before + 1);
	assert(FakeSendMessage(window, WM_USER, 0, 1) == 0);
	FakeDestroyWindow(window);
}
void cancelInside() {
	var scope = CallbackScope();
	var window = FakeCreateWindow();
	int before = destroyed;
	ICallbackRegistration registration = SetWindowSubclass(window, Window(scope), scope);
	assert(FakeSendMessage(window, WM_USER + 1, 0, 9) == 10);
	assert(registration.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(FakeSubclassCount(window) == 0 && destroyed == before + 1);
	FakeDestroyWindow(window);
}
void registrationFails() {
	var scope = CallbackScope();
	var window = FakeCreateWindow();
	int before = destroyed;
	FakeFailNextSubclass();
	bool failed = false;
	try { var registration = SetWindowSubclass(window, Window(scope), scope); }
	catch (string error) { failed = true; }
	assert(failed && FakeSubclassCount(window) == 0);
	assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
	assert(destroyed == before + 1);
	FakeDestroyWindow(window);
}
int main() {
	for (int cycle = 0; cycle < 1000; cycle++) {
		lifecycle();
		cancelInside();
		registrationFails();
	}
	assert(destroyed == 3000 && FakeWindowsLive() == 0);
	return 0;
}
"""


@pytest.fixture
def subclass_project(native_project):
    source, sdk, triple = native_project
    root = source.parent.parent
    (root / "WinShape.h").write_text(HEADER, encoding="utf-8")
    (root / "WinShape.c").write_text(SOURCE, encoding="utf-8")
    (root / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    (source.parent / "WinShape.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    source.write_text(PROGRAM, encoding="utf-8")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_window_subclass_registration_lifecycle(subclass_project, native_compile, sanitize):
    source, sdk, triple = subclass_project
    root = source.parent.parent
    plan_path = root / "Program.link.json"
    result = native_compile(source, plan_path=plan_path)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(
        result.c_source + "\n" + SOURCE.replace('#include "WinShape.h"', ""),
        root,
        sdk,
        triple,
        sanitize,
        frameworks=(),
    )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('captured-handles = ["hWnd"]\n', "", "must be listed in captured-handles"),
        ('unregister-status = "nonzero"\n', "", "unregister-status must describe an integral result"),
        ('registration-status = "nonzero"', 'registration-status = "always"', "statuses require"),
        (
            'context = ["uIdSubclass", "dwRefData"]',
            'context = ["hWnd", "dwRefData"]',
            "context must be an unqualified void pointer",
        ),
        ("typedef uintptr_t DWORD_PTR;", "typedef uint32_t DWORD_PTR;", "context must be an unqualified void pointer"),
    ],
)
def test_stored_c_registration_rejects_unchecked_mappings(subclass_project, native_compile, old, new, message):
    source, _, _ = subclass_project
    root = source.parent.parent
    for path in (root / "btrc.toml", root / "WinShape.h"):
        text = path.read_text(encoding="utf-8")
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
            break
    else:
        raise AssertionError(old)
    source.write_text("import Library.Callback;\nimport ./WinShape.btrc;\nint main() { return 0; }\n", encoding="utf-8")
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + str(result.diagnostics)
