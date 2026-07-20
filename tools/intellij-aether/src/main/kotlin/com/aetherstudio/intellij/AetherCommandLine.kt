package com.aetherstudio.intellij

import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectFileIndex
import com.intellij.openapi.util.SystemInfo
import com.intellij.openapi.vfs.LocalFileSystem
import java.io.File

enum class AetherBackend(val persistentValue: String, private val label: String) {
    NATIVE("native", "Native"),
    AST("ast", "AST");

    override fun toString(): String = label

    companion object {
        fun fromPersistentValue(value: String?): AetherBackend =
            entries.firstOrNull { it.persistentValue.equals(value, ignoreCase = true) } ?: NATIVE
    }
}

enum class AetherCommandMode {
    RUN_NATIVE,
    RUN_AST,
    CHECK,
    EMIT_IR,
    EMIT_SSA,
    EMIT_LLVM,
}

object AetherCommandLine {
    enum class Executable(val commandName: String) {
        AETHER("aether"),
        LANGUAGE_SERVER("aether-lsp"),
    }

    data class ExecutableResolution(
        val executable: String,
        val warning: String? = null,
    )

    fun resolveExecutable(
        projectBasePath: String?,
        configuredExecutable: String?,
        executable: Executable,
        isWindows: Boolean = SystemInfo.isWindows,
    ): ExecutableResolution {
        val configured = configuredExecutable?.trim().orEmpty()
        if (configured.isNotEmpty()) {
            if (!configured.looksLikeFilePath()) {
                return ExecutableResolution(configured)
            }
            val configuredFile = configuredExecutableFile(projectBasePath, configured)
            if (configuredFile.isUsableExecutable()) {
                return ExecutableResolution(configuredFile.path)
            }
        }

        val projectExecutable = projectVenvExecutable(projectBasePath, executable, isWindows)
        if (projectExecutable != null) {
            return ExecutableResolution(
                projectExecutable.path,
                invalidConfiguredPathWarning(configured, projectExecutable.path),
            )
        }

        return ExecutableResolution(
            executable.commandName,
            invalidConfiguredPathWarning(configured, executable.commandName),
        )
    }

    fun lspArguments(): List<String> = listOf("--stdio")

    fun runFileArguments(filePath: String, backend: AetherBackend): List<String> = when (backend) {
        AetherBackend.NATIVE -> listOf(filePath)
        AetherBackend.AST -> listOf("--backend=ast", filePath)
    }

    fun checkFileArguments(filePath: String): List<String> = listOf("--check", filePath)

    fun emitIrArguments(filePath: String): List<String> = listOf("--emit-ir", filePath)

    fun emitSsaArguments(filePath: String): List<String> = listOf("--emit-ssa", filePath)

    fun emitLlvmArguments(filePath: String): List<String> = listOf("--emit-llvm", filePath)

    fun lspCommandLine(project: Project): GeneralCommandLine {
        val settings = AetherSettingsState.getInstance().state
        val executable = resolveExecutable(
            project.basePath,
            settings.languageServerExecutable,
            Executable.LANGUAGE_SERVER,
        ).executable
        return GeneralCommandLine(executable).withParameters(lspArguments()).also { commandLine ->
            project.basePath?.let(commandLine::withWorkDirectory)
        }
    }

    fun runFileCommandLine(project: Project, filePath: String, backend: AetherBackend): GeneralCommandLine =
        fileCommandLine(project, filePath, runFileArguments(normalizedFilePath(project.basePath, filePath), backend))

    fun checkFileCommandLine(project: Project, filePath: String): GeneralCommandLine =
        fileCommandLine(project, filePath, checkFileArguments(normalizedFilePath(project.basePath, filePath)))

    fun emitIrCommandLine(project: Project, filePath: String): GeneralCommandLine =
        fileCommandLine(project, filePath, emitIrArguments(normalizedFilePath(project.basePath, filePath)))

    fun emitSsaCommandLine(project: Project, filePath: String): GeneralCommandLine =
        fileCommandLine(project, filePath, emitSsaArguments(normalizedFilePath(project.basePath, filePath)))

    fun emitLlvmCommandLine(project: Project, filePath: String): GeneralCommandLine =
        fileCommandLine(project, filePath, emitLlvmArguments(normalizedFilePath(project.basePath, filePath)))

