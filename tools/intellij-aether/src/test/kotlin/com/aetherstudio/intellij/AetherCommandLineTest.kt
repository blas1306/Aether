package com.aetherstudio.intellij

import com.intellij.openapi.actionSystem.ActionUpdateThread
import kotlin.io.path.createTempDirectory
import kotlin.test.Test
import kotlin.test.assertContains
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

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
    fun `highlighting lexer treats single quoted string as string`() {
        val lexer = AetherHighlightingLexer()

        lexer.start("'hola'", 0, 6, 0)
        val tokenTypes = mutableListOf<String>()
        while (lexer.tokenType != null) {
            tokenTypes.add(lexer.tokenType.toString())
            lexer.advance()
        }

        assertTrue(tokenTypes.contains(AetherTokenTypes.STRING.toString()))
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
        val insertion = AetherTypingSupport.enterBetweenBracesInsertion("    if ok {}", "    if ok {".length)

        assertNotNull(insertion)
        assertEquals("\n        \n    ", insertion.text)
        assertEquals("\n        ".length, insertion.caretShift)
    }

    @Test
    fun `enter support ignores offsets that are not between braces`() {
        assertEquals(null, AetherTypingSupport.enterBetweenBracesInsertion("if ok { value }", "if ok { ".length))
    }

    @Test
    fun `context reading actions update on background thread`() {
        assertEquals(ActionUpdateThread.BGT, NewAetherFileAction().actionUpdateThread)
        assertEquals(ActionUpdateThread.BGT, RunAetherFileAction().actionUpdateThread)
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
        assertContains(xml, "lang.parserDefinition")
        assertContains(xml, "runLineMarkerContributor")
        assertContains(xml, "AetherTypedHandler")
        assertContains(xml, "AetherEnterHandler")
        assertContains(xml, "configurationType")
        assertContains(xml, "runConfigurationProducer")
        assertContains(xml, "EditorPopupMenu")
        assertContains(xml, "lsp.serverSupportProvider")
        assertContains(xml, "toolWindow id=\"Aether\"")
    }
}
