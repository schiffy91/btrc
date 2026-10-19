/* Compiles the vendored musl sources (musl/) into the including translation
   unit for the Windows overlays: regex.h, fnmatch.h and glob.h each include
   this file once with their part selected (BTRC_WIN_MUSL_PART_REGEX,
   _FNMATCH or _GLOB), and each part compiles at most once per unit.

   The sources are textually included, so this file keeps them hygienic in a
   unit that also holds generated btrc code, MinGW headers and windows.h:

   - every system header the sources include is included first, so their own
     #include lines are no-ops and no system declaration is renamed;
   - every macro the sources or this file define, and every name renamed
     below, is saved with push_macro and undefined first, then undefined and
     restored with pop_macro afterwards, so a caller's MIN, END, TAG or
     assert is untouched and nothing new is left defined;
   - every file-scope name the sources declare is renamed into the
     btrc_win_musl_ namespace, and every function has internal linkage (the
     overlays declare the POSIX entry points static), so units never collide
     and a caller's identifiers never meet the engine's;
   - the library calls whose result depends on the locale (mbtowc, the
     wide-character classes and case mappings, isdigit) are redirected to the
     C-locale versions defined here: one byte is one character, and only
     ASCII is classified, as in the C locale glibc and macOS match in.

   test_windows_posix_overlay.py checks the hygiene: the macros visible after
   each overlay are exactly the caller's plus that overlay's POSIX names, and
   every file-scope name the engine declares is in btrc's namespace. */

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
#ifdef BTRC_WIN_MUSL_PART_GLOB
#include <io.h>
#include "btrc_win_realpath.h"
#endif

