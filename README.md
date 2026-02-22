# btrc

A modern language that transpiles to C. Write expressive, object-oriented code that compiles to efficient native binaries.

## Quick Start

```bash
# Transpile and compile
python3 btrc.py hello.btrc -o hello.c
gcc hello.c -o hello -lm
./hello
```

## Language Overview

btrc is a C superset: all valid C is valid btrc. On top of C, btrc adds modern language features inspired by Python, C#, and Swift.

### Hello World

```btrc
int main() {
    print("Hello, world!");
    return 0;
}
```

No `#include` needed — btrc auto-includes standard headers.

### Variables and Types

```btrc
int main() {
    int x = 42;
    float pi = 3.14f;
    bool alive = true;
    string name = "btrc";      // string is char* under the hood
    var count = 100;            // type inference from initializer

    print(f"name={name}, count={count}");
    return 0;
}
```

### Classes and Objects

```btrc
class Point {
    public float x;
    public float y;

    public Point(float x, float y) {
        self.x = x;
        self.y = y;
    }

    public float distance() {
        return sqrt(self.x * self.x + self.y * self.y);
    }

    public Point __add__(Point* other) {
        return Point(self.x + other->x, self.y + other->y);
    }

    public string toString() {
        // Uses printf-style formatting via C
        printf("(%g, %g)", self.x, self.y);
        return "";
    }
}

int main() {
    var a = Point(3.0f, 4.0f);
    var b = Point(1.0f, 2.0f);
    var c = a + b;
    print(f"distance: {a.distance()}");
    print(f"sum: ({c.x}, {c.y})");
    return 0;
}
```

### Inheritance

```btrc
class Animal {
    public string name;
    public Animal(string name) {
        self.name = name;
    }
    public string speak() {
        return "...";
    }
}

class Dog extends Animal {
    public Dog(string name) {
        self.name = name;
    }
    public string speak() {
        return "Woof!";
    }
}

class Cat extends Animal {
    public Cat(string name) {
        self.name = name;
    }
    public string speak() {
        return "Meow!";
    }
}

int main() {
    var dog = Dog("Rex");
    var cat = Cat("Whiskers");
    print(f"{dog.name} says {dog.speak()}");
    print(f"{cat.name} says {cat.speak()}");
    return 0;
}
```

### Collections

```btrc
int main() {
    // Lists (dynamic arrays)
    List<int> nums = [10, 20, 30, 40, 50];
    nums.push(60);
    nums.sort();
    nums.reverse();

    for x in nums {
        print(x);
    }
    print(f"length: {nums.len}");
    print(f"contains 30: {nums.contains(30)}");
    nums.free();

    // Maps (hash tables)
    Map<string, int> ages = {"Alice": 30, "Bob": 25};
    ages.put("Carol", 28);
    print(f"Alice is {ages.get(\"Alice\")}");
    ages.free();

    return 0;
}
```

### String Methods

```btrc
int main() {
    string s = "  Hello, World!  ";

    print(s.len());                    // 17
    print(s.trim());                   // "Hello, World!"
    print(s.toUpper());               // "  HELLO, WORLD!  "
    print(s.toLower());               // "  hello, world!  "
    print(s.contains("World"));       // 1 (true)
    print(s.startsWith("  Hello"));   // 1 (true)
    print(s.endsWith("!  "));         // 1 (true)
    print(s.indexOf("World"));        // 9
    print(s.substring(2, 5));         // "Hello"

    string a = "hello";
    string b = "hello";
    print(a.equals(b));               // 1 (true)

    return 0;
}
```

### For-In Loops and Range

```btrc
int main() {
    // Range-based loops
    for i in range(5) {
        print(i);                     // 0 1 2 3 4
    }

    for i in range(10, 20) {
        print(i);                     // 10 11 ... 19
    }

    for i in range(0, 100, 10) {
        print(i);                     // 0 10 20 ... 90
    }

    // Iterate over collections
    List<string> names = ["Alice", "Bob", "Carol"];
    for name in names {
        print(f"Hello, {name}!");
    }
    names.free();

    return 0;
}
```

