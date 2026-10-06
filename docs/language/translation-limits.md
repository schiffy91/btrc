# Translation limits

btrc compiles generics by monomorphization: every specialization a program
needs, `Vector<int>` or `Map<string, Vector<(int, string)>>`, becomes its own
C code. That process has to end, so both compilers refuse a program whose
specializations would never stop growing, as C++ bounds template
instantiation. C11 5.2.4.1 sets C's own translation limits; this page states
btrc's.

## Growing specializations

A specialization that needs a larger specialization of itself, through a
cycle of uses, has no finite expansion:

```btrc
class Chain<T> {
    public T value;
    public Chain<(T, int)>? next = null;   // Chain<int> needs Chain<(int, int)>, which needs ...
    public Chain(T value) { self.value = value; }
}
```

The same happens through a generic method that calls itself with a larger
argument (`self.walk((item, depth), depth - 1)` inside `walk<U>`), through a
collection (`Nest<Vector<T>>?` inside `Nest<T>`), and through two classes that
specialize each other (`Left<T>` holding `Right<(T, int)>`, `Right<T>` holding
`Left<T>`).

Each derived specialization remembers the use that named it and the
specialization being expanded at the time. When a use that already appears in
a specialization's own derivation produces one with deeper type arguments,
that use grows without bound. Both compilers then report one diagnostic at that
use and stop specializing:

```text
error: Generic class 'Chain' grows its own type arguments through this use, so its specializations never end
```

The rule fires after a few steps, however many growing uses a declaration
has. Deep but finite nesting is unaffected: a class whose fields reuse its own
argument (`Tree<T>? left`) or a fixed one (`Tree<Vector<int>>? fixed`)
compiles, as do written-out types such as `Vector<Vector<Vector<int>>>`.

## Nesting backstop

A specialization reached through recursive instantiation whose type arguments
nest deeper than 32 levels is also refused, as a backstop:

```text
error: Generic class 'Box' needs type arguments nested deeper than 32 levels, the limit that keeps specialization finite
```

The value is `limits.generic_argument_nesting` in
`src/language/hosted_abi.toml`, generated into both compilers. A type the
program writes out is not limited, however deep.
