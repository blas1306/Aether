package com.aetherstudio.intellij

import com.intellij.execution.ExecutionException
import com.intellij.execution.Executor
import com.intellij.execution.configurations.CommandLineState
import com.intellij.execution.configurations.ConfigurationFactory
import com.intellij.execution.configurations.RunConfiguration
import com.intellij.execution.configurations.RunConfigurationBase
import com.intellij.execution.configurations.RunProfileState
import com.intellij.execution.configurations.RuntimeConfigurationError
import com.intellij.execution.configurations.RuntimeConfigurationWarning
import com.intellij.execution.process.OSProcessHandler
import com.intellij.execution.process.ProcessHandler
import com.intellij.execution.runners.ExecutionEnvironment
import com.intellij.openapi.options.SettingsEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.JDOMExternalizerUtil
import org.jdom.Element
import java.io.File

class AetherRunConfiguration(
    project: Project,
    factory: ConfigurationFactory,
    name: String,
) : RunConfigurationBase<RunProfileState>(project, factory, name) {
    var filePath: String = ""
    var backend: AetherBackend = AetherBackend.NATIVE
    internal var commandMode: AetherCommandMode = AetherCommandMode.RUN_NATIVE

    override fun getConfigurationEditor(): SettingsEditor<out RunConfiguration> = AetherRunSettingsEditor()

    override fun checkConfiguration() {
        if (filePath.isBlank()) {
            throw RuntimeConfigurationError("Choose an Aether .ae file.")
        }
        val normalizedPath = AetherCommandLine.normalizedFilePath(project.basePath, filePath)
        val file = File(normalizedPath)
        if (!file.isFile || !file.extension.equals(AetherFileType.defaultExtension, ignoreCase = true)) {
            throw RuntimeConfigurationError("Aether run configurations require an existing .ae file: $filePath")
        }
        val settings = AetherSettingsState.getInstance().state
        val resolution = AetherCommandLine.resolveExecutable(
            project.basePath,
            settings.aetherExecutable,
            AetherCommandLine.Executable.AETHER,
        )
        resolution.warning?.let { throw RuntimeConfigurationWarning(it) }
    }

    override fun getState(executor: Executor, environment: ExecutionEnvironment): RunProfileState {
        val effectiveMode = when (commandMode) {
            AetherCommandMode.RUN_NATIVE, AetherCommandMode.RUN_AST -> when (backend) {
                AetherBackend.NATIVE -> AetherCommandMode.RUN_NATIVE
                AetherBackend.AST -> AetherCommandMode.RUN_AST
            }
            else -> commandMode
        }
        return AetherRunProfileState(project, environment, filePath, effectiveMode)
    }

    override fun readExternal(element: Element) {
        super.readExternal(element)
        val persisted = AetherRunConfigurationPersistence.read(element)
        filePath = persisted.filePath
        backend = persisted.backend
        commandMode = AetherCommandMode.RUN_NATIVE
    }

    override fun writeExternal(element: Element) {
        super.writeExternal(element)
        AetherRunConfigurationPersistence.write(element, filePath, backend)
    }
}

internal object AetherRunConfigurationPersistence {
    private const val FILE_PATH_FIELD = "filePath"
    private const val BACKEND_FIELD = "backend"

    data class Persisted(val filePath: String, val backend: AetherBackend)

    fun read(element: Element): Persisted = Persisted(
        JDOMExternalizerUtil.readField(element, FILE_PATH_FIELD).orEmpty(),
        AetherBackend.fromPersistentValue(JDOMExternalizerUtil.readField(element, BACKEND_FIELD)),
    )

    fun write(element: Element, filePath: String, backend: AetherBackend) {
        JDOMExternalizerUtil.writeField(element, FILE_PATH_FIELD, filePath)
        JDOMExternalizerUtil.writeField(element, BACKEND_FIELD, backend.persistentValue)
    }
}

private class AetherRunProfileState(
    private val project: Project,
    environment: ExecutionEnvironment,
    private val filePath: String,
    private val mode: AetherCommandMode,
) : CommandLineState(environment) {
    @Throws(ExecutionException::class)
    override fun startProcess(): ProcessHandler =
        OSProcessHandler(AetherCommandLine.commandLine(project, filePath, mode))
}
