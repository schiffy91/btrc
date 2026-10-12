"""BTRC calls through an SDK-owned function table (interop step 2, M1 dispatch).

The object owns its table: every call borrows the unique owner, reloads the
table pointer and the slot, checks both for null, calls, and ends the borrow.
A table the SDK swaps is honored on the next call; a release slot runs exactly
once at final owner cleanup (native-interop-ownership.md section 2.1).
"""

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import resource_project as resource_project
from src.tests.python.native_import_fixtures import run_native_executable
from src.tests.python.native_import_fixtures import unique_project as unique_project

HEADER = """
#include <stdlib.h>
typedef struct Codec Codec;
typedef struct CodecVTable {
    int (*decode)(Codec* self, const unsigned char* input, int length);
    void (*reset)(Codec* self);
    void (*destroy)(Codec* self);
} CodecVTable;
struct Codec { const CodecVTable* vtbl; int resets; };
static int codecsDestroyed;
static int codecSum(Codec* self, const unsigned char* input, int length) {
    (void)self; int total = 0;
    for (int index = 0; index < length; index++) { total += input[index]; }
    return total;
}
static int codecDouble(Codec* self, const unsigned char* input, int length) { return 2 * codecSum(self, input, length); }
static void codecReset(Codec* self) { self->resets++; }
static void codecDestroy(Codec* self) { codecsDestroyed++; free(self); }
static const CodecVTable codecPrimary = {codecSum, codecReset, codecDestroy};
static const CodecVTable codecDoubled = {codecDouble, codecReset, codecDestroy};
static const CodecVTable codecBroken = {NULL, codecReset, codecDestroy};
static inline Codec* CodecOpen(void) {
    Codec* codec = calloc(1, sizeof(Codec));
    if (codec) { codec->vtbl = &codecPrimary; }
    return codec;
}
static inline void CodecSwap(Codec* codec) { codec->vtbl = codec->vtbl == &codecPrimary ? &codecDoubled : &codecPrimary; }
static inline void CodecBreak(Codec* codec) { codec->vtbl = &codecBroken; }
static inline void CodecDetach(Codec* codec) { codec->vtbl = NULL; }
static inline int CodecResets(Codec* codec) { return codec->resets; }
static inline int CodecDestroyedCount(void) { return codecsDestroyed; }
"""

MANIFEST = """
[native.bindings.resources.Codec]
ownership = "unique"

[native.bindings.resources.Codec.dispatch]
table = "vtbl"
context-index = 0
executor = "caller"
failure = "abort"
release = "destroy"

[native.bindings.resources.Codec.dispatch.methods]
decode = "decode"
reset = "reset"
"""

SYMBOLS = '"Codec", "CodecOpen", "CodecSwap", "CodecBreak", "CodecDetach", "CodecResets", "CodecDestroyedCount", '


@pytest.fixture
def dispatch_project(unique_project):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(header.read_text() + HEADER)
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace("symbols = [", "symbols = [" + SYMBOLS)
        .replace("owned-results = [", 'owned-results = ["CodecOpen", ')
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["CodecSwap.codec", "CodecBreak.codec", "CodecDetach.codec", "CodecResets.codec", ',
        )
        + MANIFEST
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
def test_dispatch_reloads_the_table_and_releases_once(dispatch_project, native_compile, sanitize):
    source, sdk, triple = dispatch_project
    source.write_text(
        """import ./Foundation.btrc;
int main() {
    unsigned char bytes[3] = {1, 2, 3};
    var codec = CodecOpen();
    assert(codec != null);
    assert(codec.decode(bytes, 3) == 6);
    codec.reset();
    codec.reset();
    assert(CodecResets(codec) == 2);
    CodecSwap(codec);
    assert(codec.decode(bytes, 3) == 12);
    CodecSwap(codec);
    assert(codec.decode(bytes, 3) == 6);
    var alias = codec;
    alias.close();
    assert(!codec.isOpen() && CodecDestroyedCount() == 1);
    codec.close();
    assert(CodecDestroyedCount() == 1);
    for (int iteration = 0; iteration < 1000; iteration++) {
        var transient = CodecOpen();
        assert(transient.decode(bytes, 2) == 3);
    }
    assert(CodecDestroyedCount() == 1001);
    return 0;
}
"""
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(result.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("var codec = CodecOpen(); CodecBreak(codec); codec.decode(bytes, 3);", "null table slot decode"),
        (
            "var codec = CodecOpen(); CodecDetach(codec); codec.decode(bytes, 3);",
            "Native dispatch Codec.decode: null function table",
        ),
        ("var codec = CodecOpen(); codec.close(); codec.decode(bytes, 3);", "use after close"),
    ],
)
def test_dispatch_failures_abort_before_the_slot_runs(dispatch_project, native_compile, body, expected):
    source, sdk, triple = dispatch_project
    source.write_text(
        f"import ./Foundation.btrc;\nint main() {{ unsigned char bytes[3] = {{1, 2, 3}}; {body} return 0; }}\n"
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(
        result.c_source, source.parent.parent, sdk, triple, False, frameworks=(), expected_failure=expected
    )


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        # The reader resolves each slot's record path before the importer runs.
        ('table = "vtbl"', 'table = "resets"', "Record path requires noncyclic complete SDK records"),
        ('decode = "decode"', 'decode = "missing"', "Record path names an unavailable SDK field"),
        ('executor = "caller"', 'executor = "main"', "executor currently requires caller"),
        ('release = "destroy"\n', 'release = "destroy"\ncontext = "resets"\n', "unqualified void* context"),
        ('reset = "reset"', 'close = "reset"', "cannot shadow resource operations"),
        (
            'ownership = "unique"\n\n[native.bindings.resources.Codec.dispatch]',
            'ownership = "unique"\nrelease = "CodecBreak"\n\n[native.bindings.resources.Codec.dispatch]',
            "replaces the resource release",
        ),
    ],
)
def test_dispatch_rejects_conflicting_facts(dispatch_project, native_compile, before, after, message):
    source, _, _ = dispatch_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    assert before in text
    manifest.write_text(text.replace(before, after, 1))
    result = native_compile(source)
    assert not result.successful
    assert message in str(result.failure) + str(result.diagnostics)
