package javax.annotation;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

/** A stand-in for JSR-305's javax.annotation.CheckForNull (see Nonnull). */
@Retention(RetentionPolicy.RUNTIME)
public @interface CheckForNull {
}
