"""Code completion provider for btrc.

Provides keyword, type, member access, static method, and snippet completions.
"""

import re
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer import ClassInfo
from src.compiler.python.ast_nodes import (
    FieldDecl, MethodDecl, TypeExpr, VarDeclStmt, ClassDecl, FunctionDecl,
    Param,
)

from devex.lsp.diagnostics import AnalysisResult


# ---------------------------------------------------------------------------
# Keyword completions
# ---------------------------------------------------------------------------

_BTRC_KEYWORDS = [
    ("class", "Declares a class with fields and methods"),
    ("public", "Access modifier: visible outside the class"),
    ("private", "Access modifier: only visible within the class"),
    ("if", "Conditional branch"),
    ("else", "Alternative branch of an if statement"),
    ("while", "Loop while condition is true"),
    ("for", "Loop construct (for-in)"),
    ("in", "Used in for-in loops"),
    ("return", "Return a value from a function/method"),
    ("var", "Declare a variable with type inference"),
    ("new", "Allocate an object on the heap"),
    ("delete", "Free a heap-allocated object"),
    ("try", "Begin a try/catch error handling block"),
    ("catch", "Catch an error thrown in a try block"),
    ("throw", "Throw an error (string value)"),
    ("null", "Null value for nullable types"),
    ("true", "Boolean literal true"),
    ("false", "Boolean literal false"),
    ("self", "Reference to the current object instance"),
    ("extends", "Specifies parent class for inheritance"),
    ("break", "Break out of a loop"),
    ("continue", "Skip to next loop iteration"),
    ("switch", "Multi-way branch"),
    ("case", "Branch in a switch statement"),
    ("default", "Default branch in a switch statement"),
    ("enum", "Declare an enumeration"),
    ("struct", "Declare a C-style struct"),
    ("typedef", "Create a type alias"),
    ("sizeof", "Size of a type or expression in bytes"),
    ("parallel", "Mark a for loop for parallel execution"),
]


# ---------------------------------------------------------------------------
# Type completions
# ---------------------------------------------------------------------------

_BTRC_TYPES = [
    ("int", "Integer type"),
    ("float", "Floating-point type"),
    ("double", "Double-precision floating-point type"),
    ("string", "String type"),
    ("bool", "Boolean type"),
    ("char", "Character type"),
    ("void", "Void type (no value)"),
    ("List", "Generic dynamic array: List<T>"),
    ("Map", "Generic hash map: Map<K, V>"),
    ("Set", "Generic hash set: Set<T>"),
    ("Array", "Fixed-size array type"),
    ("long", "Long integer type"),
    ("short", "Short integer type"),
    ("unsigned", "Unsigned integer modifier"),
]


# ---------------------------------------------------------------------------
# Built-in member tables for primitive / generic types
# ---------------------------------------------------------------------------

