/* Raw C enum for btrc interop, referenced via the `enum IDENT` base_type
   (grammar.ebnf line 275). Distinct from btrc-native `enum` declarations:
   this is a plain C enum whose enumerators are bare integer constants. */
#ifndef BTRC_TEST_CENUM_COLOR_C
#define BTRC_TEST_CENUM_COLOR_C
enum Color { RED, GREEN, BLUE };
#endif
