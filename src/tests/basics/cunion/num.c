/* Raw C union for btrc interop. `union` is interop-only in btrc (grammar
   line 30): defined here in C and referenced via the `union IDENT` base_type. */
#ifndef BTRC_TEST_CUNION_NUM_C
#define BTRC_TEST_CUNION_NUM_C
union Num { int i; float f; };
#endif