/* Save, then clear, every name this file or the sources define or rename. */
#pragma push_macro("ALIGN")
#pragma push_macro("ASSERTION")
#pragma push_macro("ASSERT_AT_BOL")
#pragma push_macro("ASSERT_AT_BOW")
#pragma push_macro("ASSERT_AT_EOL")
#pragma push_macro("ASSERT_AT_EOW")
#pragma push_macro("ASSERT_AT_WB")
#pragma push_macro("ASSERT_AT_WB_NEG")
#pragma push_macro("ASSERT_BACKREF")
#pragma push_macro("ASSERT_CHAR_CLASS")
#pragma push_macro("ASSERT_CHAR_CLASS_NEG")
#pragma push_macro("ASSERT_LAST")
#pragma push_macro("BACKREF")
#pragma push_macro("BRACKET")
#pragma push_macro("BTRC_WIN_MUSL_TRE_H")
#pragma push_macro("BT_STACK_MBSTATE_IN")
#pragma push_macro("BT_STACK_MBSTATE_OUT")
#pragma push_macro("BT_STACK_POP")
#pragma push_macro("BT_STACK_PUSH")
#pragma push_macro("CHECK_ASSERTIONS")
#pragma push_macro("CHECK_CHAR_CLASSES")
#pragma push_macro("COPY_MAXIMIZE_FIRST_TAG")
#pragma push_macro("COPY_REMOVE_TAGS")
#pragma push_macro("DPRINT")
#pragma push_macro("EMPTY")
#pragma push_macro("END")
#pragma push_macro("ERROR_EXIT")
#pragma push_macro("GET_NEXT_WCHAR")
#pragma push_macro("IS_ASSERTION")
#pragma push_macro("IS_BACKREF")
#pragma push_macro("IS_EMPTY")
#pragma push_macro("IS_SPECIAL")
#pragma push_macro("IS_TAG")
#pragma push_macro("IS_WORD_CHAR")
#pragma push_macro("LCTRANS_CUR")
#pragma push_macro("MAX")
#pragma push_macro("MAX_NEG_CLASSES")
#pragma push_macro("MIN")
#pragma push_macro("PUSHINT")
#pragma push_macro("PUSHPTR")
#pragma push_macro("QUESTION")
#pragma push_macro("STACK_PUSH")
#pragma push_macro("STACK_PUSHR")
#pragma push_macro("STACK_PUSHX")
#pragma push_macro("STAR")
#pragma push_macro("TAG")
#pragma push_macro("TRE_CHAR_MAX")
#pragma push_macro("TRE_MBSTATE")
#pragma push_macro("TRE_MEM_BLOCK_SIZE")
#pragma push_macro("TRE_REGEX_T_FIELD")
#pragma push_macro("TRE_USE_ALLOCA")
#pragma push_macro("UNMATCHABLE")
#pragma push_macro("declare_popf")
#pragma push_macro("declare_pushf")
#pragma push_macro("define_popf")
#pragma push_macro("define_pushf")
#pragma push_macro("elementsof")
#pragma push_macro("tre_bt_mem_alloc")
#pragma push_macro("tre_bt_mem_destroy")
#pragma push_macro("tre_bt_mem_new")
#pragma push_macro("tre_ctype")
#pragma push_macro("tre_isalnum")
#pragma push_macro("tre_isalpha")
#pragma push_macro("tre_isblank")
#pragma push_macro("tre_iscntrl")
#pragma push_macro("tre_isctype")
#pragma push_macro("tre_isdigit")
#pragma push_macro("tre_isgraph")
#pragma push_macro("tre_islower")
#pragma push_macro("tre_isprint")
#pragma push_macro("tre_ispunct")
#pragma push_macro("tre_isspace")
#pragma push_macro("tre_isupper")
#pragma push_macro("tre_isxdigit")
#pragma push_macro("tre_mbrtowc")
#pragma push_macro("tre_mem_alloc")
#pragma push_macro("tre_mem_alloca")
#pragma push_macro("tre_mem_calloc")
#pragma push_macro("tre_mem_new")
#pragma push_macro("tre_mem_newa")
#pragma push_macro("tre_strlen")
#pragma push_macro("tre_tolower")
#pragma push_macro("tre_toupper")
#pragma push_macro("xcalloc")
#pragma push_macro("xfree")
#pragma push_macro("xmalloc")
#pragma push_macro("xrealloc")
#pragma push_macro("PATH_BUFFER_MAX")
#pragma push_macro("DT_UNKNOWN")
#pragma push_macro("DT_DIR")
#pragma push_macro("DT_REG")
#pragma push_macro("INVALID_ATTRIBUTES")
#pragma push_macro("ATTRIBUTE_DIRECTORY")
#pragma push_macro("UTF8_CODE_PAGE")
#pragma push_macro("NO_INVALID_CHARS")
#pragma push_macro("NDEBUG")
#pragma push_macro("assert")
#pragma push_macro("static_assert")
#pragma push_macro("hidden")
#pragma push_macro("RE_DUP_MAX")
#pragma push_macro("CHARCLASS_NAME_MAX")
#pragma push_macro("MB_CUR_MAX")
#pragma push_macro("mbtowc")
#pragma push_macro("isdigit")
#pragma push_macro("iswalnum")
#pragma push_macro("iswalpha")
#pragma push_macro("iswblank")
#pragma push_macro("iswcntrl")
#pragma push_macro("iswdigit")
#pragma push_macro("iswgraph")
#pragma push_macro("iswlower")
#pragma push_macro("iswprint")
#pragma push_macro("iswpunct")
#pragma push_macro("iswspace")
#pragma push_macro("iswupper")
#pragma push_macro("iswxdigit")
#pragma push_macro("towlower")
#pragma push_macro("towupper")
#pragma push_macro("iswctype")
#pragma push_macro("wctype")
#pragma push_macro("reg_errcode_t")
#pragma push_macro("tre_char_t")
#pragma push_macro("tre_cint_t")
#pragma push_macro("tre_ctype_t")
#pragma push_macro("tnfa_transition")
#pragma push_macro("tre_tnfa_transition_t")
#pragma push_macro("TRE_TAG_MINIMIZE")
#pragma push_macro("TRE_TAG_MAXIMIZE")
#pragma push_macro("tre_tag_direction_t")
#pragma push_macro("tre_submatch_data")
#pragma push_macro("tre_submatch_data_t")
#pragma push_macro("tnfa")
#pragma push_macro("tre_tnfa_t")
#pragma push_macro("tre_list")
#pragma push_macro("tre_list_t")
#pragma push_macro("tre_mem_struct")
#pragma push_macro("tre_mem_t")
#pragma push_macro("tre_mem_new_impl")
#pragma push_macro("tre_mem_alloc_impl")
#pragma push_macro("tre_mem_destroy")
#pragma push_macro("tre_pos_and_tags_t")
#pragma push_macro("LITERAL")
#pragma push_macro("CATENATION")
#pragma push_macro("ITERATION")
#pragma push_macro("UNION")
#pragma push_macro("tre_ast_type_t")
#pragma push_macro("tre_ast_node_t")
#pragma push_macro("tre_literal_t")
#pragma push_macro("tre_catenation_t")
#pragma push_macro("tre_iteration_t")
#pragma push_macro("tre_union_t")
#pragma push_macro("tre_ast_new_node")
#pragma push_macro("tre_ast_new_literal")
#pragma push_macro("tre_ast_new_iter")
#pragma push_macro("tre_ast_new_union")
#pragma push_macro("tre_ast_new_catenation")
#pragma push_macro("tre_stack_rec")
#pragma push_macro("tre_stack_t")
#pragma push_macro("tre_stack_new")
#pragma push_macro("tre_stack_destroy")
#pragma push_macro("tre_stack_num_objects")
#pragma push_macro("tre_stack_push_voidptr")
#pragma push_macro("tre_stack_push_int")
#pragma push_macro("tre_stack_pop_voidptr")
#pragma push_macro("tre_stack_pop_int")
#pragma push_macro("tre_stack_item")
#pragma push_macro("tre_stack_push")
#pragma push_macro("tre_parse_ctx_t")
#pragma push_macro("tre_macros")
#pragma push_macro("tre_expand_macro")
#pragma push_macro("tre_compare_lit")
#pragma push_macro("literals")
#pragma push_macro("tre_new_lit")
#pragma push_macro("add_icase_literals")
#pragma push_macro("neg")
#pragma push_macro("parse_bracket_terms")
#pragma push_macro("parse_bracket")
#pragma push_macro("parse_dup_count")
#pragma push_macro("parse_dup")
#pragma push_macro("hexval")
#pragma push_macro("marksub")
#pragma push_macro("parse_atom")
#pragma push_macro("tre_parse")
#pragma push_macro("tre_add_tag_left")
#pragma push_macro("tre_add_tag_right")
#pragma push_macro("ADDTAGS_RECURSE")
#pragma push_macro("ADDTAGS_AFTER_ITERATION")
#pragma push_macro("ADDTAGS_AFTER_UNION_LEFT")
#pragma push_macro("ADDTAGS_AFTER_UNION_RIGHT")
#pragma push_macro("ADDTAGS_AFTER_CAT_LEFT")
#pragma push_macro("ADDTAGS_AFTER_CAT_RIGHT")
#pragma push_macro("ADDTAGS_SET_SUBMATCH_END")
#pragma push_macro("tre_addtags_symbol_t")
#pragma push_macro("tre_tag_states_t")
#pragma push_macro("tre_purge_regset")
#pragma push_macro("tre_add_tags")
#pragma push_macro("COPY_RECURSE")
#pragma push_macro("COPY_SET_RESULT_PTR")
#pragma push_macro("tre_copyast_symbol_t")
#pragma push_macro("tre_copy_ast")
#pragma push_macro("EXPAND_RECURSE")
#pragma push_macro("EXPAND_AFTER_ITER")
#pragma push_macro("tre_expand_ast_symbol_t")
#pragma push_macro("tre_expand_ast")
#pragma push_macro("tre_set_empty")
#pragma push_macro("tre_set_one")
#pragma push_macro("tre_set_union")
#pragma push_macro("tre_match_empty")
#pragma push_macro("NFL_RECURSE")
#pragma push_macro("NFL_POST_UNION")
#pragma push_macro("NFL_POST_CATENATION")
#pragma push_macro("NFL_POST_ITERATION")
#pragma push_macro("tre_nfl_stack_symbol_t")
#pragma push_macro("tre_compute_nfl")
#pragma push_macro("tre_make_trans")
#pragma push_macro("tre_ast_to_tnfa")
#pragma push_macro("tre_fill_pmatch")
#pragma push_macro("tre_tag_order")
#pragma push_macro("tre_neg_char_classes_match")
#pragma push_macro("tre_tnfa_reach_t")
#pragma push_macro("tre_reach_pos_t")
#pragma push_macro("tre_tnfa_run_parallel")
#pragma push_macro("tre_backtrack_item_t")
#pragma push_macro("tre_backtrack_struct")
#pragma push_macro("tre_backtrack_t")
#pragma push_macro("tre_tnfa_run_backtrack")
#pragma push_macro("messages")
#pragma push_macro("str_next")
#pragma push_macro("pat_next")
#pragma push_macro("casefold")
#pragma push_macro("match_bracket")
#pragma push_macro("fnmatch_internal")
#pragma push_macro("directory")
#pragma push_macro("open_directory")
#pragma push_macro("read_directory")
#pragma push_macro("close_directory")
#pragma push_macro("path_type")
#pragma push_macro("match")
#pragma push_macro("append")
#pragma push_macro("do_glob")
#pragma push_macro("ignore_err")
#pragma push_macro("freelist")
#pragma push_macro("sort")
#undef ALIGN
#undef ASSERTION
#undef ASSERT_AT_BOL
#undef ASSERT_AT_BOW
#undef ASSERT_AT_EOL
#undef ASSERT_AT_EOW
#undef ASSERT_AT_WB
#undef ASSERT_AT_WB_NEG
#undef ASSERT_BACKREF
#undef ASSERT_CHAR_CLASS
#undef ASSERT_CHAR_CLASS_NEG
#undef ASSERT_LAST
#undef BACKREF
#undef BRACKET
#undef BTRC_WIN_MUSL_TRE_H
#undef BT_STACK_MBSTATE_IN
#undef BT_STACK_MBSTATE_OUT
#undef BT_STACK_POP
#undef BT_STACK_PUSH
#undef CHECK_ASSERTIONS
#undef CHECK_CHAR_CLASSES
#undef COPY_MAXIMIZE_FIRST_TAG
#undef COPY_REMOVE_TAGS
#undef DPRINT
#undef EMPTY
#undef END
#undef ERROR_EXIT
#undef GET_NEXT_WCHAR
#undef IS_ASSERTION
#undef IS_BACKREF
#undef IS_EMPTY
#undef IS_SPECIAL
#undef IS_TAG
#undef IS_WORD_CHAR
#undef LCTRANS_CUR
#undef MAX
#undef MAX_NEG_CLASSES
#undef MIN
#undef PUSHINT
#undef PUSHPTR
#undef QUESTION
#undef STACK_PUSH
#undef STACK_PUSHR
#undef STACK_PUSHX
#undef STAR
#undef TAG
#undef TRE_CHAR_MAX
#undef TRE_MBSTATE
#undef TRE_MEM_BLOCK_SIZE
#undef TRE_REGEX_T_FIELD
#undef TRE_USE_ALLOCA
#undef UNMATCHABLE
#undef declare_popf
#undef declare_pushf
#undef define_popf
#undef define_pushf
#undef elementsof
#undef tre_bt_mem_alloc
#undef tre_bt_mem_destroy
#undef tre_bt_mem_new
#undef tre_ctype
#undef tre_isalnum
#undef tre_isalpha
#undef tre_isblank
#undef tre_iscntrl
#undef tre_isctype
#undef tre_isdigit
#undef tre_isgraph
#undef tre_islower
#undef tre_isprint
#undef tre_ispunct
#undef tre_isspace
#undef tre_isupper
#undef tre_isxdigit
#undef tre_mbrtowc
#undef tre_mem_alloc
#undef tre_mem_alloca
#undef tre_mem_calloc
#undef tre_mem_new
#undef tre_mem_newa
#undef tre_strlen
#undef tre_tolower
#undef tre_toupper
#undef xcalloc
#undef xfree
#undef xmalloc
#undef xrealloc
#undef PATH_BUFFER_MAX
#undef DT_UNKNOWN
#undef DT_DIR
#undef DT_REG
#undef INVALID_ATTRIBUTES
#undef ATTRIBUTE_DIRECTORY
#undef UTF8_CODE_PAGE
#undef NO_INVALID_CHARS
#undef NDEBUG
#undef assert
#undef static_assert
#undef hidden
#undef RE_DUP_MAX
#undef CHARCLASS_NAME_MAX
#undef MB_CUR_MAX
#undef mbtowc
#undef isdigit
#undef iswalnum
#undef iswalpha
#undef iswblank
#undef iswcntrl
#undef iswdigit
#undef iswgraph
#undef iswlower
#undef iswprint
#undef iswpunct
#undef iswspace
#undef iswupper
#undef iswxdigit
#undef towlower
#undef towupper
#undef iswctype
#undef wctype
#undef reg_errcode_t
#undef tre_char_t
#undef tre_cint_t
#undef tre_ctype_t
#undef tnfa_transition
#undef tre_tnfa_transition_t
#undef TRE_TAG_MINIMIZE
#undef TRE_TAG_MAXIMIZE
#undef tre_tag_direction_t
#undef tre_submatch_data
#undef tre_submatch_data_t
#undef tnfa
#undef tre_tnfa_t
#undef tre_list
#undef tre_list_t
#undef tre_mem_struct
#undef tre_mem_t
#undef tre_mem_new_impl
#undef tre_mem_alloc_impl
#undef tre_mem_destroy
#undef tre_pos_and_tags_t
#undef LITERAL
#undef CATENATION
#undef ITERATION
#undef UNION
#undef tre_ast_type_t
#undef tre_ast_node_t
#undef tre_literal_t
#undef tre_catenation_t
#undef tre_iteration_t
#undef tre_union_t
#undef tre_ast_new_node
#undef tre_ast_new_literal
#undef tre_ast_new_iter
#undef tre_ast_new_union
#undef tre_ast_new_catenation
#undef tre_stack_rec
#undef tre_stack_t
#undef tre_stack_new
#undef tre_stack_destroy
#undef tre_stack_num_objects
#undef tre_stack_push_voidptr
#undef tre_stack_push_int
#undef tre_stack_pop_voidptr
#undef tre_stack_pop_int
#undef tre_stack_item
#undef tre_stack_push
#undef tre_parse_ctx_t
#undef tre_macros
#undef tre_expand_macro
#undef tre_compare_lit
#undef literals
#undef tre_new_lit
#undef add_icase_literals
#undef neg
#undef parse_bracket_terms
#undef parse_bracket
#undef parse_dup_count
#undef parse_dup
#undef hexval
#undef marksub
#undef parse_atom
#undef tre_parse
#undef tre_add_tag_left
#undef tre_add_tag_right
#undef ADDTAGS_RECURSE
#undef ADDTAGS_AFTER_ITERATION
#undef ADDTAGS_AFTER_UNION_LEFT
#undef ADDTAGS_AFTER_UNION_RIGHT
#undef ADDTAGS_AFTER_CAT_LEFT
#undef ADDTAGS_AFTER_CAT_RIGHT
#undef ADDTAGS_SET_SUBMATCH_END
#undef tre_addtags_symbol_t
#undef tre_tag_states_t
#undef tre_purge_regset
#undef tre_add_tags
#undef COPY_RECURSE
#undef COPY_SET_RESULT_PTR
#undef tre_copyast_symbol_t
#undef tre_copy_ast
#undef EXPAND_RECURSE
#undef EXPAND_AFTER_ITER
#undef tre_expand_ast_symbol_t
#undef tre_expand_ast
#undef tre_set_empty
#undef tre_set_one
#undef tre_set_union
#undef tre_match_empty
#undef NFL_RECURSE
#undef NFL_POST_UNION
#undef NFL_POST_CATENATION
#undef NFL_POST_ITERATION
#undef tre_nfl_stack_symbol_t
#undef tre_compute_nfl
#undef tre_make_trans
#undef tre_ast_to_tnfa
#undef tre_fill_pmatch
#undef tre_tag_order
#undef tre_neg_char_classes_match
#undef tre_tnfa_reach_t
#undef tre_reach_pos_t
#undef tre_tnfa_run_parallel
#undef tre_backtrack_item_t
#undef tre_backtrack_struct
#undef tre_backtrack_t
#undef tre_tnfa_run_backtrack
#undef messages
#undef str_next
#undef pat_next
#undef casefold
#undef match_bracket
#undef fnmatch_internal
#undef directory
#undef open_directory
#undef read_directory
#undef close_directory
#undef path_type
#undef match
#undef append
#undef do_glob
#undef ignore_err
#undef freelist
#undef sort

