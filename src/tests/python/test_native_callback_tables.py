"""Generated SDK callback tables keep one receiver claim per live native table."""

import pytest

from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.python.test_native_import_consumer import resource_project as resource_project
from src.tests.python.test_native_import_consumer import run_native_executable
from src.tests.python.test_native_unique_resources import unique_project as unique_project

HEADER = """
#include <string.h>
#include <pthread.h>
typedef struct Reader {
    void* user_data;
    int (*read)(void* user_data, unsigned char* dst, long long offset, int length);
    long long (*size)(void* user_data);
    const char* (*name)(void* user_data);
    struct Reader* (*open)(void* user_data, const char* filename);
    void (*close)(struct Reader* reader);
} Reader;
static Reader* savedClone;
static int tablesClosed;
static inline void ReaderClose(Reader* reader) { if (reader && reader->close) { tablesClosed++; reader->close(reader); } }
static inline int ReaderConsume(Reader* reader, int reopen) {
    unsigned char buffer[4] = {0, 0, 0, 0};
    long long size = reader->size(reader->user_data);
    int count = reader->read(reader->user_data, buffer, 1, 4);
    const char* name = reader->name(reader->user_data);
    if (reopen) {
        assert(reader->open(reader->user_data, "other.bin") == NULL);
        assert(reader->open(reader->user_data, NULL) == NULL);
        savedClone = reader->open(reader->user_data, name);
        if (!savedClone) { return -1; }
    }
    return count == 4 && size == 8 && strcmp(name, "memory.bin") == 0 && buffer[0] == 1 && buffer[3] == 4 ? 0 : -2;
}
static inline int ReaderConsumeClone(void) {
    unsigned char buffer[2] = {0, 0};
    if (!savedClone || savedClone->read(savedClone->user_data, buffer, 6, 2) != 2) { return -1; }
    return buffer[0] == 6 && buffer[1] == 7 && savedClone->size(savedClone->user_data) == 8 ? 0 : -2;
}
static inline void ReaderCloseClone(void) { ReaderClose(savedClone); savedClone = NULL; }
static inline int ReaderTablesClosed(void) { return tablesClosed; }
static void* readOnWorker(void* raw) {
    Reader* reader = raw; unsigned char buffer[1] = {0};
    reader->read(reader->user_data, buffer, 0, 1);
    return NULL;
}
static inline void ReaderReadFromWorker(Reader* reader) {
    pthread_t worker;
    assert(pthread_create(&worker, NULL, readOnWorker, reader) == 0);
    assert(pthread_join(worker, NULL) == 0);
}
"""

MANIFEST = """
[native.bindings.resources.Reader]
ownership = "unique"
release = "ReaderClose"

[native.bindings.resources.Reader.table]
name = "openReader"
interface = "IReaderSource"
context = "user_data"
context-index = 0
executor = "caller"
failure = "abort"
label = "name"
reopen = "open"
release = "close"

[native.bindings.resources.Reader.table.methods]
read = "read"
size = "size"
"""

PROGRAM = """import ./Foundation.btrc;
import Library.OwnedBuffer;
static int destroyed = 0;
class MemorySource implements IReaderSource {
    private OwnedBuffer<unsigned char> _bytes;
    public MemorySource() {
        self._bytes = OwnedBuffer((size_t)8);
        for (int index = 0; index < 8; index++) { assert(self._bytes.set((size_t)index, (unsigned char)index)); }
    }
    public int read(unsigned char* destination, long long offset, int length) {
        if (destination == null || offset < 0LL || length <= 0 || offset >= 8LL) { return 0; }
        int count = length < (int)(8LL - offset) ? length : (int)(8LL - offset);
        assert(self._bytes.tryCopyTo((size_t)offset, destination, (size_t)count));
        return count;
    }
    public long long size() { return 8LL; }
    public void __del__() { destroyed++; }
}
"""


