"""Realtime contracts on native calls, through to a real AudioUnit render callback."""

import json

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_import_fixtures import run_native_executable


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("null_argument", [False, True])
@pytest.mark.parametrize("boundary", ["argument", "return"])
def test_native_realtime_contract_checks_nullable_boundary_without_logging(
    native_project, native_compile, tmp_path, sanitized, null_argument, boundary
):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["nativeRead"]\nrealtime-safe = ["nativeRead"]',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        '#pragma clang diagnostic ignored "-Wnullability-extension"\n'
        + (
            "static inline int nativeRead(const int * _Nonnull value) { return *value; }\n"
            if boundary == "argument"
            else "static inline const int * _Nonnull nativeRead(const int * _Nullable value) { return value; }\n"
        )
    )
    (source.parent / "Foundation.btrc").write_text(
        ("@realtime int readValue" if boundary == "argument" else "@realtime const int* readValue")
        + "(const int* value) { return nativeRead(value); }\nint verifyFoundation() { "
        + ("" if null_argument else "int value = 42; ")
        + ("return readValue(" if boundary == "argument" else "return *readValue(")
        + ("null" if null_argument else "&value")
        + ") == 42 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    assert "__builtin_trap()" in result.c_source
    assert "Native call nativeRead:" not in result.c_source
    run_native_executable(
        result.c_source,
        tmp_path,
        sdk,
        triple,
        sanitized,
        frameworks=(),
        expected_failure="" if null_argument else None,
    )


@pytest.mark.parametrize(
    "contract, body, message",
    [
        ("[]", "return nativeRead(value);", "bodyless"),
        ('["nativeRead"]', "print(1); return nativeRead(value);", "@realtime"),
        ('["nativeRead"]', "while (*value > 0) { } return nativeRead(value);", "@realtime"),
        ('["nativeRead"]', "CFunction<int, const int*> callback = nativeRead; return callback(value);", "@realtime"),
        ('["Missing"]', "return 0;", "selected function"),
        ('["nativeRead", "nativeRead"]', "return 0;", "duplicate"),
        ('"nativeRead"', "return 0;", "array"),
        ('["NativeValue"]', "return 0;", "non-function"),
    ],
)
def test_native_realtime_contract_is_explicit_and_does_not_hide_wrapper_effects(
    native_project, native_compile, tmp_path, contract, body, message
):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            f'symbols = ["nativeRead", "NativeValue"]\nrealtime-safe = {contract}',
        )
    )
    (tmp_path / "Foundation.h").write_text(
        "static inline int nativeRead(const int *value) { return *value; }\nenum { NativeValue = 42 };\n"
    )
    (source.parent / "Foundation.btrc").write_text(
        f"@realtime int readValue(const int* value) {{ {body} }}\n"
        "int verifyFoundation() { int value = 42; return readValue(&value); }\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert message in str(result.failure) + str(result.diagnostics)


def test_native_realtime_contract_cannot_override_known_blocking_sdk_call(native_project, native_compile, tmp_path):
    source, _sdk, _triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["pthread_join"]\nrealtime-safe = ["pthread_join"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <pthread.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        "@realtime int joinWorker(pthread_t worker) { return pthread_join(worker, null); }\n"
        "int verifyFoundation() { return 0; }\n"
    )
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "blocking" in str(result.failure) + str(result.diagnostics)


def test_native_realtime_sdk_clock_executes_with_actual_header_types(native_project, native_compile, tmp_path):
    source, sdk, triple = native_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            'symbols = ["AudioGetCurrentHostTime", "AudioConvertHostTimeToNanos"]\n'
            'realtime-safe = ["AudioGetCurrentHostTime", "AudioConvertHostTimeToNanos"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <CoreAudio/HostTime.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        "@realtime unsigned long long readClock() { return AudioConvertHostTimeToNanos(AudioGetCurrentHostTime()); }\n"
        "int verifyFoundation() { return readClock() > 0 ? 0 : 1; }\n"
    )
    result = native_compile(source)
    assert result.successful, (result.failure, result.diagnostics)
    run_native_executable(result.c_source, tmp_path, sdk, triple, False, frameworks=("CoreAudio",))


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("with_callback", [False, True])
def test_native_realtime_audio_unit_renders_without_handwritten_adapter(
    native_project, native_compile, tmp_path, sanitized, with_callback
):
    source, sdk, triple = native_project
    symbols = [
        "AudioComponentDescription",
        "AudioComponentFindNext",
        "AudioComponentInstanceNew",
        "AudioComponentInstanceDispose",
        "AudioUnitInitialize",
        "AudioUnitUninitialize",
        "AudioUnitSetProperty",
        "AudioUnitRender",
        "AudioStreamBasicDescription",
        "AudioTimeStamp",
        "AudioBufferList",
        "AudioBuffer",
        "kAudioUnitType_Mixer",
        "kAudioUnitSubType_MultiChannelMixer",
        "kAudioUnitManufacturer_Apple",
        "kAudioUnitProperty_StreamFormat",
        "kAudioUnitScope_Output",
        "kAudioFormatLinearPCM",
        "kAudioFormatFlagIsFloat",
        "kAudioFormatFlagIsPacked",
        "kAudioFormatFlagIsNonInterleaved",
        "kAudioTimeStampSampleTimeValid",
        "AURenderCallbackStruct",
        "kAudioUnitProperty_SetRenderCallback",
        "kAudioUnitScope_Input",
        "kAudioUnitRenderAction_OutputIsSilence",
        "AudioUnitSetParameter",
        "kAudioUnitProperty_ElementCount",
        "kMultiChannelMixerParam_Enable",
        "kMultiChannelMixerParam_Volume",
    ]
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["CFStringCreateWithCString", "CFStringGetLength", "CFRelease", "kCFStringEncodingUTF8"]',
            f'symbols = {json.dumps(symbols)}\nrealtime-safe = ["AudioUnitRender"]',
        )
    )
    (tmp_path / "Foundation.h").write_text("#include <AudioToolbox/AudioToolbox.h>\n")
    (source.parent / "Foundation.btrc").write_text(
        """struct InputContext { float* samples; uint calls; };

@realtime OSStatus supplyInput(void* context, AudioUnitRenderActionFlags* flags, const AudioTimeStamp* time, UInt32 bus, UInt32 frames, AudioBufferList* buffers) {
	if (context == null || buffers == null || frames > 16u || buffers->mNumberBuffers != 1u) { return -50; }
	InputContext* input = (InputContext*)context;
	input->calls++;
	buffers->mBuffers[0].mData = input->samples;
	buffers->mBuffers[0].mNumberChannels = 1u;
	buffers->mBuffers[0].mDataByteSize = frames * 4u;
	if (flags != null) { *flags = *flags & ~(uint)kAudioUnitRenderAction_OutputIsSilence; }
	return 0;
}

@realtime int renderSamples(AudioUnit unit, const AudioTimeStamp* time, AudioBufferList* buffers) {
	return AudioUnitRender(unit, null, time, 0u, 16u, buffers);
}

int verifyFoundation() {
	bool withCallback = WITH_CALLBACK;
	AudioComponentDescription description;
	memset(&description, 0, sizeof(AudioComponentDescription));
	description.componentType = kAudioUnitType_Mixer;
	description.componentSubType = kAudioUnitSubType_MultiChannelMixer;
	description.componentManufacturer = kAudioUnitManufacturer_Apple;
	var component = AudioComponentFindNext(null, &description);
	if (component == null) { return 1; }
	AudioUnit unit = null;
	if (AudioComponentInstanceNew(component, &unit) != 0 || unit == null) { return 2; }
	UInt32 inputs = withCallback ? 1u : 0u;
	if (AudioUnitSetProperty(unit, kAudioUnitProperty_ElementCount, kAudioUnitScope_Input, 0u, &inputs, (uint)sizeof(UInt32)) != 0) { AudioComponentInstanceDispose(unit); return 12; }
	AudioStreamBasicDescription format;
	memset(&format, 0, sizeof(AudioStreamBasicDescription));
	format.mSampleRate = 48000.0;
	format.mFormatID = kAudioFormatLinearPCM;
	format.mFormatFlags = kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked | kAudioFormatFlagIsNonInterleaved;
	format.mBytesPerPacket = 4u; format.mFramesPerPacket = 1u;
	format.mBytesPerFrame = 4u; format.mChannelsPerFrame = 1u; format.mBitsPerChannel = 32u;
	if (AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 0u, &format, (uint)sizeof(AudioStreamBasicDescription)) != 0) { AudioComponentInstanceDispose(unit); return 3; }
	float* input = (float*)calloc(16, sizeof(float));
	if (input == null) { AudioComponentInstanceDispose(unit); return 9; }
	for (int index = 0; index < 16; index++) { input[index] = 0.25f; }
	InputContext context = {input, 0u};
	if (withCallback) {
		AURenderCallbackStruct callback;
		callback.inputProc = supplyInput;
		callback.inputProcRefCon = &context;
		if (AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0u, &format, (uint)sizeof(AudioStreamBasicDescription)) != 0 || AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0u, &callback, (uint)sizeof(AURenderCallbackStruct)) != 0) { AudioComponentInstanceDispose(unit); free(input); return 10; }
		if (AudioUnitSetParameter(unit, kMultiChannelMixerParam_Enable, kAudioUnitScope_Input, 0u, 1.0f, 0u) != 0 || AudioUnitSetParameter(unit, kMultiChannelMixerParam_Volume, kAudioUnitScope_Input, 0u, 1.0f, 0u) != 0 || AudioUnitSetParameter(unit, kMultiChannelMixerParam_Volume, kAudioUnitScope_Output, 0u, 1.0f, 0u) != 0) { AudioComponentInstanceDispose(unit); free(input); return 13; }
	}
	if (AudioUnitInitialize(unit) != 0) { AudioComponentInstanceDispose(unit); free(input); return 4; }
	float* samples = (float*)calloc(16, sizeof(float));
	if (samples == null) { AudioUnitUninitialize(unit); AudioComponentInstanceDispose(unit); free(input); return 5; }
	for (int index = 0; index < 16; index++) { samples[index] = 1.0f; }
	AudioTimeStamp time;
	memset(&time, 0, sizeof(AudioTimeStamp));
	time.mFlags = kAudioTimeStampSampleTimeValid;
	AudioBufferList buffers;
	memset(&buffers, 0, sizeof(AudioBufferList));
	buffers.mNumberBuffers = 1u;
	buffers.mBuffers[0].mNumberChannels = 1u;
	buffers.mBuffers[0].mDataByteSize = 64u;
	buffers.mBuffers[0].mData = samples;
	int status = renderSamples(unit, &time, &buffers);
	float expected = withCallback ? 0.25f : 0.0f;
	for (int index = 0; index < 16; index++) { if (samples[index] != expected) { print(index); print(samples[index]); status = 6; } }
	if (withCallback && context.calls == 0u) { print("callback was not invoked"); status = 11; }
	free(samples);
	if (AudioUnitUninitialize(unit) != 0) { status = 7; }
	if (AudioComponentInstanceDispose(unit) != 0) { status = 8; }
	free(input);
	return status;
}
""".replace("WITH_CALLBACK", "true" if with_callback else "false")
    )
    result = native_compile(source)
    assert result.successful, str(result.failure) + "\n" + "\n".join(item.message for item in result.diagnostics)
    assert "Native call AudioUnitRender:" not in result.c_source
    run_native_executable(result.c_source, tmp_path, sdk, triple, sanitized, frameworks=("AudioToolbox",))
