"""Registration-owned SDK leases expose only invocation-local RT operations."""

from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.python.test_native_import_consumer import resource_project as resource_project
from src.tests.python.test_native_import_consumer import run_native_executable
from src.tests.python.test_native_unique_resources import unique_project as unique_project


@pytest.fixture
def realtime_project(unique_project):
    source, sdk, triple = unique_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        + """
#include <stdio.h>
#include <pthread.h>
#include <stdatomic.h>
typedef int (*RenderProc)(void* context, unsigned frames, float* samples);
typedef struct RenderRecord { RenderProc render; void* context; } RenderRecord;
static RenderRecord savedRender;
static int stopResult;
static int stopCalls;
static int inputCalls;
static _Atomic int asyncEntered;
static _Atomic int asyncReleased;
static _Atomic int asyncEnabled;
static pthread_t renderThread;
static inline int InstallRender(WidgetRef owner, unsigned property, const void* data, unsigned size) {
    assert(owner && property == 1 && size == sizeof(RenderRecord));
    const RenderRecord* record = data;
    savedRender = *record;
    float samples[1] = {0};
    return record->render(record->context, 1, samples);
}
static inline int StopRender(WidgetRef owner) {
    assert(owner); stopCalls++;
    if (!stopResult) { savedRender.context = NULL; }
    return stopResult;
}
static inline int RenderInput(WidgetRef owner, unsigned frames, float* samples) {
    assert(owner && frames == 1); inputCalls++;
    if (atomic_load(&asyncEnabled)) {
        atomic_store(&asyncEntered, 1);
        while (!atomic_load(&asyncReleased)) {}
    }
    samples[0] = 3; return 0;
}
static void* runAsyncRender(void* ignored) {
    (void)ignored; RenderRecord record = savedRender; float samples[1] = {0};
    assert(record.render(record.context, 1, samples) == 0 && samples[0] == 3);
    return NULL;
}
static inline void StartAsyncRender(void) {
    atomic_store(&asyncEnabled, 1);
    assert(pthread_create(&renderThread, NULL, runAsyncRender, NULL) == 0);
    while (!atomic_load(&asyncEntered)) {}
}
static inline void ReleaseAsyncRender(void) {
    atomic_store(&asyncReleased, 1);
    assert(pthread_join(renderThread, NULL) == 0);
}
static inline void FailStop(void) { stopResult = -7; }
static inline void VerifyLateSilence(void) {
    float samples[1] = {42}; int before = inputCalls;
    assert(savedRender.context && stopCalls == 1);
    assert(savedRender.render(savedRender.context, 1, samples) == 0);
    assert(samples[0] == 0 && inputCalls == before);
    fprintf(stderr, "late silence verified\\n");
}
"""
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            "symbols = [",
            'symbols = ["RenderRecord", "InstallRender", "StopRender", "RenderInput", "FailStop", "VerifyLateSilence", "StartAsyncRender", "ReleaseAsyncRender", ',
        )
        .replace(
            "borrowed-parameters = [",
            'borrowed-parameters = ["InstallRender.owner", "StopRender.owner", "RenderInput.owner", ',
        )
        .replace("[native.bindings.resources.", 'realtime-safe = ["RenderInput"]\n[native.bindings.resources.', 1)
        + """
[native.bindings.callbacks."InstallRender.data"]
name = "installRender"
record = "RenderRecord"
field = "render"
context = "context"
context-index = 0
size = "size"
interface = "IRender"
invocation = "RenderInvocation"
lifetime = "stored"
executor = "realtime"
failure = "abort"
owner = "owner"
unregister = "StopRender"
cancellation = "entry-barrier"
activation-failure = "abort"
[native.bindings.callbacks."InstallRender.data".operations]
input = "RenderInput.owner"
"""
    )
    source.write_text("import ./Foundation.btrc;\nimport Library.Callback;\nint main() { return 0; }\n")
    return source, sdk, triple


def frontend(source):
    return Compiler().compile_frontend(source.read_text(), str(source), CompilerOptions(include_stdlib=False))


