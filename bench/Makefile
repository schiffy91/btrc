# btrc benchmark suite — times transpile + C compile + run for each program.
# Run from the project root via `make bench` (inside the nix dev shell).
ROOT    := ..
BTRC    := python3 -m src.compiler.python.main
CC      := cc
CFLAGS  := -std=c11 -O2
BENCHES := fib loop vector strings

.PHONY: all clean
all:
	@for b in $(BENCHES); do \
	  echo "=== $$b ==="; \
	  ( cd $(ROOT) && $(BTRC) bench/$$b.btrc -o bench/$$b.c ) >/dev/null || exit 1; \
	  $(CC) $(CFLAGS) $$b.c -o $$b -lm -lpthread || exit 1; \
	  /usr/bin/time -p ./$$b; \
	  echo ""; \
	done

clean:
	rm -f *.c fib loop vector strings
