pluginManagement { repositories { mavenCentral(); google(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        val getuiCache = file("../build/toolchains/getui-maven")
        if (getuiCache.isDirectory) {
            maven {
                url = uri(getuiCache)
                content { includeGroup("com.getui"); includeGroup("com.zxid.sdk") }
                metadataSources { mavenPom(); artifact(); ignoreGradleMetadataRedirection() }
            }
        }
        mavenCentral()
        google()
        maven {
            url = uri("https://mvn.getui.com/nexus/content/repositories/releases/")
            content { includeGroupByRegex("com\\.getui.*"); includeGroup("com.zxid.sdk") }
        }
    }
}
rootProject.name = "FamilyElder"
include(":app")
