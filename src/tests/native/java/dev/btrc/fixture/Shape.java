package dev.btrc.fixture;

/** An interface: its abstract, default and static methods and its constant. */
public interface Shape {
    int SIDES = 0;

    double area();

    default String kind() {
        return "shape";
    }

    static Shape unit() {
        return null;
    }
}
