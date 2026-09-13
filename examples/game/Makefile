# Native window and managed WebGPU child. Build through the emitted SDK plan.
BTRC_ROOT := ../..
BTRC := python3 -m src.compiler.python.main

.PHONY: all game verify clean
all: game

game:
	cd $(BTRC_ROOT) && $(BTRC) examples/game/Game.btrc -o examples/game/game.c --emit-link-plan examples/game/game.link.json
	cd $(BTRC_ROOT) && python3 -m tools.native_plan --plan examples/game/game.link.json --generated-c examples/game/game.c --output examples/game/game --cc clang --cxx clang++

verify: game
	./game --verify

clean:
	rm -f game game.c game.link.json
