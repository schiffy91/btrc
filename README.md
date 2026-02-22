# btrc

A modern language that transpiles to C. Write expressive, object-oriented code that compiles to efficient native binaries. No garbage collector — you own your memory.

## Quick Start

```bash
python3 btrc.py hello.btrc -o hello.c
gcc hello.c -o hello -lm
./hello
```

## Hello World

No boilerplate required — `main` is your entry point.

```
int main() {
    print("hello from btrc!");
    return 0;
}
```

## Classes

Fields, constructors, instance methods, and static methods.

```
class Counter {
    private int count = 0;

    public void inc() { self.count++; }
    public int get() { return self.count; }
}

class Math {
    class int square(int x) { return x * x; }
}

int main() {
    Counter c = Counter();
    c.inc(); c.inc(); c.inc();
    print(f"count = {c.get()}");        // count = 3
    print(f"5^2 = {Math.square(5)}");   // 5^2 = 25
    return 0;
}
```

## Generics & Collections

`List<T>`, `Map<K,V>`, `Set<T>`, and `Array<T>` with for-in iteration. User-defined generic classes are also supported.

```
int main() {
    List<int> nums = [10, 20, 30];
    int sum = 0;
    for x in nums {
        sum += x;
    }
    print(f"sum = {sum}");  // sum = 60

    Map<string, int> ages = {};
    ages.put("alice", 30);
    ages.put("bob", 25);
    for name, age in ages {
        print(f"{name}: {age}");
    }

    Set<int> s = {1, 2, 3};
    s.add(4);
    print(f"contains 2: {s.contains(2)}");  // contains 2: true
    return 0;
}
```

User-defined generic classes:

```
class Pair<A, B> {
    public A first;
    public B second;

    public Pair(A first, B second) {
        self.first = first;
        self.second = second;
    }
}

int main() {
    var p = Pair<string, int>("age", 30);
    print(f"{p.first}: {p.second}");  // age: 30
    return 0;
}
```

## Interfaces & Abstract Classes

Interfaces define contracts. Abstract classes provide partial implementations.

```
interface Printable {
    string toString();
}

abstract class Shape implements Printable {
    public abstract float area();

    public string toString() {
        return f"Shape(area={self.area()})";
    }
}

class Circle extends Shape {
    public float radius;
    public Circle(float r) { self.radius = r; }
    public float area() { return 3.14159 * self.radius * self.radius; }
}

int main() {
    var c = Circle(5.0);
    print(c.toString());  // Shape(area=78.539749)
    return 0;
}
```

## Enums

Enums with `toString()` and rich enums with associated values.

```
enum Color { Red, Green, Blue }

enum Shape {
    Circle(float radius),
    Rect(float w, float h)
}

int main() {
    Color c = Color.Green;
    print(c.toString());  // Green

    Shape s = Shape.Circle(5.0);
    match (s) {
        Circle(r) => print(f"circle r={r}"),
        Rect(w, h) => print(f"rect {w}x{h}")
    }
    return 0;
}
```

## Inheritance

Classes extend other classes. Methods override naturally.

```
class Animal {
    public string name;
    public int age;

    public Animal(string name, int age) {
        self.name = name;
        self.age = age;
    }

    public string speak() { return "..."; }
}

class Dog extends Animal {
    public string breed;

    public Dog(string name, int age, string breed) {
        self.name = name;
        self.age = age;
        self.breed = breed;
    }

    public string speak() { return "Woof!"; }
}

int main() {
    var rex = Dog("Rex", 5, "Shepherd");
    print(f"{rex.name} says {rex.speak()}");  // Rex says Woof!
    return 0;
}
```

## Lambdas & Closures

First-class functions with variable capture.

```
int main() {
    List<int> nums = [3, 1, 4, 1, 5];

    // Filter and map with lambdas
    var evens = nums.filter((int x) => x % 2 == 0);
    var doubled = nums.map((int x) => x * 2);

    // Closures capture variables
    int factor = 10;
    var scaled = nums.map((int x) => x * factor);

    return 0;
}
```

## Tuples

Lightweight grouping of values.

```
int main() {
    (int, string) pair = (42, "hello");
    print(f"{pair.0}: {pair.1}");  // 42: hello

    // Tuple unpacking
    var (x, y) = (10, 20);
    print(f"{x} + {y} = {x + y}");  // 10 + 20 = 30
    return 0;
}
```

## Properties

Computed getters and setters.

```
class Temperature {
    private float celsius;

    public Temperature(float c) { self.celsius = c; }

    public float fahrenheit {
        get { return self.celsius * 1.8 + 32.0; }
        set { self.celsius = (value - 32.0) / 1.8; }
    }
}

int main() {
    var t = Temperature(100.0);
    print(f"{t.fahrenheit}");   // 212.000000
    t.fahrenheit = 32.0;
    print(f"{t.celsius}");      // 0.000000
    return 0;
}
```

## Nullable Types & Type Inference

Safe nullable types and `var` for type inference.

```
int main() {
    int? maybe = 42;
    if (maybe != null) {
        print(f"got {maybe}");
    }

    var name = "btrc";       // inferred as string
    var nums = [1, 2, 3];    // inferred as List<int>
    return 0;
}
```

## Error Handling

`try`/`catch`/`finally`/`throw` with string exceptions.

```
class Account {
    public string owner;
    public int balance;

    public Account(string owner, int balance = 0) {
        self.owner = owner;
        self.balance = balance;
    }

    public void withdraw(int amount) {
        if (amount > self.balance) {
            throw "insufficient funds";
        }
        self.balance -= amount;
    }
}

int main() {
    var acct = Account("Alice", 100);
    try {
        acct.withdraw(200);
    } catch (string e) {
        print(f"Error: {e}");  // Error: insufficient funds
    } finally {
        print("done");
    }
    return 0;
}
```

