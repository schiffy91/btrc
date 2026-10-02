"""One-shot C completions: record payloads, owned resources, copied strings and native futures."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.fixture(params=[False, True], ids=["context-last", "context-first"])
def c_one_shot_project(native_project, request):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Completion.h").write_text(
        "#include <assert.h>\n#include <pthread.h>\n"
        "typedef void (*Completion)(int, void*);\n"
        "static Completion pending; static void *pendingContext;\n"
        "static inline void FinishNow(int value, Completion completion, void *context) { completion(value, context); }\n"
        "static inline void FinishLater(int value, Completion completion, void *context) { "
        "assert(value == 7 && !pending); pending = completion; pendingContext = context; }\n"
        "static inline void Drain(void) { assert(pending); Completion callback = pending; void *context = pendingContext; "
        "pending = 0; pendingContext = 0; callback(7, context); }\n"
        "static inline void *Worker(void *unused) { (void)unused; Drain(); return 0; }\n"
        "static inline void DrainOnWorker(void) { pthread_t worker; assert(pthread_create(&worker, 0, Worker, 0) == 0); "
        "assert(pthread_join(worker, 0) == 0); }\n"
        "static inline void DrainTwice(void) { Completion callback = pending; void *context = pendingContext; "
        "Drain(); callback(7, context); }\n"
    )
    (root / "src/Completion.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "cCompletion"\n'
        '[[native.bindings]]\nmodule = "Completion"\nheader = "Completion.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["FinishNow", "FinishLater", "Drain", "DrainOnWorker", "DrainTwice"]\n'
        + "".join(
            f'[native.bindings.callbacks."{function}.completion"]\n'
            'interface = "ICompletion"\ncontext = "context"\ncontext-index = 1\n'
            'lifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n'
            for function in ("FinishNow", "FinishLater")
        )
    )
    source.write_text("""import Library.Callback;
