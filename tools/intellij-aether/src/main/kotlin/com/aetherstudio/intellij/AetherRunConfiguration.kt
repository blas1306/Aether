package com.aetherstudio.intellij

import com.intellij.execution.ExecutionException
import com.intellij.execution.Executor
import com.intellij.execution.configurations.CommandLineState
import com.intellij.execution.configurations.ConfigurationFactory
import com.intellij.execution.configurations.RunConfiguration
import com.intellij.execution.configurations.RunConfigurationBase
import com.intellij.execution.configurations.RunProfileState
import com.intellij.execution.configurations.RuntimeConfigurationError
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

    override fun getConfigurationEditor(): SettingsEditor<out RunConfiguration> = AetherRunSettingsEditor()

    override fun checkConfiguration() {
        if (filePath.isBlank()) {
            throw RuntimeConfigurationError("Choose an Aether .ae file.")
        }
        val file = File(filePath)
        if (!file.isFile || file.extension != AetherFileType.defaultExtension) {
            throw RuntimeConfigurationError("Aether run configurations require an existing .ae file.")
        }
    }

    override fun getState(executor: Executor, environment: ExecutionEnvironment): RunProfileState =
        AetherRunProfileState(project, environment, filePath)

    override fun readExternal(element: Element) {
        super.readExternal(element)
        filePath = JDOMExternalizerUtil.readField(element, FILE_PATH_FIELD).orEmpty()
    }

    override fun writeExternal(element: Element) {
        super.writeExternal(element)
        JDOMExternalizerUtil.writeField(element, FILE_PATH_FIELD, filePath)
    }

    companion object {
        private const val FILE_PATH_FIELD = "filePath"
    }
}

private class AetherRunProfileState(
    private val project: Project,
    environment: ExecutionEnvironment,
    private val filePath: String,
) : CommandLineState(environment) {
    @Throws(ExecutionException::class)
    override fun startProcess(): ProcessHandler =
        OSProcessHandler(AetherCommandLine.runFileCommandLine(project, filePath))
}