_STRING_MEMBERS = [
    # Fields
    ("len", "int", "field", "Length of the string (bytes)"),
    # Methods
    ("charAt", "char", "method", "char charAt(int index) -- character at index"),
    ("trim", "string", "method", "string trim() -- remove leading/trailing whitespace"),
    ("lstrip", "string", "method", "string lstrip() -- remove leading whitespace"),
    ("rstrip", "string", "method", "string rstrip() -- remove trailing whitespace"),
    ("toUpper", "string", "method", "string toUpper() -- convert to uppercase"),
    ("toLower", "string", "method", "string toLower() -- convert to lowercase"),
    ("contains", "bool", "method", "bool contains(string sub) -- check if contains substring"),
    ("startsWith", "bool", "method", "bool startsWith(string prefix) -- check prefix"),
    ("endsWith", "bool", "method", "bool endsWith(string suffix) -- check suffix"),
    ("indexOf", "int", "method", "int indexOf(string sub) -- index of first occurrence"),
    ("lastIndexOf", "int", "method", "int lastIndexOf(string sub) -- index of last occurrence"),
    ("substring", "string", "method", "string substring(int start, int end) -- extract substring"),
    ("equals", "bool", "method", "bool equals(string other) -- compare strings"),
    ("split", "List<string>", "method", "List<string> split(string delim) -- split into list"),
    ("replace", "string", "method", "string replace(string old, string new) -- replace occurrences"),
    ("repeat", "string", "method", "string repeat(int count) -- repeat N times"),
    ("count", "int", "method", "int count(string sub) -- count non-overlapping occurrences"),
    ("find", "int", "method", "int find(string sub, int start) -- find from start index"),
    ("capitalize", "string", "method", "string capitalize() -- uppercase first char"),
    ("title", "string", "method", "string title() -- capitalize each word"),
    ("swapCase", "string", "method", "string swapCase() -- swap upper/lower case"),
    ("padLeft", "string", "method", "string padLeft(int width, char fill) -- left-pad"),
    ("padRight", "string", "method", "string padRight(int width, char fill) -- right-pad"),
    ("center", "string", "method", "string center(int width, char fill) -- center with padding"),
    ("charLen", "int", "method", "int charLen() -- UTF-8 character count"),
    ("byteLen", "int", "method", "int byteLen() -- byte length"),
    ("isDigitStr", "bool", "method", "bool isDigitStr() -- all chars are digits"),
    ("isAlphaStr", "bool", "method", "bool isAlphaStr() -- all chars are alphabetic"),
    ("isBlank", "bool", "method", "bool isBlank() -- empty or all whitespace"),
    ("isAlnum", "bool", "method", "bool isAlnum() -- all chars are alphanumeric"),
    ("isUpper", "bool", "method", "bool isUpper() -- all chars are uppercase"),
    ("isLower", "bool", "method", "bool isLower() -- all chars are lowercase"),
    ("reverse", "string", "method", "string reverse() -- reverse the string"),
    ("isEmpty", "bool", "method", "bool isEmpty() -- true if string is empty"),
    ("removePrefix", "string", "method", "string removePrefix(string prefix) -- remove prefix if present"),
    ("removeSuffix", "string", "method", "string removeSuffix(string suffix) -- remove suffix if present"),
    ("toInt", "int", "method", "int toInt() -- parse as integer"),
    ("toFloat", "float", "method", "float toFloat() -- parse as float"),
    ("toDouble", "double", "method", "double toDouble() -- parse as double"),
    ("toLong", "long", "method", "long toLong() -- parse as long"),
    ("toBool", "bool", "method", "bool toBool() -- parse as bool (false for empty, \"false\", \"0\")"),
    ("zfill", "string", "method", "string zfill(int width) -- left-pad with zeros (preserves sign)"),
]

