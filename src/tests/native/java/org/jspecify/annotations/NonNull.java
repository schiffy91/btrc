package org.jspecify.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * A stand-in for JSpecify's NonNull: a type annotation kept at run time, so
 * javac writes it in RuntimeVisibleTypeAnnotations with a type path
 * (src/tests/python/test_java_class_reader.py).
 */
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE_USE)
public @interface NonNull {
}
