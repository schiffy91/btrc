BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
CC       ?= cc
SOURCE   := main.btrc
GENERATED := main.c
PROGRAM  := realtime-primitives

.PHONY: all run clean

all: run

run: $(PROGRAM)
	./$(PROGRAM)

$(PROGRAM): $(GENERATED)
	$(CC) -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 \
		$(GENERATED) -o $(PROGRAM) -lm -lpthread

$(GENERATED): $(SOURCE) $(BTRC_ROOT)/src/stdlib/spsc.btrc
	cd $(BTRC_ROOT) && $(BTRC) examples/realtime-primitives/$(SOURCE) \
		-o examples/realtime-primitives/$(GENERATED)

clean:
	rm -f $(GENERATED) $(PROGRAM)