_LIST_MEMBERS = [
    # Fields
    ("len", "int", "field", "Number of elements in the list"),
    # Methods
    ("push", "void", "method", "void push(T value) -- append element"),
    ("get", "T", "method", "T get(int index) -- get element at index"),
    ("set", "void", "method", "void set(int index, T value) -- set element at index"),
    ("remove", "void", "method", "void remove(int index) -- remove element at index"),
    ("pop", "T", "method", "T pop() -- remove and return last element"),
    ("reverse", "void", "method", "void reverse() -- reverse the list in-place"),
    ("sort", "void", "method", "void sort() -- sort the list in-place"),
    ("contains", "bool", "method", "bool contains(T value) -- check if list contains value"),
    ("indexOf", "int", "method", "int indexOf(T value) -- index of first occurrence (-1 if not found)"),
    ("lastIndexOf", "int", "method", "int lastIndexOf(T value) -- index of last occurrence (-1 if not found)"),
    ("slice", "List<T>", "method", "List<T> slice(int start, int end) -- extract sub-list"),
    ("join", "string", "method", "string join(string separator) -- join elements with separator"),
    ("joinToString", "string", "method", "string joinToString(string separator) -- alias for join"),
    ("forEach", "void", "method", "void forEach(fn callback) -- call fn for each element"),
    ("filter", "List<T>", "method", "List<T> filter(fn predicate) -- filter by predicate"),
    ("any", "bool", "method", "bool any(fn predicate) -- true if any element matches"),
    ("all", "bool", "method", "bool all(fn predicate) -- true if all elements match"),
    ("clear", "void", "method", "void clear() -- remove all elements"),
    ("size", "int", "method", "int size() -- number of elements"),
    ("isEmpty", "bool", "method", "bool isEmpty() -- true if list has no elements"),
    ("map", "List<T>", "method", "List<T> map(fn transform) -- apply fn to each element"),
    ("extend", "void", "method", "void extend(List<T> other) -- append all elements from other list"),
    ("insert", "void", "method", "void insert(int index, T value) -- insert element at index"),
    ("first", "T", "method", "T first() -- get first element (error if empty)"),
    ("last", "T", "method", "T last() -- get last element (error if empty)"),
    ("reduce", "T", "method", "T reduce(T init, fn accumulator) -- fold list into single value"),
    ("fill", "void", "method", "void fill(T value) -- set all elements to value"),
    ("count", "int", "method", "int count(T value) -- count occurrences of value"),
    ("removeAll", "void", "method", "void removeAll(T value) -- remove all occurrences of value"),
    ("swap", "void", "method", "void swap(int i, int j) -- swap elements at indices i and j"),
    ("min", "T", "method", "T min() -- minimum element (numeric types only)"),
    ("max", "T", "method", "T max() -- maximum element (numeric types only)"),
    ("sum", "T", "method", "T sum() -- sum of all elements (numeric types only)"),
    ("sorted", "List<T>", "method", "List<T> sorted() -- return a new sorted copy"),
    ("distinct", "List<T>", "method", "List<T> distinct() -- return a new list with duplicates removed"),
    ("reversed", "List<T>", "method", "List<T> reversed() -- return a new reversed copy"),
    ("addAll", "void", "method", "void addAll(List<T> other) -- alias for extend()"),
    ("subList", "List<T>", "method", "List<T> subList(int start, int end) -- alias for slice()"),
    ("removeAt", "void", "method", "void removeAt(int index) -- alias for remove()"),
    ("findIndex", "int", "method", "int findIndex(fn predicate) -- index of first match, -1 if not found"),
    ("take", "List<T>", "method", "List<T> take(int n) -- return first n elements"),
    ("drop", "List<T>", "method", "List<T> drop(int n) -- return all elements after skipping first n"),
    ("free", "void", "method", "void free() -- free list memory"),
]

_MAP_MEMBERS = [
    # Fields
    ("len", "int", "field", "Number of entries in the map"),
    # Methods
    ("put", "void", "method", "void put(K key, V value) -- insert or update entry"),
    ("get", "V", "method", "V get(K key) -- get value by key (aborts if missing, use getOrDefault for safe access)"),
    ("getOrDefault", "V", "method", "V getOrDefault(K key, V fallback) -- get value or fallback"),
    ("has", "bool", "method", "bool has(K key) -- check if key exists"),
    ("contains", "bool", "method", "bool contains(K key) -- check if key exists"),
    ("keys", "List<K>", "method", "List<K> keys() -- get list of keys"),
    ("values", "List<V>", "method", "List<V> values() -- get list of values"),
    ("remove", "void", "method", "void remove(K key) -- remove entry by key"),
    ("clear", "void", "method", "void clear() -- remove all entries"),
    ("forEach", "void", "method", "void forEach(fn callback) -- call fn(key, value) for each entry"),
    ("size", "int", "method", "int size() -- number of entries"),
    ("isEmpty", "bool", "method", "bool isEmpty() -- true if map has no entries"),
    ("putIfAbsent", "void", "method", "void putIfAbsent(K key, V value) -- insert only if key doesn't exist"),
    ("containsValue", "bool", "method", "bool containsValue(V value) -- check if any entry has the value"),
    ("merge", "void", "method", "void merge(Map<K,V> other) -- copy all entries from other map"),
    ("free", "void", "method", "void free() -- free map memory"),
]

