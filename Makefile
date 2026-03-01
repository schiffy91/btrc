# btrc
# Usage: make <target>
# All targets run inside `nix develop` to ensure Python 3.13 + gcc + ruff.

.PHONY: help build test test-btrc generate-expected gen-builtins lint format install-ext package-ext setup-gpu gpu-example devcontainer clean

SHELL := /bin/bash
NIX   := nix develop --command

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: ## Create bin/btrcpy wrapper script
	@mkdir -p bin
	@echo '#!/usr/bin/env python3' > bin/btrcpy
	@echo 'import sys, os' >> bin/btrcpy
	@echo 'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))' >> bin/btrcpy
	@echo 'from src.compiler.python.main import main' >> bin/btrcpy
	@echo 'main()' >> bin/btrcpy
	@chmod +x bin/btrcpy
	@echo "Built bin/btrcpy"

test: ## Run all tests (unit + language)
	$(NIX) python3 -m pytest src/compiler/python/tests/ src/tests/runner.py -x -q -n auto

test-btrc: ## Run language tests only (292 .btrc files)
	$(NIX) python3 -m pytest src/tests/runner.py -x -q -n auto

generate-expected: ## Regenerate golden .stdout files
	$(NIX) python3 src/tests/generate_expected.py

gen-builtins: ## Regenerate built-in type stubs
	$(NIX) python3 src/language/ast/gen_builtins.py

lint: ## Run ruff linter
	$(NIX) ruff check src/

format: ## Format with ruff
	$(NIX) ruff format src/

install-ext: ## Install VSCode extension (dev)
	cd src/devex/ext && npm install && npm run install-ext

package-ext: ## Package VSCode extension (.vsix)
	cd src/devex/ext && npm install && npm run package

setup-gpu: ## Install WebGPU + GLFW and build GPU runtime
	$(NIX) nix run .#setup-gpu -- $(ARGS)

gpu-example: ## Build and run the GPU triangle example
	$(MAKE) -C examples/gpu triangle

devcontainer: ## Generate .devcontainer/ and build image
	@set -e; \
	mkdir -p .devcontainer; \
	nix build .#devcontainer --out-link .devcontainer/.result; \
	install -m 644 .devcontainer/.result/devcontainer.json .devcontainer/devcontainer.json; \
	install -m 644 .devcontainer/.result/Containerfile .devcontainer/Containerfile; \
	install -m 644 .devcontainer/.result/bashrc .devcontainer/bashrc; \
	install -m 755 .devcontainer/.result/host.sh .devcontainer/host.sh; \
	install -m 755 .devcontainer/.result/container.sh .devcontainer/container.sh; \
	rm -f .devcontainer/.result; \
	podman build -f .devcontainer/Containerfile -t btrc-devcontainer:latest .; \
	echo "Done. Image: btrc-devcontainer:latest"

clean: ## Remove all build artifacts
	rm -rf bin/ .btrc-cache/ src/devex/ext/out/ src/devex/ext/node_modules/ src/devex/ext/*.vsix src/stdlib/gpu/build/