### Tuples

```btrc
(int, int) divmod(int a, int b) {
    return (a / b, a % b);
}

int main() {
    var result = divmod(17, 5);
    print(f"quotient: {result._0}");  // 3
    print(f"remainder: {result._1}"); // 2
    return 0;
}
```

### Error Handling

```btrc
void validate(int age) {
    if (age < 0) {
        throw "age cannot be negative";
    }
    if (age > 150) {
        throw "age seems unrealistic";
    }
}

int main() {
    try {
        validate(200);
    } catch (string e) {
        print(f"Error: {e}");
    }
    return 0;
}
```

### Nullable Types and Optional Chaining

```btrc
class Node {
    public int value;
    public Node* next;
    public Node(int v) {
        self.value = v;
        self.next = null;
    }
}

int main() {
    var a = Node(10);
    var b = Node(20);
    a.next = &b;

    // Optional chaining — safe access through nullable pointers
    print(a.next?.value);       // 20
    print(a.next?.next?.value); // 0 (null, returns default)

    // Null coalescing
    char* name = null;
    char* result = name ?? "Anonymous";
    print(result);              // Anonymous

    return 0;
}
```

### Default Parameters

```btrc
void greet(string name, string greeting = "Hello") {
    print(f"{greeting}, {name}!");
}

class Window {
    public int width;
    public int height;
    public string title;

    public Window(int width = 800, int height = 600, string title = "btrc App") {
        self.width = width;
        self.height = height;
        self.title = title;
    }
}

int main() {
    greet("World");                // Hello, World!
    greet("World", "Bonjour");    // Bonjour, World!

    var w = Window();              // 800x600, "btrc App"
    var w2 = Window(1920, 1080);   // 1920x1080, "btrc App"
    return 0;
}
```

### Operator Overloading

```btrc
class Vec2 {
    public float x;
    public float y;

    public Vec2(float x, float y) {
        self.x = x;
        self.y = y;
    }

    public Vec2 __add__(Vec2* other) {
        return Vec2(self.x + other->x, self.y + other->y);
    }

    public Vec2 __sub__(Vec2* other) {
        return Vec2(self.x - other->x, self.y - other->y);
    }

    public Vec2 __mul__(Vec2* other) {
        return Vec2(self.x * other->x, self.y * other->y);
    }

    public bool __eq__(Vec2* other) {
        return self.x == other->x && self.y == other->y;
    }
}

int main() {
    var a = Vec2(1.0f, 2.0f);
    var b = Vec2(3.0f, 4.0f);
    var c = a + b;
    print(f"({c.x}, {c.y})");    // (4.0, 6.0)
    return 0;
}
```

### Static Methods

```btrc
class MathUtils {
    class int max(int a, int b) {
        return a > b ? a : b;
    }

    class int min(int a, int b) {
        return a < b ? a : b;
    }

    class int clamp(int val, int lo, int hi) {
        return MathUtils.min(MathUtils.max(val, lo), hi);
    }
}

int main() {
    print(MathUtils.max(10, 20));      // 20
    print(MathUtils.clamp(150, 0, 100)); // 100
    return 0;
}
```

### Heap Allocation (new/delete)

```btrc
class TreeNode {
    public int value;
    public TreeNode* left;
    public TreeNode* right;

    public TreeNode(int v) {
        self.value = v;
        self.left = null;
        self.right = null;
    }
}

int main() {
    TreeNode* root = new TreeNode(10);
    root->left = new TreeNode(5);
    root->right = new TreeNode(15);

    print(root->value);        // 10
    print(root->left->value);  // 5
    print(root->right->value); // 15

    delete root->left;
    delete root->right;
    delete root;
    return 0;
}
```

### C Interop

btrc is a superset of C. You can freely mix C and btrc:

```btrc
#include <time.h>

int main() {
    // Pure C code works
    time_t now = time(NULL);
    struct tm* local = localtime(&now);
    printf("Year: %d\n", local->tm_year + 1900);

    // btrc features alongside C
    var greeting = "Hello from btrc!";
    print(greeting);

    return 0;
}
```

