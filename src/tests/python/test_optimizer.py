"""Unit tests for the IR optimizer (dead-function + dead-helper elimination)."""

from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionRef,
    IRGlobalDecl,
    IRHelperDecl,
    IRInclude,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRStructDef,
    IRStructField,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRTypedefDef,
    IRVar,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog


def _fn(name, body_stmts=None):
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void"),
        params=[],
        body=IRBlock(stmts=body_stmts or []),
    )


def _decl(name, return_type="void"):
    return IRFunctionDecl(
        name=name,
        return_type=CType(text=return_type),
    )


def test_removes_unreferenced_function():
    main = _fn("main", [IRExprStmt(expr=IRCall(callee="used_fn", args=[]))])
    used = _fn("used_fn")
    dead = _fn("dead_fn")
    m = IRModule(
        function_defs=[main, used, dead],
        function_decls=[
            _decl("main"),
            _decl("used_fn"),
            _decl("dead_fn"),
        ],
    )
    IROptimizer(m).optimize()
    names = {f.name for f in m.function_defs}
    assert "main" in names
    assert "used_fn" in names
    assert "dead_fn" not in names
    # the dead function's forward declaration is pruned; the live one's remains
    assert "dead_fn" not in {decl.name for decl in m.function_decls}
    assert "used_fn" in {decl.name for decl in m.function_decls}


def test_sole_entry_point_survives_normal_reachability():
    module = IRModule(function_defs=[_fn("main")])

    IROptimizer(module).optimize()

    assert [function.name for function in module.function_defs] == ["main"]


def test_sole_non_entry_function_is_removed():
    module = IRModule(
        function_defs=[_fn("orphan")],
        function_decls=[_decl("orphan")],
    )

    IROptimizer(module).optimize()

    assert module.function_defs == []
    assert module.function_decls == []


def test_string_literal_payload_does_not_root_function():
    module = IRModule(
        function_defs=[
            _fn("main", [IRExprStmt(expr=IRLiteral(text='"dead_fn"'))]),
            _fn("dead_fn"),
        ]
    )

    IROptimizer(module).optimize()

    assert [function.name for function in module.function_defs] == ["main"]


def test_keeps_function_referenced_in_macro_replacement():
    m = IRModule(
        function_defs=[_fn("main"), _fn("callback_fn")],
        preprocessor_decls=[IRMacroDef(name="CALLBACK", replacement="&callback_fn")],
    )
    IROptimizer(m).optimize()
    assert {f.name for f in m.function_defs} == {"main", "callback_fn"}


def test_keeps_thread_entry_referenced_by_structured_helper_call():
    body = [
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_thread_spawn",
                args=[
                    IRCast(
                        target_type=CType(text="void*(*)(void*)"),
                        expr=IRFunctionRef(name="worker_fn"),
                    ),
                    IRLiteral(text="NULL"),
                ],
                helper_ref="__btrc_thread_spawn",
            )
        )
    ]
    m = IRModule(function_defs=[_fn("main", body), _fn("worker_fn")])
    IROptimizer(m).optimize()
    assert {f.name for f in m.function_defs} == {"main", "worker_fn"}


def test_keeps_address_taken_function():
    body = [IRExprStmt(expr=IRFunctionRef(name="handler_fn"))]
    m = IRModule(function_defs=[_fn("main", body), _fn("handler_fn")])
    IROptimizer(m).optimize()
    assert "handler_fn" in {f.name for f in m.function_defs}


def test_local_value_with_function_name_does_not_keep_function():
    module = IRModule(
        function_defs=[
            _fn("main", [IRExprStmt(expr=IRVar(name="shadowed"))]),
            _fn("shadowed"),
        ]
    )

    IROptimizer(module).optimize()

    assert [function.name for function in module.function_defs] == ["main"]


