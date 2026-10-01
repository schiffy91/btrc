BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..

# Headless example — runs offscreen, no display required.
run: font

# Optional SDK-backed loading uses the canonical native package plan. Missing
# SDKs and compilation failures are explicit errors, not successful skips.
font: font_smoke.c
	cd $(ROOT) && python3 -m tools.native_plan --plan examples/gui/font_smoke.link.json --generated-c examples/gui/font_smoke.c --output examples/gui/gui_font --cc clang --cxx clang++
	./gui_font

font_smoke.c: FontSmoke.btrc
	cd $(ROOT) && $(BTRC) examples/gui/FontSmoke.btrc -o examples/gui/font_smoke.c --emit-link-plan examples/gui/font_smoke.link.json

clean:
	rm -f font_smoke.c font_smoke.link.json gui_font