/* The sources include <assert.h> for internal invariants, which musl
   compiles out; NDEBUG makes that inclusion define a no-op assert. */
#define NDEBUG
/* musl's internal-visibility marker: internal linkage here. */
#define hidden static
/* <limits.h> constants musl provides and MinGW does not. */
#define RE_DUP_MAX 255
#define CHARCLASS_NAME_MAX 14

/* C-locale library calls. */
#define mbtowc btrc_win_musl_mbtowc
#define isdigit btrc_win_musl_isdigit
#define iswalnum btrc_win_musl_iswalnum
#define iswalpha btrc_win_musl_iswalpha
#define iswblank btrc_win_musl_iswblank
#define iswcntrl btrc_win_musl_iswcntrl
#define iswdigit btrc_win_musl_iswdigit
#define iswgraph btrc_win_musl_iswgraph
#define iswlower btrc_win_musl_iswlower
#define iswprint btrc_win_musl_iswprint
#define iswpunct btrc_win_musl_iswpunct
#define iswspace btrc_win_musl_iswspace
#define iswupper btrc_win_musl_iswupper
#define iswxdigit btrc_win_musl_iswxdigit
#define towlower btrc_win_musl_towlower
#define towupper btrc_win_musl_towupper
#define iswctype btrc_win_musl_iswctype
#define wctype btrc_win_musl_wctype