## Standard Library

btrc includes an object-oriented standard library that wraps C's standard library in idiomatic btrc classes. Inspired by Python's stdlib.

> **Note:** btrc does not yet have an `import` system. To use a stdlib module, copy the class definitions into your `.btrc` file. A proper module/import system is planned.

### Math

Static utility class for common math operations.

```btrc
// Constants
float pi = Math.PI();
float e  = Math.E();

// Basic operations
Math.abs(-42);           // 42
Math.max(10, 20);        // 20
Math.min(10, 20);        // 10
Math.clamp(150, 0, 100); // 100

// Power and roots
Math.power(2.0f, 10);    // 1024.0
Math.sqrt(16.0f);        // 4.0

// Combinatorics
Math.factorial(6);       // 720
Math.gcd(48, 18);        // 6
Math.lcm(4, 6);          // 12
Math.fibonacci(10);      // 55

// Checks
Math.isPrime(17);        // true
Math.isEven(42);         // true

// Aggregation
List<int> nums = [1, 2, 3, 4, 5];
Math.sum(nums);          // 15
```

### IO (File / Path)

`File` provides object-oriented file I/O. `Path` provides static convenience methods.

```btrc
// Write a file
var f = File("output.txt", "w");
f.writeLine("Hello, world!");
f.writeLine("Second line");
f.close();

// Read a file
var f2 = File("output.txt", "r");
string content = f2.read();
f2.close();

// Read lines
var f3 = File("output.txt", "r");
List<string> lines = f3.readLines();
for line in lines {
    print(line);
}
f3.close();

// Static helpers
Path.writeAll("data.txt", "quick write");
string data = Path.readAll("data.txt");
bool exists = Path.exists("data.txt");
```

### Strings

`Strings` provides static utility functions for string manipulation.

```btrc
// String repetition and joining
Strings.repeat("ha", 3);      // "hahaha"

List<string> words = ["one", "two", "three"];
Strings.join(words, ", ");     // "one, two, three"

Strings.replace("hello world", "world", "btrc");  // "hello btrc"

// Character and conversion utilities
Strings.isDigit('5');          // true
Strings.isAlpha('A');          // true
Strings.toInt("42");           // 42
Strings.toFloat("3.14");      // 3.14
```

### Collections (Stack / Queue / Counter)

Higher-level data structures built on top of `List<int>` and `Map<string, int>`.

```btrc
// Stack — LIFO
var stack = Stack();
stack.push(10);
stack.push(20);
stack.push(30);
stack.peek();      // 30
stack.pop();       // 30
stack.size();      // 2
stack.isEmpty();   // false
stack.cleanup();

// Queue — FIFO
var queue = Queue();
queue.enqueue(1);
queue.enqueue(2);
queue.enqueue(3);
queue.peek();      // 1
queue.dequeue();   // 1
queue.size();      // 2
queue.cleanup();

// Counter — count occurrences
var counter = Counter();
counter.add("apple");
counter.add("banana");
counter.add("apple");
counter.get("apple");      // 2
counter.get("banana");     // 1
counter.get("cherry");     // 0
counter.totalCount();      // 3
counter.uniqueCount();     // 2
counter.cleanup();
```

### Random

Random number generation with auto-seeding.

```btrc
var rng = Random();
rng.seed(42);              // Deterministic seed
// rng.seedTime();         // Or seed from system clock

rng.randint(1, 100);       // Random int in [1, 100]
rng.random();              // Random float in [0.0, 1.0]
rng.uniform(5.0f, 10.0f);  // Random float in [5.0, 10.0]

List<int> items = [10, 20, 30, 40, 50];
rng.choice(items);          // Random element
rng.shuffle(items);         // Shuffle in place
```

### DateTime (DateTime / Timer)

Date/time and performance measurement.