def test_substring_name_not_spuriously_kept():
    """A dead `foo` must be dropped even when a live `foobar` is referenced.

    The raw-text scan matches whole identifiers only — `foo` appearing as a
    substring of `foobar` no longer keeps the dead `foo` alive. `foobar` is
    referenced in a macro replacement, so it survives.
    """
    m = IRModule(
        function_defs=[_fn("main"), _fn("foo"), _fn("foobar")],
        preprocessor_decls=[IRMacroDef(name="CALLBACK", replacement="&foobar")],
    )
    IROptimizer(m).optimize()
    names = {f.name for f in m.function_defs}
    assert "main" in names
    assert "foobar" in names  # whole-word reference keeps it
    assert "foo" not in names  # substring of `foobar` must NOT keep it


def test_whole_word_reference_in_macro_replacement_still_kept():
    """The fix stays conservative: a real identifier reference is still kept."""
    m = IRModule(
        function_defs=[_fn("main"), _fn("foo"), _fn("foobar")],
        preprocessor_decls=[IRMacroDef(name="CALLBACKS", replacement="&foo, &foobar")],
    )
    IROptimizer(m).optimize()
    names = {f.name for f in m.function_defs}
    assert {"main", "foo", "foobar"} <= names


def test_externally_visible_global_initializer_roots_referenced_function():
    module = IRModule(
        function_defs=[_fn("main"), _fn("callback"), _fn("dead")],
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="void (*)(void)"),
                name="callback_slot",
                init=IRFunctionRef(name="callback"),
                is_static=False,
            )
        ],
    )

    IROptimizer(module).optimize()

    assert {function.name for function in module.function_defs} == {
        "main",
        "callback",
    }


def test_typed_global_keeps_its_struct_definition():
    module = IRModule(
        function_defs=[_fn("main")],
        struct_defs=[IRStructDef(name="Live"), IRStructDef(name="Dead")],
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="Live*"),
                name="live_global",
                is_static=False,
            )
        ],
    )

    IROptimizer(module).optimize()

    assert [struct.name for struct in module.struct_defs] == ["Live"]


def test_typed_top_level_declarations_keep_referenced_structs():
    module = IRModule(
        function_defs=[_fn("main")],
        struct_defs=[
            IRStructDef(name="Aliased"),
            IRStructDef(name="Payload"),
            IRStructDef(name="Dead"),
        ],
        typedef_defs=[
            IRTypedefDef(
                target_type=CType(text="Aliased*"),
                name="Alias",
            )
        ],
        tagged_union_defs=[
            IRTaggedUnionDef(
                name="Value",
                tag_type=CType(text="int"),
                variants=[
                    IRTaggedUnionVariant(
                        name="payload",
                        fields=[
                            IRStructField(
                                c_type=CType(text="Payload*"),
                                name="value",
                            )
                        ],
                    )
                ],
            )
        ],
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="Alias"),
                name="alias_value",
                is_static=False,
            ),
            IRGlobalDecl(
                c_type=CType(text="Value"),
                name="tagged_value",
                is_static=False,
            ),
        ],
    )

    IROptimizer(module).optimize()

    assert [struct.name for struct in module.struct_defs] == [
        "Aliased",
        "Payload",
    ]


def test_literal_and_value_names_do_not_keep_dead_structs():
    module = IRModule(
        function_defs=[
            _fn(
                "main",
                [
                    IRExprStmt(expr=IRLiteral(text='"DeadType"')),
                    IRExprStmt(expr=IRVar(name="AlsoDead")),
                ],
            )
        ],
        struct_defs=[
            IRStructDef(name="DeadType"),
            IRStructDef(name="AlsoDead"),
        ],
    )

    IROptimizer(module).optimize()

    assert module.struct_defs == []


def test_single_unreferenced_struct_is_eliminated():
    module = IRModule(
        function_defs=[_fn("main")],
        struct_defs=[IRStructDef(name="OnlyDeadType")],
    )

    IROptimizer(module).optimize()

    assert module.struct_defs == []


def test_typed_global_initializer_keeps_extern_declaration():
    module = IRModule(
        function_defs=[_fn("main")],
        function_decls=[
            _decl("main"),
            _decl("live_extern", "int"),
            _decl("dead_extern", "int"),
        ],
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="int"),
                name="external_value",
                init=IRCall(callee="live_extern", args=[]),
            )
        ],
    )

    IROptimizer(module).optimize()

    assert "live_extern" in {decl.name for decl in module.function_decls}
    assert "dead_extern" not in {decl.name for decl in module.function_decls}