/* The file-scope names the sources declare. */
#define reg_errcode_t btrc_win_musl_reg_errcode_t
#define tre_char_t btrc_win_musl_tre_char_t
#define tre_cint_t btrc_win_musl_tre_cint_t
#define tre_ctype_t btrc_win_musl_tre_ctype_t
#define tnfa_transition btrc_win_musl_tnfa_transition
#define tre_tnfa_transition_t btrc_win_musl_tre_tnfa_transition_t
#define TRE_TAG_MINIMIZE btrc_win_musl_TRE_TAG_MINIMIZE
#define TRE_TAG_MAXIMIZE btrc_win_musl_TRE_TAG_MAXIMIZE
#define tre_tag_direction_t btrc_win_musl_tre_tag_direction_t
#define tre_submatch_data btrc_win_musl_tre_submatch_data
#define tre_submatch_data_t btrc_win_musl_tre_submatch_data_t
#define tnfa btrc_win_musl_tnfa
#define tre_tnfa_t btrc_win_musl_tre_tnfa_t
#define tre_list btrc_win_musl_tre_list
#define tre_list_t btrc_win_musl_tre_list_t
#define tre_mem_struct btrc_win_musl_tre_mem_struct
#define tre_mem_t btrc_win_musl_tre_mem_t
#define tre_mem_new_impl btrc_win_musl_tre_mem_new_impl
#define tre_mem_alloc_impl btrc_win_musl_tre_mem_alloc_impl
#define tre_mem_destroy btrc_win_musl_tre_mem_destroy
#define tre_pos_and_tags_t btrc_win_musl_tre_pos_and_tags_t
#define LITERAL btrc_win_musl_LITERAL
#define CATENATION btrc_win_musl_CATENATION
#define ITERATION btrc_win_musl_ITERATION
#define UNION btrc_win_musl_UNION
#define tre_ast_type_t btrc_win_musl_tre_ast_type_t
#define tre_ast_node_t btrc_win_musl_tre_ast_node_t
#define tre_literal_t btrc_win_musl_tre_literal_t
#define tre_catenation_t btrc_win_musl_tre_catenation_t
#define tre_iteration_t btrc_win_musl_tre_iteration_t
#define tre_union_t btrc_win_musl_tre_union_t
#define tre_ast_new_node btrc_win_musl_tre_ast_new_node
#define tre_ast_new_literal btrc_win_musl_tre_ast_new_literal
#define tre_ast_new_iter btrc_win_musl_tre_ast_new_iter
#define tre_ast_new_union btrc_win_musl_tre_ast_new_union
#define tre_ast_new_catenation btrc_win_musl_tre_ast_new_catenation
#define tre_stack_rec btrc_win_musl_tre_stack_rec
#define tre_stack_t btrc_win_musl_tre_stack_t
#define tre_stack_new btrc_win_musl_tre_stack_new
#define tre_stack_destroy btrc_win_musl_tre_stack_destroy
#define tre_stack_num_objects btrc_win_musl_tre_stack_num_objects
#define tre_stack_push_voidptr btrc_win_musl_tre_stack_push_voidptr
#define tre_stack_push_int btrc_win_musl_tre_stack_push_int
#define tre_stack_pop_voidptr btrc_win_musl_tre_stack_pop_voidptr
#define tre_stack_pop_int btrc_win_musl_tre_stack_pop_int
#define tre_stack_item btrc_win_musl_tre_stack_item
#define tre_stack_push btrc_win_musl_tre_stack_push
#define tre_parse_ctx_t btrc_win_musl_tre_parse_ctx_t
#define tre_macros btrc_win_musl_tre_macros
#define tre_expand_macro btrc_win_musl_tre_expand_macro
#define tre_compare_lit btrc_win_musl_tre_compare_lit
#define literals btrc_win_musl_literals
#define tre_new_lit btrc_win_musl_tre_new_lit
#define add_icase_literals btrc_win_musl_add_icase_literals
#define neg btrc_win_musl_neg
#define parse_bracket_terms btrc_win_musl_parse_bracket_terms
#define parse_bracket btrc_win_musl_parse_bracket
#define parse_dup_count btrc_win_musl_parse_dup_count
#define parse_dup btrc_win_musl_parse_dup
#define hexval btrc_win_musl_hexval
#define marksub btrc_win_musl_marksub
#define parse_atom btrc_win_musl_parse_atom
#define tre_parse btrc_win_musl_tre_parse
#define tre_add_tag_left btrc_win_musl_tre_add_tag_left
#define tre_add_tag_right btrc_win_musl_tre_add_tag_right
#define ADDTAGS_RECURSE btrc_win_musl_ADDTAGS_RECURSE
#define ADDTAGS_AFTER_ITERATION btrc_win_musl_ADDTAGS_AFTER_ITERATION
#define ADDTAGS_AFTER_UNION_LEFT btrc_win_musl_ADDTAGS_AFTER_UNION_LEFT
#define ADDTAGS_AFTER_UNION_RIGHT btrc_win_musl_ADDTAGS_AFTER_UNION_RIGHT
#define ADDTAGS_AFTER_CAT_LEFT btrc_win_musl_ADDTAGS_AFTER_CAT_LEFT
#define ADDTAGS_AFTER_CAT_RIGHT btrc_win_musl_ADDTAGS_AFTER_CAT_RIGHT
#define ADDTAGS_SET_SUBMATCH_END btrc_win_musl_ADDTAGS_SET_SUBMATCH_END
#define tre_addtags_symbol_t btrc_win_musl_tre_addtags_symbol_t
#define tre_tag_states_t btrc_win_musl_tre_tag_states_t
#define tre_purge_regset btrc_win_musl_tre_purge_regset
#define tre_add_tags btrc_win_musl_tre_add_tags
#define COPY_RECURSE btrc_win_musl_COPY_RECURSE
#define COPY_SET_RESULT_PTR btrc_win_musl_COPY_SET_RESULT_PTR
#define tre_copyast_symbol_t btrc_win_musl_tre_copyast_symbol_t
#define tre_copy_ast btrc_win_musl_tre_copy_ast
#define EXPAND_RECURSE btrc_win_musl_EXPAND_RECURSE
#define EXPAND_AFTER_ITER btrc_win_musl_EXPAND_AFTER_ITER
#define tre_expand_ast_symbol_t btrc_win_musl_tre_expand_ast_symbol_t
#define tre_expand_ast btrc_win_musl_tre_expand_ast
#define tre_set_empty btrc_win_musl_tre_set_empty
#define tre_set_one btrc_win_musl_tre_set_one
#define tre_set_union btrc_win_musl_tre_set_union
#define tre_match_empty btrc_win_musl_tre_match_empty
#define NFL_RECURSE btrc_win_musl_NFL_RECURSE
#define NFL_POST_UNION btrc_win_musl_NFL_POST_UNION
#define NFL_POST_CATENATION btrc_win_musl_NFL_POST_CATENATION
#define NFL_POST_ITERATION btrc_win_musl_NFL_POST_ITERATION
#define tre_nfl_stack_symbol_t btrc_win_musl_tre_nfl_stack_symbol_t
#define tre_compute_nfl btrc_win_musl_tre_compute_nfl
#define tre_make_trans btrc_win_musl_tre_make_trans
#define tre_ast_to_tnfa btrc_win_musl_tre_ast_to_tnfa
#define tre_fill_pmatch btrc_win_musl_tre_fill_pmatch
#define tre_tag_order btrc_win_musl_tre_tag_order
#define tre_neg_char_classes_match btrc_win_musl_tre_neg_char_classes_match
#define tre_tnfa_reach_t btrc_win_musl_tre_tnfa_reach_t
#define tre_reach_pos_t btrc_win_musl_tre_reach_pos_t
#define tre_tnfa_run_parallel btrc_win_musl_tre_tnfa_run_parallel
#define tre_backtrack_item_t btrc_win_musl_tre_backtrack_item_t
#define tre_backtrack_struct btrc_win_musl_tre_backtrack_struct
#define tre_backtrack_t btrc_win_musl_tre_backtrack_t
#define tre_tnfa_run_backtrack btrc_win_musl_tre_tnfa_run_backtrack
#define messages btrc_win_musl_messages
#define str_next btrc_win_musl_str_next
#define pat_next btrc_win_musl_pat_next
#define casefold btrc_win_musl_casefold
#define match_bracket btrc_win_musl_match_bracket
#define fnmatch_internal btrc_win_musl_fnmatch_internal
#define directory btrc_win_musl_directory
#define open_directory btrc_win_musl_open_directory
#define read_directory btrc_win_musl_read_directory
#define close_directory btrc_win_musl_close_directory
#define path_type btrc_win_musl_path_type
#define match btrc_win_musl_match
#define append btrc_win_musl_append
#define do_glob btrc_win_musl_do_glob
#define ignore_err btrc_win_musl_ignore_err
#define freelist btrc_win_musl_freelist
#define sort btrc_win_musl_sort

