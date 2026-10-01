"""WebGPU through native imports: real devices, packaged headers, owned descriptors and rendered pixels."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
def test_c_completion_real_webgpu_device(native_project, native_compile, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "src/NativeGPU.btrc").write_text("")
    (root / "WebGPU.h").write_text("""#include <webgpu.h>
static inline void ProbeTexture(WGPUDevice device, WGPUSurfaceTexture* output) {
    WGPUTextureDescriptor descriptor = {0};
    descriptor.usage = WGPUTextureUsage_CopyDst;
    descriptor.dimension = WGPUTextureDimension_2D;
    descriptor.size.width = 8; descriptor.size.height = 4; descriptor.size.depthOrArrayLayers = 1;
    descriptor.format = WGPUTextureFormat_RGBA8Unorm;
    descriptor.mipLevelCount = 1; descriptor.sampleCount = 1;
    output->texture = wgpuDeviceCreateTexture(device, &descriptor);
    output->status = WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal;
}
static inline WGPUShaderModule ProbeShader(WGPUDevice device) {
    WGPUShaderSourceWGSL source = {0};
    source.chain.sType = WGPUSType_ShaderSourceWGSL;
    source.code.data = "@vertex fn main() -> @builtin(position) vec4f { return vec4f(0.0, 0.0, 0.0, 1.0); }";
    source.code.length = WGPU_STRLEN;
    WGPUShaderModuleDescriptor descriptor = {0};
    descriptor.nextInChain = &source.chain;
    return wgpuDeviceCreateShaderModule(device, &descriptor);
}
""")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "nativeGPUCompletion"
[[native.pkg-config]]
name = "wgpu-native"
modules = ["NativeGPU"]
[[native.bindings]]
module = "NativeGPU"
header = "WebGPU.h"
language = "c"
standard = "c11"
symbols = ["WGPUInstance", "WGPUAdapter", "WGPUDevice", "WGPUQueue", "WGPUStringView", "WGPUSurface", "WGPURequestAdapterOptions", "wgpuSurfaceAddRef", "wgpuSurfaceRelease",
"WGPUTexture", "WGPUSurfaceTexture", "wgpuTextureAddRef", "wgpuTextureRelease", "wgpuTextureGetWidth", "wgpuSurfaceGetCurrentTexture", "ProbeTexture", "WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal",
"WGPUShaderModule", "WGPURenderPipeline", "WGPUPipelineLayout", "WGPUVertexState", "WGPURenderPipelineDescriptor", "WGPUPrimitiveTopology_TriangleList",
"WGPUDepthStencilState", "WGPUTextureFormat_Depth32Float", "WGPUOptionalBool_False", "WGPUCompareFunction_Always",
"ProbeShader", "wgpuShaderModuleAddRef", "wgpuShaderModuleRelease", "wgpuDeviceCreateRenderPipeline", "wgpuRenderPipelineAddRef", "wgpuRenderPipelineRelease", "wgpuPipelineLayoutAddRef", "wgpuPipelineLayoutRelease",
"WGPURequestAdapterCallbackInfo", "WGPURequestDeviceCallbackInfo",
"wgpuCreateInstance", "wgpuInstanceAddRef", "wgpuInstanceRelease", "wgpuInstanceProcessEvents",
"wgpuInstanceRequestAdapter", "wgpuAdapterAddRef", "wgpuAdapterRelease", "wgpuAdapterRequestDevice",
"wgpuDeviceAddRef", "wgpuDeviceRelease", "wgpuDeviceGetQueue", "wgpuQueueAddRef", "wgpuQueueRelease",
"WGPUCallbackMode_AllowProcessEvents", "WGPURequestAdapterStatus_Success", "WGPURequestDeviceStatus_Success"]
owned-results = ["wgpuCreateInstance", "wgpuDeviceGetQueue", "ProbeShader", "wgpuDeviceCreateRenderPipeline"]
borrowed-parameters = ["wgpuInstanceProcessEvents.instance", "wgpuInstanceRequestAdapter.instance", "wgpuAdapterRequestDevice.adapter", "wgpuDeviceGetQueue.device", "ProbeTexture.device", "wgpuTextureGetWidth.texture", "wgpuSurfaceGetCurrentTexture.surface", "ProbeShader.device", "wgpuDeviceCreateRenderPipeline.device"]
owned-records = ["WGPURequestAdapterCallbackInfo", "WGPURequestDeviceCallbackInfo", "WGPURequestAdapterOptions", "WGPUSurfaceTexture", "WGPUVertexState", "WGPURenderPipelineDescriptor", "WGPUDepthStencilState"]
record-inputs = ["wgpuInstanceRequestAdapter.callbackInfo", "wgpuAdapterRequestDevice.callbackInfo", "wgpuInstanceRequestAdapter.options", "wgpuDeviceCreateRenderPipeline.descriptor"]
record-outputs = ["ProbeTexture.output", "wgpuSurfaceGetCurrentTexture.surfaceTexture"]
owned-output-fields = ["ProbeTexture.output.texture", "wgpuSurfaceGetCurrentTexture.surfaceTexture.texture"]
null-output-fields = ["ProbeTexture.output.nextInChain", "wgpuSurfaceGetCurrentTexture.surfaceTexture.nextInChain"]
[native.bindings.object-fields]
"WGPURenderPipelineDescriptor.depthStencil" = "WGPUDepthStencilState?"
[native.bindings.resources.WGPUShaderModule]
ownership = "reference-counted"
retain = "wgpuShaderModuleAddRef"
release = "wgpuShaderModuleRelease"
[native.bindings.resources.WGPURenderPipeline]
ownership = "reference-counted"
retain = "wgpuRenderPipelineAddRef"
release = "wgpuRenderPipelineRelease"
[native.bindings.resources.WGPUPipelineLayout]
ownership = "reference-counted"
retain = "wgpuPipelineLayoutAddRef"
release = "wgpuPipelineLayoutRelease"
[native.bindings.resources.WGPUTexture]
ownership = "reference-counted"
retain = "wgpuTextureAddRef"
release = "wgpuTextureRelease"
[native.bindings.resources.WGPUSurface]
ownership = "reference-counted"
retain = "wgpuSurfaceAddRef"
release = "wgpuSurfaceRelease"
[native.bindings.resources.WGPUInstance]
ownership = "reference-counted"
retain = "wgpuInstanceAddRef"
release = "wgpuInstanceRelease"
[native.bindings.resources.WGPUAdapter]
ownership = "reference-counted"
retain = "wgpuAdapterAddRef"
release = "wgpuAdapterRelease"
[native.bindings.resources.WGPUDevice]
ownership = "reference-counted"
retain = "wgpuDeviceAddRef"
release = "wgpuDeviceRelease"
[native.bindings.resources.WGPUQueue]
ownership = "reference-counted"
retain = "wgpuQueueAddRef"
release = "wgpuQueueRelease"
[native.bindings.string-views.WGPUStringView]
data = "data"
length = "length"
null-length = "zero-or-max"
[native.bindings.callbacks."wgpuInstanceRequestAdapter.callbackInfo"]
field = "callback"
context = ["userdata1", "userdata2"]
context-index = [3, 4]
interface = "IAdapterCompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
owned-arguments = [1]
[native.bindings.callbacks."wgpuAdapterRequestDevice.callbackInfo"]
field = "callback"
context = ["userdata1", "userdata2"]
context-index = [3, 4]
interface = "IDeviceCompletion"
lifetime = "one-shot"
executor = "caller"
failure = "abort"
activation-failure = "abort"
cancellation = "abandon"
owned-arguments = [1]
""")
    source.write_text("""import Library.Callback;
import ./NativeGPU.btrc;
class AdapterCompletion implements IAdapterCompletion {
	public WGPUAdapter? value;
	public bool delivered = false;
	public void invoke(WGPURequestAdapterStatus status, WGPUAdapter? adapter, string message) {
		assert(!self.delivered);
		if (status != WGPURequestAdapterStatus_Success) { throw message; }
		self.value = adapter; self.delivered = true;
	}
}
class DeviceCompletion implements IDeviceCompletion {
	public WGPUDevice? value;
	public bool delivered = false;
	public void invoke(WGPURequestDeviceStatus status, WGPUDevice? device, string message) {
		assert(!self.delivered);
		if (status != WGPURequestDeviceStatus_Success) { throw message; }
		self.value = device; self.delivered = true;
	}
}
int main() {
	var instance = wgpuCreateInstance(null); assert(instance != null);
	var scope = CallbackScope();
	var adapter = AdapterCompletion();
	var adapterInfo = WGPURequestAdapterCallbackInfoInput();
	adapterInfo.mode = WGPUCallbackMode_AllowProcessEvents; adapterInfo.callback = adapter;
	var options = WGPURequestAdapterOptionsInput();
	options.compatibleSurface = null;
	var adapterRequest = wgpuInstanceRequestAdapter(instance, options, adapterInfo, scope);
	release adapterInfo;
	for (int poll = 0; poll < 1000000 && !adapter.delivered; poll++) { wgpuInstanceProcessEvents(instance); }
	assert(adapter.delivered && adapter.value != null);
	assert(adapterRequest.request.pollCompletion() == CallbackCancellation.Complete);
	var device = DeviceCompletion();
	var deviceInfo = WGPURequestDeviceCallbackInfoInput();
	deviceInfo.mode = WGPUCallbackMode_AllowProcessEvents; deviceInfo.callback = device;
	var deviceRequest = wgpuAdapterRequestDevice(adapter.value, null, deviceInfo, scope);
	release deviceInfo;
	for (int poll = 0; poll < 1000000 && !device.delivered; poll++) { wgpuInstanceProcessEvents(instance); }
	assert(device.delivered && device.value != null);
	assert(deviceRequest.request.pollCompletion() == CallbackCancellation.Complete);
	var queue = wgpuDeviceGetQueue(device.value); assert(queue != null);
	var frame = ProbeTexture(device.value);
	assert(frame.status == WGPUSurfaceGetCurrentTextureStatus_SuccessOptimal && frame.texture != null);
	var texture = frame.texture; release frame;
	assert(wgpuTextureGetWidth(texture) == (uint32_t)8); release texture;
	var vertex = WGPUVertexStateInput(); vertex.module = ProbeShader(device.value); assert(vertex.module != null);
	vertex.entryPoint.length = (size_t)(-1); // SDK absent entry-point sentinel; select the only vertex entry.
	var pipelineInfo = WGPURenderPipelineDescriptorInput(); pipelineInfo.vertex = vertex;
	var depth = WGPUDepthStencilStateInput(); depth.format = WGPUTextureFormat_Depth32Float;
	depth.depthWriteEnabled = WGPUOptionalBool_False; depth.depthCompare = WGPUCompareFunction_Always;
	pipelineInfo.depthStencil = depth; release depth;
	pipelineInfo.primitive.topology = WGPUPrimitiveTopology_TriangleList;
	pipelineInfo.multisample.count = (uint32_t)1; pipelineInfo.multisample.mask = (uint32_t)0xffffffff;
	release vertex;
	var pipeline = wgpuDeviceCreateRenderPipeline(device.value, pipelineInfo); assert(pipeline != null);
	release pipelineInfo; release pipeline;
	assert(scope.cancel() == CallbackCancellation.Complete);
	release queue; device.value = null; adapter.value = null;
	print("PASS: real WebGPU adapter/device completion through managed bindings");
	return 0;
}
""")
    plan = root / "Device.link.json"
    result = native_compile(source, plan_path=plan)
    assert result.successful, (result.failure, result.diagnostics)
    assert "btrc_gpu_async" not in result.c_source
    generated = root / "Device.c"
    generated.write_text(result.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Device"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    assert "PASS: real WebGPU" in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("consumer", ["Main", "Portable"])
def test_native_gpu_child_renders_and_reads_pixels(native_project, native_compile, sanitize, consumer):
    source, _sdk, _triple = native_project
    root = source.parent.parent / "render"
    shutil.copytree(REPO / "src/tests/native/gui/webgpu_child", root)
    plan = root / "Program.link.json"
    compiled = native_compile(root / f"{consumer}.btrc", plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.failure and not compiled.diagnostics, "native GPU consumer must compile without warnings"
    assert "btrc_gpu_compute_internal.h" not in compiled.c_source
    assert "btrc_gpu_async" not in compiled.c_source
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    executable = root / "Program"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    if consumer == "Main":
        assert "clear, present and pixel readback" in completed.stdout
        assert completed.stdout.count("headerInk=") == 3
    else:
        assert "portable GPU view renders, resizes and drains through native application shutdown" in completed.stdout


def test_packaged_webgpu_dependency_uses_typed_headers_and_link_plan(native_project, native_compile):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("#include <webgpu.h>\n", encoding="utf-8")
    (root / "src/Foundation.btrc").write_text("// Dependency-owned WebGPU API.\n", encoding="utf-8")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "webGpuDependency"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["wgpuCreateInstance", "wgpuInstanceRelease"]\n'
        '[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["Foundation"]\nos = ["macos"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./Foundation.btrc;\nint main() { var instance = wgpuCreateInstance(null); "
        "if (instance == null) { return 1; } wgpuInstanceRelease(instance); return 0; }\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "Program"
    NativePlanBuilder().build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("imports_layer", [False, True])
def test_owned_webgpu_descriptor_retains_nested_layer(native_project, native_compile, sanitize, imports_layer):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "WebGpu.h").write_text("#include <webgpu.h>\n", encoding="utf-8")
    (root / "Layer.h").write_text(
        "#import <QuartzCore/QuartzCore.h>\n@interface LayerProbe : NSObject\n"
        "+ (void)watch:(CAMetalLayer* _Nonnull)layer;\n+ (BOOL)alive;\n@end\n",
        encoding="utf-8",
    )
    (root / "Layer.m").write_text(
        '#import "Layer.h"\nstatic __weak CAMetalLayer* observedLayer;\n@implementation LayerProbe\n'
        "+ (void)watch:(CAMetalLayer*)layer { observedLayer = layer; }\n"
        "+ (BOOL)alive { return observedLayer != nil; }\n@end\n",
        encoding="utf-8",
    )
    (source.parent / "NativeLayer.btrc").write_text("// Selected native object API.\n", encoding="utf-8")
    (source.parent / "NativeWebGpu.btrc").write_text(
        "import ./NativeLayer.btrc;\n" if imports_layer else "// Missing input field dependency.\n", encoding="utf-8"
    )
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "ownedWebGpu"\n'
        '[[native.bindings]]\nmodule = "NativeLayer"\nheader = "Layer.h"\nlanguage = "objective-c"\nstandard = "c11"\n'
        'symbols = ["+[CAMetalLayer layer]", "+[CATransaction flush]", "+[LayerProbe watch:]", "+[LayerProbe alive]"]\n'
        '[[native.bindings]]\nmodule = "NativeWebGpu"\nheader = "WebGpu.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["wgpuCreateInstance", "wgpuInstanceRelease", "wgpuInstanceCreateSurface", "wgpuSurfaceRelease", "WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer", "WGPUSType_SurfaceSourceMetalLayer"]\n'
        'owned-records = ["WGPUSurfaceDescriptor", "WGPUSurfaceSourceMetalLayer"]\n'
        'record-inputs = ["wgpuInstanceCreateSurface.descriptor"]\n'
        '[native.bindings.object-fields]\n"WGPUSurfaceSourceMetalLayer.layer" = "CAMetalLayer"\n'
        '"WGPUSurfaceDescriptor.nextInChain" = "WGPUSurfaceSourceMetalLayer?"\n'
        '[[native.sources]]\npath = "Layer.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "QuartzCore"\n[[native.frameworks]]\nname = "Foundation"\n'
        '[[native.pkg-config]]\nname = "wgpu-native"\nmodules = ["NativeWebGpu"]\nos = ["macos"]\n',
        encoding="utf-8",
    )
    source.write_text(
        "import ./NativeLayer.btrc;\nimport ./NativeWebGpu.btrc;\nint main() {\n"
        "\tvar descriptor = WGPUSurfaceDescriptorInput();\n\t{\n"
        "\t\tvar metal = WGPUSurfaceSourceMetalLayerInput();\n\t\t{\n"
        "\t\t\tvar layer = CAMetalLayer.layer(); if (layer == null) { return 1; }\n"
        "\t\t\tmetal.layer = layer; LayerProbe.watch(layer);\n\t\t}\n"
        "\t\tif (!LayerProbe.alive()) { return 2; }\n"
        "\t\tmetal.chain.sType = WGPUSType_SurfaceSourceMetalLayer;\n"
        "\t\tdescriptor.nextInChain = metal;\n\t}\n"
        "\tif (!LayerProbe.alive()) { return 3; }\n"
        "\tvar instance = wgpuCreateInstance(null); if (instance == null) { return 4; }\n"
        "\tvar surface = wgpuInstanceCreateSurface(instance, descriptor); if (surface == null) { return 5; }\n"
        "\trelease descriptor;\n\tif (!LayerProbe.alive()) { return 6; }\n"
        "\twgpuSurfaceRelease(surface); CATransaction.flush();\n"
        "\tif (LayerProbe.alive()) { return 7; }\n\twgpuInstanceRelease(instance); return 0;\n}\n",
        encoding="utf-8",
    )
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    if not imports_layer:
        assert not compiled.successful and not compiled.c_source
        assert "does not import" in str(compiled.failure)
        return
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source, encoding="utf-8")

    def run(command, **kwargs):
        flags = (
            ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else [])]
            if Path(command[0]).name in {"clang", "clang++"}
            else []
        )
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr
