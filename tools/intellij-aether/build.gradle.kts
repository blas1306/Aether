plugins {
    kotlin("jvm") version "2.2.21"
    id("org.jetbrains.intellij.platform") version "2.16.0"
}

group = "com.aetherstudio"
val aetherPackageVersion = rootProject.file("src/aether/version.py")
    .readLines()
    .first { it.startsWith("PACKAGE_VERSION = ") }
    .substringAfter('"')
    .substringBeforeLast('"')
version = aetherPackageVersion.replace(Regex("rc([0-9]+)$"), "-rc.$1")

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

    val seedRunIdeHighContrastSettings by registering {
        val optionsDir = rootProject.layout.projectDirectory.dir(
            ".intellijPlatform/sandbox/intellij-aether/IU-2026.1/config/options"
        )
        outputs.upToDateWhen { false }

        doLast {
            val dir = optionsDir.asFile
            dir.mkdirs()
            dir.resolve("colors.scheme.xml").writeText(
                """
                <application>
                  <component name="EditorColorsManagerImpl">
                    <global_color_scheme name="High contrast" />
                  </component>
                </application>
                """.trimIndent()
            )
            dir.resolve("laf.xml").writeText(
                """
                <application>
                  <component name="LafManager">
                    <laf themeId="JetBrainsHighContrastTheme" />
                  </component>
                </application>
                """.trimIndent()
            )
        }
    }

    named("runIde") {
        dependsOn(seedRunIdeHighContrastSettings)
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
