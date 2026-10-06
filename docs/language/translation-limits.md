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

Both compilers keep a graph of type-parameter uses, as Go does for generic
instantiation cycles. Each type parameter a reached declaration has is a node,
such as `Chain.T`. A use that passes a parameter to a generic adds an edge to
that generic's parameter; the use *grows* when it wraps the parameter
(`(T, int)`, `Vector<T>`, `T*`, `T[]`, `T?`) rather than passing it bare. A
use in a generic method that names the method's own type parameters holds
only once the method is specialized, so the method's parameters, its class's
included, are nodes of their own (`Walker.walk.U`), and a call to it passes
its arguments into them. A use there that names only the class's parameters
is specialized with every class instance, so it is the class's. A cycle of
edges that
contains a growing use nests one more level on every pass, so it never ends.
Once specialization finds such a cycle it admits no further derived
specialization, and both compilers report one diagnostic at the growing use on
a cycle that comes first in source:

```text
error: Generic class 'Chain' grows its own type arguments through this use, so its specializations never end
```

The rule depends on the uses alone, so it fires once each declaration on the
cycle has been reached, however many growing uses a declaration has. Deep but
finite nesting is unaffected: a class whose fields reuse its own argument
(`Tree<T>? left`), a fixed one (`Tree<Vector<int>>? fixed`), or wrap a
parameter outside any cycle (`Box<Vector<T>>` inside `Tree<T>`, when `Box`
never uses `Tree`) compiles, as do written-out types such as
`Vector<Vector<Vector<int>>>`.

## Nesting backstop

A specialization reached through recursive instantiation whose type arguments
nest deeper than 32 levels (each generic argument, pointer and array level
counts) is also refused, as a backstop:

```text
error: Generic class 'Box' needs type arguments nested deeper than 32 levels, the limit that keeps specialization finite
```

The value is `limits.generic_argument_nesting` in
`src/language/hosted_abi.toml`, generated into both compilers. A type the
program writes out is not limited, however deep.
