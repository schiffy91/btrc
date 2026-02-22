# btrc

A modern language that transpiles to C. Write expressive, object-oriented code that compiles to efficient native binaries.

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

`List<T>`, `Map<K,V>`, and `Set<T>` with for-in iteration.

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

## Error Handling

`try`/`catch`/`throw` with default parameters.

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
    }
    return 0;
}
```

## Pointers & Memory

Heap allocation with `new`/`delete`, pointer types, and destructors.

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

## Project Structure

```
btrc.py              # CLI entry point
Makefile             # Build, test, lint, extension targets
src/
  compiler/
    python/          # Python-based transpiler (lexer, parser, analyzer, codegen)
    btrc/            # Self-hosted compiler (written in btrc)
  stdlib/            # Standard library (math, io, strings, collections, datetime, random)
  tests/             # Integration tests
devex/
  lsp/               # Language server (diagnostics, completion, hover, go-to-def, references)
  ext/               # VS Code extension
.devcontainer/       # Dev container setup (project.json for per-project config)
```

## Development

```bash
make test           # Run all tests (~990 tests)
make lint           # Run ruff linter
make build          # Build self-hosted compiler
make bootstrap      # Full self-hosted bootstrap (stage 2 verification)
make install-ext    # Build + install VS Code extension
make package-ext    # Package extension as .vsix
make clean          # Clean build artifacts
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
