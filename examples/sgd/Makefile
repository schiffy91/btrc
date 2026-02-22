# btrc GPU SGD example
#
# Prerequisites: run  make gpu  first

BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
GPU_DIR   := $(BTRC_ROOT)/src/stdlib/gpu
GPU_BUILD := $(GPU_DIR)/build

CC      := cc
CFLAGS  := -I$(GPU_DIR) $(GPU_CFLAGS) -O2
LDFLAGS := -L$(GPU_BUILD) -lbtrc_gpu $(GPU_LDFLAGS) -lm

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
