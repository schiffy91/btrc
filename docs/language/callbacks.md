# Callback representations

BTRC has two deliberately different callback representations.

`CFunction<Result, Parameters...>` is one exact C function-pointer word.  Its
result, parameter count, pointer depth, and `const` qualifiers are part of the
type.  It carries no context and therefore accepts only named functions and
noncapturing lambdas.  The hosted-ABI manifest records whether each C callback
parameter is borrowed for the call or stored until unregister.

`OwnedClosure<CFunction<...>>` is an ARC-managed owner for a callback that must
outlive one call.  It contains an exact invoke pointer, an opaque context, and
one context destroy callback.  Aliases and fields retain the same owner;
`close()` and final ARC destruction invoke the context destroy callback at most
once.  The invoke signature remains exactly as written, so a caller passes the
stored context in the position required by the external C API.

An external registration has a stricter lifetime boundary than an owned
closure alone.  Its owner must close callback admission, call the external
unregister operation, drain callbacks that entered before admission closed,
and only then close the `OwnedClosure`.  A raw callback context must never
outlive that sequence.
