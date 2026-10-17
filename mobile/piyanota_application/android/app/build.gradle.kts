plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

/** Present once the LAME 3.100 release sources are vendored. */
val LAME_MARKER = "src/main/cpp/lame/libmp3lame/lame.c"

android {
    namespace = "com.piyanota.piyanota_application"
    // permission_handler_android requires SDK 37; flutter.compileSdkVersion (36) is behind it.
    compileSdk = 37
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.piyanota.piyanota_application"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // PIYA-211: LAME 3.100 (MP3 encoding for Export Audio) is built from
    // vendored sources. Without them the app still builds, but export
    // fails with generation_failed, so warn loudly rather than silently.
    if (file(LAME_MARKER).exists()) {
        externalNativeBuild {
            cmake {
                path = file("src/main/cpp/CMakeLists.txt")
                version = "3.22.1"
            }
        }
    } else {
        logger.warn(
            "WARNING: LAME 3.100 sources not found at app/$LAME_MARKER. " +
                "Export Audio will fail until lame-3.100.tar.gz is unpacked into " +
                "app/src/main/cpp/lame (see THIRD_PARTY_NOTICES.md).",
        )
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

dependencies {
    // Sonic time-stretch for the export (FR-9 pitch kept). Already in the
    // APK through just_audio's ExoPlayer, and Gradle resolves both to the
    // higher version, so the export always runs Playback's Sonic. Declared
    // at the version just_audio brings in (check with `gradlew
    // :app:dependencies`), so this line says what actually ships.
    implementation("androidx.media3:media3-common:1.9.0")

    // JVM tests of the export mixer (Sonic runs on the plain JVM).
    testImplementation("junit:junit:4.13.2")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
