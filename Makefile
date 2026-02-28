.PHONY: build test test-btrc generate-expected gen-builtins lint format install-ext package-ext clean

build:
	@mkdir -p bin
	@echo '#!/usr/bin/env python3' > bin/btrcpy
	@echo 'import sys, os' >> bin/btrcpy
	@echo 'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' >> bin/btrcpy
	@echo 'from src.compiler.python.main import main' >> bin/btrcpy
	@echo 'main()' >> bin/btrcpy
	@chmod +x bin/btrcpy
	@echo "Built bin/btrcpy"

test:
	python3 -m pytest src/compiler/python/tests/ src/tests/runner.py -x -q

test-btrc:
	python3 -m pytest src/tests/runner.py -x -q

generate-expected:
	python3 src/tests/generate_expected.py

gen-builtins:
	python3 src/language/ast/gen_builtins.py

lint:
	ruff check src/

format:
	ruff format src/

install-ext:
	cd src/devex/ext && npm install && npm run install-ext

package-ext:
	cd src/devex/ext && npm install && npm run package

clean:
	rm -rf bin/ src/devex/ext/out/ src/devex/ext/node_modules/ src/devex/ext/*.vsix
