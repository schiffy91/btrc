plugins {
    id("com.android.application") version "9.4.0"
}

android {
    namespace = "dev.btrc.testhost"
    compileSdk = 36
    buildToolsVersion = providers.gradleProperty("btrcBuildTools").get()
    ndkVersion = providers.gradleProperty("btrcNdk").get()
    defaultConfig {
        applicationId = providers.gradleProperty("btrcPackage").get()
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "1"
        ndk { abiFilters += providers.gradleProperty("btrcAbi").getOrElse("x86_64") }
    }
    sourceSets.getByName("main").jniLibs.srcDir(providers.gradleProperty("btrcJniLibs").get())
}
layout.buildDirectory = file(providers.gradleProperty("btrcBuildDir").get())
