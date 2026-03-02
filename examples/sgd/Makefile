# btrc GPU SGD example
#
# Prerequisites: run  make setup-gpu  first
#

BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
GPU_DIR   := $(BTRC_ROOT)/src/stdlib/gpu
GPU_BUILD := $(GPU_DIR)/build

# Load saved paths from setup-gpu
-include $(GPU_BUILD)/gpu_paths.mk

# Detect platform
UNAME_S := $(shell uname -s)

# Common flags
CFLAGS  := -I$(GPU_DIR) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu -lm

ifeq ($(UNAME_S),Darwin)
  WGPU_PREFIX  ?= $(shell brew --prefix wgpu-native 2>/dev/null)
  GLFW_PREFIX  ?= $(shell brew --prefix glfw 2>/dev/null)
  CFLAGS  += -I$(WGPU_PREFIX)/include -I$(GLFW_PREFIX)/include
  LDFLAGS += -L$(WGPU_PREFIX)/lib -lwgpu_native \
             -L$(GLFW_PREFIX)/lib -lglfw \
             -framework Metal -framework QuartzCore \
             -framework Cocoa -framework IOKit -framework CoreVideo
  CC := clang
else
  LDFLAGS += -lwgpu_native -lglfw -lpthread
  CC := gcc
endif

.PHONY: all clean

all: sgd

sgd: sgd.btrc
	@echo "--- Transpiling sgd.btrc → sgd.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/sgd/sgd.btrc -o examples/sgd/sgd.c
	@echo "--- Compiling sgd.c → sgd ---"
	$(CC) sgd.c -o sgd $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./sgd ---"

clean:
	rm -f sgd sgd.c