    fun commandLine(project: Project, filePath: String, mode: AetherCommandMode): GeneralCommandLine = when (mode) {
        AetherCommandMode.RUN_NATIVE -> runFileCommandLine(project, filePath, AetherBackend.NATIVE)
        AetherCommandMode.RUN_AST -> runFileCommandLine(project, filePath, AetherBackend.AST)
        AetherCommandMode.CHECK -> checkFileCommandLine(project, filePath)
        AetherCommandMode.EMIT_IR -> emitIrCommandLine(project, filePath)
        AetherCommandMode.EMIT_SSA -> emitSsaCommandLine(project, filePath)
        AetherCommandMode.EMIT_LLVM -> emitLlvmCommandLine(project, filePath)
    }

    fun workingDirectory(projectBasePath: String?, filePath: String, contentRootPath: String? = null): String? {
        val resolvedFile = File(normalizedFilePath(projectBasePath, filePath))
        val contentRoot = contentRootPath?.let(::File)
        if (contentRoot != null && contentRoot.isAncestorOf(resolvedFile)) {
            return contentRoot.path
        }
        val projectRoot = projectBasePath?.let(::File)
        if (projectRoot != null && projectRoot.isAncestorOf(resolvedFile)) {
            return projectRoot.path
        }
        return resolvedFile.parentFile?.path
    }

    internal fun normalizedFilePath(projectBasePath: String?, filePath: String): String {
        val file = File(filePath)
        return if (file.isAbsolute || projectBasePath == null) file.path else File(projectBasePath, filePath).path
    }

    private fun fileCommandLine(project: Project, originalFilePath: String, arguments: List<String>): GeneralCommandLine {
        val settings = AetherSettingsState.getInstance().state
        val executable = resolveExecutable(
            project.basePath,
            settings.aetherExecutable,
            Executable.AETHER,
        ).executable
        val normalizedPath = normalizedFilePath(project.basePath, originalFilePath)
        val virtualFile = LocalFileSystem.getInstance().findFileByPath(normalizedPath)
        val contentRoot = virtualFile?.let { ProjectFileIndex.getInstance(project).getContentRootForFile(it) }
        return GeneralCommandLine(executable).withParameters(arguments).also { commandLine ->
            workingDirectory(project.basePath, normalizedPath, contentRoot?.path)?.let(commandLine::withWorkDirectory)
        }
    }

    private fun projectVenvExecutable(
        projectBasePath: String?,
        executable: Executable,
        isWindows: Boolean,
    ): File? {
        val basePath = projectBasePath ?: return null
        val candidates = if (isWindows) {
            listOf(
                ".venv/Scripts/${executable.commandName}.exe",
                ".venv/Scripts/${executable.commandName}.cmd",
                ".venv/Scripts/${executable.commandName}",
            )
        } else {
            listOf(".venv/bin/${executable.commandName}")
        }
        return candidates.asSequence().map { File(basePath, it) }.firstOrNull { it.isUsableExecutable() }
    }

    private fun configuredExecutableFile(projectBasePath: String?, configured: String): File {
        val file = File(configured)
        if (file.isAbsolute || configured.isWindowsAbsolutePath() || projectBasePath == null) {
            return file
        }
        return File(projectBasePath, configured)
    }

    private fun invalidConfiguredPathWarning(configured: String, fallback: String): String? =
        configured.takeIf { it.isNotEmpty() && it.looksLikeFilePath() }?.let {
            "Configured executable '$it' is not executable; using '$fallback'."
        }

    private fun String.looksLikeFilePath(): Boolean =
        contains('/') || contains('\\') || File(this).isAbsolute || isWindowsAbsolutePath()

    private fun String.isWindowsAbsolutePath(): Boolean =
        length >= 3 && this[0].isLetter() && this[1] == ':' && (this[2] == '\\' || this[2] == '/')

    private fun File.isUsableExecutable(): Boolean = isFile && canExecute()

    private fun File.isAncestorOf(child: File): Boolean = try {
        child.canonicalFile.toPath().startsWith(canonicalFile.toPath())
    } catch (_: Exception) {
        child.absoluteFile.toPath().normalize().startsWith(absoluteFile.toPath().normalize())
    }
}
