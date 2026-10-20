import java.util.Properties

plugins {
    id("com.android.application")
}

// Version passée par build-apk.ps1 (-PappVersion=1.2.3), sinon celle du fichier VERSION ; versionCode = 10203.
val appVersion = (findProperty("appVersion") as String?) ?: rootProject.file("../VERSION").readText().trim()
val appVersionCode = appVersion.split(".").mapNotNull { it.toIntOrNull() }.let { parts ->
    require(parts.size == 3) { "appVersion attendue au format x.y.z, reçu « $appVersion »" }
    parts[0] * 10000 + parts[1] * 100 + parts[2]
}

// Clé de signature locale, créée par build-apk.ps1 (à sauvegarder : sans elle, plus de mise à jour possible).
val keystore = Properties().apply {
    val file = rootProject.file("keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "local.telecommande.arcom"
    compileSdk = 36

    defaultConfig {
        applicationId = "local.telecommande.arcom"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersion
    }

    signingConfigs {
        if (keystore.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystore.getProperty("storeFile"))
                storePassword = keystore.getProperty("storePassword")
                keyAlias = keystore.getProperty("keyAlias")
                keyPassword = keystore.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    // Robolectric : l'écran, les widgets et le service tournent sur le vrai framework, sur la JVM.
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.17")
}
