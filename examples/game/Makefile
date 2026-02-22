# btrc 3D Engine example
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

all: game

game: game.btrc engine/engine.btrc engine/input.btrc engine/time.btrc \
      engine/gameobject.btrc engine/camera.btrc engine/light.btrc \
      engine/material.btrc engine/ground.btrc engine/sky.btrc \
      engine/scene.btrc engine/renderer.btrc
	@echo "--- Transpiling game.btrc → game.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/game/game.btrc -o examples/game/game.c
	@echo "--- Compiling game.c → game ---"
	$(CC) game.c -o game $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./game ---"

clean:
	rm -f game game.c