/* A unit uses only some of the engine's functions. musl, which builds
   without -Wextra, compares a char with 128U on purpose (a high byte converts
   to a large unsigned value) and leaves regerror's preg unused. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wunused-parameter"

#ifndef BTRC_WIN_MUSL_C_LOCALE
#define BTRC_WIN_MUSL_C_LOCALE
static int btrc_win_musl_mbtowc(wchar_t *character, const char *bytes, size_t length)
{
	if (!bytes) return 0;
	if (!length) return -1;
	if (character) *character = (wchar_t)(unsigned char)*bytes;
	return *bytes != 0;
}
static int btrc_win_musl_iswupper(int c) { return c >= 'A' && c <= 'Z'; }
static int btrc_win_musl_iswlower(int c) { return c >= 'a' && c <= 'z'; }
static int btrc_win_musl_iswalpha(int c) { return btrc_win_musl_iswupper(c) || btrc_win_musl_iswlower(c); }
static int btrc_win_musl_iswdigit(int c) { return c >= '0' && c <= '9'; }
static int btrc_win_musl_isdigit(int c) { return btrc_win_musl_iswdigit(c); }
static int btrc_win_musl_iswalnum(int c) { return btrc_win_musl_iswalpha(c) || btrc_win_musl_iswdigit(c); }
static int btrc_win_musl_iswblank(int c) { return c == ' ' || c == '\t'; }
static int btrc_win_musl_iswcntrl(int c) { return (c >= 0 && c < 0x20) || c == 0x7f; }
static int btrc_win_musl_iswgraph(int c) { return c > 0x20 && c < 0x7f; }
static int btrc_win_musl_iswprint(int c) { return c >= 0x20 && c < 0x7f; }
static int btrc_win_musl_iswpunct(int c) { return btrc_win_musl_iswgraph(c) && !btrc_win_musl_iswalnum(c); }
static int btrc_win_musl_iswspace(int c) { return c == ' ' || (c >= '\t' && c <= '\r'); }
static int btrc_win_musl_iswxdigit(int c)
{
	return btrc_win_musl_iswdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
static int btrc_win_musl_towlower(int c) { return btrc_win_musl_iswupper(c) ? c - 'A' + 'a' : c; }
static int btrc_win_musl_towupper(int c) { return btrc_win_musl_iswlower(c) ? c - 'a' + 'A' : c; }
static const char btrc_win_musl_classes[12][7] = {
	"alnum", "alpha", "blank", "cntrl", "digit", "graph",
	"lower", "print", "punct", "space", "upper", "xdigit",
};
static wctype_t btrc_win_musl_wctype(const char *name)
{
	for (int index = 0; index < 12; index++)
		if (!strcmp(name, btrc_win_musl_classes[index])) return (wctype_t)(index + 1);
	return 0;
}
static int btrc_win_musl_iswctype(int c, wctype_t class_id)
{
	switch (class_id) {
	case 1: return btrc_win_musl_iswalnum(c);
	case 2: return btrc_win_musl_iswalpha(c);
	case 3: return btrc_win_musl_iswblank(c);
	case 4: return btrc_win_musl_iswcntrl(c);
	case 5: return btrc_win_musl_iswdigit(c);
	case 6: return btrc_win_musl_iswgraph(c);
	case 7: return btrc_win_musl_iswlower(c);
	case 8: return btrc_win_musl_iswprint(c);
	case 9: return btrc_win_musl_iswpunct(c);
	case 10: return btrc_win_musl_iswspace(c);
	case 11: return btrc_win_musl_iswupper(c);
	case 12: return btrc_win_musl_iswxdigit(c);
	default: return 0;
	}
}
#endif

#if defined(BTRC_WIN_MUSL_PART_REGEX) && !defined(BTRC_WIN_MUSL_REGEX)
#define BTRC_WIN_MUSL_REGEX
#include "musl/tre.h"
#include "musl/tre-mem.c"
#include "musl/regcomp.c"
#include "musl/regexec.c"
#include "musl/regerror.c"
#endif

#if defined(BTRC_WIN_MUSL_PART_FNMATCH) && !defined(BTRC_WIN_MUSL_FNMATCH)
#define BTRC_WIN_MUSL_FNMATCH
#include "musl/fnmatch.c"
#endif

#if defined(BTRC_WIN_MUSL_PART_GLOB) && !defined(BTRC_WIN_MUSL_GLOB)
#define BTRC_WIN_MUSL_GLOB
#include "musl/glob.c"
#endif

#pragma GCC diagnostic pop

/* Undefine every name used above and restore the caller's definitions. */
#undef ALIGN
#undef ASSERTION
#undef ASSERT_AT_BOL
#undef ASSERT_AT_BOW
#undef ASSERT_AT_EOL
#undef ASSERT_AT_EOW
#undef ASSERT_AT_WB
#undef ASSERT_AT_WB_NEG
#undef ASSERT_BACKREF
#undef ASSERT_CHAR_CLASS
#undef ASSERT_CHAR_CLASS_NEG
#undef ASSERT_LAST
#undef BACKREF
#undef BRACKET
#undef BTRC_WIN_MUSL_TRE_H
#undef BT_STACK_MBSTATE_IN
#undef BT_STACK_MBSTATE_OUT
#undef BT_STACK_POP
#undef BT_STACK_PUSH
#undef CHECK_ASSERTIONS
#undef CHECK_CHAR_CLASSES
#undef COPY_MAXIMIZE_FIRST_TAG
#undef COPY_REMOVE_TAGS
#undef DPRINT
#undef EMPTY
#undef END
#undef ERROR_EXIT
#undef GET_NEXT_WCHAR
#undef IS_ASSERTION
#undef IS_BACKREF
#undef IS_EMPTY
#undef IS_SPECIAL
#undef IS_TAG
#undef IS_WORD_CHAR
#undef LCTRANS_CUR
#undef MAX
#undef MAX_NEG_CLASSES
#undef MIN
#undef PUSHINT
#undef PUSHPTR
#undef QUESTION
#undef STACK_PUSH
#undef STACK_PUSHR
#undef STACK_PUSHX
#undef STAR
#undef TAG
#undef TRE_CHAR_MAX
#undef TRE_MBSTATE
#undef TRE_MEM_BLOCK_SIZE
#undef TRE_REGEX_T_FIELD
#undef TRE_USE_ALLOCA
#undef UNMATCHABLE
#undef declare_popf
#undef declare_pushf
#undef define_popf
#undef define_pushf
#undef elementsof
#undef tre_bt_mem_alloc
#undef tre_bt_mem_destroy
#undef tre_bt_mem_new
#undef tre_ctype
#undef tre_isalnum
#undef tre_isalpha
#undef tre_isblank
#undef tre_iscntrl
#undef tre_isctype
#undef tre_isdigit
#undef tre_isgraph
#undef tre_islower
#undef tre_isprint
#undef tre_ispunct
#undef tre_isspace
#undef tre_isupper
#undef tre_isxdigit
#undef tre_mbrtowc
#undef tre_mem_alloc
#undef tre_mem_alloca
#undef tre_mem_calloc
#undef tre_mem_new
#undef tre_mem_newa
#undef tre_strlen
#undef tre_tolower
#undef tre_toupper
#undef xcalloc
#undef xfree
#undef xmalloc
#undef xrealloc
#undef PATH_BUFFER_MAX
#undef DT_UNKNOWN
#undef DT_DIR
#undef DT_REG
#undef INVALID_ATTRIBUTES
#undef ATTRIBUTE_DIRECTORY
#undef UTF8_CODE_PAGE
#undef NO_INVALID_CHARS
#undef NDEBUG
#undef assert
#undef static_assert
#undef hidden
#undef RE_DUP_MAX
#undef CHARCLASS_NAME_MAX
#undef MB_CUR_MAX
#undef mbtowc
#undef isdigit
#undef iswalnum
#undef iswalpha
#undef iswblank
#undef iswcntrl
#undef iswdigit
#undef iswgraph
#undef iswlower
#undef iswprint
#undef iswpunct
#undef iswspace
#undef iswupper
#undef iswxdigit
#undef towlower
#undef towupper
#undef iswctype
#undef wctype
#undef reg_errcode_t
#undef tre_char_t
#undef tre_cint_t
#undef tre_ctype_t
#undef tnfa_transition
#undef tre_tnfa_transition_t
#undef TRE_TAG_MINIMIZE
#undef TRE_TAG_MAXIMIZE
#undef tre_tag_direction_t
#undef tre_submatch_data
#undef tre_submatch_data_t
#undef tnfa
#undef tre_tnfa_t
#undef tre_list
#undef tre_list_t
#undef tre_mem_struct
#undef tre_mem_t
#undef tre_mem_new_impl
#undef tre_mem_alloc_impl
#undef tre_mem_destroy
#undef tre_pos_and_tags_t
#undef LITERAL
#undef CATENATION
#undef ITERATION
#undef UNION
#undef tre_ast_type_t
#undef tre_ast_node_t
#undef tre_literal_t
#undef tre_catenation_t
#undef tre_iteration_t
#undef tre_union_t
#undef tre_ast_new_node
#undef tre_ast_new_literal
#undef tre_ast_new_iter
#undef tre_ast_new_union
#undef tre_ast_new_catenation
#undef tre_stack_rec
#undef tre_stack_t
#undef tre_stack_new
#undef tre_stack_destroy
#undef tre_stack_num_objects
#undef tre_stack_push_voidptr
#undef tre_stack_push_int
#undef tre_stack_pop_voidptr
#undef tre_stack_pop_int
#undef tre_stack_item
#undef tre_stack_push
#undef tre_parse_ctx_t
#undef tre_macros
#undef tre_expand_macro
#undef tre_compare_lit
#undef literals
#undef tre_new_lit
#undef add_icase_literals
#undef neg
#undef parse_bracket_terms
#undef parse_bracket
#undef parse_dup_count
#undef parse_dup
#undef hexval
#undef marksub
#undef parse_atom
#undef tre_parse
#undef tre_add_tag_left
#undef tre_add_tag_right
#undef ADDTAGS_RECURSE
#undef ADDTAGS_AFTER_ITERATION
#undef ADDTAGS_AFTER_UNION_LEFT
#undef ADDTAGS_AFTER_UNION_RIGHT
#undef ADDTAGS_AFTER_CAT_LEFT
#undef ADDTAGS_AFTER_CAT_RIGHT
#undef ADDTAGS_SET_SUBMATCH_END
#undef tre_addtags_symbol_t
#undef tre_tag_states_t
#undef tre_purge_regset
#undef tre_add_tags
#undef COPY_RECURSE
#undef COPY_SET_RESULT_PTR
#undef tre_copyast_symbol_t
#undef tre_copy_ast
#undef EXPAND_RECURSE
#undef EXPAND_AFTER_ITER
#undef tre_expand_ast_symbol_t
#undef tre_expand_ast
#undef tre_set_empty
#undef tre_set_one
#undef tre_set_union
#undef tre_match_empty
#undef NFL_RECURSE
#undef NFL_POST_UNION
#undef NFL_POST_CATENATION
#undef NFL_POST_ITERATION
#undef tre_nfl_stack_symbol_t
#undef tre_compute_nfl
#undef tre_make_trans
#undef tre_ast_to_tnfa
#undef tre_fill_pmatch
#undef tre_tag_order
#undef tre_neg_char_classes_match
#undef tre_tnfa_reach_t
#undef tre_reach_pos_t
#undef tre_tnfa_run_parallel
#undef tre_backtrack_item_t
#undef tre_backtrack_struct
#undef tre_backtrack_t
#undef tre_tnfa_run_backtrack
#undef messages
#undef str_next
#undef pat_next
#undef casefold
#undef match_bracket
#undef fnmatch_internal
#undef directory
#undef open_directory
#undef read_directory
#undef close_directory
#undef path_type
#undef match
#undef append
#undef do_glob
#undef ignore_err
#undef freelist
#undef sort
#pragma pop_macro("ALIGN")
#pragma pop_macro("ASSERTION")
#pragma pop_macro("ASSERT_AT_BOL")
#pragma pop_macro("ASSERT_AT_BOW")
#pragma pop_macro("ASSERT_AT_EOL")
#pragma pop_macro("ASSERT_AT_EOW")
#pragma pop_macro("ASSERT_AT_WB")
#pragma pop_macro("ASSERT_AT_WB_NEG")
#pragma pop_macro("ASSERT_BACKREF")
#pragma pop_macro("ASSERT_CHAR_CLASS")
#pragma pop_macro("ASSERT_CHAR_CLASS_NEG")
#pragma pop_macro("ASSERT_LAST")
#pragma pop_macro("BACKREF")
#pragma pop_macro("BRACKET")
#pragma pop_macro("BTRC_WIN_MUSL_TRE_H")
#pragma pop_macro("BT_STACK_MBSTATE_IN")
#pragma pop_macro("BT_STACK_MBSTATE_OUT")
#pragma pop_macro("BT_STACK_POP")
#pragma pop_macro("BT_STACK_PUSH")
#pragma pop_macro("CHECK_ASSERTIONS")
#pragma pop_macro("CHECK_CHAR_CLASSES")
#pragma pop_macro("COPY_MAXIMIZE_FIRST_TAG")
#pragma pop_macro("COPY_REMOVE_TAGS")
#pragma pop_macro("DPRINT")
#pragma pop_macro("EMPTY")
#pragma pop_macro("END")
#pragma pop_macro("ERROR_EXIT")
#pragma pop_macro("GET_NEXT_WCHAR")
#pragma pop_macro("IS_ASSERTION")
#pragma pop_macro("IS_BACKREF")
#pragma pop_macro("IS_EMPTY")
#pragma pop_macro("IS_SPECIAL")
#pragma pop_macro("IS_TAG")
#pragma pop_macro("IS_WORD_CHAR")
#pragma pop_macro("LCTRANS_CUR")
#pragma pop_macro("MAX")
#pragma pop_macro("MAX_NEG_CLASSES")
#pragma pop_macro("MIN")
#pragma pop_macro("PUSHINT")
#pragma pop_macro("PUSHPTR")
#pragma pop_macro("QUESTION")
#pragma pop_macro("STACK_PUSH")
#pragma pop_macro("STACK_PUSHR")
#pragma pop_macro("STACK_PUSHX")
#pragma pop_macro("STAR")
#pragma pop_macro("TAG")
#pragma pop_macro("TRE_CHAR_MAX")
#pragma pop_macro("TRE_MBSTATE")
#pragma pop_macro("TRE_MEM_BLOCK_SIZE")
#pragma pop_macro("TRE_REGEX_T_FIELD")
#pragma pop_macro("TRE_USE_ALLOCA")
#pragma pop_macro("UNMATCHABLE")
#pragma pop_macro("declare_popf")
#pragma pop_macro("declare_pushf")
#pragma pop_macro("define_popf")
#pragma pop_macro("define_pushf")
#pragma pop_macro("elementsof")
#pragma pop_macro("tre_bt_mem_alloc")
#pragma pop_macro("tre_bt_mem_destroy")
#pragma pop_macro("tre_bt_mem_new")
#pragma pop_macro("tre_ctype")
#pragma pop_macro("tre_isalnum")
#pragma pop_macro("tre_isalpha")
#pragma pop_macro("tre_isblank")
#pragma pop_macro("tre_iscntrl")
#pragma pop_macro("tre_isctype")
#pragma pop_macro("tre_isdigit")
#pragma pop_macro("tre_isgraph")
#pragma pop_macro("tre_islower")
#pragma pop_macro("tre_isprint")
#pragma pop_macro("tre_ispunct")
#pragma pop_macro("tre_isspace")
#pragma pop_macro("tre_isupper")
#pragma pop_macro("tre_isxdigit")
#pragma pop_macro("tre_mbrtowc")
#pragma pop_macro("tre_mem_alloc")
#pragma pop_macro("tre_mem_alloca")
#pragma pop_macro("tre_mem_calloc")
#pragma pop_macro("tre_mem_new")
#pragma pop_macro("tre_mem_newa")
#pragma pop_macro("tre_strlen")
#pragma pop_macro("tre_tolower")
#pragma pop_macro("tre_toupper")
#pragma pop_macro("xcalloc")
#pragma pop_macro("xfree")
#pragma pop_macro("xmalloc")
#pragma pop_macro("xrealloc")
#pragma pop_macro("PATH_BUFFER_MAX")
#pragma pop_macro("DT_UNKNOWN")
#pragma pop_macro("DT_DIR")
#pragma pop_macro("DT_REG")
#pragma pop_macro("INVALID_ATTRIBUTES")
#pragma pop_macro("ATTRIBUTE_DIRECTORY")
#pragma pop_macro("UTF8_CODE_PAGE")
#pragma pop_macro("NO_INVALID_CHARS")
#pragma pop_macro("NDEBUG")
#pragma pop_macro("assert")
#pragma pop_macro("static_assert")
#pragma pop_macro("hidden")
#pragma pop_macro("RE_DUP_MAX")
#pragma pop_macro("CHARCLASS_NAME_MAX")
#pragma pop_macro("MB_CUR_MAX")
#pragma pop_macro("mbtowc")
#pragma pop_macro("isdigit")
#pragma pop_macro("iswalnum")
#pragma pop_macro("iswalpha")
#pragma pop_macro("iswblank")
#pragma pop_macro("iswcntrl")
#pragma pop_macro("iswdigit")
#pragma pop_macro("iswgraph")
#pragma pop_macro("iswlower")
#pragma pop_macro("iswprint")
#pragma pop_macro("iswpunct")
#pragma pop_macro("iswspace")
#pragma pop_macro("iswupper")
#pragma pop_macro("iswxdigit")
#pragma pop_macro("towlower")
#pragma pop_macro("towupper")
#pragma pop_macro("iswctype")
#pragma pop_macro("wctype")
#pragma pop_macro("reg_errcode_t")
#pragma pop_macro("tre_char_t")
#pragma pop_macro("tre_cint_t")
#pragma pop_macro("tre_ctype_t")
#pragma pop_macro("tnfa_transition")
#pragma pop_macro("tre_tnfa_transition_t")
#pragma pop_macro("TRE_TAG_MINIMIZE")
#pragma pop_macro("TRE_TAG_MAXIMIZE")
#pragma pop_macro("tre_tag_direction_t")
#pragma pop_macro("tre_submatch_data")
#pragma pop_macro("tre_submatch_data_t")
#pragma pop_macro("tnfa")
#pragma pop_macro("tre_tnfa_t")
#pragma pop_macro("tre_list")
#pragma pop_macro("tre_list_t")
#pragma pop_macro("tre_mem_struct")
#pragma pop_macro("tre_mem_t")
#pragma pop_macro("tre_mem_new_impl")
#pragma pop_macro("tre_mem_alloc_impl")
#pragma pop_macro("tre_mem_destroy")
#pragma pop_macro("tre_pos_and_tags_t")
#pragma pop_macro("LITERAL")
#pragma pop_macro("CATENATION")
#pragma pop_macro("ITERATION")
#pragma pop_macro("UNION")
#pragma pop_macro("tre_ast_type_t")
#pragma pop_macro("tre_ast_node_t")
#pragma pop_macro("tre_literal_t")
#pragma pop_macro("tre_catenation_t")
#pragma pop_macro("tre_iteration_t")
#pragma pop_macro("tre_union_t")
#pragma pop_macro("tre_ast_new_node")
#pragma pop_macro("tre_ast_new_literal")
#pragma pop_macro("tre_ast_new_iter")
#pragma pop_macro("tre_ast_new_union")
#pragma pop_macro("tre_ast_new_catenation")
#pragma pop_macro("tre_stack_rec")
#pragma pop_macro("tre_stack_t")
#pragma pop_macro("tre_stack_new")
#pragma pop_macro("tre_stack_destroy")
#pragma pop_macro("tre_stack_num_objects")
#pragma pop_macro("tre_stack_push_voidptr")
#pragma pop_macro("tre_stack_push_int")
#pragma pop_macro("tre_stack_pop_voidptr")
#pragma pop_macro("tre_stack_pop_int")
#pragma pop_macro("tre_stack_item")
#pragma pop_macro("tre_stack_push")
#pragma pop_macro("tre_parse_ctx_t")
#pragma pop_macro("tre_macros")
#pragma pop_macro("tre_expand_macro")
#pragma pop_macro("tre_compare_lit")
#pragma pop_macro("literals")
#pragma pop_macro("tre_new_lit")
#pragma pop_macro("add_icase_literals")
#pragma pop_macro("neg")
#pragma pop_macro("parse_bracket_terms")
#pragma pop_macro("parse_bracket")
#pragma pop_macro("parse_dup_count")
#pragma pop_macro("parse_dup")
#pragma pop_macro("hexval")
#pragma pop_macro("marksub")
#pragma pop_macro("parse_atom")
#pragma pop_macro("tre_parse")
#pragma pop_macro("tre_add_tag_left")
#pragma pop_macro("tre_add_tag_right")
#pragma pop_macro("ADDTAGS_RECURSE")
#pragma pop_macro("ADDTAGS_AFTER_ITERATION")
#pragma pop_macro("ADDTAGS_AFTER_UNION_LEFT")
#pragma pop_macro("ADDTAGS_AFTER_UNION_RIGHT")
#pragma pop_macro("ADDTAGS_AFTER_CAT_LEFT")
#pragma pop_macro("ADDTAGS_AFTER_CAT_RIGHT")
#pragma pop_macro("ADDTAGS_SET_SUBMATCH_END")
#pragma pop_macro("tre_addtags_symbol_t")
#pragma pop_macro("tre_tag_states_t")
#pragma pop_macro("tre_purge_regset")
#pragma pop_macro("tre_add_tags")
#pragma pop_macro("COPY_RECURSE")
#pragma pop_macro("COPY_SET_RESULT_PTR")
#pragma pop_macro("tre_copyast_symbol_t")
#pragma pop_macro("tre_copy_ast")
#pragma pop_macro("EXPAND_RECURSE")
#pragma pop_macro("EXPAND_AFTER_ITER")
#pragma pop_macro("tre_expand_ast_symbol_t")
#pragma pop_macro("tre_expand_ast")
#pragma pop_macro("tre_set_empty")
#pragma pop_macro("tre_set_one")
#pragma pop_macro("tre_set_union")
#pragma pop_macro("tre_match_empty")
#pragma pop_macro("NFL_RECURSE")
#pragma pop_macro("NFL_POST_UNION")
#pragma pop_macro("NFL_POST_CATENATION")
#pragma pop_macro("NFL_POST_ITERATION")
#pragma pop_macro("tre_nfl_stack_symbol_t")
#pragma pop_macro("tre_compute_nfl")
#pragma pop_macro("tre_make_trans")
#pragma pop_macro("tre_ast_to_tnfa")
#pragma pop_macro("tre_fill_pmatch")
#pragma pop_macro("tre_tag_order")
#pragma pop_macro("tre_neg_char_classes_match")
#pragma pop_macro("tre_tnfa_reach_t")
#pragma pop_macro("tre_reach_pos_t")
#pragma pop_macro("tre_tnfa_run_parallel")
#pragma pop_macro("tre_backtrack_item_t")
#pragma pop_macro("tre_backtrack_struct")
#pragma pop_macro("tre_backtrack_t")
#pragma pop_macro("tre_tnfa_run_backtrack")
#pragma pop_macro("messages")
#pragma pop_macro("str_next")
#pragma pop_macro("pat_next")
#pragma pop_macro("casefold")
#pragma pop_macro("match_bracket")
#pragma pop_macro("fnmatch_internal")
#pragma pop_macro("directory")
#pragma pop_macro("open_directory")
#pragma pop_macro("read_directory")
#pragma pop_macro("close_directory")
#pragma pop_macro("path_type")
#pragma pop_macro("match")
#pragma pop_macro("append")
#pragma pop_macro("do_glob")
#pragma pop_macro("ignore_err")
#pragma pop_macro("freelist")
#pragma pop_macro("sort")
