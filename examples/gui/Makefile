BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..
GUI   := ../../src/stdlib/GUI

# Headless examples — run offscreen, no display required.
run: demo declarative font

# Immediate-mode widget demo.
demo: main.c
	gcc -std=c11 -I$(GUI) main.c -o gui_demo -lm -lpthread && ./gui_demo

main.c: Main.btrc
	cd $(ROOT) && $(BTRC) examples/gui/Main.btrc -o examples/gui/main.c

# Declarative View tree: layout, events-by-id, resize reflow, UTF-8 metrics.
declarative: declarative.c
	gcc -std=c11 -I$(GUI) declarative.c -o gui_declarative -lm -lpthread && ./gui_declarative

declarative.c: Declarative.btrc
	cd $(ROOT) && $(BTRC) examples/gui/Declarative.btrc -o examples/gui/declarative.c

# Optional SDK-backed loading uses the canonical native package plan. Missing
# SDKs and compilation failures are explicit errors, not successful skips.
font: font_smoke.c
	cd $(ROOT) && python3 -m tools.native_plan --plan examples/gui/font_smoke.link.json --generated-c examples/gui/font_smoke.c --output examples/gui/gui_font --cc clang --cxx clang++
	./gui_font

font_smoke.c: FontSmoke.btrc
	cd $(ROOT) && $(BTRC) examples/gui/FontSmoke.btrc -o examples/gui/font_smoke.c --emit-link-plan examples/gui/font_smoke.link.json

clean:
	rm -f main.c gui_demo declarative.c gui_declarative font_smoke.c font_smoke.link.json gui_font
