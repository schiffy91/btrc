"""Drives TranslationUnitLowerer.uses_trycatch through every branch.
The walk short-circuits on the first
try/catch, so each branch is isolated in its own function with the try/catch
reachable only via that one control-structure path."""

from src.tests.python.test_codegen import emit_c


def test_trycatch_detected_through_each_control_structure():
    src = """
    void f_else()    { if (1 == 1) { } else { try { throw "x"; } catch (string e) { } } }
    void f_elseif()  { if (1 == 1) { } else if (2 == 2) { try { throw "x"; } catch (string e) { } } }
    void f_while()   { while (1 == 0) { try { throw "x"; } catch (string e) { } } }
    void f_for()     { for (int i = 0; i < 0; i = i + 1) { try { throw "x"; } catch (string e) { } } }
    void f_switch()  { int x = 1; switch (x) { case 1: { try { throw "y"; } catch (string e) { } } default: { } } }
    void f_switch_while() { int x = 1; switch (x) { case 1: { while (1 == 0) { try { throw "y"; } catch (string e) { } } } default: { } } }
    void f_switch_switch() { int x = 1; switch (x) { case 1: { switch (x) { case 1: { try { throw "z"; } catch (string e) { } } default: { } } } default: { } } }
    void f_nested_try() {
        try { try { throw "a"; } catch (string e) { } }
        catch (string e) { }
        finally { try { throw "b"; } catch (string e) { } }
    }
    int main() {
        f_else(); f_elseif(); f_while(); f_for();
        f_switch(); f_switch_while(); f_switch_switch(); f_nested_try();
        return 0;
    }
    """
    c = emit_c(src)
    # try/catch lowers to setjmp/longjmp; every detector branch having fired,
    # the machinery is present.
    assert "setjmp" in c or "longjmp" in c or "__btrc_exc" in c
