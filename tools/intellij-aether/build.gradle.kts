plugins {
    kotlin("jvm") version "2.2.21"
    id("org.jetbrains.intellij.platform") version "2.16.0"
}

group = "com.aetherstudio"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    intellijPlatform {
        intellijIdea("2026.1")
    }
    testImplementation(kotlin("test-junit5"))
}

tasks {
    test {
        useJUnitPlatform()
    }
}

intellijPlatform {
    pluginConfiguration {
        name = "Aether"
        version = project.version.toString()
        ideaVersion {
            sinceBuild = "261"
        }
    }
}
