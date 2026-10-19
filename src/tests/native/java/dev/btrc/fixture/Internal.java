package dev.btrc.fixture;

/**
 * A package-private class: the reader reports it as unknown, and its public
 * member class with it, since a member class is visible only through visible
 * enclosing classes.
 */
class Internal {
    public static int value() {
        return 1;
    }

    public static class Exposed {
        public static int value() {
            return 2;
        }
    }
}
