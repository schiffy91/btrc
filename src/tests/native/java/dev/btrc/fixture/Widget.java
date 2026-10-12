package dev.btrc.fixture;

import java.io.File;

/**
 * The class reader's main fixture (src/tests/python/test_java_class_reader.py):
 * every member kind, access flag and descriptor shape the reader reports or
 * hides, including the bridge method javac adds for Comparable<Widget>.
 */
public class Widget extends Base implements Shape, Comparable<Widget> {
    public static final int LIMIT = 42;
    public static final long BIG = 1L << 40;
    public static final double RATIO = 0.5;
    /* A string constant may hold NUL and a lone surrogate; a name may not. */
    public static final String NAME = "fix\u0000ture\uD800";
    public static String label = "widget";
    public final long id;
    public double weight;
    public int[][] grid;
    protected int guarded;
    int packaged;
    private int secret;

    public Widget() {
        this("", new int[0]);
    }

    public Widget(String name, int[] sizes) {
        this.id = sizes.length + secret;
    }

    private Widget(long id) {
        this.id = id;
    }

    public static int add(int left, int right) {
        return left + right;
    }

    public String describe(Object other, String[][] names, boolean flag, byte b, char c, short s, long l, float f,
            double d) {
        return String.valueOf(other) + names.length + flag + b + c + s + l + f + d;
    }

    public native void poke(File file);

    public static Widget[] many(int count) {
        return new Widget[count];
    }

    public void run(Runnable task) {
        Runnable wrapped = () -> task.run();
        wrapped.run();
    }

    public int compareTo(Widget other) {
        return Long.compare(id, other.id);
    }

    public double area() {
        return weight;
    }

    public void reset() {
        weight = 0;
    }

    private void hidden() {
    }

    public static class Inner {
        public int value;

        public Inner(int value) {
            this.value = value;
        }
    }

    protected static class Guarded {
    }

    private static class Secret {
    }
}
