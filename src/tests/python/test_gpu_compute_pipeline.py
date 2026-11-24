"""Headless WebGPU compute, texture array, 3D LUT, storage buffer, and instanced render E2E tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]

HEADLESS_GPU_TEST_PROGRAM = r"""
import Library.Array;
import Library.GPU.GPUCommandBatch;
import Library.GPU.GPUComputeProgram;
import Library.GPU.GPUDevice;
import Library.GPU.GPUProgram;
import Library.GPU.GPUStorageBuffer;
import Library.GPU.GPUTexture;
import Library.GPU.GPUUniformBuffer;
import Library.Image;
import Library.Math;
import Library.Testing;

void testExposureLinearityAndHDR(GPUDevice device) {
	int w = 64;
	int h = 64;
	GPUTexture src = GPUTexture.create2D(device, w, h, GPU_FORMAT_RGBA16_FLOAT, false, false, false, true);
	GPUTexture dst = GPUTexture.create2D(device, w, h, GPU_FORMAT_RGBA16_FLOAT, true, false, true, true);
	Array<float> pixels = Array(w * h * 4);
	for (int y = 0; y < h; y++) {
		for (int x = 0; x < w; x++) {
			int idx = (y * w + x) * 4;
			float r = (x == 0 && y == 0) ? 2.5f : ((float)x / 63.0f);
			float g = (float)y / 63.0f;
			float b = 0.25f;
			pixels.set(idx, r);
			pixels.set(idx + 1, g);
			pixels.set(idx + 2, b);
			pixels.set(idx + 3, 1.0f);
		}
	}
	src.uploadFloats(pixels);

	GPUUniformBuffer params = GPUUniformBuffer(device, 4);
	params.set(0, 1.0f); // +1.0 EV => exact 2.0x linear gain
	params.set(1, (float)w);
	params.set(2, (float)h);
	params.set(3, 0.0f);

	string wgsl =
		"struct Params { ev: f32, w: f32, h: f32, pad: f32 }\n" +
		"@group(0) @binding(0) var<uniform> params: Params;\n" +
		"@group(0) @binding(1) var srcTex: texture_2d<f32>;\n" +
		"@group(0) @binding(2) var dstTex: texture_storage_2d<rgba16float, write>;\n" +
		"@compute @workgroup_size(8, 8)\n" +
		"fn main(@builtin(global_invocation_id) gid: vec3<u32>) {\n" +
		"  if (gid.x >= u32(params.w) || gid.y >= u32(params.h)) { return; }\n" +
		"  let px = textureLoad(srcTex, vec2<i32>(gid.xy), 0);\n" +
		"  let gain = exp2(params.ev);\n" +
		"  textureStore(dstTex, vec2<i32>(gid.xy), vec4<f32>(px.rgb * gain, px.a));\n" +
		"}\n";

	GPUBindLayout layout = GPUBindLayout()
		.addUniform(0, GPU_STAGE_COMPUTE)
		.addTexture2D(1, GPU_STAGE_COMPUTE)
		.addStorageTextureWrite(2, GPU_FORMAT_RGBA16_FLOAT, GPU_STAGE_COMPUTE);
	GPUComputeProgram prog = GPUComputeProgram.createSync(device, wgsl, layout, "main");
	GPUBindResources res = GPUBindResources()
		.bindUniform(0, params)
		.bindTexture(1, src)
		.bindTexture(2, dst);

	GPUCommandBatch batch = GPUCommandBatch.begin(device);
	batch.dispatchCompute(prog, res, w / 8, h / 8, 1);
	batch.submitAndWait();

	Array<float> out = dst.readbackFloats();
	Expect.intEq(out.length, w * h * 4);
	// HDR pixel (0,0): 2.5 * 2.0 == 5.0 (proving unclamped linear RGBA16Float)
	Expect.isTrue(Math.absDouble((double)out.get(0) - 5.0) < 0.01);
	for (int i = 4; i < w * h * 4; i += 4) {
		float expectedR = pixels.get(i) * 2.0f;
		float expectedG = pixels.get(i + 1) * 2.0f;
		float expectedB = pixels.get(i + 2) * 2.0f;
		Expect.isTrue(Math.absDouble((double)out.get(i) - (double)expectedR) < 0.005);
		Expect.isTrue(Math.absDouble((double)out.get(i + 1) - (double)expectedG) < 0.005);
		Expect.isTrue(Math.absDouble((double)out.get(i + 2) - (double)expectedB) < 0.005);
		Expect.isTrue(Math.absDouble((double)out.get(i + 3) - 1.0) < 0.005);
	}
	prog.close();
	params.close();
	dst.close();
	src.close();
}

