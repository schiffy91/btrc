# Native AppKit window and managed WebGPU child. The SDK reader and
# wgpu-native pkg-config dependency must be available in the build environment.
BTRC_ROOT := ../..
BTRC := python3 -m src.compiler.python.main

.PHONY: all triangle verify clean
all: triangle

triangle:
	cd $(BTRC_ROOT) && $(BTRC) examples/triangle/Triangle.btrc -o examples/triangle/triangle.c --emit-link-plan examples/triangle/triangle.link.json
	cd $(BTRC_ROOT) && python3 -m tools.native_plan --plan examples/triangle/triangle.link.json --generated-c examples/triangle/triangle.c --output examples/triangle/triangle --cc clang --cxx clang++

verify: triangle
	./triangle --verify

clean:
	rm -f triangle triangle.c triangle.link.json
