plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "cn.familyguard.elder"
    compileSdk = 35
    defaultConfig {
        applicationId = "cn.familyguard.elder"
        minSdk = 26
        targetSdk = 35
        versionCode = 8
        versionName = "0.1.7"
        manifestPlaceholders["GETUI_APPID"] = "NtGxfjmcjPAb27hjz2R1e1"
        buildConfigField("String", "GETUI_APP_ID", "\"NtGxfjmcjPAb27hjz2R1e1\"")
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("com.getui:gtsdk:3.3.16.0")
    implementation("com.getui:gtc:3.3.3.0")
}