def test_helper_dependencies_are_helper_names_not_categories():
    base = IRHelperDecl(
        category="types",
        name="base_types",
        c_source="typedef int helper_value;",
    )
    consumer = IRHelperDecl(
        category="consumer",
        name="consumer_helper",
        c_source="static helper_value consume(void) { return 0; }",
        depends_on=["base_types"],
    )
    dead = IRHelperDecl(
        category="dead",
        name="dead_helper",
        c_source="static void unused(void) {}",
    )
    module = IRModule(
        function_defs=[
            _fn(
                "main",
                [
                    IRExprStmt(
                        expr=IRCall(
                            callee="consumer_helper",
                            helper_ref="consumer_helper",
                        )
                    )
                ],
            )
        ],
        helper_decls=[base, consumer, dead],
    )

    IROptimizer(module).optimize()

    assert [helper.name for helper in module.helper_decls] == [
        "base_types",
        "consumer_helper",
    ]


def test_helper_used_as_function_pointer_survives_elimination():
    callback = IRHelperDecl(
        category="callbacks",
        name="cleanup_callback",
        c_source="static void cleanup_callback(void* value) { (void)value; }",
    )
    module = IRModule(
        function_defs=[
            _fn(
                "main",
                [IRExprStmt(expr=IRFunctionRef(name="cleanup_callback"))],
            )
        ],
        helper_decls=[callback],
    )

    IROptimizer(module).optimize()

    assert [helper.name for helper in module.helper_decls] == ["cleanup_callback"]


def test_typed_global_initializer_keeps_helper_dependency_closure():
    base = IRHelperDecl(
        category="types",
        name="base_types",
        c_source="typedef int helper_value;",
    )
    consumer = IRHelperDecl(
        category="consumer",
        name="consumer_helper",
        c_source="static helper_value consume(void) { return 0; }",
        depends_on=["base_types"],
    )
    module = IRModule(
        function_defs=[_fn("main")],
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="int"),
                name="global_value",
                init=IRCall(
                    callee="consumer_helper",
                    helper_ref="consumer_helper",
                ),
            )
        ],
        helper_decls=[base, consumer],
    )

    IROptimizer(module).optimize()

    assert [helper.name for helper in module.helper_decls] == [
        "base_types",
        "consumer_helper",
    ]


def test_structured_runtime_call_rematerializes_catalog_closure_without_dce():
    module = IRModule(
        function_defs=[
            _fn(
                "archive_entry",
                [IRExprStmt(expr=IRCall(callee="__btrc_close_descriptors_except"))],
            )
        ]
    )

    IROptimizer(module, dce=False).optimize()

    names = [helper.name for helper in module.helper_decls]
    assert names.index("__btrc_close_descriptors_from") < names.index("__btrc_close_descriptors_except")
    assert IRInclude(header="errno.h") in module.preprocessor_decls
    assert IRInclude(header="unistd.h") in module.preprocessor_decls


def test_live_runtime_object_reference_rematerializes_catalog_provider():
    module = IRModule(
        function_defs=[
            _fn(
                "main",
                [IRExprStmt(expr=IRVar(name="__btrc_mutex_arc_descriptor"))],
            )
        ]
    )

    IROptimizer(module).optimize()

    assert "__btrc_mutex_arc_type" in {helper.name for helper in module.helper_decls}


def test_dead_runtime_object_reference_does_not_retain_catalog_provider():
    catalog = RuntimeHelperCatalog()
    module = IRModule(
        helper_decls=[IRHelperDecl.from_runtime(catalog.definition("__btrc_mutex_arc_type"))],
        function_defs=[
            _fn("main"),
            _fn(
                "dead",
                [IRExprStmt(expr=IRVar(name="__btrc_mutex_arc_descriptor"))],
            ),
        ],
    )

    IROptimizer(module, runtime_catalog=catalog).optimize()

    assert [function.name for function in module.function_defs] == ["main"]
    assert "__btrc_mutex_arc_type" not in {helper.name for helper in module.helper_decls}
