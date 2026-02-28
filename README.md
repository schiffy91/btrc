# btrc

**Modern syntax. C output. No magic.**

btrc is a statically-typed language that transpiles to C. It adds modern features — classes, generics, type inference, lambdas, f-strings, collections — while keeping C's memory model and performance characteristics. The generated C is readable and self-contained: no runtime library, no garbage collector, no virtual machine. It includes small inline helpers for strings, collections, and exception handling, but requires no separate runtime. You can inspect, debug, and link the output against anything.

```
class Counter {
    private int count = 0;
    public void inc() { self.count++; }
    public int get() { return self.count; }
}

int main() {
    var c = Counter();
    c.inc();
    c.inc();
    print(f"count = {c.get()}");
    return 0;
}
```

## Why btrc?

As LLMs make programming more accessible, code itself becomes less about typing and more about taste — what you choose to build, how you choose to build it, what tradeoffs you find beautiful. Programming is becoming an art. btrc is an art project.

The design question: *what if you could write C with modern syntax and get readable C output you can inspect?* The compiler is spec-driven — a formal [EBNF grammar](spec/grammar.ebnf) defines every keyword and operator, an [algebraic AST spec](spec/ast/ast.asdl) defines every node type, and the pipeline walks through six stages from source to native binary. The generated C is something a human could have written. You can read it, debug it, link it against anything.