## F-Strings

Interpolated string expressions with format specifiers.

```
int main() {
    int x = 42;
    float pi = 3.14159;
    print(f"x = {x}, pi = {pi:.2f}");  // x = 42, pi = 3.14
    print(f"hex: {x:x}");               // hex: 2a
    print(f"literal braces: {{escaped}}"); // literal braces: {escaped}
    return 0;
}
```

## Operator Overloading

Define `+`, `-`, `*`, `/`, `==`, `<`, and other operators for your types.

```
class Vec2 {
    public float x;
    public float y;

    public Vec2(float x, float y) { self.x = x; self.y = y; }

    public Vec2 __add__(Vec2 other) {
        return Vec2(self.x + other.x, self.y + other.y);
    }
}

int main() {
    var a = Vec2(1.0, 2.0);
    var b = Vec2(3.0, 4.0);
    var c = a + b;
    print(f"({c.x}, {c.y})");  // (4.000000, 6.000000)
    return 0;
}
```

## Range & Iteration

`range()` with start, end, and step.

```
int main() {
    for i in range(5) {
        print(f"{i}");  // 0, 1, 2, 3, 4
    }

    for i in range(0, 10, 2) {
        print(f"{i}");  // 0, 2, 4, 6, 8
    }
    return 0;
}
```

## Memory Model

Classes are value types (C structs). No garbage collector — you allocate and free explicitly.

- **Stack**: `Counter c = Counter();` — lives on the stack, freed automatically when scope ends
- **Heap**: `Node* n = new Node(42);` — lives on the heap, you call `delete n;` when done
- **Pointers**: `Node*` is a pointer to a heap-allocated `Node`, accessed with `->`
- **Destructors**: `__del__()` methods let you clean up owned resources

```
class Node {
    public int value;
    public Node* next;

    public Node(int value) {
        self.value = value;
        self.next = null;
    }
}

class LinkedList {
    public Node* head = null;
    public int size = 0;

    public void append(int value) {
        Node* node = new Node(value);
        if (self.head == null) {
            self.head = node;
        } else {
            Node* curr = self.head;
            while (curr->next != null) {
                curr = curr->next;
            }
            curr->next = node;
        }
        self.size++;
    }

    public void __del__() {
        while (self.head != null) {
            Node* old = self.head;
            self.head = self.head->next;
            delete old;
        }
    }
}

int main() {
    var list = LinkedList();
    list.append(10);
    list.append(20);
    list.append(30);
    print(f"size: {list.size}");  // size: 3
    list.__del__();
    return 0;
}
```

btrc gives you C's performance and control with a cleaner syntax. There's no hidden runtime, no GC pauses, no reference counting — just straightforward `new`/`delete` and stack allocation.

## Standard Library

| Module | Description |
|--------|-------------|
| `math.btrc` | Math functions, constants, Vec2/Vec3 |
| `strings.btrc` | String utilities (split, trim, replace, etc.) |
| `collections.btrc` | Stack, Queue, PriorityQueue |
| `io.btrc` | File I/O, Path utilities |
| `datetime.btrc` | Date/time types and formatting |
| `random.btrc` | Random number generation |
| `error.btrc` | Error types (ValueError, IOError, TypeError) |
| `console.btrc` | Console I/O (readLine, print, error) |

Include with `#include "stdlib/math.btrc"`.

## Project Structure

```
btrc.py              # CLI entry point
Makefile             # Build, test, lint, extension targets
src/
  compiler/
    python/          # Python-based transpiler (lexer, parser, analyzer, codegen)
    btrc/            # Self-hosted compiler (written in btrc)
  stdlib/            # Standard library
  tests/             # Integration tests with golden file comparison
    expected/        # Expected output golden files
devex/
  lsp/               # Language server (diagnostics, completion, hover, go-to-def, references)
  ext/               # VS Code extension
.devcontainer/       # Dev container setup
```

## Development

```bash
make test              # Run Python compiler tests + btrc integration tests
make test-all          # Run all tests including self-hosted compiler tests
make lint              # Run ruff linter
make format            # Run ruff formatter
make build             # Build self-hosted compiler
make bootstrap         # Full self-hosted bootstrap (stage 2 verification)
make generate-expected # Regenerate golden expected output files
make install-ext       # Build + install VS Code extension
make package-ext       # Package extension as .vsix
make clean             # Clean build artifacts
```

## Self-Hosted Compiler

btrc has a self-hosted compiler written in btrc itself (`src/compiler/btrc/`). The bootstrap chain verifies correctness:

1. **Stage 1**: Python compiler compiles the btrc compiler source → native binary
2. **Stage 2**: Stage 1 binary compiles its own source → second native binary
3. **Verification**: Stage 2 binary compiles and runs a test program

```bash
make bootstrap    # Run the full bootstrap chain
```

## VS Code Extension

The btrc VS Code extension provides syntax highlighting, diagnostics, code completion, hover info, go-to-definition, references, signature help, and semantic tokens.

```bash
make install-ext    # Build and install to VS Code
```

Or manually:

```bash
cd devex/ext
npm install
npm run install-ext
```

## Dev Container

The `.devcontainer/` directory contains a full dev container setup with Claude Code, firewall, SSH agent forwarding, and credential management. Edit `.devcontainer/project.json` to configure project-specific settings (setup commands, firewall domains, VSCode extensions).
