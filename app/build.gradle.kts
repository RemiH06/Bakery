plugins {
    id("com.android.application") version "9.3.3"
}

android {
    namespace = "dev.remlam.bakery"
    compileSdk { version = release(36) { minorApiLevel = 1 } }

    defaultConfig {
        applicationId = "dev.remlam.bakery"
        minSdk = 34
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }
    buildTypes {
        release {
            optimization { enable = true }
            // Solo se instala por adb en el teléfono de quien la compila: basta la llave de depuración de su máquina
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.work:work-runtime:2.11.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20260814")  // en Android ya viene; en la JVM de pruebas es un hueco
}
