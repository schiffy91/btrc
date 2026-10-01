include ../Example.mk

.PHONY: all run clean

all: run

# Main.btrc exercises the bounded primitives; RealtimeGain.btrc is the
# standalone @realtime kernel, which exits nonzero if its arithmetic is wrong.
run: realtime-primitives realtime-gain
	./realtime-primitives
	./realtime-gain

realtime-primitives: main.c
	$(CC) $(STRICT_CFLAGS) -O2 main.c -o realtime-primitives $(HOSTED_LIBS)

realtime-gain: gain.c
	$(CC) $(STRICT_CFLAGS) -O2 gain.c -o realtime-gain $(HOSTED_LIBS)

main.c: Main.btrc $(BTRC_ROOT)/src/stdlib/SPSC.btrc
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Main.btrc -o $(EXAMPLE)/main.c

gain.c: RealtimeGain.btrc
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/RealtimeGain.btrc -o $(EXAMPLE)/gain.c

clean:
	rm -f main.c gain.c realtime-primitives realtime-gain
