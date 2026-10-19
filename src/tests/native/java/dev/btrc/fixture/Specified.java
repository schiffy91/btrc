package dev.btrc.fixture;

import java.util.List;
import org.jspecify.annotations.NonNull;
import org.jspecify.annotations.Nullable;

/**
 * Reader v2's type annotations (src/tests/python/test_java_class_reader.py):
 * JSpecify's NonNull and Nullable are TYPE_USE only, so their type paths
 * choose an array level or, through the InnerClasses entries, the nested
 * type they mark. `inner` marks the inner class itself and `outerMarked` only
 * its enclosing type; a type argument is not modelled.
 */
public class Specified {
    public @NonNull String name = "";
    public @Nullable String @NonNull [] names = {};
    public String @Nullable [] @NonNull [] grid;
    public Specified.@NonNull Holder holder;
    public Specified.@NonNull Inner inner;
    public @NonNull Specified.Inner outerMarked;
    public List<@NonNull String> list;

    public @NonNull String label(@Nullable Object key, @NonNull Holder holder) {
        return "";
    }

    public <T> @NonNull T first(T @NonNull [] values) {
        return values[0];
    }

    public static class Holder {
    }

    public class Inner {
        public Inner(@NonNull String first, @Nullable String second) {
        }
    }
}
