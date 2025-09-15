plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "org.pulseaudiolambda"
    compileSdk = 33

    defaultConfig {
        applicationId = "org.pulseaudiolambda"
        minSdk = 29
        targetSdk = 33
        versionCode = 1
        versionName = "0.1"
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
}

dependencies {
    implementation("androidx.core:core-ktx:1.10.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.9.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // PyTorch mobile runtime
    implementation("org.pytorch:pytorch_android_lite:1.12.2")
    implementation("org.pytorch:pytorch_android_torchvision:1.12.2")
}
