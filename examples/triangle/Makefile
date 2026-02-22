# btrc GPU examples
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

all: triangle

triangle: triangle.btrc
	@echo "--- Transpiling triangle.btrc → triangle.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/triangle/triangle.btrc -o examples/triangle/triangle.c
	@echo "--- Compiling triangle.c → triangle ---"
	$(CC) triangle.c -o triangle $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./triangle ---"

clean:
	rm -f triangle triangle.c
