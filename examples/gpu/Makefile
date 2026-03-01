# btrc GPU examples
#
# Prerequisites: run  scripts/setup-gpu.sh  first
#

BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
GPU_DIR   := $(BTRC_ROOT)/src/stdlib/gpu
GPU_BUILD := $(GPU_DIR)/build

# Load saved paths from setup-gpu.sh
-include $(GPU_BUILD)/gpu_paths.mk

# Detect platform
UNAME_S := $(shell uname -s)

# Common flags
CFLAGS  := -I$(GPU_DIR) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu -lm

ifeq ($(UNAME_S),Darwin)
  # macOS: use Homebrew paths
  WGPU_PREFIX  ?= $(shell brew --prefix wgpu-native 2>/dev/null)
  GLFW_PREFIX  ?= $(shell brew --prefix glfw 2>/dev/null)
  CFLAGS  += -I$(WGPU_PREFIX)/include -I$(GLFW_PREFIX)/include
  LDFLAGS += -L$(WGPU_PREFIX)/lib -lwgpu_native \
             -L$(GLFW_PREFIX)/lib -lglfw \
             -framework Metal -framework QuartzCore \
             -framework Cocoa -framework IOKit -framework CoreVideo
  CC := clang
else
  # Linux
  LDFLAGS += -lwgpu_native -lglfw -lpthread
  CC := gcc
endif

# Targets
.PHONY: all clean

all: triangle

triangle: triangle.btrc
	@echo "--- Transpiling triangle.btrc → triangle.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/gpu/triangle.btrc -o examples/gpu/triangle.c
	@echo "--- Compiling triangle.c → triangle ---"
	$(CC) triangle.c -o triangle $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./triangle ---"

clean:
	rm -f triangle triangle.c