```btrc
// Current date and time
var now = DateTime.now();
print(f"Date: {now.dateString()}");    // 2026-02-21
print(f"Time: {now.timeString()}");    // 14:30:05
print(f"Full: {now.format()}");        // 2026-02-21 14:30:05

// Construct a specific date
var date = DateTime(2025, 12, 25);
date.display();   // Prints: 2025-12-25 00:00:00

// Timer — measure elapsed time
var timer = Timer();
timer.start();
// ... do work ...
timer.stop();
printf("Elapsed: %f seconds\n", timer.elapsed());
timer.reset();
```

## Examples

The `examples/` directory contains runnable programs:

| File | Description |
|------|-------------|
| `hello.btrc` | Hello World |
| `classes.btrc` | Classes, constructors, methods |
| `collections.btrc` | Lists, maps, for-in loops |
| `animals.btrc` | Inheritance and method overriding |
| `calculator.btrc` | Static methods, operator overloading, f-strings |
| `error_handling.btrc` | Try/catch, throw, error propagation |
| `string_processing.btrc` | String methods, f-strings with expressions |
| `todo_app.btrc` | Full app: classes, `List<CustomClass>`, maps |
| `linked_list.btrc` | Heap allocation (`new`/`delete`), pointers, data structures |
| `shapes.btrc` | Inheritance hierarchy, multi-level inheritance, math |
| `sorting.btrc` | Sorting algorithms with `List<int>` and static methods |
| `stdlib_demo.btrc` | Standard library showcase: Math, Strings, Stack, Counter |

```bash
# Run any example
python3 btrc.py examples/animals.btrc -o build/animals.c
gcc build/animals.c -o build/animals -lm
./build/animals
```

## Self-Hosted Compiler

btrc includes a self-hosted compiler written in btrc itself. Currently at **Milestone A** (lexer), it tokenizes btrc source files. The compiler is bootstrapped — the Python compiler compiles the btrc compiler to C, which then compiles to a native binary.

```bash
# Build the self-hosted compiler
python3 btrc.py compiler/btrc/btrc_compiler.btrc -o build/btrc_compiler.c
gcc build/btrc_compiler.c -o build/btrc_compiler -lm

# Tokenize a btrc file
./build/btrc_compiler examples/hello.btrc --emit-tokens
```

The compiler is written in idiomatic btrc: classes (`Lexer`, `Token`, `Keywords`, `CharBuffer`, `Console`), `Map<string, int>` for keyword lookup, `List<Token>` for token storage, `string` methods for source traversal, enums for exit codes, and stdlib `Path.readAll()` for file I/O.

## File Structure

```
btrc/
  btrc.py                    # Entry point
  compiler/
    python/                  # Python-based transpiler
      lexer.py               #   Tokenizer
      parser.py              #   Parser → AST
      analyzer.py            #   Semantic analysis
      codegen.py             #   C code generation
      tests/                 #   Unit tests (pytest)
    btrc/                    # Self-hosted compiler (Milestone A)
      btrc_compiler.btrc     #   Main entry point
      lexer.btrc             #   Lexer class
      token.btrc             #   Token class
      token_types.btrc       #   Token type enum + names
      keywords.btrc          #   Keyword lookup (Map<string, int>)
      char_buffer.btrc       #   Character buffer utility
      console.btrc           #   Console output + exit codes
  stdlib/                    # btrc standard library
    math.btrc                #   Math utilities
    io.btrc                  #   File and Path classes
    strings.btrc             #   String utilities (Strings)
    collections.btrc         #   Stack, Queue, Counter
    random.btrc              #   Random number generation
    datetime.btrc            #   DateTime and Timer
  examples/                  # Example programs (12)
  tests/btrc/                # btrc integration tests (17)
  build/                     # Build output (gitignored)
```

## Running Tests

```bash
# All tests (Python compiler + btrc integration)
python3 -m pytest -q

# Just Python compiler tests
python3 -m pytest compiler/python/tests/ -q

# Just btrc integration tests
python3 -m pytest tests/btrc/test_btrc_runner.py -v
```

## Design Principles

1. **C is always valid** — btrc is a strict superset of C
2. **Zero runtime overhead** — everything compiles to plain C
3. **Gradual adoption** — use as much or as little btrc as you want
4. **No garbage collector** — explicit memory management, like C
5. **Readable output** — generated C is human-readable
