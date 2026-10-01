include ../Example.mk

.PHONY: run clean

run: callback
	./callback

callback: callback.c
	$(CC) $(STRICT_CFLAGS) callback.c -o callback $(HOSTED_LIBS)

callback.c: Main.btrc $(BTRC_ROOT)/src/stdlib/Callback.btrc
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Main.btrc -o $(EXAMPLE)/callback.c

clean:
	rm -f callback.c callback
