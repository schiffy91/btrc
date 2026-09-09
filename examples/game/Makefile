# btrc 3D Engine example
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

all: game

game: Game.btrc engine/Engine.btrc engine/Input.btrc engine/Time.btrc \
      engine/Gameobject.btrc engine/Camera.btrc engine/Light.btrc \
      engine/Material.btrc engine/Ground.btrc engine/Sky.btrc \
      engine/Scene.btrc engine/Renderer.btrc
	@echo "--- Transpiling Game.btrc → game.c ---"
	cd $(BTRC_ROOT) && $(BTRC) examples/game/Game.btrc -o examples/game/game.c
	@echo "--- Compiling game.c → game ---"
	$(CC) game.c -o game $(CFLAGS) $(LDFLAGS)
	@echo "--- Done: ./game ---"

clean:
	rm -f game game.c
