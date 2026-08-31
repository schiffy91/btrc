# btrc GPU examples
#
# Prerequisites: run  make gpu  first

BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
GPU_DIR   := $(BTRC_ROOT)/src/stdlib/gpu
GPU_BUILD := $(BTRC_ROOT)/build/stdlib/gpu
APP_DIR   := $(BTRC_ROOT)/src/stdlib/app
APP_BUILD := $(BTRC_ROOT)/build/stdlib/app

CC      := cc
GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)
CFLAGS  := -I$(GPU_DIR) -I$(APP_DIR) $(GPU_CFLAGS) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu -L$(APP_BUILD) -lbtrc_app $(GPU_LDFLAGS) -lm $(GPU_THREAD_FLAGS)

.PHONY: all clean

all: triangle

triangle: triangle.btrc
	@echo "--- Transpiling triangle.btrc → triangle.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/triangle/triangle.btrc -o examples/triangle/triangle.c
	@echo "--- Compiling triangle.c → triangle ---"
	$(CC) triangle.c -o triangle $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./triangle ---"

clean:
	rm -f triangle triangle.c