@pytest.fixture
def table_project(unique_project):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(header.read_text() + HEADER)
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            "symbols = [",
            'symbols = ["Reader", "ReaderClose", "ReaderConsume", "ReaderConsumeClone", "ReaderCloseClone", "ReaderTablesClosed", "ReaderReadFromWorker", ',
        )
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["ReaderConsume.reader", "ReaderReadFromWorker.reader", ',
        )
        + MANIFEST
    )
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    return source, sdk, triple


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("order", ["original-first", "clone-first", "abandoned"])
def test_callback_table_claims_follow_every_live_table(table_project, native_compile, sanitize, order):
    source, sdk, triple = table_project
    steps = {
        "original-first": "reader.close(); assert(destroyed == iteration); assert(ReaderConsumeClone() == 0); ReaderCloseClone();",
        "clone-first": "ReaderCloseClone(); assert(destroyed == iteration); assert(ReaderConsume(reader, 0) == 0); reader.close();",
        "abandoned": "release reader; assert(destroyed == iteration); assert(ReaderConsumeClone() == 0); ReaderCloseClone();",
    }[order]
    source.write_text(
        PROGRAM
        + f"""
int main() {{
    for (int iteration = 0; iteration < 3; iteration++) {{
        var receiver = new MemorySource();
        var reader = openReader(receiver, "memory.bin");
        assert(reader != null && reader.isOpen());
        release receiver;
        assert(destroyed == iteration);
        assert(ReaderConsume(reader, 1) == 0);
        {steps}
        assert(destroyed == iteration + 1);
        assert(ReaderTablesClosed() == (iteration + 1) * 2);
    }}
    var plain = openReader(new MemorySource(), "memory.bin");
    assert(ReaderConsume(plain, 0) == 0);
    var alias = plain;
    plain.close();
    assert(!alias.isOpen() && destroyed == 4);
    return 0;
}}
"""
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(result.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=())


@pytest.mark.parametrize("failure", ["exception", "wrong-thread", "null-receiver"])
def test_callback_table_failures_terminate_before_native_return(table_project, native_compile, failure):
    source, sdk, triple = table_project
    if failure == "exception":
        program = PROGRAM.replace(
            "public long long size() { return 8LL; }", 'public long long size() { throw "no size"; }'
        )
        body = 'var reader = openReader(new MemorySource(), "memory.bin"); ReaderConsume(reader, 0); return 0;'
        expected = "BTRC native callback failed: no size"
    elif failure == "wrong-thread":
        program = PROGRAM
        body = 'var reader = openReader(new MemorySource(), "memory.bin"); ReaderReadFromWorker(reader); return 0;'
        expected = "wrong thread"
    else:
        program = PROGRAM
        body = 'IReaderSource? receiver = null; var reader = openReader(receiver, "memory.bin"); return 0;'
        expected = "null argument receiver"
    source.write_text(program + f"int main() {{ {body} }}\n")
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(
        result.c_source, source.parent.parent, sdk, triple, False, frameworks=(), expected_failure=expected
    )


@pytest.mark.parametrize(
    "invalid",
    [
        ('label = "name"\n', ""),
        ('context = "user_data"', 'context = "read"'),
        ('read = "read"\n', ""),
        ('size = "size"', 'size = "open"'),
        ('executor = "caller"', 'executor = "realtime"'),
        ('failure = "abort"', 'failure = "ignore"'),
        ('name = "openReader"', 'name = "ReaderClose"'),
        ('read = "read"', 'close = "read"'),
    ],
)
def test_callback_table_rejects_incomplete_or_conflicting_facts(table_project, native_compile, invalid):
    source, _, _ = table_project
    manifest = source.parent.parent / "btrc.toml"
    before, after = invalid
    text = manifest.read_text()
    assert before in text
    manifest.write_text(text.replace(before, after, 1))
    result = native_compile(source)
    assert not result.successful


def test_callback_table_projects_only_portable_api(table_project, native_compile):
    source, _, _ = table_project
    source.write_text(
        PROGRAM
        + """
int main() {
    var reader = openReader(new MemorySource(), "memory.bin");
    reader.read(null, 0LL, 0);
    return 0;
}
"""
    )
    result = native_compile(source)
    assert not result.successful
