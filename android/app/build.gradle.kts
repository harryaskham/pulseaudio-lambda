plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "org.pulseaudiolambda"
    compileSdk = 34
    buildToolsVersion = "34.0.0"

    defaultConfig {
        applicationId = "org.pulseaudiolambda"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
        ndk {
            // Limit to 64-bit which most devices require; reduces APK size.
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildFeatures {
        viewBinding = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    // Avoid compressing large model assets so first-run copy is faster
    androidResources {
        noCompress += setOf("pt", "ptl", "pte")
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.10.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.9.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Coroutines for background audio processing
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // PyTorch mobile runtime
    // Upgrade to PyTorch Android 2.1 for newer ops like aten::rms_norm
    implementation("org.pytorch:pytorch_android:2.1.0")
}
