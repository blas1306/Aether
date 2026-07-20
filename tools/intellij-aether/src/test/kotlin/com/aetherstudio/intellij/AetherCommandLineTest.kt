package com.aetherstudio.intellij

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.util.JDOMExternalizerUtil
import org.jdom.Element
import java.io.File
import kotlin.io.path.createTempDirectory
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import com.intellij.testFramework.LightVirtualFile

class AetherCommandLineTest {
    @Test
    fun `file type is ae`() {
        assertEquals("Aether", AetherFileType.name)
        assertEquals("ae", AetherFileType.defaultExtension)
    }

    @Test
    fun `configured command name wins`() {
        assertEquals(
            "custom-aether",
            AetherCommandLine.resolveExecutable(
                "/tmp/project",
                " custom-aether ",
                AetherCommandLine.Executable.AETHER,
            ).executable,
        )
    }

    @Test
    fun `configured relative aether path wins when executable exists`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val executable = projectDir.resolve("bin/aether")
        executable.parentFile.mkdirs()
        executable.writeText("")
        executable.setExecutable(true)

        assertEquals(
            executable.path,
            AetherCommandLine.resolveExecutable(
                projectDir.path,
                " bin/aether ",
                AetherCommandLine.Executable.AETHER,
            ).executable,
        )
    }

    @Test
    fun `configured absolute aether path wins`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val executable = projectDir.resolve("tools/aether")
        executable.parentFile.mkdirs()
        executable.writeText("")
        executable.setExecutable(true)

        assertEquals(
            executable.path,
            AetherCommandLine.resolveExecutable(
                projectDir.path,
                executable.absolutePath,
                AetherCommandLine.Executable.AETHER,
            ).executable,
        )
    }

    @Test
    fun `broken configured path falls back to project venv`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val executable = projectDir.resolve(".venv/bin/aether")
        executable.parentFile.mkdirs()
        executable.writeText("")
        executable.setExecutable(true)

        val resolution = AetherCommandLine.resolveExecutable(
            projectDir.path,
            "/missing/aether",
            AetherCommandLine.Executable.AETHER,
            isWindows = false,
        )
        assertEquals(executable.path, resolution.executable)
        assertContains(resolution.warning.orEmpty(), "not executable")
    }

    @Test
    fun `project venv resolves aether and lsp separately`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val aether = executableFile(projectDir, ".venv/bin/aether")
        val lsp = executableFile(projectDir, ".venv/bin/aether-lsp")

        assertEquals(aether.path, resolve(projectDir, AetherCommandLine.Executable.AETHER).executable)
        assertEquals(lsp.path, resolve(projectDir, AetherCommandLine.Executable.LANGUAGE_SERVER).executable)
    }

    @Test
    fun `windows project venv resolves exe wrappers`() {
        val projectDir = createTempDirectory("aether-plugin-test").toFile()
        val aether = executableFile(projectDir, ".venv/Scripts/aether.exe")
        val lsp = executableFile(projectDir, ".venv/Scripts/aether-lsp.exe")

        assertEquals(aether.path, resolve(projectDir, AetherCommandLine.Executable.AETHER, true).executable)
        assertEquals(lsp.path, resolve(projectDir, AetherCommandLine.Executable.LANGUAGE_SERVER, true).executable)
    }

    @Test
    fun `fallback commands use PATH names`() {
        assertEquals("aether", resolve(null, AetherCommandLine.Executable.AETHER).executable)
        assertEquals("aether-lsp", resolve(null, AetherCommandLine.Executable.LANGUAGE_SERVER).executable)
    }

    @Test
    fun `broken configured path falls back to PATH with warning`() {
        val resolution = AetherCommandLine.resolveExecutable(
            "/tmp/project-without-venv",
            "/missing/aether",
            AetherCommandLine.Executable.AETHER,
            isWindows = false,
        )

        assertEquals("aether", resolution.executable)
        assertContains(resolution.warning.orEmpty(), "not executable")
        assertContains(resolution.warning.orEmpty(), "using 'aether'")
    }

    @Test
    fun `lsp arguments use stdio without python module`() {
        assertEquals(listOf("--stdio"), AetherCommandLine.lspArguments())
    }

    @Test
    fun `native and ast arguments are separate tokens`() {
        val path = "/tmp/project with spaces/example file.ae"
        assertEquals(
            listOf(path),
            AetherCommandLine.runFileArguments(path, AetherBackend.NATIVE),
        )
        assertEquals(listOf("--backend=ast", path), AetherCommandLine.runFileArguments(path, AetherBackend.AST))
    }

    @Test
    fun `check and emit arguments are exact separate tokens`() {
        val path = "/tmp/example.ae"
        assertEquals(listOf("--check", path), AetherCommandLine.checkFileArguments(path))
        assertEquals(listOf("--emit-ir", path), AetherCommandLine.emitIrArguments(path))
        assertEquals(listOf("--emit-ssa", path), AetherCommandLine.emitSsaArguments(path))
        assertEquals(listOf("--emit-llvm", path), AetherCommandLine.emitLlvmArguments(path))
    }

    @Test
    fun `working directory uses content root then project then external parent`() {
        val project = createTempDirectory("aether project").toFile()
        val module = project.resolve("module with spaces").apply { mkdirs() }
        val nestedFile = module.resolve("examples/demo file.ae").apply { parentFile.mkdirs(); writeText("") }
        val projectFile = project.resolve("root.ae").apply { writeText("") }
        val external = createTempDirectory("aether external").resolve("outside file.ae").toFile().apply { writeText("") }

        assertEquals(module.path, AetherCommandLine.workingDirectory(project.path, nestedFile.path, module.path))
        assertEquals(project.path, AetherCommandLine.workingDirectory(project.path, projectFile.path))
        assertEquals(external.parentFile.path, AetherCommandLine.workingDirectory(project.path, external.path))
    }

    @Test
    fun `backend defaults to native and rejects unknown persisted values`() {
        assertEquals(AetherBackend.NATIVE, AetherSettingsState.State().backend())
        assertEquals(AetherBackend.NATIVE, AetherBackend.fromPersistentValue(null))
        assertEquals(AetherBackend.NATIVE, AetherBackend.fromPersistentValue("legacy"))
        assertEquals(AetherBackend.AST, AetherBackend.fromPersistentValue("ast"))
    }

    @Test
    fun `legacy settings keep loading while python is ignored`() {
        @Suppress("DEPRECATION")
        val oldState = AetherSettingsState.State(pythonPath = "/old/python")
        val service = AetherSettingsState()
        service.loadState(oldState)

        assertEquals("", service.state.aetherExecutable)
        assertEquals("", service.state.languageServerExecutable)
        assertEquals(AetherBackend.NATIVE, service.state.backend())
    }

    @Test
    fun `run configuration serializes file and backend and legacy configuration is native`() {
        val serialized = Element("configuration")
        AetherRunConfigurationPersistence.write(serialized, "/tmp/example.ae", AetherBackend.AST)
        val restored = AetherRunConfigurationPersistence.read(serialized)

        assertEquals("/tmp/example.ae", restored.filePath)
        assertEquals(AetherBackend.AST, restored.backend)

        val legacy = Element("configuration")
        JDOMExternalizerUtil.writeField(legacy, "filePath", "/tmp/legacy.ae")
        val restoredLegacy = AetherRunConfigurationPersistence.read(legacy)
        assertEquals("/tmp/legacy.ae", restoredLegacy.filePath)
        assertEquals(AetherBackend.NATIVE, restoredLegacy.backend)
    }

    @Test
    fun `new aether file helper appends ae extension`() {
        assertEquals("demo.ae", AetherNewFileSupport.normalizeFileName("demo"))
    }

    @Test
    fun `new aether file helper preserves ae extension`() {
        assertEquals("demo.ae", AetherNewFileSupport.normalizeFileName(" demo.ae "))
    }

    @Test
    fun `new aether file helper rejects blank names`() {
        assertNull(AetherNewFileSupport.normalizeFileName(""))
        assertNull(AetherNewFileSupport.normalizeFileName("   "))
    }

    @Test
    fun `new aether file helper validates path separators`() {
        assertTrue(AetherNewFileSupport.isValidFileName("demo.ae"))
        assertTrue(!AetherNewFileSupport.isValidFileName("nested/demo.ae"))
        assertTrue(!AetherNewFileSupport.isValidFileName("nested\\demo.ae"))
    }

    @Test
    fun `highlighting lexer treats backslash as operator`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("A \\ b", 0, 5, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.OPERATOR.toString()))
    }

    @Test
    fun `highlighting lexer treats percent as operator`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("a % b", 0, 5, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.OPERATOR.toString()))
    }

    @Test
    fun `highlighting lexer treats caret as operator`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("x^2", 0, 3, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.OPERATOR.toString()))
        assertTrue(!tokenTypes.contains(AetherTokenTypes.BAD_CHARACTER.toString()))
    }

    @Test
    fun `highlighting lexer accepts abbreviated function equals syntax`() {
        val source = "f(double x) = x * exp(x) - 1.0;"
        val lexer = AetherHighlightingLexer()

        lexer.start(source, 0, source.length, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.OPERATOR.toString()))
        assertTrue(!tokenTypes.contains(AetherTokenTypes.BAD_CHARACTER.toString()))
    }

    @Test
    fun `highlighting lexer treats apostrophe operator as operator`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("A'", 0, 2, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.OPERATOR.toString()))
        assertTrue(!tokenTypes.contains(AetherTokenTypes.BAD_CHARACTER.toString()))
    }

    @Test
    fun `highlighting lexer treats single quotes as apostrophe operators`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("'hola'", 0, 6, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(!tokenTypes.contains(AetherTokenTypes.STRING.toString()))
        assertEquals(2, tokenTypes.count { it == AetherTokenTypes.OPERATOR.toString() })
        assertTrue(!tokenTypes.contains(AetherTokenTypes.BAD_CHARACTER.toString()))
    }

    @Test
    fun `typing support knows matching braces`() {
        assertEquals(')', AetherTypingSupport.matchingClosing('('))
        assertEquals(']', AetherTypingSupport.matchingClosing('['))
        assertEquals('}', AetherTypingSupport.matchingClosing('{'))
    }

    @Test
    fun `enter between braces inserts inner indent and places caret inside block`() {
        val insertion = AetherTypingSupport.enterBetweenBracesInsertion("    if (ok) {}", "    if (ok) {".length)

        assertNotNull(insertion)
        assertEquals("\n        \n    ", insertion.text)
        assertEquals("\n        ".length, insertion.caretShift)
    }

    @Test
    fun `enter support ignores offsets that are not between braces`() {
        assertEquals(null, AetherTypingSupport.enterBetweenBracesInsertion("if (ok) { value }", "if (ok) { ".length))
    }

    @Test
    fun `context reading actions update on background thread`() {
        assertEquals(ActionUpdateThread.BGT, NewAetherFileAction().actionUpdateThread)
        assertEquals(ActionUpdateThread.BGT, RunAetherFileAction().actionUpdateThread)
    }

    @Test
    fun `run action support finds explicit ae file before other contexts`() {
        val explicit = LightVirtualFile("demo.ae")
        val psi = LightVirtualFile("other.ae")
        val editor = LightVirtualFile("scratch.ae")

        assertEquals(
            explicit,
            AetherRunActionSupport.currentAetherFile(explicit, psi, editor),
        )
    }

    @Test
    fun `run action support falls back to psi and editor ae files`() {
        val psi = LightVirtualFile("fromPsi.ae")
        val editor = LightVirtualFile("fromEditor.ae")

        assertEquals(
            psi,
            AetherRunActionSupport.currentAetherFile(LightVirtualFile("notes.txt"), psi, editor),
        )
        assertEquals(
            editor,
            AetherRunActionSupport.currentAetherFile(LightVirtualFile("notes.txt"), null, editor),
        )
    }

    @Test
    fun `run action support rejects non ae files`() {
        assertNull(
            AetherRunActionSupport.currentAetherFile(
                LightVirtualFile("notes.txt"),
                LightVirtualFile("script.py"),
                LightVirtualFile("legacy.mtx"),
            )
        )
    }

    @Test
    fun `run action support validates ae file existence`() {
        val missing = LightVirtualFile("missing.ae")

        assertContains(AetherRunActionSupport.validationError(missing).orEmpty(), "does not exist")
        assertContains(AetherRunActionSupport.validationError(LightVirtualFile("notes.txt")).orEmpty(), ".ae")
    }

    @Test
    fun `plugin xml registers aether surface`() {
        val resource = javaClass.classLoader.getResource("META-INF/plugin.xml")
        assertNotNull(resource)
        val xml = resource.readText()

        assertContains(xml, "extensions=\"ae\"")
        assertContains(xml, "Aether.NewFile")
        assertContains(xml, "NewAetherFileAction")
        assertContains(xml, "NewGroup")
        assertContains(xml, "Aether.RunFile")
        assertContains(xml, "Aether.RunFileAst")
        assertContains(xml, "Aether.CheckFile")
        assertContains(xml, "Aether.EmitIr")
        assertContains(xml, "Aether.EmitSsa")
        assertContains(xml, "Aether.EmitLlvm")
        assertContains(xml, "Aether.RestartLanguageServer")
        assertContains(xml, "Aether.CommandActions")
        assertContains(xml, "lang.parserDefinition")
        assertContains(xml, "runLineMarkerContributor")
        assertContains(xml, "AetherTypedHandler")
        assertContains(xml, "AetherEnterHandler")
        assertContains(xml, "configurationType")
        assertContains(xml, "runConfigurationProducer")
        assertContains(xml, "EditorPopupMenu")
        assertContains(xml, "lsp.serverSupportProvider")
        assertFalse(xml.contains("toolWindow id=\"Aether\""))
        assertFalse(xml.contains("AetherConsoleService"))
        assertFalse(xml.contains("AetherToolWindowFactory"))
        assertFalse(xml.contains("aether_lsp.run_file"))
        assertFalse(xml.contains("python -m"))
    }

    private fun executableFile(projectDir: File, relativePath: String): File =
        projectDir.resolve(relativePath).apply {
            parentFile.mkdirs()
            writeText("")
            setExecutable(true)
        }

    private fun resolve(
        projectDir: File?,
        executable: AetherCommandLine.Executable,
        isWindows: Boolean = false,
    ): AetherCommandLine.ExecutableResolution = AetherCommandLine.resolveExecutable(
        projectDir?.path,
        "",
        executable,
        isWindows,
    )
}
