# Native window and managed WebGPU child. Build through the emitted SDK plan.
include ../Example.mk

.PHONY: all game verify clean
all: game

game:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Game.btrc -o $(EXAMPLE)/game.c --emit-link-plan $(EXAMPLE)/game.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/game.link.json --generated-c $(EXAMPLE)/game.c \
		--output $(EXAMPLE)/game --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

verify: game
	./game --verify

clean:
	rm -f game game.c game.link.json