void testAtomicHistogramOracle(GPUDevice device) {
	int w = 64;
	int h = 64;
	GPUTexture src = GPUTexture.create2D(device, w, h, GPU_FORMAT_RGBA16_FLOAT, false, false, false, true);
	Array<float> pixels = Array(w * h * 4);
	for (int i = 0; i < w * h; i++) {
		// Half at 0.25 (bin 64), half at 0.75 (bin 191)
		float v = (i < (w * h) / 2) ? 0.25f : 0.75f;
		pixels.set(i * 4, v);
		pixels.set(i * 4 + 1, v);
		pixels.set(i * 4 + 2, v);
		pixels.set(i * 4 + 3, 1.0f);
	}
	src.uploadFloats(pixels);

	GPUStorageBuffer hist = GPUStorageBuffer.create(device, 256 * 4, true, false);
	hist.clearZero();

	string wgsl =
		"@group(0) @binding(0) var srcTex: texture_2d<f32>;\n" +
		"@group(0) @binding(1) var<storage, read_write> bins: array<atomic<u32>, 256>;\n" +
		"@compute @workgroup_size(8, 8)\n" +
		"fn main(@builtin(global_invocation_id) gid: vec3<u32>) {\n" +
		"  let dims = textureDimensions(srcTex);\n" +
		"  if (gid.x >= dims.x || gid.y >= dims.y) { return; }\n" +
		"  let px = textureLoad(srcTex, vec2<i32>(gid.xy), 0);\n" +
		"  let luma = clamp(px.r, 0.0, 1.0);\n" +
		"  let idx = min(u32(luma * 255.0 + 0.5), 255u);\n" +
		"  atomicAdd(&bins[idx], 1u);\n" +
		"}\n";

	GPUBindLayout layout = GPUBindLayout()
		.addTexture2D(0, GPU_STAGE_COMPUTE)
		.addStorageReadWrite(1, GPU_STAGE_COMPUTE);
	GPUComputeProgram prog = GPUComputeProgram.createSync(device, wgsl, layout, "main");
	GPUBindResources res = GPUBindResources()
		.bindTexture(0, src)
		.bindStorage(1, hist);

	GPUCommandBatch batch = GPUCommandBatch.begin(device);
	batch.dispatchCompute(prog, res, w / 8, h / 8, 1);
	batch.submitAndWait();

	Array<unsigned int> bins = hist.readbackUints();
	Expect.intEq(bins.length, 256);
	unsigned int total = 0u;
	for (int i = 0; i < 256; i++) { total += bins.get(i); }
	Expect.intEq((int)total, w * h);
	Expect.intEq((int)bins.get(64), 2048);
	Expect.intEq((int)bins.get(191), 2048);

	prog.close();
	hist.close();
	src.close();
}

void testR16UintAnd3DLUT(GPUDevice device) {
	int w = 16;
	int h = 16;
	GPUTexture rawTex = GPUTexture.create2D(device, w, h, GPU_FORMAT_R16_UINT, false, false, false, false);
	Array<unsigned short> cfa = Array(w * h);
	for (int i = 0; i < w * h; i++) { cfa.set(i, (unsigned short)(i * 256)); }
	rawTex.uploadU16(cfa);

	int lutSize = 4;
	GPUTexture lut = GPUTexture.create3D(device, lutSize, lutSize, lutSize, GPU_FORMAT_RGBA16_FLOAT, false, true);
	Array<float> lutData = Array(lutSize * lutSize * lutSize * 4);
	for (int z = 0; z < lutSize; z++) {
		for (int y = 0; y < lutSize; y++) {
			for (int x = 0; x < lutSize; x++) {
				int idx = ((z * lutSize + y) * lutSize + x) * 4;
				// Swap R and B in the 3D LUT so sampling proves 3D coordinate lookup
				lutData.set(idx, (float)z / 3.0f);
				lutData.set(idx + 1, (float)y / 3.0f);
				lutData.set(idx + 2, (float)x / 3.0f);
				lutData.set(idx + 3, 1.0f);
			}
		}
	}
	lut.upload3DFloats(lutData);

	GPUTexture dst = GPUTexture.create2D(device, w, h, GPU_FORMAT_RGBA16_FLOAT, true, false, true, true);
	string wgsl =
		"@group(0) @binding(0) var rawTex: texture_2d<u32>;\n" +
		"@group(0) @binding(1) var lutTex: texture_3d<f32>;\n" +
		"@group(0) @binding(2) var lutSamp: sampler;\n" +
		"@group(0) @binding(3) var dstTex: texture_storage_2d<rgba16float, write>;\n" +
		"@compute @workgroup_size(8, 8)\n" +
		"fn main(@builtin(global_invocation_id) gid: vec3<u32>) {\n" +
		"  let v = textureLoad(rawTex, vec2<i32>(gid.xy), 0).r;\n" +
		"  let norm = f32(v) / 65535.0;\n" +
		"  let coord = vec3<f32>(0.875, 0.125, 0.125);\n" +
		"  let mapped = textureSampleLevel(lutTex, lutSamp, coord, 0.0);\n" +
		"  textureStore(dstTex, vec2<i32>(gid.xy), vec4<f32>(norm, mapped.r, mapped.b, 1.0));\n" +
		"}\n";

	GPUBindLayout layout = GPUBindLayout()
		.addTexture2DUint(0, GPU_STAGE_COMPUTE)
		.addTexture3D(1, GPU_STAGE_COMPUTE)
		.addSampler(2, GPU_STAGE_COMPUTE)
		.addStorageTextureWrite(3, GPU_FORMAT_RGBA16_FLOAT, GPU_STAGE_COMPUTE);
	GPUComputeProgram prog = GPUComputeProgram.createSync(device, wgsl, layout, "main");
	GPUBindResources res = GPUBindResources()
		.bindTexture(0, rawTex)
		.bindTexture(1, lut)
		.bindSampler(2, lut)
		.bindTexture(3, dst);

	GPUCommandBatch batch = GPUCommandBatch.begin(device);
	batch.dispatchCompute(prog, res, w / 8, h / 8, 1);
	batch.submitAndWait();

	Array<float> out = dst.readbackFloats();
	// Pixel (5, 2) => index = 37 => cfa = 37 * 256 = 9472 => norm = 9472 / 65535 = 0.144533
	int pIdx = (2 * w + 5) * 4;
	Expect.isTrue(Math.absDouble((double)out.get(pIdx) - (9472.0 / 65535.0)) < 0.002);
	// 3D LUT swapped R and B: at coord=(0.875, 0.125, 0.125), mapped.r ~ 0.0, mapped.b ~ 1.0
	Expect.isTrue(out.get(pIdx + 1) < 0.05f);
	Expect.isTrue(out.get(pIdx + 2) > 0.95f);

	prog.close();
	dst.close();
	lut.close();
	rawTex.close();
}

