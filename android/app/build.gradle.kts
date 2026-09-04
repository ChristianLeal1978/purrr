import java.util.Properties

plugins {
    id("com.android.application")
    // Sin org.jetbrains.kotlin.android: AGP 9 trae soporte de Kotlin integrado
    // ("built-in Kotlin") — aplicar el plugin viejo además choca con la extensión
    // "kotlin" que AGP ya registra solo.
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.google.devtools.ksp")
}

// Firma de release (para subir a Play Console) — el keystore y sus contraseñas
// viven en keystore.properties, gitignoreado (ver android/.gitignore). Si el
// archivo no existe (ej. un clon nuevo del repo en otra máquina), el build de
// release simplemente queda sin firmar en vez de romperse.
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) load(keystorePropertiesFile.inputStream())
}

android {
    namespace = "io.github.christianlealreyes.purrr"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.christianlealreyes.purrr"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "0.1.0"
    }

    signingConfigs {
        if (keystorePropertiesFile.exists()) {
            create("release") {
                storeFile = rootProject.file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        // El "built-in Kotlin" de AGP 9 toma jvmTarget de acá — no hace falta un
        // bloque kotlin.compilerOptions aparte para este caso simple.
    }

    buildFeatures {
        compose = true
    }

    sourceSets {
        getByName("main") {
            kotlin.srcDirs("src/main/kotlin")
        }
    }
}

dependencies {
    // --- Compose ---------------------------------------------------------
    implementation(platform("androidx.compose:compose-bom:2026.08.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.navigation:navigation-compose:2.10.0")
    implementation("androidx.core:core-ktx:1.19.0")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // --- Login de Google + acceso a Drive (Fase 6.3 del plan) -------------
    implementation("androidx.credentials:credentials:1.6.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.6.0")
    implementation("com.google.android.gms:play-services-auth:22.0.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.2.0")

    // --- Login de Spotify (PKCE manual, Fase 7.2 del plan) -----------------
    implementation("androidx.browser:browser:1.10.0")

    // --- Supabase (mismo backend/schema que el escritorio) ----------------
    implementation(platform("io.github.jan-tennert.supabase:bom:3.1.4"))
    implementation("io.github.jan-tennert.supabase:auth-kt")
    implementation("io.github.jan-tennert.supabase:postgrest-kt")
    implementation("io.github.jan-tennert.supabase:realtime-kt")
    // 3.2.0 tiene un bug real conocido: un campo con espacios en el nombre
    // ("use streaming syntax" en io.ktor.client.plugins.Messages) que rompe D8/R8
    // al generar DEX ("Space characters in SimpleName ... not allowed prior to DEX
    // version 040") — confirmado acá mismo al compilar. 3.1.3 no lo tiene.
    implementation("io.ktor:ktor-client-okhttp:3.1.3")

    // --- Room (cache local — espejo recortado del schema de escritorio) ---
    implementation("androidx.room:room-runtime:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    ksp("androidx.room:room-compiler:2.8.4")

    // --- Reproducción (Media3/ExoPlayer) -----------------------------------
    implementation("androidx.media3:media3-exoplayer:1.11.0")
    implementation("androidx.media3:media3-session:1.11.0")
    implementation("androidx.media3:media3-common:1.11.0")

    // --- HTTP (Drive REST) + serialización + imágenes ----------------------
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-guava:1.10.2")
    implementation("io.coil-kt.coil3:coil-compose:3.2.0")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.2.0")
}
