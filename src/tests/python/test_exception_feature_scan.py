"""Whole-module exception discovery, including expression-owned bodies."""

from __future__ import annotations

import re

from src.compiler.python.ir.lowering.translation_unit import TranslationUnitLowerer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c


def _parse(source: str):
    return Parser(Lexer(source, "<test>").tokenize()).parse()


def test_exception_scan_descends_into_lambda_expressions() -> None:
    program = _parse('void invoke() { var fail = () => { throw "nested"; }; fail(); }')

    assert TranslationUnitLowerer.program_uses_trycatch(program)


def test_exception_scan_tolerates_cyclic_annotations() -> None:
    sequence = []
    sequence.append(sequence)
    mapping = {}
    mapping["self"] = mapping

    assert not TranslationUnitLowerer.uses_trycatch(sequence)
    assert not TranslationUnitLowerer.uses_trycatch(mapping)


def test_lambda_only_exception_contract_guards_constructor_wrapper() -> None:
    generated = emit_c(
        """
        class LambdaScanChild {
            public LambdaScanChild() {}
        }
        class LambdaScanOwner {
            public LambdaScanChild child;
            public LambdaScanOwner() {
                self.child = new LambdaScanChild();
                var fail = () => { throw "constructor failure"; };
                fail();
            }
        }
        int main() {
            var run = () => {
                try {
                    LambdaScanOwner value = new LambdaScanOwner();
                } catch (string error) {
                    return error.equals("constructor failure") ? 0 : 1;
                }
                return 2;
            };
            return run();
        }
        """
    )
    definition = re.search(
        r"LambdaScanOwner\* LambdaScanOwner_new\([^)]*\) \{(.*?)^\}",
        generated,
        re.MULTILINE | re.DOTALL,
    )

    assert definition is not None
    assert "__btrc_register_direct_cleanup" in definition.group(1)
    assert "__btrc_arc_abandon" in definition.group(1)