void testInstancedTextureArrayAndCopy(GPUDevice device) {
	// 2-layer 32x32 atlas: layer 0 red, layer 1 copied from a green source via copyTextureToTexture
	GPUTexture atlas = GPUTexture.createArray(device, 32, 32, 2, GPU_FORMAT_RGBA8_UNORM, false, true, true);
	GPUTexture greenSrc = GPUTexture.create2D(device, 32, 32, GPU_FORMAT_RGBA8_UNORM, false, false, true, true);

	Image redImg = Image(32, 32);
	Image greenImg = Image(32, 32);
	for (int y = 0; y < 32; y++) {
		for (int x = 0; x < 32; x++) {
			redImg.setPixel(x, y, RGBA(240, 20, 10, 255));
			greenImg.setPixel(x, y, RGBA(10, 230, 30, 255));
		}
	}
	atlas.uploadImage(redImg, 0);
	greenSrc.uploadImage(greenImg, 0);

	// Storage buffer with 2 tile instances: [x0, y0, x1, y1, layer, pad, pad, pad]
	GPUStorageBuffer instances = GPUStorageBuffer.create(device, 2 * 8 * 4, false, false);
	Array<float> tileData = Array(16);
	// Tile 0: left half NDC [-1, 0] x [-1, 1], layer 0
	tileData.set(0, -1.0f); tileData.set(1, -1.0f); tileData.set(2, 0.0f); tileData.set(3, 1.0f);
	tileData.set(4, 0.0f); tileData.set(5, 0.0f); tileData.set(6, 0.0f); tileData.set(7, 0.0f);
	// Tile 1: right half NDC [0, 1] x [-1, 1], layer 1
	tileData.set(8, 0.0f); tileData.set(9, -1.0f); tileData.set(10, 1.0f); tileData.set(11, 1.0f);
	tileData.set(12, 1.0f); tileData.set(13, 0.0f); tileData.set(14, 0.0f); tileData.set(15, 0.0f);
	instances.writeFloats(tileData);

	GPUTexture target = GPUTexture.create2D(device, 64, 32, GPU_FORMAT_RGBA8_UNORM, false, true, true, true);
	string wgsl =
		"struct Tile { rect: vec4<f32>, layer: f32, p1: f32, p2: f32, p3: f32 }\n" +
		"@group(0) @binding(0) var<storage, read> tiles: array<Tile>;\n" +
		"@group(0) @binding(1) var atlasTex: texture_2d_array<f32>;\n" +
		"@group(0) @binding(2) var atlasSamp: sampler;\n" +
		"struct VOut { @builtin(position) pos: vec4<f32>, @location(0) uv: vec2<f32>, @location(1) layer: f32 }\n" +
		"@vertex fn vs_main(@builtin(vertex_index) vid: u32, @builtin(instance_index) iid: u32) -> VOut {\n" +
		"  var corners = array<vec2<f32>, 6>(vec2<f32>(0.0,0.0), vec2<f32>(1.0,0.0), vec2<f32>(0.0,1.0), vec2<f32>(1.0,0.0), vec2<f32>(1.0,1.0), vec2<f32>(0.0,1.0));\n" +
		"  let c = corners[vid];\n" +
		"  let t = tiles[iid];\n" +
		"  let x = mix(t.rect.x, t.rect.z, c.x);\n" +
		"  let y = mix(t.rect.y, t.rect.w, c.y);\n" +
		"  var o: VOut;\n" +
		"  o.pos = vec4<f32>(x, y, 0.0, 1.0);\n" +
		"  o.uv = c;\n" +
		"  o.layer = t.layer;\n" +
		"  return o;\n" +
		"}\n" +
		"@fragment fn fs_main(in: VOut) -> @location(0) vec4<f32> {\n" +
		"  return textureSample(atlasTex, atlasSamp, in.uv, i32(in.layer + 0.5));\n" +
		"}\n";

	GPUBindLayout layout = GPUBindLayout()
		.addStorageRead(0, GPU_STAGE_VERTEX)
		.addTexture2DArray(1, GPU_STAGE_FRAGMENT)
		.addSampler(2, GPU_STAGE_FRAGMENT);
	GPUProgram renderProg = GPUProgram.createWithLayoutSync(device, target.nativeFormat(), wgsl, layout, false, "vs_main", "fs_main");
	GPUBindResources res = GPUBindResources()
		.bindStorage(0, instances)
		.bindTexture(1, atlas)
		.bindSampler(2, atlas);

	// Single command batch: copyTextureToTexture into atlas layer 1 -> 1-draw-call instanced render -> wait!
	GPUCommandBatch batch = GPUCommandBatch.begin(device);
	batch.copyTextureToTexture(greenSrc, 0, 0, 0, atlas, 0, 0, 1, 32, 32);
	batch.beginRenderPass(target, 0.0, 0.0, 0.0, 1.0, 0);
	batch.drawProgram(renderProg, res, 6, 2);
	batch.endRenderPass();
	batch.submitAndWait();

	Image result = target.readbackImage();
	Expect.intEq(result.width, 64);
	Expect.intEq(result.height, 32);
	// Left tile pixel (16, 16) should be red (240, 20, 10)
	RGBA leftPx = result.pixel(16, 16);
	Expect.intEq(leftPx.red, 240);
	Expect.intEq(leftPx.green, 20);
	Expect.intEq(leftPx.blue, 10);
	// Right tile pixel (48, 16) should be green (10, 230, 30)
	RGBA rightPx = result.pixel(48, 16);
	Expect.intEq(rightPx.red, 10);
	Expect.intEq(rightPx.green, 230);
	Expect.intEq(rightPx.blue, 30);

	renderProg.close();
	target.close();
	instances.close();
	greenSrc.close();
	atlas.close();
}

