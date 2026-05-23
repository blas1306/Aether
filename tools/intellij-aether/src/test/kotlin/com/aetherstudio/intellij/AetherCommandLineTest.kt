package com.aetherstudio.intellij

import kotlin.io.path.createTempDirectory
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

class AetherCommandLineTest {
    @Test
    fun `file type is ae`() {
        assertEquals("Aether", AetherFileType.name)
        assertEquals("ae", AetherFileType.defaultExtension)
    }

    @Test
    fun `configured command wins`() {
        assertEquals(
            "python3.14",
            AetherCommandLine.pythonExecutable("/tmp/project", " python3.14 "),
        )
    }

    @Test
    fun `configured python path wins when executable exists`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val python = projectDir.resolve("bin/python")
        python.parentFile.mkdirs()
        python.writeText("")
        python.setExecutable(true)

        assertEquals(
            python.path,
            AetherCommandLine.pythonExecutable(projectDir.path, " bin/python "),
        )
    }

    @Test
    fun `broken configured python path falls back to project venv`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val python = projectDir.resolve(".venv/bin/python")
        python.parentFile.mkdirs()
        python.writeText("")
        python.setExecutable(true)

        assertEquals(
            python.path,
            AetherCommandLine.pythonExecutable(projectDir.path, " /missing/aether/python "),
        )
    }

    @Test
    fun `repo venv python is preferred`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val python = projectDir.resolve(".venv/bin/python")
        python.parentFile.mkdirs()
        python.writeText("")
        python.setExecutable(true)

        assertEquals(python.path, AetherCommandLine.pythonExecutable(projectDir.path, ""))
    }

    @Test
    fun `fallback python is python3`() {
        assertEquals("python3", AetherCommandLine.pythonExecutable(null, ""))
    }

    @Test
    fun `lsp command arguments target python language server`() {
        assertEquals(listOf("-m", "aether_lsp.server", "--stdio"), AetherCommandLine.lspArguments())
    }

    @Test
    fun `run file arguments target aether runner bridge`() {
        assertEquals(
            listOf("-m", "aether_lsp.run_file", "/tmp/example.ae"),
            AetherCommandLine.runFileArguments("/tmp/example.ae"),
        )
    }

    @Test
    fun `plugin xml registers aether surface`() {
        val resource = javaClass.classLoader.getResource("META-INF/plugin.xml")
        assertNotNull(resource)
        val xml = resource.readText()

        assertContains(xml, "extensions=\"ae\"")
        assertContains(xml, "Aether.RunFile")
        assertContains(xml, "lang.parserDefinition")
        assertContains(xml, "runLineMarkerContributor")
        assertContains(xml, "configurationType")
        assertContains(xml, "runConfigurationProducer")
        assertContains(xml, "EditorPopupMenu")
        assertContains(xml, "lsp.serverSupportProvider")
        assertContains(xml, "toolWindow id=\"Aether\"")
    }
}
