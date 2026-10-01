# btrc GPU SGD example
#
# Prerequisites: run  make gpu  first

include ../Example.mk

GPU_DIR   := $(BTRC_ROOT)/src/stdlib/GPU
GPU_BUILD := $(BTRC_ROOT)/build/stdlib/GPU

GPU_THREAD_FLAGS ?= $(if $(filter Windows_NT,$(OS)),,-pthread)
CFLAGS  := -std=c11 -I$(GPU_DIR) $(GPU_CFLAGS) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu $(GPU_LDFLAGS) -lm $(GPU_THREAD_FLAGS)

.PHONY: all clean

all: sgd

sgd: Sgd.btrc
	@echo "--- Transpiling Sgd.btrc → sgd.c ---"
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Sgd.btrc -o $(EXAMPLE)/sgd.c
	@echo "--- Compiling sgd.c → sgd ---"
	$(CC) sgd.c -o sgd $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./sgd ---"

clean:
	rm -f sgd sgd.c
