package javax.annotation;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import javax.annotation.meta.When;

/**
 * A stand-in for JSR-305's javax.annotation.Nonnull: kept at run time,
 * applicable to declarations only, and qualified by `when`
 * (src/tests/python/test_java_class_reader.py).
 */
@Retention(RetentionPolicy.RUNTIME)
public @interface Nonnull {
    When when() default When.ALWAYS;
}
