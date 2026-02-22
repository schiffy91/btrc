.PHONY: build test test-all bootstrap generate-expected lint format install-ext package-ext clean

build:
	@mkdir -p build
	python3 btrc.py src/compiler/btrc/btrc_compiler.btrc -o build/btrc_compiler.c
	gcc build/btrc_compiler.c -o build/btrc_compiler -lm -Wno-parentheses-equality

test:
	python3 -m pytest src/compiler/python/tests/ src/tests/test_btrc_runner.py -x -q

test-all:
	python3 -m pytest src/compiler/python/tests/ src/tests/ -x -q

generate-expected:
	python3 src/tests/generate_expected.py

lint:
	ruff check src/ devex/

format:
	ruff format src/ devex/

bootstrap: build
	@echo "Stage 2: self-hosted compiles itself..."
	./build/btrc_compiler src/compiler/btrc/btrc_compiler.btrc -o build/btrc_stage2.c
	gcc build/btrc_stage2.c -o build/btrc_stage2 -lm -Wno-parentheses-equality
	@echo "Stage 2 verification..."
	./build/btrc_stage2 src/tests/test_classes.btrc -o /tmp/btrc_verify.c
	gcc /tmp/btrc_verify.c -o /tmp/btrc_verify -lm
	/tmp/btrc_verify
	@echo "Bootstrap successful!"

install-ext:
	cd devex/ext && npm install && npm run install-ext

package-ext:
	cd devex/ext && npm install && npm run package

clean:
	rm -rf build/ devex/ext/out/ devex/ext/node_modules/ devex/ext/btrc.vsix