_SET_MEMBERS = [
    # Fields
    ("len", "int", "field", "Number of elements in the set"),
    # Methods
    ("add", "void", "method", "void add(T value) -- add element to set"),
    ("contains", "bool", "method", "bool contains(T value) -- check if set contains value"),
    ("has", "bool", "method", "bool has(T value) -- check if set contains value"),
    ("remove", "void", "method", "void remove(T value) -- remove element from set"),
    ("toList", "List<T>", "method", "List<T> toList() -- convert to list"),
    ("clear", "void", "method", "void clear() -- remove all elements"),
    ("forEach", "void", "method", "void forEach(fn) -- call fn(element) for each element"),
    ("filter", "Set<T>", "method", "Set<T> filter(fn) -- new set of elements matching predicate"),
    ("any", "bool", "method", "bool any(fn) -- true if any element matches predicate"),
    ("all", "bool", "method", "bool all(fn) -- true if all elements match predicate"),
    ("size", "int", "method", "int size() -- number of elements"),
    ("isEmpty", "bool", "method", "bool isEmpty() -- true if set has no elements"),
    ("unite", "Set<T>", "method", "Set<T> unite(Set<T> other) -- elements in either set"),
    ("intersect", "Set<T>", "method", "Set<T> intersect(Set<T> other) -- elements in both sets"),
    ("subtract", "Set<T>", "method", "Set<T> subtract(Set<T> other) -- elements in this but not other"),
    ("symmetricDifference", "Set<T>", "method", "Set<T> symmetricDifference(Set<T> other) -- elements in either but not both"),
    ("isSubsetOf", "bool", "method", "bool isSubsetOf(Set<T> other) -- true if all elements are in other"),
    ("isSupersetOf", "bool", "method", "bool isSupersetOf(Set<T> other) -- true if other's elements are all in this"),
    ("copy", "Set<T>", "method", "Set<T> copy() -- create independent copy"),
    ("free", "void", "method", "void free() -- free set memory"),
]


# ---------------------------------------------------------------------------
# Stdlib static-method tables (for classes that are typically all-static)
# ---------------------------------------------------------------------------

_STDLIB_STATIC_METHODS: dict[str, list[tuple[str, str]]] = {
    "Math": [
        ("PI", "float PI() -- 3.14159..."),
        ("E", "float E() -- 2.71828..."),
        ("TAU", "float TAU() -- 6.28318..."),
        ("INF", "float INF() -- infinity"),
        ("abs", "int abs(int x)"),
        ("fabs", "float fabs(float x)"),
        ("max", "int max(int a, int b)"),
        ("min", "int min(int a, int b)"),
        ("fmax", "float fmax(float a, float b)"),
        ("fmin", "float fmin(float a, float b)"),
        ("clamp", "int clamp(int x, int lo, int hi)"),
        ("power", "float power(float base, int exp)"),
        ("sqrt", "float sqrt(float x)"),
        ("factorial", "int factorial(int n)"),
        ("gcd", "int gcd(int a, int b)"),
        ("lcm", "int lcm(int a, int b)"),
        ("fibonacci", "int fibonacci(int n)"),
        ("isPrime", "bool isPrime(int n)"),
        ("isEven", "bool isEven(int n)"),
        ("isOdd", "bool isOdd(int n)"),
        ("sum", "int sum(List<int> items)"),
        ("fsum", "float fsum(List<float> items)"),
        ("sin", "float sin(float x)"),
        ("cos", "float cos(float x)"),
        ("tan", "float tan(float x)"),
        ("asin", "float asin(float x)"),
        ("acos", "float acos(float x)"),
        ("atan", "float atan(float x)"),
        ("atan2", "float atan2(float y, float x)"),
        ("ceil", "float ceil(float x)"),
        ("floor", "float floor(float x)"),
        ("round", "int round(float x)"),
        ("truncate", "int truncate(float x)"),
        ("log", "float log(float x)"),
        ("log10", "float log10(float x)"),
        ("log2", "float log2(float x)"),
        ("exp", "float exp(float x)"),
        ("toRadians", "float toRadians(float degrees)"),
        ("toDegrees", "float toDegrees(float radians)"),
        ("fclamp", "float fclamp(float val, float lo, float hi)"),
        ("sign", "int sign(int x)"),
        ("fsign", "float fsign(float x)"),
    ],
    "Strings": [
        ("repeat", "string repeat(string s, int count)"),
        ("join", "string join(List<string> items, string sep)"),
        ("replace", "string replace(string s, string old, string replacement)"),
        ("isDigit", "bool isDigit(char c)"),
        ("isAlpha", "bool isAlpha(char c)"),
        ("isAlnum", "bool isAlnum(char c)"),
        ("isSpace", "bool isSpace(char c)"),
        ("toInt", "int toInt(string s)"),
        ("toFloat", "float toFloat(string s)"),
        ("count", "int count(string s, string sub)"),
        ("find", "int find(string s, string sub, int start)"),
        ("rfind", "int rfind(string s, string sub)"),
        ("capitalize", "string capitalize(string s)"),
        ("title", "string title(string s)"),
        ("swapCase", "string swapCase(string s)"),
        ("padLeft", "string padLeft(string s, int width, char fill)"),
        ("padRight", "string padRight(string s, int width, char fill)"),
        ("center", "string center(string s, int width, char fill)"),
        ("lstrip", "string lstrip(string s)"),
        ("rstrip", "string rstrip(string s)"),
        ("fromInt", "string fromInt(int n)"),
        ("fromFloat", "string fromFloat(float f)"),
        ("isDigitStr", "bool isDigitStr(string s)"),
        ("isAlphaStr", "bool isAlphaStr(string s)"),
        ("isBlank", "bool isBlank(string s)"),
    ],
    "Path": [
        ("exists", "bool exists(string path)"),
        ("readAll", "string readAll(string path)"),
        ("writeAll", "void writeAll(string path, string content)"),
    ],
}