import ./Completion.btrc;
int delivered = 0;
int destroyed = 0;
class Receiver implements ICompletion {
    public CallbackScope? scope;
    public bool fail = false;
    public void invoke(int value) {
        assert(value == 7); delivered++;
        if (self.fail) { throw "C completion receiver failed"; }
        if (self.scope != null) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
    }
    public void __del__() { destroyed++; }
}
void verify(bool inlineCall, bool cancel) {
    int before = delivered;
    int freed = destroyed;
    var scope = CallbackScope();
    var receiver = Receiver();
    var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);
    receiver = null;
    if (!inlineCall) {
        if (cancel) { assert(scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
        assert(destroyed == freed);
        Drain();
    }
    assert(request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
    assert(delivered == before + ((!inlineCall && cancel) ? 0 : 1));
    assert(destroyed == freed + 1);
    assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
}
int main() {
    verify(true, false); verify(false, false); verify(false, true);
    int freed = destroyed;
    int before = delivered;
    var abandoned = CallbackScope();
    FinishLater(7, Receiver(), abandoned);
    assert(abandoned.cancel() == CALLBACK_CANCELLATION_PENDING);
    assert(destroyed == freed);
    Drain();
    assert(destroyed == freed + 1 && delivered == before);
    assert(abandoned.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
    var scope = CallbackScope();
    var receiver = Receiver();
    receiver.scope = scope;
    var request = FinishNow(7, receiver, scope);
    receiver = null;
    assert(request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
    assert(destroyed == freed + 2 && delivered == before + 1);
    var cancelled = CallbackScope();
    cancelled.cancel();
    bool rejected = false;
    try { FinishLater(7, Receiver(), cancelled); } catch (string error) { rejected = true; }
    assert(rejected && destroyed == freed + 3);
    print("PASS: C one-shot native completion and cancellation");
    return 0;
}
""")
    if request.param:
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("(*Completion)(int, void*)", "(*Completion)(void*, int)")
            .replace(
                "int value, Completion completion, void *context", "void *context, int value, Completion completion"
            )
            .replace("completion(value, context)", "completion(context, value)")
            .replace("callback(7, context)", "callback(context, 7)")
        )
        manifest = root / "btrc.toml"
        manifest.write_text(manifest.read_text().replace("context-index = 1", "context-index = 0"))
    return source


@pytest.fixture
def c_record_completion_project(c_one_shot_project):
    source = c_one_shot_project
    root = source.parent.parent
    header = root / "Completion.h"
    content = header.read_text()
    end = content.index(";", content.index("typedef void (*Completion)")) + 1
    content = (
        content[:end]
        + "\ntypedef struct Info { int marker; Completion completion; void* context; } Info;"
        + content[end:]
    )
    content = content.replace("int value, Completion completion, void *context", "int value, Info info")
    content = content.replace("void *context, int value, Completion completion", "int value, Info info")
    content = content.replace(
        "completion(value, context);", "assert(info.marker == 42); info.completion(value, info.context);"
    )
    content = content.replace(
        "completion(context, value);", "assert(info.marker == 42); info.completion(info.context, value);"
    )
    content = content.replace(
        "pending = completion; pendingContext = context;",
        "assert(info.marker == 42); pending = info.completion; pendingContext = info.context;",
    )
    header.write_text(content)
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace('symbols = ["FinishNow"', 'symbols = ["Info", "FinishNow"')
        .replace(
            '[native.bindings.callbacks."FinishNow.completion"]',
            'owned-records = ["Info"]\nrecord-inputs = ["FinishNow.info", "FinishLater.info"]\n[native.bindings.callbacks."FinishNow.info"]\nfield = "completion"',
        )
        .replace(
            '[native.bindings.callbacks."FinishLater.completion"]',
            '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"',
        )
    )
    content = source.read_text()
    for receiver in ("receiver", "Receiver()"):
        for function in ("FinishNow", "FinishLater"):
            content = content.replace(f"{function}(7, {receiver},", f"{function}(7, makeInfo({receiver}),")
    source.write_text(
        content
        + "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.marker = 42; info.completion = receiver; return info; }\n"
    )
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifecycle", "worker", "failure", "duplicate", "abandoned-scope"])
def test_c_record_completion_lifetime(c_record_completion_project, native_compile, sanitize, scenario):
    test_c_one_shot_completion_lifetime(c_record_completion_project, native_compile, sanitize, scenario, record=True)


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-records",
        "missing-inputs",
        "unknown-field",
        "unknown-context",
        "same-field",
        "scalar-field",
        "scalar-context",
        "pointer-input",
        "unmapped-call",
        "const-callback",
        "const-context",
        "volatile-context",
    ],
)
def test_c_record_completion_rejects_invalid_mapping(c_record_completion_project, native_compile, scenario):
    source = c_record_completion_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    text = manifest.read_text()
    diagnostic = ""
    if scenario == "missing-records":
        text = text.replace('owned-records = ["Info"]\n', "").replace(
            'record-inputs = ["FinishNow.info", "FinishLater.info"]\n', ""
        )
        diagnostic = "callback fields require owned-records and record-inputs"
    elif scenario == "missing-inputs":
        text = text.replace('record-inputs = ["FinishNow.info", "FinishLater.info"]\n', "")
        diagnostic = "callback fields require owned-records and record-inputs"
    elif scenario in {"unknown-field", "unknown-context"}:
        text = text.replace(
            'field = "completion"' if scenario == "unknown-field" else 'context = "context"',
            'field = "absent"' if scenario == "unknown-field" else 'context = "absent"',
        )
        diagnostic = "callback field/context must identify fields"
    elif scenario == "same-field":
        text = text.replace('context = "context"', 'context = "completion"')
        diagnostic = "callback field and context must be distinct"
    elif scenario == "scalar-field":
        text = text.replace('field = "completion"', 'field = "marker"')
        diagnostic = "nonvariadic function pointer"
    elif scenario == "scalar-context":
        text = text.replace('context = "context"', 'context = "marker"')
        diagnostic = "context must be an unqualified void pointer"
    elif scenario == "pointer-input":
        header = root / "Completion.h"
        header.write_text(
            header.read_text().replace("int value, Info info", "int value, const Info* info").replace("info.", "info->")
        )
        diagnostic = "complete by-value record parameter"
    elif scenario in {"const-callback", "const-context", "volatile-context"}:
        header = root / "Completion.h"
        before = "Completion completion;" if scenario == "const-callback" else "void* context;"
        after = (
            "Completion const completion;"
            if scenario == "const-callback"
            else "void* volatile context;"
            if scenario == "volatile-context"
            else "void* const context;"
        )
        header.write_text(header.read_text().replace(before, after))
        diagnostic = "callback fields require assignable unqualified storage"
    else:
        text = text.split('[native.bindings.callbacks."FinishLater.info"]')[0]
        diagnostic = "record callback fields require a callback mapping on every input call"
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert diagnostic in str(result.failure)
    assert not plan.exists()


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("future", [False, True])
def test_c_record_completion_snapshots_reused_input(
    c_record_completion_project,
    native_compile,
    sanitize,
    indirect,
    future,
    context_count=1,
    cancel=False,
    corrupt=False,
):
    source = c_record_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    context_first = "(*Completion)(void*, int)" in header.read_text()
    signature = "void*, int" if context_first else "int, void*"
    arguments = "pending[index].context, 7" if context_first else "7, pending[index].context"
    context_fields = ["context", *(f"context{index}" for index in range(1, context_count))]
    extra_fields = "".join(f" void* {field};" for field in context_fields[1:])
    for field in context_fields[1:]:
        signature += ", void*"
        arguments += f", pending[index].{field}" if not corrupt else ", NULL"
    context_indices = [0 if context_first else 1, *range(2, context_count + 1)]
    context_declaration = (
        f'context = "context"\ncontext-index = {context_indices[0]}\n'
        if context_count == 1
        else f"context = {json.dumps(context_fields[::-1])}\ncontext-index = {context_indices[::-1]}\n"
    )
    matching_contexts = " && ".join(f"info.{field} == info.context" for field in context_fields)
    result_type = "uint64_t" if future else "void"
    result_value = "return UINT64_C(4294967296) + (uint64_t)count;" if future else ""
    header.write_text(
        "#include <assert.h>\n#include <stdint.h>\n#include <stddef.h>\n"
        f"typedef void (*Completion)({signature});\n"
        f"typedef struct Info {{ int marker; Completion completion; void* context;{extra_fields} }} Info;\n"
        "static Info pending[2]; static int count;\n"
        f"static inline {result_type} FinishLater(int value, Info info) {{ assert(value == 7 && info.marker == 42 && count < 2 && info.context && {matching_contexts}); pending[count++] = info; {result_value} }}\n"
        "static inline void Drain(void) { assert(count == 2);\n"
        f"    for (int index = 0; index < count; ++index) {{ pending[index].completion({arguments}); pending[index] = (Info){{0}}; }}\n"
        "    count = 0;\n}\n"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "recordRequests"\n'
        '[[native.bindings]]\nmodule = "Completion"\nheader = "Completion.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["Info", "FinishLater", "Drain"]\nowned-records = ["Info"]\nrecord-inputs = ["FinishLater.info"]\n'
        '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"\ninterface = "ICompletion"\n'
        f'{context_declaration}lifetime = "one-shot"\nexecutor = "caller"\nfailure = "abort"\n'
        'activation-failure = "abort"\ncancellation = "abandon"\n'
    )
    call = "start" if indirect else "FinishLater"
    alias = "var start = FinishLater;" if indirect else ""
    request = ".request" if future else ""
    check_future = "assert(first.value == 4294967297ULL && second.value == 4294967298ULL);" if future else ""
    cancellation = "scope.cancel();" if cancel else ""
    source.write_text(
        "import Library.Callback;\nimport ./Completion.btrc;\n"
        "int mask = 0; int freed = 0;\n"
        "class Receiver implements ICompletion {\n\tprivate int bit;\n"
        "\tpublic Receiver(int bit) { self.bit = bit; }\n"
        "\tpublic void invoke(int value) { assert(value == 7 && (mask & self.bit) == 0); mask |= self.bit; }\n"
        "\tpublic void __del__() { freed++; }\n}\n"
        "int main() {\n\tvar scope = CallbackScope(); var info = InfoInput(); info.marker = 42;\n"
        f"\t{alias} info.completion = Receiver(1); var first = {call}(7, info, scope);\n"
        f"\tinfo.completion = Receiver(2); var second = {call}(7, info, scope);\n"
        f"\trelease info; assert(freed == 0 && mask == 0); {cancellation} Drain();\n"
        f"\tassert(freed == 2 && mask == {0 if cancel else 3});\n"
        f"\t{check_future}\n"
        f"\tassert(first{request}.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);\n"
        f"\tassert(second{request}.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);\n"
        "\tassert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE); return 0;\n}\n"
    )
    plan = root / "Program.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Program.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if corrupt:
        assert completed.returncode != 0
        assert "inconsistent context slots" in completed.stderr
        assert "ERROR: AddressSanitizer" not in completed.stderr
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("context_count", [2, 3])
@pytest.mark.parametrize("scenario", ["complete", "cancel", "corrupt"])
def test_c_record_completion_multiple_contexts(
    c_record_completion_project, native_compile, sanitize, context_count, scenario
):
    test_c_record_completion_snapshots_reused_input(
        c_record_completion_project,
        native_compile,
        sanitize,
        indirect=True,
        future=True,
        context_count=context_count,
        cancel=scenario == "cancel",
        corrupt=scenario == "corrupt",
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "empty",
        "count",
        "duplicate-field",
        "duplicate-index",
        "boolean-index",
        "negative-index",
        "huge-index",
        "unknown-field",
        "scalar-field",
        "const-field",
        "unknown-index",
        "scalar-index",
        "owned-context",
        "flat",
    ],
)
def test_c_record_completion_multiple_contexts_rejects_invalid_mapping(
    c_record_completion_project, native_compile, scenario
):
    source = c_record_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    header.write_text(
        "typedef void (*Completion)(void*, int, void*);\n"
        "typedef struct Info { int marker; Completion completion; void* context; void* second; } Info;\n"
        "void FinishNow(int value, Info info); void FinishLater(int value, Info info);\n"
        "void Drain(void); void DrainOnWorker(void); void DrainTwice(void);\n"
    )
    manifest = root / "btrc.toml"
    text = manifest.read_text().replace('context = "context"', 'context = ["context", "second"]')
    text = text.replace("context-index = 0", "context-index = [0, 2]").replace(
        "context-index = 1", "context-index = [0, 2]"
    )
    replacements = {
        "empty": ('context = ["context", "second"]', "context = []"),
        "count": ("context-index = [0, 2]", "context-index = [0]"),
        "duplicate-field": ('"context", "second"', '"context", "context"'),
        "duplicate-index": ("[0, 2]", "[0, 0]"),
        "boolean-index": ("[0, 2]", "[0, true]"),
        "negative-index": ("[0, 2]", "[0, -1]"),
        "huge-index": ("[0, 2]", "[0, 1000000000]"),
        "unknown-field": ('"context", "second"', '"context", "absent"'),
        "scalar-field": ('"context", "second"', '"context", "marker"'),
        "unknown-index": ("[0, 2]", "[0, 4]"),
        "scalar-index": ("[0, 2]", "[0, 1]"),
        "owned-context": ('cancellation = "abandon"', 'cancellation = "abandon"\nowned-arguments = [2]'),
        "flat": ('field = "completion"\n', ""),
    }
    if scenario == "const-field":
        header.write_text(header.read_text().replace("void* second", "void* const second"))
    else:
        before, after = replacements[scenario]
        text = text.replace(before, after)
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert "context" in str(result.failure) or "callback" in str(result.failure)
    assert not plan.exists()


@pytest.mark.parametrize(
    "operation", ["read-callback", "write-callback", "read-context", "write-context", "owning-context"]
)
def test_c_record_completion_reserves_native_storage(c_record_completion_project, native_compile, operation):
    source = c_record_completion_project
    statements = {
        "read-callback": "Info raw = {}; var escaped = raw.completion;",
        "write-callback": "Info raw = {}; raw.completion = null;",
        "read-context": "Info raw = {}; var escaped = raw.context;",
        "write-context": "Info raw = {}; raw.context = null;",
        "owning-context": "var input = InfoInput(); var escaped = input.context;",
    }
    source.write_text(
        "import Library.Callback;\nimport ./Completion.btrc;\nint main() { " + statements[operation] + " return 0; }\n"
    )
    plan = source.parent.parent / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    diagnostics = str(result.failure) + "\n".join(diagnostic.message for diagnostic in result.diagnostics)
    member = "completion" if "callback" in operation else "context"
    assert f"'{member}'" in diagnostics, diagnostics
    assert not plan.exists()


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifecycle", "worker", "failure", "duplicate", "abandoned-scope"])
def test_c_one_shot_completion_lifetime(c_one_shot_project, native_compile, sanitize, scenario, record=False):
    source = c_one_shot_project
    if scenario == "abandoned-scope":
        prefix = source.read_text().split("int main()", 1)[0]
        source.write_text(
            prefix
            + "int main() { { var scope = CallbackScope(); FinishLater(7, Receiver(), scope); } Drain(); return 0; }\n"
        )
    elif scenario != "lifecycle":
        prefix = source.read_text().split("int main()", 1)[0]
        source.write_text(
            prefix
            + "int main() { var scope = CallbackScope(); var receiver = Receiver(); "
            + ("receiver.fail = true; " if scenario == "failure" else "")
            + "var request = FinishLater(7, receiver, scope); "
            + {"worker": "DrainOnWorker();", "failure": "Drain();", "duplicate": "DrainTwice();"}[scenario]
            + " request.pollCompletion(); return 0; }\n"
        )
    if record:
        content = source.read_text()
        for receiver in ("receiver", "Receiver()"):
            for function in ("FinishNow", "FinishLater"):
                content = content.replace(f"{function}(7, {receiver},", f"{function}(7, makeInfo({receiver}),")
        if "InfoInput makeInfo(" not in content:
            content += "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.marker = 42; info.completion = receiver; return info; }\n"
        source.write_text(content)
    root = source.parent.parent
    plan = root / "Completion.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Completion.c"
    generated.write_text(compiled.c_source)
    executable = root / "Completion"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if scenario == "lifecycle":
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert "PASS: C one-shot native completion" in completed.stdout
    else:
        assert completed.returncode != 0, (completed.stdout, completed.stderr)
        assert {
            "worker": "creating thread",
            "failure": "C completion receiver failed",
            "duplicate": "deliver twice",
            "abandoned-scope": "Callback scope released before cancellation completed",
        }[scenario] in completed.stderr


@pytest.fixture
def c_owned_completion_project(c_one_shot_project):
    source = c_one_shot_project
    root = source.parent.parent
    manifest = root / "btrc.toml"
    context_first = "context-index = 0" in manifest.read_text()
    argument = 1 if context_first else 0
    manifest.write_text(
        manifest.read_text()
        .replace(
            '"DrainTwice"]', '"DrainTwice", "WidgetRef", "WidgetRetain", "WidgetRelease", "WidgetRead", "LiveWidgets"]'
        )
        .replace(
            "[native.bindings.callbacks.", 'borrowed-parameters = ["WidgetRead.widget"]\n[native.bindings.callbacks.', 1
        )
        .replace('cancellation = "abandon"', f'cancellation = "abandon"\nowned-arguments = [{argument}]')
        + '\n[native.bindings.resources.WidgetRef]\nownership = "reference-counted"\n'
        'retain = "WidgetRetain"\nrelease = "WidgetRelease"\n'
    )
    header = root / "Completion.h"
    header.write_text(
        "#include <stdlib.h>\n#include <assert.h>\n"
        "typedef struct Widget { int refs; int value; } *WidgetRef;\n"
        "static int liveWidgets;\n"
        "static inline WidgetRef MakeWidget(int value) { if (!value) return NULL; "
        "WidgetRef widget = malloc(sizeof(*widget)); assert(widget); *widget = (struct Widget){1, value}; "
        "liveWidgets++; return widget; }\n"
        "static inline void WidgetRetain(WidgetRef widget) { assert(widget->refs > 0); widget->refs++; }\n"
        "static inline void WidgetRelease(WidgetRef widget) { assert(widget->refs > 0); "
        "if (--widget->refs == 0) { liveWidgets--; free(widget); } }\n"
        "static inline int WidgetRead(WidgetRef widget) { return widget->value; }\n"
        "static inline int LiveWidgets(void) { return liveWidgets; }\n"
        + header.read_text()
        .replace("(*Completion)(int, void*)", "(*Completion)(WidgetRef, void*)")
        .replace("(*Completion)(void*, int)", "(*Completion)(void*, WidgetRef)")
        .replace("completion(value, context)", "completion(MakeWidget(value), context)")
        .replace("completion(context, value)", "completion(context, MakeWidget(value))")
        .replace("callback(7, context)", "callback(MakeWidget(7), context)")
        .replace("callback(context, 7)", "callback(context, MakeWidget(7))")
    )
    source.write_text("""import Library.Callback;
import ./Completion.btrc;
int delivered = 0;
class Receiver implements ICompletion {
    public WidgetRef? saved;
    public CallbackScope? scope;
    public void invoke(WidgetRef? value) {
        delivered++;
        if (value != null) { assert(WidgetRead(value) == 7); }
        self.saved = value;
        if (self.scope != null) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
    }
}
void verify(bool inlineCall, bool abandon, bool selfCancel) {
    var scope = CallbackScope();
    var receiver = Receiver();
    if (selfCancel) { receiver.scope = scope; }
    int before = delivered;
    var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);
    if (!inlineCall) {
        assert(LiveWidgets() == 0);
        if (abandon) { assert(scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
        Drain();
    }
    assert(request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
    assert(delivered == before + (abandon ? 0 : 1));
    assert(LiveWidgets() == (abandon ? 0 : 1));
    if (!abandon) { assert(receiver.saved != null && WidgetRead(receiver.saved) == 7); }
    receiver.saved = null;
    assert(LiveWidgets() == 0);
    assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
}
int main() {
    verify(true, false, false); verify(false, false, false);
    verify(false, true, false); verify(true, false, true); verify(false, false, true);
    var scope = CallbackScope();
    var receiver = Receiver();
    var request = FinishNow(0, receiver, scope);
    assert(receiver.saved == null && LiveWidgets() == 0);
    assert(request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
    FinishLater(7, Receiver(), scope);
    Drain();
    assert(LiveWidgets() == 0);
    assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE);
    print("PASS: claimed and abandoned native resource completions");
    return 0;
}
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("payloads", [1, 2])
@pytest.mark.parametrize("fails", [False, True], ids=["lifecycle", "receiver-failure"])
def test_c_completion_owned_resource(
    c_owned_completion_project, native_compile, sanitize, payloads, fails, record_contexts=False
):
    source = c_owned_completion_project
    root = source.parent.parent
    if payloads == 2:
        manifest = root / "btrc.toml"
        text = manifest.read_text()
        context_first = "context-index = 0" in text
        text = (
            text.replace("owned-arguments = [1]", "owned-arguments = [1, 2]")
            if context_first
            else text.replace("owned-arguments = [0]", "owned-arguments = [0, 1]").replace(
                "context-index = 1", "context-index = 2"
            )
        )
        manifest.write_text(text)
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("(*Completion)(WidgetRef, void*)", "(*Completion)(WidgetRef, WidgetRef, void*)")
            .replace("(*Completion)(void*, WidgetRef)", "(*Completion)(void*, WidgetRef, WidgetRef)")
            .replace("MakeWidget(value)", "MakeWidget(value), MakeWidget(value ? 8 : 0)")
            .replace("MakeWidget(7)", "MakeWidget(7), MakeWidget(8)")
        )
        source.write_text(
            source.read_text()
            .replace("public WidgetRef? saved;", "public WidgetRef? saved; public WidgetRef? second;")
            .replace("invoke(WidgetRef? value)", "invoke(WidgetRef? value, WidgetRef? second)")
            .replace(
                "self.saved = value;",
                "self.saved = value; self.second = second; if (second != null) { assert(WidgetRead(second) == 8); }",
            )
            .replace("LiveWidgets() == (abandon ? 0 : 1)", "LiveWidgets() == (abandon ? 0 : 2)")
            .replace("receiver.saved = null;", "receiver.saved = null; receiver.second = null;")
        )
    if fails:
        header = root / "Completion.h"
        header.write_text(
            "#include <stdio.h>\n"
            + header.read_text().replace(
                "liveWidgets--; free(widget);", 'liveWidgets--; free(widget); fprintf(stderr, "RESOURCE_FREED\\n");'
            )
        )
        source.write_text(
            source.read_text().replace(
                "delivered++;", 'delivered++; if (value != null) { throw "owned completion failed"; }'
            )
        )
    if record_contexts:
        manifest = root / "btrc.toml"
        text = manifest.read_text()
        context_first = "context-index = 0" in text
        text = text.replace('symbols = ["FinishNow"', 'symbols = ["Info", "FinishNow"')
        text = text.replace(
            '[native.bindings.callbacks."FinishNow.completion"]',
            'owned-records = ["Info"]\nrecord-inputs = ["FinishNow.info", "FinishLater.info"]\n[native.bindings.callbacks."FinishNow.info"]\nfield = "completion"',
        ).replace(
            '[native.bindings.callbacks."FinishLater.completion"]',
            '[native.bindings.callbacks."FinishLater.info"]\nfield = "completion"',
        )
        text = text.replace('context = "context"', 'context = ["context", "second"]')
        native_context = 0 if context_first else payloads
        text = text.replace(f"context-index = {native_context}", f"context-index = [{native_context}, {payloads + 1}]")
        manifest.write_text(text)
        header = root / "Completion.h"
        content = header.read_text()
        end = content.index(";", content.index("typedef void (*Completion)"))
        content = content[: end - 1] + ", void*)" + content[end:]
        end = content.index(";", content.index("typedef void (*Completion)")) + 1
        content = (
            content[:end]
            + "\ntypedef struct Info { Completion completion; void* context; void* second; } Info;\nstatic void* pendingSecond;\n"
            + content[end:]
        )
        content = content.replace("int value, Completion completion, void *context", "int value, Info info")
        content = content.replace("void *context, int value, Completion completion", "int value, Info info")
        content = content.replace(
            "int value, Info info) {",
            "int value, Info info) { Completion completion = info.completion; void* context = info.context;",
        )
        content = content.replace(
            "pending = completion; pendingContext = context;",
            "pending = completion; pendingContext = context; pendingSecond = info.second;",
        )
        content = content.replace(
            "void *context = pendingContext;", "void *context = pendingContext; void* second = pendingSecond;"
        )
        for function, expression, extra in (("completion", "value", "info.second"), ("callback", "7", "second")):
            values = f"MakeWidget({expression})"
            if payloads == 2:
                values += ", MakeWidget(value ? 8 : 0)" if expression == "value" else ", MakeWidget(8)"
            arguments = f"context, {values}" if context_first else f"{values}, context"
            content = content.replace(f"{function}({arguments});", f"{function}({arguments}, {extra});")
        header.write_text(content)
        source.write_text(
            source.read_text()
            .replace(", receiver, scope)", ", makeInfo(receiver), scope)")
            .replace(", Receiver(), scope)", ", makeInfo(Receiver()), scope)")
            + "\nInfoInput makeInfo(ICompletion receiver) { var info = InfoInput(); info.completion = receiver; return info; }\n"
        )
    plan = root / "Resource.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Resource.c"
    generated.write_text(compiled.c_source)
    executable = root / "Resource"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if fails:
        assert completed.returncode != 0
        assert "owned completion failed" in completed.stderr
        assert completed.stderr.count("RESOURCE_FREED") == payloads
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)
        assert "PASS: claimed and abandoned" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("payloads", [1, 2])
@pytest.mark.parametrize("fails", [False, True], ids=["lifecycle", "receiver-failure"])
def test_c_record_completion_multiple_contexts_owned_resources(
    c_owned_completion_project, native_compile, sanitize, payloads, fails
):
    test_c_completion_owned_resource(
        c_owned_completion_project, native_compile, sanitize, payloads, fails, record_contexts=True
    )


@pytest.fixture
def c_string_completion_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "src/Text.btrc").write_text("")
    (root / "Text.h").write_text("""#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
typedef struct Text { const char* data; size_t length; } Text;
typedef void (*Completion)(int, Text, void*, void*);
typedef struct Info { Completion callback; void* first; void* second; } Info;
static Info pending;
static inline void Schedule(Info info) { assert(!pending.callback && info.first && info.first == info.second); pending = info; }
static inline void Complete(int mode) {
    static const unsigned char bytes[] = {'c', 'a', 'f', 0xc3, 0xa9, 0xf0, 0x9f, 0x8e, 0xb8};
    char* storage = malloc(sizeof(bytes)); assert(storage); memcpy(storage, bytes, sizeof(bytes));
    Text text = {storage, sizeof(bytes)};
    if (mode == 1) text = (Text){NULL, 0};
    if (mode == 2) text = (Text){NULL, SIZE_MAX};
    if (mode == 3) text = (Text){(const char*)1, 0};
    if (mode == 4) text = (Text){NULL, 1};
    if (mode == 5) text = (Text){(const char*)1, (size_t)INT32_MAX + 1};
    if (mode == 6) storage[2] = 0;
    if (mode == 7) text = (Text){(const char*)1, SIZE_MAX};
    assert(pending.callback);
    Info info = pending; pending = (Info){0};
    info.callback(7, text, info.first, info.second);
    memset(storage, '?', sizeof(bytes)); free(storage);
}
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "callbackText"
[[native.bindings]]
module = "Text"
header = "Text.h"
language = "c"
standard = "c11"
symbols = ["Text", "Info", "Schedule", "Complete"]
owned-records = ["Info"]
record-inputs = ["Schedule.info"]
[native.bindings.string-views.Text]
data = "data"
length = "length"
null-length = "zero-or-max"
[native.bindings.callbacks."Schedule.info"]
field = "callback"
context = ["first", "second"]
context-index = [2, 3]
interface = "ICompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "scenario",
    [
        "copy",
        "empty",
        "null-max",
        "empty-pointer",
        "cancel",
        "cancel-invalid",
        "zero-null",
        "zero-null-max",
        "null-bad",
        "oversize",
        "embedded-nul",
        "nonnull-max",
        "receiver-failure",
    ],
)
def test_c_completion_copies_borrowed_string(
    c_string_completion_project, native_compile, sanitize, scenario, sdk=False
):
    source = c_string_completion_project
    root = source.parent.parent
    if scenario in {"zero-null", "zero-null-max"}:
        manifest = root / "btrc.toml"
        manifest.write_text(manifest.read_text().replace('null-length = "zero-or-max"', 'null-length = "zero"'))
    if sdk:
        header = root / "Text.h"
        header.write_text(
            header.read_text().replace(
                "typedef struct Text { const char* data; size_t length; } Text;",
                "#include <webgpu.h>\ntypedef WGPUStringView Text;",
            )
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Text"]\n'
        )
    mode = {
        "empty": 1,
        "null-max": 2,
        "empty-pointer": 3,
        "null-bad": 4,
        "oversize": 5,
        "embedded-nul": 6,
        "nonnull-max": 7,
        "cancel-invalid": 7,
        "zero-null": 1,
        "zero-null-max": 2,
    }.get(scenario, 0)
    canceled = scenario in {"cancel", "cancel-invalid"}
    cancel = "scope.cancel();" if canceled else ""
    throws = 'if (status == 7) { throw "text receiver failed"; }' if scenario == "receiver-failure" else ""
    expected = "" if canceled or scenario in {"empty", "null-max", "empty-pointer", "zero-null"} else "café🎸"
    source.write_text(
        "import Library.Callback;\nimport ./Text.btrc;\n"
        'int delivered = 0;\nclass Receiver implements ICompletion {\n\tpublic string saved = "";\n'
        f"\tpublic void invoke(int status, string message) {{ assert(status == 7); {throws} self.saved = message; delivered++; }}\n}}\n"
        "int main() {\n\tvar receiver = Receiver();\n\tvar baseline = __btrc_string_live_count();\n"
        "\tfor (int index = 0; index < 30; index++) {\n\t\tvar scope = CallbackScope(); var info = InfoInput(); info.callback = receiver;\n"
        f"\t\tvar schedule = Schedule; var request = schedule(info, scope); release info; {cancel} Complete({mode});\n"
        f"\t\tassert(receiver.saved == {json.dumps(expected, ensure_ascii=False)});\n"
        f"\t\tassert(delivered == {'0' if canceled else 'index + 1'});\n"
        "\t\tassert(request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);\n"
        '\t\tassert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE); receiver.saved = "";\n'
        "\t\tassert(__btrc_string_live_count() == baseline);\n\t}\n\treturn 0;\n}\n"
    )
    plan = root / "Text.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Text.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Text"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    if scenario in {"null-bad", "oversize", "embedded-nul", "nonnull-max", "zero-null-max", "receiver-failure"}:
        assert completed.returncode != 0
        assert ("text receiver failed" if scenario == "receiver-failure" else "Native string view:") in completed.stderr
        assert "ERROR: AddressSanitizer" not in completed.stderr
    else:
        assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["copy", "null-max", "cancel", "nonnull-max"])
def test_c_completion_copies_webgpu_string(c_string_completion_project, native_compile, sanitize, scenario):
    test_c_completion_copies_borrowed_string(c_string_completion_project, native_compile, sanitize, scenario, sdk=True)


@pytest.mark.parametrize("conflict", [False, True])
def test_c_completion_string_view_alias_identity(c_string_completion_project, native_compile, conflict):
    source = c_string_completion_project
    root = source.parent.parent
    header = root / "Text.h"
    header.write_text(
        header.read_text().replace("typedef void (*Completion)", "typedef Text Alias;\ntypedef void (*Completion)")
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace('symbols = ["Text",', 'symbols = ["Text", "Alias",')
        + '\n[native.bindings.string-views.Alias]\ndata = "data"\nlength = "length"\n'
        + f'null-length = "{"zero" if conflict else "zero-or-max"}"\n'
    )
    if conflict:
        source.write_text("import Library.Callback;\nimport ./Text.btrc;\nint main() { return 0; }\n")
        result = native_compile(source)
        assert not result.successful and not result.c_source
        assert "conflicting string-view mappings" in str(result.failure), result.failure
    else:
        test_c_completion_copies_borrowed_string(source, native_compile, True, "copy")


@pytest.mark.parametrize(
    "scenario",
    [
        "missing-field",
        "same-field",
        "unknown-field",
        "unknown-fact",
        "empty",
        "extra-field",
        "not-pointer",
        "not-char",
        "signed-length",
        "float-length",
        "volatile-data",
        "volatile-length",
        "null-policy",
        "call-scoped",
        "unused",
    ],
)
def test_c_completion_rejects_invalid_string_view(c_string_completion_project, native_compile, scenario):
    source = c_string_completion_project
    root = source.parent.parent
    source.write_text("import Library.Callback;\nimport ./Text.btrc;\nint main() { return 0; }\n")
    header = root / "Text.h"
    manifest = root / "btrc.toml"
    text = manifest.read_text()
    replacements = {
        "missing-field": ('length = "length"\n', ""),
        "same-field": ('length = "length"', 'length = "data"'),
        "unknown-field": ('data = "data"', 'data = "absent"'),
        "unknown-fact": ('data = "data"', 'unknown = "data"'),
        "null-policy": ('null-length = "zero-or-max"', 'null-length = "guess"'),
        "empty": ('data = "data"\nlength = "length"\nnull-length = "zero-or-max"\n', ""),
    }
    native_replacements = {
        "extra-field": ("size_t length;", "size_t length; int extra;"),
        "not-pointer": ("const char* data", "size_t data"),
        "not-char": ("const char* data", "const int* data"),
        "signed-length": ("size_t length", "long length"),
        "float-length": ("size_t length", "double length"),
        "volatile-data": ("const char* data", "const volatile char* data"),
        "volatile-length": ("size_t length", "volatile size_t length"),
    }
    if scenario in native_replacements:
        # Import declarations only: deliberately invalid shapes must be rejected
        # by the BTRC binding validator, not by a malformed C test implementation.
        native = header.read_text().split("static Info pending;", 1)[0]
        before, after = native_replacements[scenario]
        header.write_text(native.replace(before, after) + "void Schedule(Info info); void Complete(int mode);\n")
    elif scenario == "unused":
        text = text.split('[native.bindings.callbacks."Schedule.info"]')[0]
        text = text.replace('symbols = ["Text", "Info", "Schedule", "Complete"]', 'symbols = ["Text"]')
        text = text.replace('owned-records = ["Info"]\nrecord-inputs = ["Schedule.info"]\n', "")
    elif scenario == "call-scoped":
        text = text.replace('lifetime = "one-shot"', 'lifetime = "call"').replace('field = "callback"\n', "")
        text = text.replace('activation-failure = "abort"\ncancellation = "abandon"\n', "")
        text = text.replace('context = ["first", "second"]', 'context = "second"').replace(
            "context-index = [2, 3]", "context-index = 2"
        )
        text = text.replace('owned-records = ["Info"]\nrecord-inputs = ["Schedule.info"]\n', "")
        text = text.replace('"Schedule.info"', '"Schedule.callback"')
        header.write_text(
            "#include <stddef.h>\ntypedef struct Text { const char* data; size_t length; } Text;\n"
            "typedef void (*Completion)(int, Text, void*); typedef struct Info { int unused; } Info;\n"
            "void Schedule(Completion callback, void* second); void Complete(int mode);\n"
        )
    else:
        before, after = replacements[scenario]
        text = text.replace(before, after)
    manifest.write_text(text)
    plan = root / "Invalid.link.json"
    result = native_compile(source, plan_path=plan)
    assert not result.successful and not result.c_source
    assert "string" in str(result.failure), (result.failure, result.diagnostics)
    assert not plan.exists()


@pytest.fixture
def c_future_project(c_owned_completion_project):
    source = c_owned_completion_project
    root = source.parent.parent
    header = root / "Completion.h"
    text = header.read_text()
    text = "#include <stdint.h>\ntypedef struct RequestTicket { uint64_t id; } RequestTicket;\n" + text
    text = text.replace("static inline void Finish", "static inline RequestTicket Finish")
    text = text.replace(
        "completion(MakeWidget(value), context); }",
        "completion(MakeWidget(value), context); return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    text = text.replace(
        "completion(context, MakeWidget(value)); }",
        "completion(context, MakeWidget(value)); return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    text = text.replace(
        "pendingContext = context; }",
        "pendingContext = context; return (RequestTicket){UINT64_C(4294967296) + value}; }",
    )
    header.write_text(text)
    text = source.read_text()
    text = text.replace(
        "var request = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope);",
        "var started = inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope); "
        "var request = started.request; assert(started.value.id == 4294967303ULL);",
    )
    text = text.replace(
        "var request = FinishNow(0, receiver, scope);",
        "var started = FinishNow(0, receiver, scope); var request = started.request; assert(started.value.id == 4294967296ULL);",
    )
    source.write_text(text)
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("result_kind", ["record", "scalar", "nested", "zero", "webgpu"])
def test_c_completion_preserves_native_future(c_future_project, native_compile, sanitize, indirect, result_kind):
    source = c_future_project
    root = source.parent.parent
    text = source.read_text()
    if indirect:
        text = text.replace(
            "int before = delivered;", "int before = delivered; var beginNow = FinishNow; var beginLater = FinishLater;"
        )
        text = text.replace(
            "inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope)",
            "inlineCall ? beginNow(7, receiver, scope) : beginLater(7, receiver, scope)",
        )
    header = root / "Completion.h"
    native = header.read_text()
    if result_kind == "scalar":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;", "typedef uint64_t RequestTicket;"
        )
        text = text.replace("started.value.id", "started.value")
    elif result_kind == "nested":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;",
            "typedef struct TicketIdentity { uint64_t id; } TicketIdentity; typedef struct RequestTicket { TicketIdentity identity; } RequestTicket;",
        )
        native = native.replace(
            "(RequestTicket){UINT64_C(4294967296) + value}", "(RequestTicket){{UINT64_C(4294967296) + value}}"
        )
        text = text.replace("started.value.id", "started.value.identity.id")
    elif result_kind == "zero":
        native = native.replace("(RequestTicket){UINT64_C(4294967296) + value}", "(RequestTicket){0}")
        text = text.replace("4294967303ULL", "0ULL").replace("4294967296ULL", "0ULL")
    elif result_kind == "webgpu":
        native = native.replace(
            "typedef struct RequestTicket { uint64_t id; } RequestTicket;",
            "#include <webgpu.h>\ntypedef WGPUFuture RequestTicket;",
        )
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text() + '\n[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Completion"]\n'
        )
    header.write_text(native)
    source.write_text(text)
    plan = root / "Future.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Future.c"
    generated.write_text(compiled.c_source)
    executable = root / "Future"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "PASS: claimed and abandoned" in completed.stdout


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("indirect", [False, True])
@pytest.mark.parametrize("future", [False, True])
def test_c_completion_future_releases_all_allocations(c_future_project, native_compile, sanitize, indirect, future):
    source = c_future_project
    root = source.parent.parent
    program = source.read_text().replace("int main() {", "int exercise() {")
    if not future:
        header = root / "Completion.h"
        header.write_text(
            header.read_text()
            .replace("static inline RequestTicket Finish", "static inline void Finish")
            .replace("return (RequestTicket){UINT64_C(4294967296) + value};", "return;")
        )
        program = program.replace(
            "var request = started.request; assert(started.value.id == 4294967303ULL);", "var request = started;"
        )
        program = program.replace(
            "var request = started.request; assert(started.value.id == 4294967296ULL);", "var request = started;"
        )
    if indirect:
        program = program.replace(
            "int before = delivered;", "int before = delivered; var beginNow = FinishNow; var beginLater = FinishLater;"
        )
        program = program.replace(
            "inlineCall ? FinishNow(7, receiver, scope) : FinishLater(7, receiver, scope)",
            "inlineCall ? beginNow(7, receiver, scope) : beginLater(7, receiver, scope)",
        )
    source.write_text(
        program
        + """
extern void arc_test_allocation_checkpoint();
extern long arc_test_allocation_delta();
void throwAfterCompletion() {
	var scope = CallbackScope(); var receiver = Receiver();
	var started = FinishNow(7, receiver, scope);
	assert(started.value.id == 4294967303ULL);
	assert(started.request.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
	throw "expected";
}
void exerciseExceptions() {
	bool caught = false;
	try { throwAfterCompletion(); } catch (string error) { caught = error == "expected"; }
	assert(caught && LiveWidgets() == 0);
}
int main() {
	for (int index = 0; index < 10; index++) { assert(exercise() == 0); exerciseExceptions(); }
	arc_test_allocation_checkpoint();
	for (int index = 0; index < 20; index++) { assert(exercise() == 0); exerciseExceptions(); }
	long remaining = arc_test_allocation_delta();
	print(f"Remaining allocations: {remaining}");
	assert(remaining == 0L); return 0;
}
"""
    )
    if not future:
        source.write_text(
            source.read_text()
            .replace("assert(started.value.id == 4294967303ULL);", "")
            .replace("started.request.pollCompletion()", "started.pollCompletion()")
        )
    plan = root / "Tracked.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    generated = root / "Tracked.c"
    generated.write_text(result.c_source)
    tracker = REPO / "src/tests/btrc/fixtures/arc_boundary_alloc_tracker.c"
    tracker_object = root / "Tracker.o"
    flags = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
    built = subprocess.run(
        ["/usr/bin/clang", *flags, "-c", str(tracker), "-o", str(tracker_object)],
        env=apple_environment(),
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr

    def runner(command, **kwargs):
        if Path(command[0]).name not in {"clang", "clang++"}:
            return subprocess.run(command, env=apple_environment(), **kwargs)
        redirects = [f"-D{name}=btrc_test_{name}" for name in ("malloc", "calloc", "realloc", "free")]
        objects = [] if "-c" in command else [str(tracker_object)]
        return subprocess.run(
            [command[0], *flags, *redirects, *command[1:], *objects], env=apple_environment(), **kwargs
        )

    executable = root / "Tracked"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)


@pytest.mark.parametrize("shape", ["pointer", "record-pointer", "nested-pointer", "union"])
def test_c_completion_rejects_unowned_future_storage(c_future_project, native_compile, shape):
    source = c_future_project
    root = source.parent.parent
    header = root / "Completion.h"
    declaration, initializer = {
        "pointer": ("typedef void* RequestTicket;", "NULL"),
        "record-pointer": ("typedef struct RequestTicket { void* hidden; } RequestTicket;", "(RequestTicket){NULL}"),
        "nested-pointer": (
            "typedef struct TicketStorage { void* hidden; } TicketStorage; typedef struct RequestTicket { TicketStorage storage; } RequestTicket;",
            "(RequestTicket){{NULL}}",
        ),
        "union": (
            "typedef union RequestTicket { uint64_t id; double number; } RequestTicket;",
            "(RequestTicket){UINT64_C(4294967296) + value}",
        ),
    }[shape]
    header.write_text(
        header.read_text()
        .replace("typedef struct RequestTicket { uint64_t id; } RequestTicket;", declaration)
        .replace("(RequestTicket){UINT64_C(4294967296) + value}", initializer)
    )
    source.write_text("import Library.Callback;\nimport ./Completion.btrc;\nint main() { return 0; }\n")
    plan = root / "Rejected.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert not compiled.successful
    assert "pointer-free scalar or record value" in (str(compiled.failure) + str(compiled.diagnostics))
    assert not plan.exists()


@pytest.mark.parametrize("scenario", ["missing", "context", "outside", "duplicate", "boolean", "string", "call"])
def test_c_completion_resource_rejects_invalid_ownership(c_owned_completion_project, native_compile, scenario):
    source = c_owned_completion_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    context = 0 if "context-index = 0" in text else 1
    argument = 1 - context
    replacement = {
        "missing": "",
        "context": f"owned-arguments = [{context}]",
        "outside": "owned-arguments = [2]",
        "duplicate": f"owned-arguments = [{argument}, {argument}]",
        "boolean": "owned-arguments = [true]",
        "string": 'owned-arguments = ["0"]',
        "call": f"owned-arguments = [{argument}]",
    }[scenario]
    text = text.replace(f"owned-arguments = [{argument}]", replacement)
    if scenario == "call":
        text = text.replace('lifetime = "one-shot"', 'lifetime = "call"')
        text = text.replace('activation-failure = "abort"\n', "").replace('cancellation = "abandon"\n', "")
    manifest.write_text(text)
    result = native_compile(source)
    assert not result.successful
    expected = {
        "missing": "non-scalar arguments",
        "context": "resource payload parameters",
        "outside": "resource payload parameters",
        "duplicate": "distinct nonnegative native parameter indices",
        "boolean": "distinct nonnegative native parameter indices",
        "string": "distinct nonnegative native parameter indices",
        "call": "requires a C one-shot callback",
    }[scenario]
    assert expected in (str(result.failure) + str(result.diagnostics))


def test_c_completion_rejects_scalar_ownership(c_one_shot_project, native_compile):
    source = c_one_shot_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    argument = 1 if "context-index = 0" in text else 0
    manifest.write_text(
        text.replace('cancellation = "abandon"', f'cancellation = "abandon"\nowned-arguments = [{argument}]')
    )
    result = native_compile(source)
    assert not result.successful
    assert "requires a declared native resource" in (str(result.failure) + str(result.diagnostics))
