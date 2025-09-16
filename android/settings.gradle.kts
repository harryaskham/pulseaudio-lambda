pluginManagement {
    repositories {
        // Prefer Google + Maven Central for Android + Kotlin plugins
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "PulseAudioLambdaAndroid"
include(":app")
