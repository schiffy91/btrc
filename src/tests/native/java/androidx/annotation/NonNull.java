package androidx.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * A stand-in with androidx.annotation.NonNull's retention and targets, so
 * javac writes it where the real one goes: RuntimeInvisibleAnnotations and
 * RuntimeInvisibleParameterAnnotations (src/tests/python/test_java_class_reader.py).
 */
@Retention(RetentionPolicy.CLASS)
@Target({ElementType.METHOD, ElementType.PARAMETER, ElementType.FIELD, ElementType.LOCAL_VARIABLE,
        ElementType.ANNOTATION_TYPE, ElementType.PACKAGE})
public @interface NonNull {
}