def test_realtime_callback_projects_exact_sdk_contract(realtime_project):
    source, _, _ = realtime_project
    result = frontend(source)
    assert not result.analyzed.errors, result.analyzed.errors
    analyzed = result.analyzed
    assert "RenderInvocation" in analyzed.class_table
    assert "input" in analyzed.class_table["RenderInvocation"].methods
    assert "IRender" in analyzed.interface_table
    assert "RenderInput" not in analyzed.function_table


def test_realtime_invocation_operations_are_effect_checked(realtime_project, native_compile):
    source, _, _ = realtime_project
    source.write_text(
        source.read_text()
        + """
class Renderer implements IRender {
    public @realtime int invoke(RenderInvocation invocation, unsigned int frames, float* samples) {
        return invocation.input(frames, samples);
    }
}
"""
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    "body",
    [
        "var alias = invocation; return 0;",
        "keep invocation; return 0;",
        "release invocation; return 0;",
        "var pointer = (void*)invocation; return 0;",
        "var address = &invocation; return 0;",
        "forward(invocation); return 0;",
        "var callback = invocation.input; return 0;",
        "return invocation == invocation ? 0 : 1;",
        "var boxed = [invocation]; return 0;",
    ],
)
def test_realtime_invocation_cannot_escape(realtime_project, native_compile, body):
    source, _, _ = realtime_project
    helper = (
        "@realtime int forward(RenderInvocation value) { keep value; return 0; }" if body.startswith("forward(") else ""
    )
    source.write_text(
        source.read_text()
        + f"""
{helper}
class Renderer implements IRender {{
    public @realtime int invoke(RenderInvocation invocation, unsigned int frames, float* samples) {{ {body} }}
}}
"""
    )
    result = native_compile(source)
    assert not result.successful
    assert "cannot escape or be reinterpreted" in str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize(
    "declaration",
    [
        "class Holder { public RenderInvocation value; }",
        "RenderInvocation? stored;",
        "RenderInvocation returnCapability() { return null; }",
        "void indirect(RenderInvocation* value) {}",
        "class Child extends RenderInvocation {}",
        "@realtime int fake(RenderInvocation value) { return 0; } int fabricate() { return fake(null); }",
    ],
)
def test_realtime_invocation_has_no_owned_storage(realtime_project, native_compile, declaration):
    source, _, _ = realtime_project
    source.write_text(source.read_text() + declaration)
    result = native_compile(source)
    assert not result.successful
    assert "Native invocation" in str(result.failure) + str(result.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("mode", ["normal", "indeterminate", "active-close", "last-owner", "in-flight"])
def test_realtime_registration_native_invocation(realtime_project, native_compile, sanitize, mode):
    source, sdk, triple = realtime_project
    program = """import ./Foundation.btrc;
import Library.Callback;
class Renderer implements IRender {
    public @realtime int invoke(RenderInvocation invocation, unsigned int frames, float* samples) {
        return invocation.input(frames, samples);
    }
}
@realtime int silence(unsigned int frames, float* samples) { samples[0] = 0.0f; return 0; }
int main() {
    var owner = WidgetCreate(7);
    var scope = new CallbackScope();
    var receiver = new Renderer();
    var registration = installRender(owner, 1u, receiver, silence, scope);
    assert(registration.isOpen());
    // MODE
    assert(scope.cancel() == CallbackCancellation.Complete);
    assert(scope.pendingCount() == 0);
    owner.close();
    assert(WidgetLive() == 0);
    return 0;
}
"""
    expected = None
    if mode == "indeterminate":
        program = (
            program.split("// MODE", 1)[0]
            + "FailStop(); assert(scope.cancel() == CallbackCancellation.Failed); assert(scope.pollCompletion() == CallbackCancellation.Failed); VerifyLateSilence(); return 0; }"
        )
        expected = "Callback scope released before cancellation completed"
    elif mode == "active-close":
        program = program.replace("// MODE", "owner.close();")
        expected = "close during borrow"
    elif mode == "last-owner":
        program = program.replace("// MODE", "release owner;").replace("owner.close();", "")
    elif mode == "in-flight":
        program = program.replace(
            "// MODE",
            "StartAsyncRender(); assert(scope.cancel() == CallbackCancellation.Pending); "
            "assert(WidgetLive() == 1); ReleaseAsyncRender(); "
            "assert(scope.pollCompletion() == CallbackCancellation.Complete);",
        )
    source.write_text(program)
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    ran = run_native_executable(
        result.c_source, source.parent.parent, sdk, triple, sanitize, frameworks=(), expected_failure=expected
    )
    if mode == "indeterminate":
        assert "late silence verified" in ran.stderr


@pytest.mark.parametrize("sanitize", [False, True])
def test_audio_unit_typed_realtime_sdk_callback(native_project, native_compile, sanitize):
    source, sdk, triple = native_project
    root = source.parent.parent
    faults = Path(__file__).resolve().parents[1] / "native/core_audio_device/UnitFaults.c"
    (root / "Foundation.h").write_text(f'#include "{faults}"\n')
    (source.parent / "Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "audioRealtime"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "c"
standard = "c11"
symbols = ["AudioComponent", "AudioComponentInstance", "AudioComponentDescription", "AudioTimeStamp", "AudioBufferList", "AURenderCallbackStruct", "unitFind", "unitNew", "unitDispose", "unitReset", "unitSet", "unitInitialize", "unitUninitialize", "unitStart", "unitStop", "unitRender", "unitDeliver", "unitOutput", "unitRegistrations", "unitDisposals", "kAudioUnitType_Output", "kAudioUnitSubType_HALOutput", "kAudioUnitManufacturer_Apple", "kAudioOutputUnitProperty_EnableIO", "kAudioUnitScope_Input", "kAudioUnitProperty_SetRenderCallback"]
borrowed-parameters = ["unitSet.unit", "unitInitialize.unit", "unitUninitialize.unit", "unitStart.unit", "unitStop.unit", "unitRender.unit"]
realtime-safe = ["unitRender"]
[native.bindings.resources.AudioComponentInstance]
ownership = "unique"
release = "unitDispose"
release-consumption = "success-or-indeterminate"
cleanup-status = "abort"
[native.bindings.owned-outputs."unitNew.result"]
result = "AudioUnitOpenResult"
[native.bindings.callbacks."unitSet.value"]
name = "installRender"
record = "AURenderCallbackStruct"
field = "inputProc"
context = "inputProcRefCon"
context-index = 0
size = "size"
interface = "IRender"
invocation = "RenderInvocation"
lifetime = "stored"
executor = "realtime"
failure = "abort"
owner = "unit"
unregister = "unitStop"
cancellation = "entry-barrier"
activation-failure = "abort"
[native.bindings.callbacks."unitSet.value".operations]
input = "unitRender.unit"
""")
    source.write_text("""import ./Foundation.btrc;
import Library.Callback;
class Renderer implements IRender {
    public @realtime OSStatus invoke(RenderInvocation invocation, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* time, UInt32 bus, UInt32 frames, AudioBufferList? output) {
        if (output == null) { return 0; }
        return invocation.input(flags, time, 1u, frames, output);
    }
}
@realtime OSStatus silence(AudioUnitRenderActionFlags* flags, const AudioTimeStamp* time, UInt32 bus, UInt32 frames, AudioBufferList? output) { return 0; }
int main() {
    unitReset(0);
    AudioComponentDescription description = {kAudioUnitType_Output, kAudioUnitSubType_HALOutput, kAudioUnitManufacturer_Apple, 0u, 0u};
    var result = unitNew(unitFind(null, &description));
    assert(result.status == 0 && result.value != null);
    var unit = result.value; release result;
    UInt32 enabled = 1u;
    assert(unitSet(unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1u, &enabled, (UInt32)sizeof(UInt32)) == 0);
    assert(unitInitialize(unit) == 0 && unitRegistrations() == 0);
    var scope = new CallbackScope();
    var registration = installRender(unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0u, new Renderer(), silence, scope);
    assert(unitRegistrations() == 1 && unitStart(unit) == 0);
    unitDeliver(1, 1, 0);
    assert(unitOutput(0) == 0.25f && unitOutput(2) == 2.25f);
    assert(scope.cancel() == CallbackCancellation.Complete);
    assert(unitUninitialize(unit) == 0 && unit.close() == 0 && unitDisposals() == 1);
    return 0;
}
""")
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    run_native_executable(result.c_source, root, sdk, triple, sanitize, frameworks=("AudioToolbox", "CoreAudio"))
