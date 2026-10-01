# Native AppKit window and managed WebGPU child. The SDK reader and
# wgpu-native pkg-config dependency must be available in the build environment.
include ../Example.mk

.PHONY: all triangle verify clean
all: triangle

triangle:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Triangle.btrc -o $(EXAMPLE)/triangle.c --emit-link-plan $(EXAMPLE)/triangle.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/triangle.link.json --generated-c $(EXAMPLE)/triangle.c \
		--output $(EXAMPLE)/triangle --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

verify: triangle
	./triangle --verify

clean:
	rm -f triangle triangle.c triangle.link.json