void testInvalidWGSLValidationFailure(GPUDevice device) {
	GPUBindLayout layout = GPUBindLayout().addStorageReadWrite(0, GPU_STAGE_COMPUTE);
	bool failed = false;
	try {
		GPUComputeProgram bad = GPUComputeProgram.createSync(device, "@compute fn main() { let x: invalid_type = 1; }", layout, "main");
		bad.close();
	} catch (string error) {
		failed = !error.isEmpty();
	}
	Expect.isTrue(failed);
}

int main() {
	GPUDevice device = GPUDevice.openHeadless();
	Expect.isTrue(device.maxTextureDimension2D() >= 4096);
	Expect.isTrue(device.maxTextureArrayLayers() >= 256);
	testExposureLinearityAndHDR(device);
	testAtomicHistogramOracle(device);
	testR16UintAnd3DLUT(device);
	testInstancedTextureArrayAndCopy(device);
	testInvalidWGSLValidationFailure(device);
	device.close();
	print("HEADLESS_GPU_COMPUTE_OK");
	return 0;
}
"""


@pytest.mark.parametrize("sanitize", [False, True], ids=["plain", "sanitized"])
def test_headless_gpu_compute_and_instanced_atlas_pipeline(native_project, native_compile, sanitize: bool) -> None:
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text(HEADLESS_GPU_TEST_PROGRAM, encoding="utf-8")
    plan = root / "HeadlessGPU.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    generated = root / "HeadlessGPU.c"
    generated.write_text(compiled.c_source, encoding="utf-8")
    executable = root / "HeadlessGPU"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    assert "HEADLESS_GPU_COMPUTE_OK" in completed.stdout
