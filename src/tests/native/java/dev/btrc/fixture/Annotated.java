package dev.btrc.fixture;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import javax.annotation.CheckForNull;
import javax.annotation.Nonnull;
import javax.annotation.meta.When;

/**
 * Reader v2's declaration annotations and natives
 * (src/tests/python/test_java_class_reader.py): androidx keeps NonNull and
 * Nullable in the class file only, JSR-305 keeps its own at run time and
 * qualifies Nonnull by `when`. A declaration annotation marks the declared
 * type itself, so `tags` is a nonnull array of nullable strings, and one on a
 * primitive marks nothing. The natives cover every access: --native reports
 * them all, --symbol only the public one.
 */
public class Annotated {
    public @NonNull String name = "";
    public @Nullable String alias;
    public @NonNull String[] tags = {};
    public @NonNull int count;
    public @Nonnull String code = "";
    public @Nonnull(when = When.MAYBE) String maybe;
    public @Nonnull(when = When.UNKNOWN) String unknown;
    public @CheckForNull String checked;
    public @NonNull @Nullable String conflicted;

    public Annotated(@NonNull String name) {
        this.name = name;
    }

    public static @NonNull Annotated create(@NonNull String name, @Nullable String alias, int count) {
        return new Annotated(name);
    }

    public @Nonnull String describe(@Nonnull(when = When.NEVER) Object other, @Nonnull Object[] more,
            @javax.annotation.Nullable String note) {
        return "";
    }

    public native @NonNull String peek(@NonNull Annotated other);

    private native void poke(@NonNull String text);

    private static native int tally();

    protected native void guard();

    native void share();

    private void hidden() {
    }
}