# ---------------------------------------------------------------------------
# Snippet completions
# ---------------------------------------------------------------------------

_SNIPPETS = [
    (
        "class",
        "class ... { ... }",
        "Class with constructor",
        (
            "class ${1:ClassName} {\n"
            "\tpublic ${2:int} ${3:field};\n"
            "\n"
            "\tpublic ${1:ClassName}(${2:int} ${3:field}) {\n"
            "\t\tself.${3:field} = ${3:field};\n"
            "\t}\n"
            "\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "for in",
        "for ... in range(...) { ... }",
        "For-in loop with range",
        (
            "for ${1:i} in range(${2:n}) {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "for in collection",
        "for ... in collection { ... }",
        "For-in loop over collection",
        (
            "for ${1:item} in ${2:collection} {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "try",
        "try { ... } catch(e) { ... }",
        "Try/catch block",
        (
            "try {\n"
            "\t$1\n"
            "} catch(${2:e}) {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "if",
        "if (...) { ... }",
        "If statement",
        (
            "if (${1:condition}) {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "if else",
        "if (...) { ... } else { ... }",
        "If/else statement",
        (
            "if (${1:condition}) {\n"
            "\t$2\n"
            "} else {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "while",
        "while (...) { ... }",
        "While loop",
        (
            "while (${1:condition}) {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "public method",
        "public ... method(...) { ... }",
        "Public method declaration",
        (
            "public ${1:void} ${2:methodName}(${3:}) {\n"
            "\t$0\n"
            "}"
        ),
    ),
    (
        "println",
        'println("...")',
        "Print line",
        'println("${1:message}")$0',
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _type_repr(type_expr) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"
    return repr(type_expr)


def _find_token_at_position(tokens: list[Token], position: lsp.Position) -> Optional[Token]:
    """Find the token covering the given 0-based LSP position."""
    target_line = position.line + 1
    target_col = position.character + 1

    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line != target_line:
            continue
        tok_end_col = tok.col + len(tok.value)
        if tok.col <= target_col <= tok_end_col:
            return tok
    return None


def _find_token_before_position(tokens: list[Token], position: lsp.Position) -> Optional[Token]:
    """Find the last token before the given 0-based LSP position."""
    target_line = position.line + 1
    target_col = position.character + 1

    best: Optional[Token] = None
    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line < target_line or (tok.line == target_line and tok.col < target_col):
            best = tok
    return best


def _get_line_text(source: str, line: int) -> str:
    """Get the text of a specific 0-based line."""
    lines = source.split('\n')
    if 0 <= line < len(lines):
        return lines[line]
    return ""


def _get_text_before_cursor(source: str, position: lsp.Position) -> str:
    """Get the text on the current line before the cursor."""
    lines = source.split('\n')
    if 0 <= position.line < len(lines):
        line_text = lines[position.line]
        return line_text[:position.character]
    return ""


def _resolve_variable_type(
    result: AnalysisResult,
    var_name: str,
    cursor_line: int,
) -> Optional[str]:
    """Try to resolve the type of a variable by scanning AST declarations.

    Walks through VarDeclStmt nodes in the AST looking for the variable name,
    then returns its base type string. Also checks function/method parameters
    and class fields accessed via `self`.
    """
    if not result.ast:
        return None

    # First check if var_name is 'self' — resolve to the enclosing class
    if var_name == "self":
        return _find_enclosing_class(result, cursor_line)

    # Walk all declarations looking for var decl or param with this name
    # that appears before cursor_line (1-based in AST, 0-based in LSP)
    target_line_1based = cursor_line + 1

    best_type: Optional[TypeExpr] = None

    for decl in result.ast.declarations:
        found = _search_for_var_in_node(decl, var_name, target_line_1based)
        if found is not None:
            best_type = found

    if best_type is not None:
        return best_type.base
    return None


def _find_enclosing_class(result: AnalysisResult, cursor_line: int) -> Optional[str]:
    """Find the class that encloses the given cursor line."""
    if not result.ast:
        return None

    source_lines = result.source.split('\n')

    for decl in result.ast.declarations:
        if isinstance(decl, ClassDecl):
            # Check if cursor is within the class body
            class_start = decl.line - 1  # 0-based
            class_end = _find_closing_brace_line(source_lines, class_start)
            if class_end is not None and class_start <= cursor_line <= class_end:
                return decl.name
    return None


def _find_closing_brace_line(source_lines: list[str], start_line: int) -> Optional[int]:
    """Find the line of the closing brace matching the first opening brace."""
    depth = 0
    found_open = False
    for i in range(start_line, len(source_lines)):
        for ch in source_lines[i]:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i
    return None


def _search_for_var_in_node(node, var_name: str, before_line: int) -> Optional[TypeExpr]:
    """Recursively search AST nodes for a VarDeclStmt or Param matching var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name and node.line <= before_line and node.type is not None:
            return node.type
        return None

    if isinstance(node, Param):
        if node.name == var_name and node.type is not None:
            return node.type
        return None

    if isinstance(node, FunctionDecl):
        # Check params
        for p in node.params:
            if p.name == var_name and p.type is not None:
                return p.type
        # Check body
        if node.body:
            return _search_block_for_var(node.body, var_name, before_line)
        return None

    if isinstance(node, MethodDecl):
        for p in node.params:
            if p.name == var_name and p.type is not None:
                return p.type
        if node.body:
            return _search_block_for_var(node.body, var_name, before_line)
        return None

    if isinstance(node, ClassDecl):
        # Search in fields (for field access via self)
        for member in node.members:
            if isinstance(member, FieldDecl):
                if member.name == var_name and member.type is not None:
                    return member.type
            elif isinstance(member, MethodDecl):
                result = _search_for_var_in_node(member, var_name, before_line)
                if result is not None:
                    return result
        return None

    return None


def _search_block_for_var(block, var_name: str, before_line: int) -> Optional[TypeExpr]:
    """Search a Block's statements for a VarDeclStmt."""
    if block is None or not hasattr(block, 'statements'):
        return None

    best: Optional[TypeExpr] = None
    for stmt in block.statements:
        if isinstance(stmt, VarDeclStmt):
            if stmt.name == var_name and stmt.line <= before_line and stmt.type is not None:
                best = stmt.type
        # Recurse into nested blocks (if, while, for, try, etc.)
        for attr in ('body', 'then_block', 'else_block', 'try_block', 'catch_block'):
            child = getattr(stmt, attr, None)
            if child is not None:
                found = _search_block_for_var(child, var_name, before_line)
                if found is not None:
                    best = found
    return best


# ---------------------------------------------------------------------------
# Completion builders
# ---------------------------------------------------------------------------

def _keyword_completions() -> list[lsp.CompletionItem]:
    """Build completion items for btrc keywords."""
    items = []
    for kw, doc in _BTRC_KEYWORDS:
        items.append(lsp.CompletionItem(
            label=kw,
            kind=lsp.CompletionItemKind.Keyword,
            detail=doc,
            insert_text=kw,
        ))
    return items


def _type_completions() -> list[lsp.CompletionItem]:
    """Build completion items for built-in types."""
    items = []
    for name, doc in _BTRC_TYPES:
        items.append(lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Class,
            detail=doc,
            insert_text=name,
        ))
    return items


def _snippet_completions() -> list[lsp.CompletionItem]:
    """Build snippet completion items."""
    items = []
    for label, filter_text, doc, body in _SNIPPETS:
        items.append(lsp.CompletionItem(
            label=label,
            kind=lsp.CompletionItemKind.Snippet,
            detail=doc,
            insert_text=body,
            insert_text_format=lsp.InsertTextFormat.Snippet,
            filter_text=filter_text,
        ))
    return items


def _class_name_completions(class_table: dict[str, ClassInfo]) -> list[lsp.CompletionItem]:
    """Build completion items for user-defined class names."""
    items = []
    for name, info in class_table.items():
        detail = f"class {name}"
        if info.generic_params:
            detail += f"<{', '.join(info.generic_params)}>"
        if info.parent:
            detail += f" extends {info.parent}"
        items.append(lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Class,
            detail=detail,
            insert_text=name,
        ))
    return items


def _builtin_member_items(members: list[tuple[str, str, str, str]]) -> list[lsp.CompletionItem]:
    """Build completion items from a built-in member table."""
    items = []
    for name, ret_type, kind, doc in members:
        if kind == "field":
            items.append(lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Field,
                detail=f"{ret_type} (field)",
                documentation=doc,
                insert_text=name,
            ))
        else:
            items.append(lsp.CompletionItem(
                label=name,
                kind=lsp.CompletionItemKind.Method,
                detail=doc,
                insert_text=f"{name}($1)$0",
                insert_text_format=lsp.InsertTextFormat.Snippet,
            ))
    return items


def _class_member_items(class_name: str, info: ClassInfo) -> list[lsp.CompletionItem]:
    """Build completion items for fields and methods of a user-defined class."""
    items = []

    for fname, fdecl in info.fields.items():
        if isinstance(fdecl, FieldDecl):
            ftype = _type_repr(fdecl.type)
            items.append(lsp.CompletionItem(
                label=fname,
                kind=lsp.CompletionItemKind.Field,
                detail=f"{fdecl.access} {ftype} {fname}",
                documentation=f"Field of {class_name}",
                insert_text=fname,
            ))

    for mname, mdecl in info.methods.items():
        if isinstance(mdecl, MethodDecl):
            params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in mdecl.params)
            ret = _type_repr(mdecl.return_type)
            access = mdecl.access
            static = " (static)" if access == "class" else ""
            items.append(lsp.CompletionItem(
                label=mname,
                kind=lsp.CompletionItemKind.Method,
                detail=f"{access} {ret} {mname}({params}){static}",
                documentation=f"Method of {class_name}",
                insert_text=f"{mname}($1)$0",
                insert_text_format=lsp.InsertTextFormat.Snippet,
            ))

    return items


def _static_method_items(class_name: str, methods: list[tuple[str, str]]) -> list[lsp.CompletionItem]:
    """Build completion items for stdlib static methods."""
    items = []
    for name, doc in methods:
        items.append(lsp.CompletionItem(
            label=name,
            kind=lsp.CompletionItemKind.Method,
            detail=doc,
            documentation=f"Static method of {class_name}",
            insert_text=f"{name}($1)$0",
            insert_text_format=lsp.InsertTextFormat.Snippet,
        ))
    return items


# ---------------------------------------------------------------------------
# Main completion entry point
# ---------------------------------------------------------------------------

def get_completions(
    result: AnalysisResult,
    position: lsp.Position,
) -> list[lsp.CompletionItem]:
    """Compute completion items for the given cursor position.

    Returns an empty list if no completions are applicable.
    """
    text_before = _get_text_before_cursor(result.source, position)
    class_table = result.analyzed.class_table if result.analyzed else {}

    # ---------------------------------------------------------------
    # Dot-triggered completions: member access or static methods
    # ---------------------------------------------------------------
    dot_match = re.search(r'(\w+)\.\s*$', text_before)
    if dot_match:
        obj_name = dot_match.group(1)
        return _dot_completions(result, obj_name, position, class_table)

    # ---------------------------------------------------------------
    # Optional-chaining triggered completions: obj?.member
    # ---------------------------------------------------------------
    opt_match = re.search(r'(\w+)\?\.\s*$', text_before)
    if opt_match:
        obj_name = opt_match.group(1)
        return _dot_completions(result, obj_name, position, class_table)

    # ---------------------------------------------------------------
    # Arrow triggered completions: obj->member
    # ---------------------------------------------------------------
    arrow_match = re.search(r'(\w+)->\s*$', text_before)
    if arrow_match:
        obj_name = arrow_match.group(1)
        return _dot_completions(result, obj_name, position, class_table)

    # ---------------------------------------------------------------
    # General completions: keywords + types + snippets + class names
    # ---------------------------------------------------------------
    items: list[lsp.CompletionItem] = []
    items.extend(_keyword_completions())
    items.extend(_type_completions())
    items.extend(_snippet_completions())
    items.extend(_class_name_completions(class_table))

    # Add stdlib class names that might not be in the class_table
    for stdlib_name in _STDLIB_STATIC_METHODS:
        if stdlib_name not in class_table:
            items.append(lsp.CompletionItem(
                label=stdlib_name,
                kind=lsp.CompletionItemKind.Class,
                detail=f"stdlib class {stdlib_name}",
                insert_text=stdlib_name,
            ))

    return items


def _dot_completions(
    result: AnalysisResult,
    obj_name: str,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Resolve completions after a dot (member access or static methods)."""

    # 1. Check if obj_name is a known class name (static method access)
    if obj_name in class_table:
        info = class_table[obj_name]
        # Offer static (class) methods and also instance methods/fields
        # since it could be either pattern
        items = _class_member_items(obj_name, info)
        # Also check stdlib static methods
        if obj_name in _STDLIB_STATIC_METHODS:
            # Merge — avoid duplicates by label
            existing_labels = {item.label for item in items}
            for item in _static_method_items(obj_name, _STDLIB_STATIC_METHODS[obj_name]):
                if item.label not in existing_labels:
                    items.append(item)
        return items

    # Check stdlib static methods for classes not in the class_table
    if obj_name in _STDLIB_STATIC_METHODS:
        return _static_method_items(obj_name, _STDLIB_STATIC_METHODS[obj_name])

    # 2. Resolve the type of the variable
    var_type = _resolve_variable_type(result, obj_name, position.line)

    if var_type is not None:
        return _members_for_type(var_type, class_table)

    # 3. Fallback: if we can't resolve the type, try searching class_table
    #    for any class that has members (best-effort)
    return []


def _members_for_type(
    type_base: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Return member completion items for a given base type."""
    # Built-in types
    if type_base == "string":
        return _builtin_member_items(_STRING_MEMBERS)
    if type_base == "List":
        return _builtin_member_items(_LIST_MEMBERS)
    if type_base == "Map":
        return _builtin_member_items(_MAP_MEMBERS)
    if type_base == "Set":
        return _builtin_member_items(_SET_MEMBERS)

    # User-defined class
    if type_base in class_table:
        return _class_member_items(type_base, class_table[type_base])

    # Check parent chain for inherited members
    for cname, cinfo in class_table.items():
        if cname == type_base:
            return _class_member_items(cname, cinfo)

    return []
