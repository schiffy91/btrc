# Shared settings for the example Makefiles.
#
# Every example transpiles from the repository root, so imports and diagnostics
# resolve the same way as in the test suites. The Python reference compiler is
# the default; build an example with the self-hosted compiler instead with
#   make BTRC=/path/to/btrcc
# test_examples.py transpiles every entry through both compilers and checks the
# generated C is byte-identical.

EXAMPLES_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BTRC_ROOT := $(abspath $(EXAMPLES_DIR)/..)
PYTHON ?= python3
BTRC ?= PYTHONPATH=$(BTRC_ROOT) $(PYTHON) -m src.compiler.python.main
NATIVE_PLAN ?= PYTHONPATH=$(BTRC_ROOT) $(PYTHON) -m tools.native_plan
CXX ?= c++
PKG_CONFIG ?= pkg-config

# Generated C is strict C11; every hosted example compiles it that way.
STRICT_CFLAGS := -std=c11 -pedantic-errors -Wall -Wextra -Werror
HOSTED_LIBS := -lm -lpthread

# The native plan builds Objective-C adapters on macOS, which need Apple clang.
ifeq ($(shell uname -s),Darwin)
NATIVE_CC ?= clang
NATIVE_CXX ?= clang++
else
NATIVE_CC ?= $(CC)
NATIVE_CXX ?= $(CXX)
endif

# The directory of the including example, relative to the repository root.
EXAMPLE := examples/$(notdir $(CURDIR))
