package com.aetherstudio.intellij

import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.project.Project
import java.io.File

object AetherCommandLine {
    fun pythonExecutable(projectBasePath: String?, configuredPython: String?): String {
        val configured = configuredPython?.trim().orEmpty()
        if (configured.isNotEmpty() && isUsableConfiguredPython(projectBasePath, configured)) {
            return resolvedConfiguredPython(projectBasePath, configured)
        }

        val basePath = projectBasePath ?: return "python3"
        val unixVenv = File(basePath, ".venv/bin/python")
        if (unixVenv.isUsableExecutable()) {
            return unixVenv.path
        }
        val windowsVenv = File(basePath, ".venv/Scripts/python.exe")
        if (windowsVenv.isUsableExecutable()) {
            return windowsVenv.path
        }
        return "python3"
    }

    fun sourcePath(projectBasePath: String?): String? {
        val basePath = projectBasePath ?: return null
        val src = File(basePath, "src")
        return if (src.isDirectory) src.path else null
    }

    fun lspArguments(): List<String> = listOf("-m", "aether_lsp.server", "--stdio")

    fun runFileArguments(filePath: String): List<String> = listOf("-m", "aether_lsp.run_file", filePath)

    fun lspCommandLine(project: Project): GeneralCommandLine =
        baseCommandLine(project).withParameters(lspArguments())

    fun runFileCommandLine(project: Project, filePath: String): GeneralCommandLine =
        baseCommandLine(project).withParameters(runFileArguments(filePath))

    private fun baseCommandLine(project: Project): GeneralCommandLine {
        val settings = AetherSettingsState.getInstance().state
        val commandLine = GeneralCommandLine(pythonExecutable(project.basePath, settings.pythonPath))
        project.basePath?.let { commandLine.withWorkDirectory(it) }
        sourcePath(project.basePath)?.let { commandLine.environment["PYTHONPATH"] = it }
        return commandLine
    }

    private fun isUsableConfiguredPython(projectBasePath: String?, configured: String): Boolean {
        if (!configured.looksLikeFilePath()) {
            return true
        }
        return configuredPythonFile(projectBasePath, configured).isUsableExecutable()
    }

    private fun resolvedConfiguredPython(projectBasePath: String?, configured: String): String {
        if (!configured.looksLikeFilePath()) {
            return configured
        }
        return configuredPythonFile(projectBasePath, configured).path
    }

    private fun configuredPythonFile(projectBasePath: String?, configured: String): File {
        val file = File(configured)
        if (file.isAbsolute || projectBasePath == null) {
            return file
        }
        return File(projectBasePath, configured)
    }

    private fun String.looksLikeFilePath(): Boolean =
        contains('/') || contains('\\') || File(this).isAbsolute

    private fun File.isUsableExecutable(): Boolean =
        isFile && canExecute()
}
