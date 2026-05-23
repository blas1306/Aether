pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

rootProject.name = "AetherStudio"
include(":tools:intellij-aether")
project(":tools:intellij-aether").projectDir = file("tools/intellij-aether")
