# Renders the GPU SGD example to PPM frames, and those frames to a GIF.
#
# Prerequisites: run  make gpu  first (the @gpu kernel links the compute
# runtime). Without a GPU adapter the kernel takes the compiler's CPU
# fallback and the output is the same.

include ../Example.mk

GPU_DIR   := $(BTRC_ROOT)/src/runtime/gpu
GPU_BUILD := $(BTRC_ROOT)/build/stdlib/GPU

GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)
CFLAGS  := $(STRICT_CFLAGS) -I$(GPU_DIR) $(GPU_CFLAGS) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu $(GPU_LDFLAGS) -lm $(GPU_THREAD_FLAGS)

.PHONY: all run gif clean

all: sgd_render

sgd_render: SgdRender.btrc
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/SgdRender.btrc -o $(EXAMPLE)/sgd_render.c
	$(CC) sgd_render.c -o sgd_render $(CFLAGS) $(LDFLAGS)

# Write the frames.
run: sgd_render
	mkdir -p frames
	./sgd_render

# Re-encode the README's committed animation (sgd.gif) from a fresh run.
# Needs Pillow.
gif: run
	$(PYTHON) ../make_gif.py frames sgd.gif

clean:
	rm -f sgd_render sgd_render.c
	rm -rf frames