It's a transpiler, not a new compiler backend — you get gcc compatibility for free but inherit C's limitations. There is no borrow checker, no lifetime analysis, and no memory safety beyond what C provides. Exception handling uses `setjmp`/`longjmp` and does not automatically free allocations on throw. If you need a production systems language with safety guarantees, use [Rust](https://www.rust-lang.org/), [Zig](https://ziglang.org/), [Odin](https://odin-lang.org/), or [C3](https://c3-lang.org/).

## Quick Start

```bash
# Build the compiler
make build

# Compile a program
./bin/btrc hello.btrc -o hello.c
gcc hello.c -o hello -lm
./hello

# Or use the Python compiler directly
python3 -m src.compiler.python.main hello.btrc -o hello.c
```

## What You Get Over C

| C Pain Point | btrc Solution |
|---|---|
| No classes | Full OOP: classes, inheritance, interfaces, abstract classes |
| No generics | Monomorphized generics (`List<T>`, `Map<K,V>`, user-defined) |
| No type inference | `var x = 42;` just works |
| `printf` formatting | f-strings: `f"x = {x + 1}"` |
| No collections | Built-in `List<T>`, `Map<K,V>`, `Set<T>` with rich APIs |
| No lambdas | Arrow lambdas: `(int x) => x * 2` |
| No exceptions | `try`/`catch`/`finally` via `setjmp`/`longjmp` (no automatic cleanup) |
| No operator overloading | `__add__`, `__sub__`, `__eq__`, `__neg__` |
| No string methods | `.len()`, `.contains()`, `.split()`, `.trim()`, `.toUpper()`, ... |
| No properties | C#-style `get`/`set` properties |
| Null pointer chaos | Optional chaining `?.` and null coalescing `??` |
| Manual memory only | Automatic reference counting with `keep`/`release` |

## What You Keep From C

- Direct memory control with `new`/`delete` and pointers
- Compilation to native code via gcc with minimal runtime overhead
- Full C interop -- call any C library, use any C header
- `#include`, `struct`, `typedef`, `extern` -- all still work
- Same mental model: stack vs heap, pointers, manual lifetime management
- Compiles with `gcc` -- no custom toolchain required

---

## Language Guide

### Types

```
// Primitives
int x = 42;
float f = 3.14;
double d = 2.718281828;
bool flag = true;
char c = 'A';
string name = "btrc";

// Pointers (just like C)
int* ptr = &x;
int val = *ptr;

// Type inference
var count = 10;          // int
var msg = "hello";       // string
var items = [1, 2, 3];   // List<int>
var cache = {"a": 1};    // Map<string, int>
```

### Number Literals

```
int dec = 255;
int hex = 0xFF;
int bin = 0b11111111;
int oct = 0o377;
float f = 3.14f;
```

### Control Flow

```
// if / else if / else
if (x > 0) {
    print("positive");
} else if (x == 0) {
    print("zero");
} else {
    print("negative");
}

// C-style for
for (int i = 0; i < 10; i++) {
    sum += i;
}

// for-in with range
for i in range(10) { }
for i in range(2, 8) { }
for i in range(0, 20, 2) { }

// for-in over collections
for val in list { }
for key, value in map { }
for ch in someString { }

// while / do-while
while (running) { tick(); }
do { x++; } while (x < 10);

// switch
switch (status) {
    case 200: handle_ok(); break;
    case 404: handle_not_found(); break;
    default: handle_error();
}
```

### Functions

```
int add(int a, int b) {
    return a + b;
}

// Default parameters
string greet(string name, string prefix = "Hello") {
    return f"{prefix}, {name}!";
}

greet("world");          // "Hello, world!"
greet("world", "Hey");   // "Hey, world!"

// Forward declarations (mutual recursion)
bool is_even(int n);
bool is_odd(int n) { return n == 0 ? false : is_even(n - 1); }
bool is_even(int n) { return n == 0 ? true : is_odd(n - 1); }
```

### Lambdas

```
// Arrow syntax (expression body)
var double_it = (int x) => x * 2;

// Arrow syntax (block body)
var abs_fn = (int x) => {
    if (x < 0) { return -x; }
    return x;
};

// Verbose syntax
var multiply = int function(int a, int b) { return a * b; };

// Use with collection methods
nums.forEach(void function(int x) { print(f"{x}"); });
List<int> evens = nums.filter(bool function(int x) { return x % 2 == 0; });
```

### Classes

```
class Point {
    public int x;
    public int y;

    public Point(int x, int y) {
        self.x = x;
        self.y = y;
    }

    public int distSquared() {
        return self.x * self.x + self.y * self.y;
    }
}

Point p = Point(3, 4);
assert(p.distSquared() == 25);
```

#### Access Control

```
class Account {
    private int balance;

    public Account(int initial) { self.balance = initial; }
    public int getBalance() { return self.balance; }

    public void deposit(int amount) {
        if (amount > 0) { self.balance += amount; }
    }
}
```

#### Static Methods

```
class MathUtil {
    class int square(int x) { return x * x; }
    class int max(int a, int b) { return a > b ? a : b; }
}

int result = MathUtil.square(5);  // 25
```

#### Default Field Values

```
class Config {
    public int width = 800;
    public int height = 600;
    public int fps = 60;
}

Config cfg = Config();  // all defaults applied
```

### Inheritance

```
class Animal {
    public string name;
    public Animal(string name) { self.name = name; }
    public string speak() { return "..."; }
}

class Dog extends Animal {
    public Dog(string name) { self.name = name; }
    public string speak() { return "Woof"; }
}

class Cat extends Animal {
    public Cat(string name) { self.name = name; }
    public string speak() { return "Meow"; }
}

Dog d = Dog("Rex");
print(d.speak());    // "Woof"
print(d.name);       // "Rex"
```

### Interfaces

```
interface Greeter {
    string greet();
}

class Dog implements Greeter {
    public string name;
    public Dog(string name) { self.name = name; }
    public string greet() { return "Woof"; }
}

// Interface inheritance
interface HasName {
    string name();
}

interface HasFullName extends HasName {
    string fullName();
}
```

### Abstract Classes

```
abstract class Shape {
    public abstract double area();
    public string kind() { return "shape"; }  // concrete method allowed
}

class Circle extends Shape {
    public double r;
    public Circle(double r) { self.r = r; }
    public double area() { return 3.14159 * self.r * self.r; }
}
```

### Generics

btrc generics are monomorphized -- the compiler generates specialized C code for each type combination. Zero runtime overhead, but binary size grows with each unique type combination (the same trade-off as C++ templates and Rust generics).

```
class Box<T> {
    public T value;
    public Box(T val) { self.value = val; }
    public T get() { return self.value; }
}

Box<int> bi = Box(42);
Box<string> bs = Box("hello");

class Pair<A, B> {
    public A first;
    public B second;
    public Pair(A a, B b) { self.first = a; self.second = b; }
}

Pair<string, int> entry = Pair("score", 100);
```

### Operator Overloading

```
class Vec2 {
    public int x;
    public int y;
    public Vec2(int x, int y) { self.x = x; self.y = y; }

    public Vec2 __add__(Vec2 other) {
        return Vec2(self.x + other.x, self.y + other.y);
    }
    public Vec2 __sub__(Vec2 other) {
        return Vec2(self.x - other.x, self.y - other.y);
    }
    public Vec2 __neg__() {
        return Vec2(-self.x, -self.y);
    }
    public bool __eq__(Vec2 other) {
        return self.x == other.x && self.y == other.y;
    }
}

Vec2 a = Vec2(1, 2);
Vec2 b = Vec2(3, 4);
Vec2 c = a + b;         // Vec2(4, 6)
Vec2 d = -a;            // Vec2(-1, -2)
bool eq = (a == b);     // false
```

### Properties

```
class Temperature {
    private float celsius;

    public Temperature(float c) { self.celsius = c; }

    public float fahrenheit {
        get { return self.celsius * 9.0 / 5.0 + 32.0; }
        set { self.celsius = (value - 32.0) * 5.0 / 9.0; }
    }
}

var t = Temperature(100.0);
float f = t.fahrenheit;      // 212.0 (getter)
t.fahrenheit = 32.0;         // sets celsius to 0.0 (setter)

// Auto-properties
class Point {
    public int x { get; set; }
    public int y { get; set; }
}
```

### Enums

```
// Simple enums
enum Color { RED, GREEN, BLUE };
enum Status { OK = 200, NOT_FOUND = 404, ERROR = 500 };

// Rich enums (algebraic data types / tagged unions)
enum class Shape {
    Circle(double radius),
    Rect(double w, double h),
    Point
}

Shape s = Shape.Circle(5.0);
if (s.tag == Shape.Circle) {
    print(f"radius: {s.data.Circle.radius}");
}
```

### Tuples

```
(int, int) divmod(int a, int b) {
    return (a / b, a % b);
}

(int, int) result = divmod(17, 5);
assert(result._0 == 3);  // quotient
assert(result._1 == 2);  // remainder

// Nested tuples
(int, (string, bool)) nested = (1, ("yes", true));
```

### Collections

#### List

```
List<int> nums = [10, 20, 30];
nums.push(40);
nums[0] = 99;
int val = nums.pop();

for x in nums { print(f"{x}"); }

// Rich API
nums.sort();
nums.reverse();
bool has = nums.contains(20);
int idx = nums.indexOf(20);
List<int> sub = nums.slice(1, 3);
List<int> head = nums.take(2);
int total = nums.sum();
int smallest = nums.min();
List<int> unique = nums.distinct();
string joined = names.join(", ");

// Functional
List<int> evens = nums.filter(bool function(int x) { return x % 2 == 0; });
bool any_neg = nums.any(bool function(int x) { return x < 0; });

nums.free();  // manual cleanup
```

#### Map

```
Map<string, int> ages = {"alice": 30, "bob": 25};
ages.put("carol", 35);
int age = ages.get("alice");
bool exists = ages.has("bob");

List<string> keys = ages.keys();
List<int> values = ages.values();

ages.free();
```

#### Set

```
Set<int> s = {};
s.add(10);
s.add(20);
s.add(10);            // duplicate ignored
assert(s.len == 2);

Set<int> other = {};
other.add(20);
other.add(30);

Set<int> u = s.unite(other);       // {10, 20, 30}
Set<int> i = s.intersect(other);   // {20}
Set<int> d = s.subtract(other);    // {10}

s.free();
```

### Strings

btrc strings have a full method API -- no more `strlen`/`strstr`/`strtok` gymnastics.

```
string s = "hello world";

// Info
int len = s.len();
bool has = s.contains("world");
int idx = s.indexOf("world");
bool starts = s.startsWith("hello");

// Transform
string up = s.toUpper();
string low = s.toLower();
string trimmed = "  hi  ".trim();
string replaced = s.replace("world", "btrc");
string repeated = "ab".repeat(3);        // "ababab"

// Extract
string sub = s.substring(0, 5);          // "hello"
char ch = s.charAt(0);                   // 'h'

// Pad
string padded = "42".padLeft(5, '0');    // "00042"
string zfilled = "42".zfill(5);          // "00042"

// Concatenation
string full = "hello" + " " + "world";

// Iterate
for ch in "hello" { print(f"{ch}"); }
```

### F-Strings

```
int x = 42;
string name = "world";
print(f"hello {name}, x = {x}");
print(f"{x * 2 + 1}");                  // expressions work
```

### Null Safety

```
// Optional chaining -- safe navigation through nullable pointers
int val = obj?.field;        // 0 if obj is null, no crash

// Null coalescing -- provide defaults
string name = ptr ?? "anonymous";

// Nullable pointers
int* p = null;
if (p != null) {
    int v = *p;
}
```

### Memory Management

btrc uses lightweight **automatic reference counting (ARC)** for memory management. Every class instance tracks how many references point to it. When the count reaches zero, the object is automatically destroyed. No garbage collector -- deterministic cleanup at scope boundaries.

> **Safety model:** btrc inherits C's memory model. The compiler checks types and access control at compile time. ARC handles common memory management automatically, but does not prevent all use-after-free or dangling pointer bugs. If you need full memory safety guarantees, use Rust. btrc is for programmers who want C's control with better ergonomics.

```
// Heap allocation -- refcount starts at 1
Node n = new Node(99);
n.val = 100;
delete n;                    // force destroy, set to NULL

// Destructors for cleanup
class Resource {
    public void __del__() {
        // called automatically when refcount reaches zero
    }
}

// Pointers work like C
int x = 42;
int* ptr = &x;
int val = *ptr;

// C memory functions available
int* buf = (int*)malloc(100 * sizeof(int));
free(buf);
```

#### ARC Keywords: `keep` and `release`

| Keyword | Usage | Meaning |
|---------|-------|---------|
| `keep` | Function param: `store(keep T t)` | "I store this pointer" -- rc++ at call site |
| `keep` | Function return: `keep T pop()` | "Caller takes ownership" -- caller auto-manages |
| `keep` | Statement: `keep p;` | Explicit rc++ (keep alive past scope exit) |
| `release` | Statement: `release p;` | rc--; destroy at zero; p = NULL |

```
// Container stores a reference -- keep param increments refcount
class Container {
    public Node item;
    public void store(keep Node n) {
        self.item = n;    // field assignment: release old, keep new
    }
}

void example() {
    var c = new Container();
    var n = new Node(42);
    c.store(n);              // rc++ at call site (keep param)
    delete c;                // Container destructor releases item (rc--)
    // n still alive -- rc was incremented by keep
    delete n;                // force destroy
}

// Explicit keep/release for manual control
var p = new Node(1);
keep p;                      // rc++ (now 2)
release p;                   // rc-- (now 1); p = NULL
// Object still alive (rc > 0) but unreachable through p
```

**Zero-cost when unused:** When no `keep` is ever applied to a variable, the compiler skips all refcount operations. The generated C is identical to hand-written manual code. Existing code that uses `new`/`delete` works exactly as before.

**Cycle detection:** For classes that can form reference cycles (A -> B -> A), the compiler includes a trial deletion cycle collector. Non-cyclable types pay zero overhead.

### Exception Handling

```
void validate(int x) {
    if (x < 0) {
        throw "negative value";
    }
}

try {
    validate(-1);
} catch (string e) {
    print(f"caught: {e}");
} finally {
    print("cleanup runs always");
}
```

### C Interop

btrc is a superset of a large subset of C. You can mix btrc and C freely in the same file.

```
#include <math.h>

struct Vec2 {
    float x;
    float y;
};

float dot(struct Vec2* a, struct Vec2* b) {
    return a->x * b->x + a->y * b->y;
}

int main() {
    struct Vec2 a = {3.0f, 4.0f};
    struct Vec2 b = {1.0f, 0.0f};
    float d = dot(&a, &b);
    printf("dot = %f, sqrt = %f\n", d, sqrt(d));
    return 0;
}
```

---

## Compilation Pipeline

btrc compiles through six stages. Two formal specs drive the front-end: [`spec/grammar.ebnf`](spec/grammar.ebnf) defines all keywords, operators, and syntax rules; [`spec/ast/ast.asdl`](spec/ast/ast.asdl) defines all AST node types using [Zephyr ASDL](https://www.cs.princeton.edu/~appel/papers/asdl97.pdf). A structured IR separates lowering from emission.

```
  spec/grammar.ebnf          (single source of truth: keywords, operators, syntax)
  spec/ast/ast.asdl          (single source of truth: AST node types)
         │
  .btrc source
         │
    [Lexer]       ──→ tokens            grammar-driven (keywords + operators from EBNF)
         │
    [Parser]      ──→ typed AST         ASDL-generated node classes
         │
    [Analyzer]    ──→ checked AST       scopes, types, generic instance collection
         │
    [IR Gen]      ──→ IR tree           structured nodes (IRIf, IRCall, IRFor, ...)
         │
    [Optimizer]   ──→ optimized IR      dead helper elimination
         │
    [C Emitter]   ──→ .c file           simple tree walk — no lowering logic
         │
    gcc -lm       ──→ native binary
```

The generated C is self-contained -- no runtime library, no special headers. It includes everything inline: vtables for inheritance, monomorphized generic structs, collection implementations, string helpers, and exception handling via `setjmp`/`longjmp`.

---

## Project Structure

```
spec/
  grammar.ebnf                 # Formal EBNF grammar (lexical + syntactic rules)
  ast/
    ast.asdl                   # Algebraic AST spec (Zephyr ASDL)
    asdl_parser.py             # ASDL file parser
    asdl_python.py             # ASDL → Python dataclasses
    asdl_btrc.py               # ASDL → btrc classes
    gen_builtins.py            # stdlib .btrc → LSP builtins (make gen-builtins)

benchmarks/                    # Performance benchmarks (.btrc programs + runner)

src/
  compiler/
    python/                    # Compiler (Python)
      ebnf.py                  # EBNF parser → GrammarInfo
      tokens.py                # Token + TokenType (grammar-driven)
      lexer.py                 # Grammar-driven lexer
      lexer_literals.py        # Number/string literal parsing
      ast_nodes.py             # GENERATED from spec/ast/ast.asdl
      main.py                  # Pipeline entry point + CLI
      parser/                  # Recursive descent parser (mixin-based)
      analyzer/                # Type checking, scopes, generics (mixin-based)
      ir/                      # IR pipeline
        nodes.py               # IR node dataclass definitions
        optimizer.py           # Dead helper elimination
        emitter.py             # IR → C text (tree walk)
        gen/                   # AST → IR lowering (classes, generics, lambdas, ...)
          generics/            # Monomorphization (lists, maps, sets, user types)
        helpers/               # Runtime helper C source text (strings, alloc, ...)
      tests/                   # Unit tests (lexer, parser, analyzer, e2e)
  stdlib/                      # Standard library (auto-included btrc source)
    vector.btrc                # Vector<T> (dynamic array)
    list.btrc                  # List<T> (doubly-linked list)
    iterable.btrc              # Iterable<T> interface
    array.btrc                 # Array<T> (fixed-size)
    map.btrc                   # Map<K,V>
    set.btrc                   # Set<T>
    strings.btrc               # String utilities
    math.btrc                  # Math functions
    datetime.btrc              # Date/time
    error.btrc                 # Error classes
    result.btrc                # Result type
    io.btrc                    # File I/O
    console.btrc               # Console output
    random.btrc                # Random numbers
  tests/                       # Language test suite (99 .btrc test programs)
  devex/
    ext/                       # VS Code extension (syntax highlighting + LSP client)
    lsp/                       # Language server (completions, diagnostics, hover, go-to-def)
```

## Build & Test

```bash
make build              # Create bin/btrcpy wrapper script
make test               # Run compiler unit tests + btrc test suite (~751 tests)
make test-btrc          # Run just the 99 btrc end-to-end tests
make lint               # Lint with ruff
make format             # Format with ruff

make gen-builtins       # Regenerate LSP builtins from stdlib sources
make install-ext        # Install VS Code extension
make package-ext        # Package VS Code extension
make clean              # Remove build artifacts
```

### Requirements

- Python 3 + pip
- gcc
- pytest (for tests)
- pygls + lsprotocol (for LSP)
- Node.js + npm (for VS Code extension)

## Editor Support

btrc ships with a VS Code extension ([`src/devex/ext/`](src/devex/ext/)) and a Language Server Protocol implementation ([`src/devex/lsp/`](src/devex/lsp/)) that reuses the compiler's own lexer, parser, and analyzer. Diagnostics match exactly what the compiler reports — there is no separate linting pass.

The LSP server maintains a two-tier cache: the current analysis (which may have parse errors while you type) and the last fully successful analysis. Features like go-to-definition and hover fall back to the good cache during transient errors, so intelligence keeps working while you edit.

### Features

| Feature | Description |
|---|---|
| Syntax highlighting | TextMate grammar + semantic tokens for rich classification |
| Diagnostics | Real-time errors from the compiler's lexer, parser, and analyzer |
| Code completion | Keywords, types, member access (`.`, `?.`, `->`), stdlib static methods, snippets |
| Hover | Type information for variables, fields, methods, classes, and built-in types |
| Go to definition | Classes, functions, methods, fields, properties, variables, enums, typedefs |
| Find references | All usages of a symbol across the document with scope-aware matching |
| Rename | Symbol rename across all references |
| Signature help | Parameter hints for functions, constructors, methods, and stdlib calls |
| Document symbols | Outline view with class hierarchy (fields, methods as children) |

### Install

```bash
# Install the VS Code extension (builds + installs)
make install-ext

# Or open the project in the devcontainer for automatic setup
```

The extension auto-discovers the LSP server and Python interpreter. Configure `btrc.pythonPath` or `btrc.serverPath` in VS Code settings if needed.

## Roadmap

Planned but not yet implemented:
- **Self-hosting** -- rewrite the compiler in btrc itself (bootstrap cycle)
- **Module system** -- currently relies on `#include "file.btrc"` textual inclusion
- **Weak references** -- `weak` keyword for intentional non-owning references (avoids cycles for known patterns like parent pointers)
- **Incremental compilation** -- only recompile changed files
